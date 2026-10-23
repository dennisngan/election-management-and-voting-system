"""Run migrations against the application's configured MySQL database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from election.server import (  # noqa: F401 -- register tables with Base.metadata
    allocation_models,
    box_models,
    complaint_models,
    complaint_period_models,
    configuration_models,
    lifecycle_models,
    models,
    polling_models,
    queue_models,
    staff_models,
    station_models,
    stock_models,
    stock_return_models,
    stock_snapshot_models,
    turnout_models,
)
from election.server.config import Settings
from election.server.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate migration SQL without creating a database connection."""
    context.configure(
        url=Settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a short-lived connection."""
    engine = create_engine(Settings().database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
