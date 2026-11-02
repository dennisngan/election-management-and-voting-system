"""One-time private deployment material; never adopt development state."""

import ipaddress
import json
import os
import re
import secrets
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from election.private_paths import private_directory, private_file

API_UID = 10001
MYSQL_UID = 999
FORMAT = "election-deployment-v1"


class DeploymentError(RuntimeError):
    """Safe operator-facing error code, without credentials or command output."""


def private_write(path: Path, contents: str | bytes, *, uid: int = 0) -> None:
    data = contents.encode() if isinstance(contents, str) else contents
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if os.geteuid() == 0:
        os.chown(path, uid, uid)


def host_name(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        name = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise DeploymentError("invalid_server_host") from None
    if len(name) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in name.split(".")
    ):
        raise DeploymentError("invalid_server_host")
    return name


def deployment_metadata(root: Path) -> dict[str, Any]:
    if root.is_symlink():
        raise DeploymentError("deployment_path_is_symlink")
    path = root / "config/deployment.json"
    if not private_file(path):
        raise DeploymentError("unrecognized_deployment_directory")
    metadata: dict[str, Any] = json.loads(path.read_text())
    if metadata.get("format") != FORMAT:
        raise DeploymentError("unrecognized_deployment_directory")
    for name in ("mysql", "backups", "config", "config/state", "tls"):
        if (root / name).is_symlink() or not (root / name).is_dir():
            raise DeploymentError("deployment_path_missing_or_unsafe")
    for name in ("config", "backups", "config/state", "tls"):
        if not private_directory(root / name):
            raise DeploymentError("deployment_directory_not_private")
    for name in (
        "config/server.env",
        "config/compose.env",
        "config/mysql-root-password",
        "config/mysql-app-password",
        "config/mysql-health.cnf",
        "tls/ca-key.pem",
        "tls/ca.pem",
        "tls/server.pem",
        "tls/server-key.pem",
    ):
        if not private_file(root / name):
            raise DeploymentError("deployment_file_missing_or_unsafe")
    return metadata


def _certificates(root: Path, host: str) -> None:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Election deployment CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )
    try:
        alternative: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        alternative = x509.DNSName(host)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName([alternative]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    for name, key, uid in (("ca-key.pem", ca_key, 0), ("server-key.pem", server_key, API_UID)):
        private_write(
            root / "tls" / name,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            uid=uid,
        )
    for name, item in (("ca.pem", ca), ("server.pem", certificate)):
        private_write(
            root / "tls" / name, item.public_bytes(serialization.Encoding.PEM), uid=API_UID
        )


def prepare(
    root: Path, host: str, bind: str, port: int, project: str, *, host_root: Path | None = None
) -> dict[str, str]:
    host = host_name(host)
    try:
        ipaddress.ip_address(bind)
    except ValueError:
        raise DeploymentError("invalid_bind_address") from None
    if not 1 <= port <= 65535 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,50}", project):
        raise DeploymentError("invalid_port_or_project")
    root = root.absolute()
    if root.is_symlink():
        raise DeploymentError("deployment_path_is_symlink")
    if root.exists() and any(root.iterdir()):
        metadata = deployment_metadata(root)
        if any(
            metadata.get(key) != value
            for key, value in (("host", host), ("bind", bind), ("port", port), ("project", project))
        ):
            raise DeploymentError("deployment_configuration_differs")
        return {"status": "existing", "host": host}
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    for name, uid in (
        ("mysql", MYSQL_UID),
        ("backups", API_UID),
        ("config", 0),
        ("config/state", API_UID),
        ("tls", 0),
    ):
        path = root / name
        path.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(path, uid, uid)
    root_password, app_password = secrets.token_hex(32), secrets.token_hex(32)
    private_write(root / "config/mysql-root-password", root_password, uid=MYSQL_UID)
    private_write(root / "config/mysql-app-password", app_password, uid=MYSQL_UID)
    private_write(
        root / "config/mysql-health.cnf",
        f"[client]\nuser=root\npassword={root_password}\nhost=127.0.0.1\nprotocol=tcp\n",
        uid=MYSQL_UID,
    )
    private_write(
        root / "config/server.env",
        f"ELECTION_DATABASE_URL=mysql+pymysql://election:{app_password}@db:3306/election\n"
        "ELECTION_HOST=0.0.0.0\nELECTION_PORT=8443\n"
        "ELECTION_TLS_CERT=/run/election/tls/server.pem\n"
        "ELECTION_TLS_KEY=/run/election/tls/server-key.pem\n"
        "ELECTION_BACKUP_DIRECTORY=/var/lib/election/backups\n"
        "ELECTION_DEPLOY_STATE_DIR=/run/election/state\n"
        f"ELECTION_PUBLIC_HOST={host}\n",
        uid=API_UID,
    )
    settings = {
        "ELECTION_DEPLOY_ROOT": str(host_root or root),
        "ELECTION_DEPLOY_BIND": bind,
        "ELECTION_DEPLOY_PORT": str(port),
        "ELECTION_DEPLOY_PROJECT": project,
    }
    private_write(
        root / "config/compose.env",
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in settings.items()),
    )
    _certificates(root, host)
    private_write(
        root / "config/deployment.json",
        json.dumps(
            {
                "format": FORMAT,
                "id": secrets.token_hex(16),
                "host": host,
                "bind": bind,
                "port": port,
                "project": project,
            },
            indent=2,
        )
        + "\n",
    )
    return {"status": "prepared", "host": host}
