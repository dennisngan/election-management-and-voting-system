"""One-command Compose initialization; only config.yml is operator-managed."""

import argparse
import json
import os
import sys
from pathlib import Path

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from election.deployment.__main__ import load_environment
from election.deployment.configuration import (
    API_UID,
    MYSQL_UID,
    DeploymentError,
    deployment_metadata,
    prepare,
    private_write,
)
from election.deployment.maintenance import migration_config, operator_lease, state_directory
from election.deployment.quick_config import QuickConfig, load_quick_config, seed_accounts
from election.private_paths import private_file
from election.server.config import Settings
from election.server.db import make_engine
from election.server.readiness import require_schema


def _directory(path: Path, uid: int) -> None:
    if path.is_symlink() or path.exists() and not path.is_dir():
        raise DeploymentError("quickstart_storage_unsafe")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)
    if os.geteuid() == 0:
        os.chown(path, uid, uid)


def _copy_generated(source: Path, destination: Path, uid: int) -> None:
    if destination.exists() or destination.is_symlink():
        if not private_file(destination) or destination.read_bytes() != source.read_bytes():
            raise DeploymentError("quickstart_generated_state_differs")
        return
    private_write(destination, source.read_bytes(), uid=uid)


def prepare_runtime(
    config: QuickConfig,
    bootstrap: Path,
    runtime: Path,
    database_secrets: Path,
    backups: Path,
    *,
    mysql_data: Path | None = None,
) -> dict[str, str]:
    fresh = not (bootstrap / "config/deployment.json").exists()
    if fresh and mysql_data is not None and mysql_data.exists() and any(mysql_data.iterdir()):
        raise DeploymentError("quickstart_database_directory_not_empty")
    if fresh and any(
        path.exists() and any(path.iterdir()) for path in (runtime, database_secrets, backups)
    ):
        raise DeploymentError("quickstart_private_state_already_exists")
    prepare(bootstrap, config.server.host, "127.0.0.1", 8443, "election-quickstart")
    metadata = deployment_metadata(bootstrap)
    if metadata["host"] != config.server.host:
        raise DeploymentError("quickstart_server_identity_changed")
    identity = bootstrap / "config/quickstart.json"
    expected = {"format": "election-quickstart-v1", "mysql": config.storage.mysql}
    if identity.exists():
        if json.loads(identity.read_text()) != expected:
            raise DeploymentError("quickstart_database_path_changed")
    else:
        private_write(identity, json.dumps(expected) + "\n")
    for path in (runtime, runtime / "state", runtime / "tls", backups):
        _directory(path, API_UID)
    _directory(database_secrets, MYSQL_UID)
    _copy_generated(bootstrap / "config/server.env", runtime / "server.env", API_UID)
    for name in ("ca.pem", "server.pem", "server-key.pem"):
        _copy_generated(bootstrap / "tls" / name, runtime / "tls" / name, API_UID)
    for source, target in (
        ("mysql-root-password", "root-password"),
        ("mysql-app-password", "app-password"),
        ("mysql-health.cnf", "health.cnf"),
    ):
        _copy_generated(bootstrap / "config" / source, database_secrets / target, MYSQL_UID)
    return {"status": "configured"}


def initialize_accounts(config: QuickConfig, runtime: Path) -> dict[str, object]:
    os.environ["ELECTION_ENV_FILE"] = str(runtime / "server.env")
    load_environment()
    with operator_lease():
        marker = state_directory() / "initialized.json"
        engine = make_engine(Settings().database_url)
        try:
            with engine.connect() as connection:
                tables = inspect(connection).get_table_names()
            if not tables:
                if marker.exists():
                    raise DeploymentError("initialized_database_is_empty")
                command.upgrade(migration_config(), "head")
            require_schema(engine)
            created = seed_accounts(engine, config.accounts)
            if not marker.exists():
                private_write(
                    marker, json.dumps({"format": "election-quickstart-v1"}) + "\n", uid=API_UID
                )
            return {"status": "initialized", "accounts_created": created}
        finally:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "initialize"))
    parser.add_argument("--config", type=Path, default=Path("/config.yml"))
    parser.add_argument("--bootstrap", type=Path, default=Path("/bootstrap"))
    parser.add_argument("--runtime", type=Path, default=Path("/run/election"))
    parser.add_argument("--database-secrets", type=Path, default=Path("/db-secrets"))
    parser.add_argument("--backups", type=Path, default=Path("/var/lib/election/backups"))
    parser.add_argument("--mysql-data", type=Path, default=Path("/mysql-data"))
    args = parser.parse_args()
    try:
        config = load_quick_config(args.config)
        result = (
            prepare_runtime(
                config,
                args.bootstrap,
                args.runtime,
                args.database_secrets,
                args.backups,
                mysql_data=args.mysql_data,
            )
            if args.command == "prepare"
            else initialize_accounts(config, args.runtime)
        )
    except DeploymentError as error:
        print(json.dumps({"status": "failed", "code": str(error)}), file=sys.stderr)
        return 1
    except OSError, ValueError, KeyError, SQLAlchemyError:
        print(json.dumps({"status": "failed", "code": "quickstart_failed"}), file=sys.stderr)
        return 1
    except RuntimeError as error:
        code = (
            str(error)
            if str(error)
            in {
                "database_unavailable",
                "database_schema_incompatible",
                "deployment_maintenance_pending",
            }
            else "quickstart_failed"
        )
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
