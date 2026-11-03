"""Public operator commands for the container deployment."""

import argparse
import http.client
import json
import os
import socket
import ssl
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from election.deployment.configuration import DeploymentError, prepare
from election.deployment.maintenance import (
    backup,
    finish,
    initialize,
    migrate,
    operator_lease,
    prepare_test_schema,
    reserve,
)
from election.private_paths import private_file
from election.server.backup_restore import RestoreError, restore
from election.server.backups import _file_hash, _source_hash
from election.server.config import Settings
from election.server.db import make_engine
from election.server.mysql_backup_tools import BackupToolError
from election.server.readiness import require_schema, schema_heads


def identity() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return {
        "format": "election-server-release-v1",
        "application_source_sha256": _source_hash(),
        "lock_sha256": _file_hash(root / "uv.lock"),
        "schema_heads": schema_heads(),
        "python": sys.version.split()[0],
    }


def load_environment(path: Path | None = None) -> None:
    path = path or Path(os.environ.get("ELECTION_ENV_FILE", "/run/election/server.env"))
    if not private_file(path):
        raise DeploymentError("private_configuration_unavailable")
    for key, value in dotenv_values(path, interpolate=False).items():
        if key.startswith("ELECTION_") and value is not None:
            os.environ[key] = value


def health() -> dict[str, str]:
    settings = Settings()
    context = ssl.create_default_context(cafile="/run/election/tls/ca.pem")
    with socket.create_connection(("127.0.0.1", settings.port), timeout=3) as connection:
        with context.wrap_socket(
            connection, server_hostname=os.environ["ELECTION_PUBLIC_HOST"]
        ) as tls:
            tls.sendall(b"GET /api/health HTTP/1.0\r\nHost: health\r\n\r\n")
            response = http.client.HTTPResponse(tls)
            response.begin()
            if response.status != 200:
                raise DeploymentError("api_unhealthy")
    return {"status": "healthy"}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "prepare":
        return prepare(
            args.root, args.host, args.bind, args.port, args.project, host_root=args.host_root
        )
    if args.command == "identity":
        return identity()
    load_environment()
    if args.command in {
        "initialize",
        "reserve",
        "backup",
        "migrate",
        "finish",
        "prepare-test",
        "restore",
    }:
        with operator_lease():
            return run_administration(args)
    if args.command == "health":
        return health()
    if args.command == "serve":
        from election.server.__main__ import main as serve

        serve()
        return {"status": "stopped"}
    engine = make_engine(Settings().database_url)
    try:
        return {"status": "ready", "schema_heads": require_schema(engine), **identity()}
    finally:
        engine.dispose()


def run_administration(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "reserve":
        return reserve()
    if args.command == "initialize":
        return initialize(args.username, args.display_name)
    if args.command == "backup":
        return backup(image_id=args.image_id)
    if args.command == "migrate":
        return migrate()
    if args.command == "finish":
        return finish()
    if args.command == "prepare-test":
        return prepare_test_schema(args.schema, restore_target=args.restore)
    if args.command == "restore":
        load_environment(Path(os.environ["ELECTION_ENV_FILE"]).parent / "restore.env")
        return restore(args.manifest, args.target_schema, None)
    raise DeploymentError("unknown_administration_command")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("identity", "serve", "health", "status", "reserve", "migrate", "finish"):
        commands.add_parser(name)
    setup = commands.add_parser("prepare")
    setup.add_argument("--root", type=Path, required=True)
    setup.add_argument("--host-root", type=Path)
    setup.add_argument("--host", required=True)
    setup.add_argument("--bind", default="127.0.0.1")
    setup.add_argument("--port", type=int, default=8443)
    setup.add_argument("--project", default="election-deployment")
    account = commands.add_parser("initialize")
    account.add_argument("--username", default="admin")
    account.add_argument("--display-name", default="Administrator")
    snapshot = commands.add_parser("backup", help="offline only: stop API writes first")
    snapshot.add_argument("--image-id")
    test = commands.add_parser("prepare-test", help="reserve a NEW disposable test schema")
    test.add_argument("--schema", required=True)
    test.add_argument("--restore", action="store_true")
    recovery = commands.add_parser("restore", help="separate existing _test target only")
    recovery.add_argument("--manifest", type=Path, required=True)
    recovery.add_argument("--target-schema", required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except EOFError:
        print(
            json.dumps({"status": "failed", "code": "administrator_input_unavailable"}),
            file=sys.stderr,
        )
        return 1
    except (DeploymentError, BackupToolError, RestoreError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}), file=sys.stderr)
        return 1
    except RuntimeError as error:
        code = (
            str(error)
            if str(error)
            in {
                "database_unavailable",
                "database_schema_incompatible",
                "deployment_maintenance_pending",
                "deployment_state_missing_or_unsafe",
            }
            else "deployment_command_failed"
        )
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 1
    except OSError, ValueError, KeyError, SQLAlchemyError, ValidationError:
        print(
            json.dumps({"status": "failed", "code": "deployment_command_failed"}), file=sys.stderr
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
