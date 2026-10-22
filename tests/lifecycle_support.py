"""Isolated lifecycle test database and public API setup helpers."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.server.configuration_models import Election
from election.server.db import make_engine
from election.server.lifecycle_models import ActiveElection
from tests.configuration_support import create_constituency, create_election


def lifecycle_database_url() -> Iterator[str]:
    url = os.getenv("ELECTION_LIFECYCLE_TEST_DATABASE_URL") or dotenv_values(".env").get(
        "ELECTION_LIFECYCLE_TEST_DATABASE_URL"
    )
    if not url:
        pytest.fail(
            "Set ELECTION_LIFECYCLE_TEST_DATABASE_URL to a dedicated MySQL lifecycle test DB"
        )
    parsed = make_url(url)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.database and parsed.database.endswith("_lifecycle_test")
    previous = os.environ.get("ELECTION_DATABASE_URL")
    os.environ["ELECTION_DATABASE_URL"] = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("ELECTION_DATABASE_URL", None)
        else:
            os.environ["ELECTION_DATABASE_URL"] = previous


@contextmanager
def lifecycle_test_state(database_url: str) -> Iterator[None]:
    # This arrangement is confined to election_lifecycle_test; election_test is untouched.
    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.database and parsed.database.endswith("_lifecycle_test")
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            db.execute(update(ActiveElection).values(election_id=None, revision=1, updated_at=None))
            db.execute(update(Election).where(Election.status == "active").values(status="draft"))
            db.commit()
        yield
    finally:
        engine.dispose()


def schedule_payload(**changes: object) -> dict:
    return {
        "election_date": "2026-11-15",
        "planned_opening_at": "2026-11-15T07:30:00+08:00",
        "planned_closing_at": "2026-11-15T22:30:00+08:00",
        "reporting_interval_minutes": 60,
        "revision": 0,
        **changes,
    }


def complete_configuration(admin: TestClient, election_id: int) -> None:
    for code in ("N", "S"):
        constituency = create_constituency(admin, election_id, code)
        base = f"/api/elections/{election_id}/constituencies/{constituency['id']}"
        candidate = admin.post(
            base + "/candidates",
            json={"name": "候選人 " + code, "ballot_number": 1, "request_id": str(uuid4())},
        )
        assert candidate.status_code == 201
        station = admin.post(
            base + "/stations",
            json={"name": "票站 " + code, "code": "P1", "request_id": str(uuid4())},
        )
        assert station.status_code == 201
        counter = admin.post(
            f"{base}/stations/{station.json()['id']}/counters",
            json={"name": "發票櫃台", "code": "C1", "request_id": str(uuid4())},
        )
        assert counter.status_code == 201


def prepared_election(admin: TestClient) -> tuple[dict, dict]:
    election = create_election(admin)
    complete_configuration(admin, election["id"])
    response = admin.put(f"/api/elections/{election['id']}/schedule", json=schedule_payload())
    assert response.status_code == 200
    return election, response.json()
