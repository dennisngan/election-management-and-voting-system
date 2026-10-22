"""Use a named, disposable MySQL test database; never substitute SQLite."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.getenv("ELECTION_TEST_DATABASE_URL") or dotenv_values(".env").get(
        "ELECTION_TEST_DATABASE_URL"
    )
    if not url:
        pytest.fail("Set ELECTION_TEST_DATABASE_URL to a dedicated MySQL database ending in _test")
    parsed = make_url(url)
    assert parsed.drivername == "mysql+pymysql", "These checks require real MySQL"
    assert parsed.database and parsed.database.endswith("_test"), "Refusing non-test database"
    original = os.environ.get("ELECTION_DATABASE_URL")
    os.environ["ELECTION_DATABASE_URL"] = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield url
    finally:
        if original is None:
            os.environ.pop("ELECTION_DATABASE_URL", None)
        else:
            os.environ["ELECTION_DATABASE_URL"] = original
