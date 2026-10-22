"""Public normal-turnout arrangements on a dedicated controlled-clock database."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Election
from election.server.db import make_engine
from election.server.lifecycle_models import ActiveElection
from tests.configuration_support import create_election
from tests.lifecycle_support import complete_configuration

INITIAL_PASSWORD = "Turnout-Initial-Test-42!"
READY_PASSWORD = "Turnout-Ready-Test-84!"


@dataclass
class TurnoutClock:
    value: datetime = field(default_factory=lambda: datetime(2026, 11, 15, 4, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.value


def turnout_scope(admin: TestClient, *, activate: bool = True, **changes: object) -> dict:
    election = create_election(admin)
    complete_configuration(admin, election["id"])
    planned = admin.put(
        f"/api/elections/{election['id']}/schedule",
        json={
            "election_date": "2026-11-15",
            "planned_opening_at": "2026-11-15T08:30:00+08:00",
            "planned_closing_at": "2026-11-15T11:10:00+08:00",
            "reporting_interval_minutes": 60,
            "revision": 0,
            **changes,
        },
    )
    assert planned.status_code == 200
    if activate:
        response = admin.post(
            f"/api/elections/{election['id']}/activate",
            json={"election_revision": election["revision"], "schedule_revision": 1},
        )
        assert response.status_code == 200
    options = admin.get("/api/accounts/station-options")
    assert options.status_code == 200
    stations = [
        row["station"] for row in options.json()["items"] if row["election"]["id"] == election["id"]
    ]
    return {
        "election": election,
        "stations": stations,
        "schedule": planned.json(),
        "path": f"/api/workspace/stations/{stations[0]['id']}/turnout",
    }


@contextmanager
def turnout_staff(
    admin: TestClient,
    database_url: str,
    clock: TurnoutClock,
    station_ids: list[int],
    role: str = "polling_officer",
    *,
    ready: bool = True,
) -> Iterator[tuple[TestClient, dict]]:
    created = admin.post(
        "/api/accounts",
        json={
            "username": "turnout_" + uuid4().hex[:12],
            "display_name": "投票人數測試職員",
            "role": role,
            "temporary_password": INITIAL_PASSWORD,
            "station_ids": station_ids,
        },
    )
    assert created.status_code == 201
    account = created.json()
    with TestClient(create_app(database_url, now=clock)) as client:
        login = client.post(
            "/api/auth/login", json={"username": account["username"], "password": INITIAL_PASSWORD}
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        if ready:
            changed = client.post(
                "/api/auth/password",
                json={"current_password": INITIAL_PASSWORD, "new_password": READY_PASSWORD},
            )
            assert changed.status_code == 200
            client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        yield client, account


def turnout_draft(expected_revision: int = 0, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": expected_revision,
        "expected_schedule_revision": 1,
        "supplied_hourly": None,
        "supplied_cumulative": None,
        "event_at": None,
        "source_context": "",
        **changes,
    }


def turnout_command(expected_revision: int, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": expected_revision,
        "expected_schedule_revision": 1,
        **changes,
    }


def submit_period(officer: TestClient, path: str, index: int, **content: object) -> dict:
    saved = officer.put(f"{path}/{index}", json=turnout_draft(**content))
    assert saved.status_code == 200
    submitted = officer.post(
        f"{path}/{index}/submit", json=turnout_command(saved.json()["revision"])
    )
    assert submitted.status_code == 200
    return submitted.json()


def approve_period(supervisor: TestClient, path: str, index: int, revision: int = 1) -> dict:
    approved = supervisor.post(
        f"{path}/{index}/approve", json=turnout_command(revision, password=READY_PASSWORD)
    )
    assert approved.status_code == 200
    return approved.json()


def arrange_finalized_turnout_election(database_url: str, election_id: int) -> None:
    """Arrange read-only history without claiming the future finalization workflow."""
    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.database and parsed.database.endswith("_lifecycle_test")
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            db.execute(
                update(ActiveElection)
                .where(ActiveElection.election_id == election_id)
                .values(election_id=None)
            )
            db.execute(
                update(Election).where(Election.id == election_id).values(status="finalized")
            )
            db.commit()
    finally:
        engine.dispose()
