"""Opt-in local development tools; never used by a packaged desktop client."""

import ipaddress
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def write_private(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(content.encode() if isinstance(content, str) else content)
    path.chmod(0o600)


def mysql_dev() -> None:
    runtime = Path(".runtime").resolve()
    runtime.mkdir(exist_ok=True)
    env_file = runtime / "mysql.env"
    if not env_file.exists():
        if Path(".env").exists():
            raise SystemExit(
                "An .env already exists; configure MySQL explicitly instead of overwriting it"
            )
        root_password = secrets.token_hex(24)
        app_password = secrets.token_hex(24)
        write_private(
            env_file,
            f"MYSQL_ROOT_PASSWORD={root_password}\nMYSQL_DATABASE=election\n"
            f"MYSQL_USER=election\nMYSQL_PASSWORD={app_password}\n",
        )
        base = f"mysql+pymysql://election:{app_password}@127.0.0.1:13307/"
        write_private(
            Path(".env"),
            f"ELECTION_DATABASE_URL={base}election\n"
            f"ELECTION_TEST_DATABASE_URL={base}election_test\n"
            "ELECTION_SERVER_URL=https://localhost:8443\n"
            "ELECTION_CA_FILE=.runtime/tls/ca.pem\n",
        )
    existing = subprocess.run(
        ["docker", "container", "inspect", "election-system-mysql"],
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0:
        label = subprocess.check_output(
            [
                "docker",
                "container",
                "inspect",
                "election-system-mysql",
                "--format",
                '{{index .Config.Labels "project"}}',
            ],
            text=True,
        ).strip()
        if label != "election-system":
            raise SystemExit("Container name belongs to another project; refusing to use it")
        subprocess.run(["docker", "start", "election-system-mysql"], check=True)
    else:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                "election-system-mysql",
                "--label",
                "project=election-system",
                "--publish",
                "127.0.0.1:13307:3306",
                "--env-file",
                str(env_file),
                "--mount",
                "type=volume,src=election-system-mysql-data,dst=/var/lib/mysql",
                "--health-cmd",
                "mysqladmin ping -h 127.0.0.1 --silent",
                "--health-interval",
                "2s",
                "--health-retries",
                "30",
                "mysql:8.4",
            ],
            check=True,
        )
    for _ in range(45):
        probe = subprocess.run(
            [
                "docker",
                "exec",
                "election-system-mysql",
                "sh",
                "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=TCP -h127.0.0.1 '
                '-uroot -e "SELECT 1"',
            ],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SystemExit("MySQL is still initializing; inspect docker logs and rerun mysql-dev")
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "election-system-mysql",
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot',
        ],
        input="CREATE DATABASE IF NOT EXISTS election_test CHARACTER SET utf8mb4;\n"
        "GRANT ALL PRIVILEGES ON election_test.* TO 'election'@'%';\n",
        text=True,
        check=True,
    )
    print("Local MySQL ready on 127.0.0.1:13307; development secrets are in ignored .env.")


def tls_dev() -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = Path(".runtime/tls")
    if any((directory / name).exists() for name in ("ca.pem", "server.pem", "server-key.pem")):
        raise SystemExit(
            "TLS files already exist; refusing to replace trusted development certificates"
        )
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Election local development CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    write_private(directory / "ca.pem", ca.public_bytes(serialization.Encoding.PEM))
    write_private(directory / "server.pem", certificate.public_bytes(serialization.Encoding.PEM))
    write_private(
        directory / "server-key.pem",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    print("Local HTTPS certificate created. Trust ca.pem only for this development client.")
