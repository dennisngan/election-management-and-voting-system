"""Credential-safe, single-schema MySQL logical dump adapter."""

import contextlib
import ipaddress
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class BackupToolError(RuntimeError):
    """A safe backup-tool failure without command output or connection details."""

    def __init__(self, code: str, *, exit_status: int | None = None) -> None:
        self.code = code
        self.exit_status = exit_status
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise BackupToolError(code) from None


def _schema_name(url: URL) -> str:
    name = url.database
    if not name or not re.fullmatch(r"[A-Za-z0-9_$]{1,64}", name):
        _fail("unsupported_database_name")
    return name


def _option_value(value: str) -> str:
    if any(char in value for char in ("\x00", "\n", "\r")):
        _fail("unsupported_database_option")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _bool_option(value: str) -> bool:
    if value.lower() in ("1", "true", "yes", "on"):
        return True
    if value.lower() in ("0", "false", "no", "off"):
        return False
    _fail("unsupported_database_option")


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _client_options(url: URL, *, container: str | None) -> tuple[str, int, bytes]:
    host = url.host
    if not host:
        _fail("unsupported_unix_socket")
    if container is not None and not _loopback(host):
        _fail("container_source_must_be_loopback")
    username = url.username
    password = url.password
    if not username or password is None:
        _fail("database_credentials_missing")

    query = dict(url.query)
    if "unix_socket" in query:
        _fail("unsupported_unix_socket")
    options = {"user": username, "password": password}
    charset = query.pop("charset", "utf8mb4")
    options["default-character-set"] = str(charset)
    if container is None:
        for source, target in (
            ("ssl_ca", "ssl-ca"),
            ("ssl_cert", "ssl-cert"),
            ("ssl_key", "ssl-key"),
            ("ssl_mode", "ssl-mode"),
            ("connect_timeout", "connect-timeout"),
        ):
            value = query.pop(source, None)
            if value is not None:
                options[target] = str(value)
        verify_cert = query.pop("ssl_verify_cert", None)
        verify_identity = query.pop("ssl_verify_identity", None)
        if verify_cert is not None or verify_identity is not None:
            cert = _bool_option(str(verify_cert)) if verify_cert is not None else False
            identity = (
                _bool_option(str(verify_identity)) if verify_identity is not None else False
            )
            if identity:
                options["ssl-mode"] = "VERIFY_IDENTITY"
            elif cert:
                options["ssl-mode"] = "VERIFY_CA"
    elif set(query) - {"connect_timeout"}:
        _fail("unsupported_container_database_option")
    elif "connect_timeout" in query:
        options["connect-timeout"] = str(query["connect_timeout"])
    if query:
        _fail("unsupported_database_option")
    if "ssl-mode" in options and options["ssl-mode"] not in {
        "DISABLED", "PREFERRED", "REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"
    }:
        _fail("unsupported_database_option")

    port = url.port or 3306
    if not 1 <= port <= 65535:
        _fail("unsupported_database_option")
    if container is not None:
        host, port = "127.0.0.1", 3306
    lines = ["[client]", *(f"{key}={_option_value(value)}" for key, value in options.items())]
    return host, port, ("\n".join(lines) + "\n").encode("utf-8")


def _validate_client_binary(client_binary: str, *, container: str | None) -> str:
    if Path(client_binary).name != "mysqldump":
        _fail("unsupported_backup_client")
    if container is not None and client_binary != "mysqldump":
        _fail("unsupported_container_client")
    binary = "docker" if container is not None else client_binary
    resolved = shutil.which(binary)
    if resolved is None:
        _fail("backup_client_unavailable")
    return resolved


def _client_environment() -> dict[str, str]:
    environment = os.environ.copy()
    protected = {
        "MYSQL_PWD",
        "MYSQL_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
        "DATABASE_URL",
        "ELECTION_DATABASE_URL",
        "ELECTION_TEST_DATABASE_URL",
        "ELECTION_LIFECYCLE_TEST_DATABASE_URL",
    }
    for key in tuple(environment):
        if key in protected or key.endswith(("_DATABASE_URL", "_PASSWORD")):
            environment.pop(key, None)
    return environment


def _client_version(command: list[str], environment: dict[str, str]) -> str:
    try:
        result = subprocess.run(
            [*command, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            env=environment,
        )
    except OSError:
        _fail("backup_client_version_failed")
    if result.returncode != 0:
        raise BackupToolError("backup_client_version_failed", exit_status=result.returncode)
    output = result.stdout + result.stderr
    match = re.search(rb"\bVer\s+(\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        _fail("unsupported_backup_client_version")
    version = ".".join(part.decode("ascii") for part in match.groups())
    major, minor, _ = (int(part) for part in version.split("."))
    if (major, minor) != (8, 4):
        _fail("unsupported_backup_client_version")
    return version


@contextlib.contextmanager
def _private_options_file(directory: Path, contents: bytes) -> Iterator[str]:
    try:
        temporary = tempfile.TemporaryDirectory(prefix=".mysqldump-options-", dir=directory)
    except OSError:
        _fail("backup_credentials_file_failed")
    try:
        temp_path = Path(temporary.name)
        temp_path.chmod(0o700)
        path = temp_path / "client.cnf"
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
    except OSError:
        try:
            temporary.cleanup()
        except OSError:
            pass
        _fail("backup_credentials_file_failed")
    try:
        yield str(path)
    finally:
        try:
            temporary.cleanup()
        except OSError:
            pass


def _publish(partial: Path, destination: Path) -> None:
    published = False
    try:
        # A hard link publishes atomically and fails rather than replacing an older artifact.
        os.link(partial, destination, follow_symlinks=False)
        published = True
        partial.unlink()
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        _fail("backup_artifact_exists")
    except OSError:
        if published:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        _fail("backup_publish_failed")


def dump_mysql(
    database_url: str,
    destination: Path,
    *,
    container: str | None = None,
    client_binary: str = "mysqldump",
) -> str:
    """Write one consistent schema dump; return its verified mysqldump 8.4 version."""
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        _fail("invalid_database_url")
    if url.drivername != "mysql+pymysql":
        _fail("unsupported_database_url")
    schema = _schema_name(url)
    name = container or ""
    if container is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        _fail("invalid_database_container")
    host, port, options = _client_options(url, container=container)
    binary = _validate_client_binary(client_binary, container=container)
    command = [binary, "exec", name, "mysqldump"] if container is not None else [binary]
    environment = _client_environment()
    version = _client_version(command, environment)

    try:
        parent = destination.parent.resolve(strict=True)
        if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
            _fail("backup_directory_not_private")
        destination = parent / destination.name
        if not destination.name or destination.name in (".", "..") or destination.exists():
            _fail("backup_artifact_exists")
    except OSError:
        _fail("backup_directory_unavailable")

    partial = destination.with_name(destination.name + ".partial")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            partial,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        _fail("backup_partial_exists")
    except OSError:
        _fail("backup_artifact_create_failed")

    owns_partial = True
    try:
        flags = [
            "--single-transaction",
            "--quick",
            "--skip-lock-tables",
            "--no-tablespaces",
            "--set-gtid-purged=OFF",
            "--hex-blob",
            "--protocol=TCP",
            f"--host={host}",
            f"--port={port}",
        ]
        with os.fdopen(descriptor, "wb") as output, tempfile.TemporaryFile(mode="w+b") as stderr:
            descriptor = None
            if container is None:
                with _private_options_file(parent, options) as defaults_file:
                    argv = [
                        binary, f"--defaults-file={defaults_file}", "--no-login-paths",
                        *flags, schema,
                    ]
                    try:
                        process = subprocess.Popen(
                            argv,
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=stderr,
                            close_fds=True,
                            shell=False,
                            env=environment,
                        )
                    except OSError:
                        _fail("backup_client_unavailable")
                    return_code = process.wait()
            else:
                argv = [
                    binary,
                    "exec",
                    "-i",
                    "--env=MYSQL_PWD=",
                    "--env=MYSQL_PASSWORD=",
                    "--env=MYSQL_ROOT_PASSWORD=",
                    "--env=DATABASE_URL=",
                    "--env=ELECTION_DATABASE_URL=",
                    "--env=ELECTION_TEST_DATABASE_URL=",
                    "--env=ELECTION_LIFECYCLE_TEST_DATABASE_URL=",
                    name,
                    "mysqldump",
                    "--defaults-file=/dev/stdin",
                    "--no-login-paths",
                    *flags,
                    schema,
                ]
                try:
                    process = subprocess.Popen(
                        argv,
                        stdin=subprocess.PIPE,
                        stdout=output,
                        stderr=stderr,
                        close_fds=True,
                        shell=False,
                        env=environment,
                    )
                    process.communicate(input=options)
                    return_code = process.returncode
                except OSError:
                    _fail("backup_client_unavailable")
            output.flush()
            os.fsync(output.fileno())
        if return_code != 0:
            raise BackupToolError("backup_dump_failed", exit_status=return_code)
        if partial.stat().st_size <= 0:
            _fail("backup_dump_empty")
        _publish(partial, destination)
        owns_partial = False
        return version
    except BackupToolError:
        if descriptor is not None:
            os.close(descriptor)
        if owns_partial:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        if owns_partial:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        _fail("backup_io_failed")
