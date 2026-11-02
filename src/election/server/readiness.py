"""Read-only schema compatibility checks; startup never applies migrations."""

import os
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from election.private_paths import private_directory


def schema_heads() -> list[str]:
    root = Path(__file__).resolve().parents[3]
    return sorted(ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads())


def require_schema(engine: Engine, *, allow_maintenance: bool = False) -> list[str]:
    state = os.environ.get("ELECTION_DEPLOY_STATE_DIR")
    if state and not allow_maintenance:
        directory = Path(state)
        if not private_directory(directory):
            raise RuntimeError("deployment_state_missing_or_unsafe")
        marker = directory / "maintenance.json"
        if marker.exists() or marker.is_symlink():
            raise RuntimeError("deployment_maintenance_pending")
    try:
        with engine.connect() as connection:
            current = sorted(MigrationContext.configure(connection).get_current_heads())
    except SQLAlchemyError:
        raise RuntimeError("database_unavailable") from None
    if current != schema_heads():
        raise RuntimeError("database_schema_incompatible")
    return current
