"""Credential-safe, single-schema MySQL logical dump adapter."""

import contextlib
import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, NoReturn

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from election.private_paths import private_directory, private_file, private_file_descriptor


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
        options["connect-timeout"] = str(query.pop("connect_timeout"))
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


def _validate_client_binary(
    client_binary: str, *, container: str | None, expected_name: str = "mysqldump"
) -> str:
    tool = "backup" if expected_name == "mysqldump" else "restore"
    if Path(client_binary).name != expected_name:
        _fail(f"unsupported_{tool}_client")
    if container is not None and client_binary != expected_name:
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


def _client_version(
    command: list[str], environment: dict[str, str], *, tool: str = "backup"
) -> str:
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
        _fail(f"{tool}_client_version_failed")
    if result.returncode != 0:
        raise BackupToolError(f"{tool}_client_version_failed", exit_status=result.returncode)
    output = result.stdout + result.stderr
    match = re.search(rb"\bVer\s+(\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        _fail(f"unsupported_{tool}_client_version")
    version = ".".join(part.decode("ascii") for part in match.groups())
    major, minor, _ = (int(part) for part in version.split("."))
    if (major, minor) != (8, 4):
        _fail(f"unsupported_{tool}_client_version")
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
        if not private_directory(temp_path):
            raise OSError("Private credential directory unavailable")
        path = temp_path / "client.cnf"
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as file:
            if not private_file_descriptor(file.fileno()):
                raise OSError("Private credential file unavailable")
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


def _private_restore_source(source: Path) -> BinaryIO:
    try:
        parent = source.parent
        parent.stat()
        if not private_directory(parent):
            _fail("restore_directory_not_private")
        parent = parent.resolve(strict=True)
        path = parent / source.name
        if not private_file(path):
            _fail("restore_source_not_private")
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        opened = os.fstat(descriptor)
        if not private_file_descriptor(descriptor):
            os.close(descriptor)
            _fail("restore_source_not_private")
        if opened.st_size <= 0:
            os.close(descriptor)
            _fail("restore_source_empty")
        return os.fdopen(descriptor, "rb")
    except BackupToolError:
        raise
    except OSError:
        _fail("restore_source_unavailable")


def _statement_heads(source: BinaryIO) -> Iterator[tuple[str, ...]]:
    """Yield leading SQL tokens per statement, ignoring quoted text and comments."""
    statement: list[str] = []
    token = bytearray()
    quote: int | None = None
    escaped = False
    line_comment = False
    block_comment = False
    executable_comment = False
    executable_version = False
    previous = 0

    def flush_token() -> None:
        if token and len(statement) < 4:
            statement.append(token.decode("ascii").upper())
        token.clear()

    for chunk in iter(lambda: source.read(64 * 1024), b""):
        for char in chunk:
            if line_comment:
                if char == 10:
                    line_comment = False
                previous = char
                continue
            if block_comment:
                if not executable_comment and char == ord("!") and previous == ord("*"):
                    executable_comment = True
                    executable_version = True
                    previous = char
                    continue
                if previous == ord("*") and char == ord("/"):
                    block_comment = False
                    executable_comment = False
                    previous = char
                    continue
                if not executable_comment:
                    previous = char
                    continue
                if executable_version:
                    if ord("0") <= char <= ord("9"):
                        previous = char
                        continue
                    executable_version = False
                    if char in b" \t\r\n":
                        previous = char
                        continue
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == ord("\\") and quote != ord("`"):
                    escaped = True
                elif char == quote:
                    quote = None
                previous = char
                continue
            if char in (ord("'"), ord('"'), ord("`")):
                if token and len(statement) < 4:
                    statement.append(token.decode("ascii").upper())
                token.clear()
                quote = char
                previous = char
                continue
            if char == ord("#") or (char == ord("-") and previous == ord("-")):
                flush_token()
                line_comment = True
                previous = char
                continue
            if char == ord("*") and previous == ord("/"):
                flush_token()
                block_comment = True
                executable_comment = False
                executable_version = False
                previous = char
                continue
            if char == ord(";"):
                flush_token()
                yield tuple(statement)
                statement.clear()
            elif char in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$":
                if len(token) < 32:
                    token.append(char)
            else:
                flush_token()
            previous = char
    flush_token()
    if statement:
        yield tuple(statement)


def _validate_restore_dump(source: BinaryIO) -> None:
    source.seek(0)
    for statement in _statement_heads(source):
        first = statement[0] if statement else ""
        second = statement[1] if len(statement) > 1 else ""
        third = statement[2] if len(statement) > 2 else ""
        if first == "USE" or (
            first in ("CREATE", "DROP")
            and (
                second in ("DATABASE", "SCHEMA")
                or (second == "TEMPORARY" and third in ("DATABASE", "SCHEMA"))
            )
        ):
            _fail("restore_dump_changes_database")
    source.seek(0)


def _docker_environment() -> list[str]:
    return [
        "--env=MYSQL_PWD=",
        "--env=MYSQL_PASSWORD=",
        "--env=MYSQL_ROOT_PASSWORD=",
        "--env=DATABASE_URL=",
        "--env=ELECTION_DATABASE_URL=",
        "--env=ELECTION_TEST_DATABASE_URL=",
        "--env=ELECTION_LIFECYCLE_TEST_DATABASE_URL=",
    ]


@contextlib.contextmanager
def _container_restore_options(
    binary: str, container: str, environment: dict[str, str], contents: bytes
) -> Iterator[str]:
    try:
        result = subprocess.run(
            [
                binary,
                "exec",
                *_docker_environment(),
                container,
                "mktemp",
                "-d",
                "/tmp/.election-mysql-restore.XXXXXXXX",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("restore_credentials_directory_failed")
    if result.returncode != 0:
        raise BackupToolError("restore_credentials_directory_failed", exit_status=result.returncode)
    try:
        directory = result.stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        _fail("restore_credentials_directory_failed")
    if not re.fullmatch(r"/tmp/\.election-mysql-restore\.[A-Za-z0-9]{8}", directory):
        _fail("restore_credentials_directory_failed")
    credentials = directory + "/client.cnf"
    cleanup_failed = False
    try:
        try:
            upload = subprocess.run(
                [
                    binary,
                    "exec",
                    "-i",
                    *_docker_environment(),
                    container,
                    "install",
                    "-m",
                    "600",
                    "/dev/stdin",
                    credentials,
                ],
                input=contents,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                env=environment,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("restore_credentials_file_failed")
        if upload.returncode != 0:
            raise BackupToolError("restore_credentials_file_failed", exit_status=upload.returncode)
        yield credentials
    finally:
        for executable, path in (("rm", credentials), ("rmdir", directory)):
            try:
                cleanup = subprocess.run(
                    [
                        binary,
                        "exec",
                        *_docker_environment(),
                        container,
                        executable,
                        "--",
                        path,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    shell=False,
                    env=environment,
                    timeout=30,
                )
                cleanup_failed = cleanup_failed or cleanup.returncode != 0
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
        if cleanup_failed:
            _fail("restore_credentials_cleanup_failed")


def _publish(partial: Path, destination: Path) -> None:
    published = False
    try:
        # A hard link publishes atomically and fails rather than replacing an older artifact.
        os.link(partial, destination, follow_symlinks=False)
        published = True
        partial.unlink()
        if os.name != "nt":
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
        parent = destination.parent
        parent.stat()
        if not private_directory(parent):
            _fail("backup_directory_not_private")
        parent = parent.resolve(strict=True)
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
        output_file = os.fdopen(descriptor, "wb")
        descriptor = None
        with (
            output_file as output,
            tempfile.TemporaryFile(mode="w+b", dir=parent) as stderr,
        ):
            if not private_file_descriptor(output.fileno()) or not private_file_descriptor(
                stderr.fileno()
            ):
                _fail("backup_io_failed")
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


def restore_mysql(
    database_url: str,
    source: Path,
    *,
    container: str | None = None,
    client_binary: str = "mysql",
) -> str:
    """Import a private single-schema dump into an explicit existing *_test schema."""
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        _fail("invalid_database_url")
    if url.drivername != "mysql+pymysql":
        _fail("unsupported_database_url")
    schema = _schema_name(url)
    if not schema.endswith("_test"):
        _fail("restore_target_must_be_test_schema")
    name = container or ""
    if container is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        _fail("invalid_database_container")
    host, port, options = _client_options(url, container=container)
    binary = _validate_client_binary(client_binary, container=container, expected_name="mysql")
    environment = _client_environment()
    version_command = (
        [binary, "exec", *_docker_environment(), name, "mysql"]
        if container is not None
        else [binary]
    )
    version = _client_version(version_command, environment, tool="restore")

    try:
        with _private_restore_source(source) as dump:
            _validate_restore_dump(dump)
            directory = source.parent.resolve(strict=True)
            with tempfile.TemporaryFile(mode="w+b", dir=directory) as stderr:
                if not private_file_descriptor(stderr.fileno()):
                    _fail("restore_io_failed")
                if container is None:
                    with _private_options_file(directory, options) as defaults:
                        argv = [
                            binary,
                            f"--defaults-file={defaults}",
                            "--no-login-paths",
                            "--binary-mode=1",
                            "--protocol=TCP",
                            f"--host={host}",
                            f"--port={port}",
                            f"--database={schema}",
                        ]
                        try:
                            process = subprocess.Popen(
                                argv,
                                stdin=dump,
                                stdout=subprocess.DEVNULL,
                                stderr=stderr,
                                close_fds=True,
                                shell=False,
                                env=environment,
                            )
                        except OSError:
                            _fail("restore_client_unavailable")
                        return_code = process.wait()
                else:
                    with _container_restore_options(binary, name, environment, options) as defaults:
                        argv = [
                            binary,
                            "exec",
                            "-i",
                            *_docker_environment(),
                            name,
                            "mysql",
                            f"--defaults-file={defaults}",
                            "--no-login-paths",
                            "--binary-mode=1",
                            "--protocol=TCP",
                            "--host=127.0.0.1",
                            "--port=3306",
                            f"--database={schema}",
                        ]
                        try:
                            process = subprocess.Popen(
                                argv,
                                stdin=dump,
                                stdout=subprocess.DEVNULL,
                                stderr=stderr,
                                close_fds=True,
                                shell=False,
                                env=environment,
                            )
                        except OSError:
                            _fail("restore_client_unavailable")
                        return_code = process.wait()
        if return_code != 0:
            raise BackupToolError("restore_import_failed", exit_status=return_code)
        return version
    except BackupToolError:
        raise
    except OSError:
        _fail("restore_io_failed")
