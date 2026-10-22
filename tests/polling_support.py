"""Arrange polling-event tests through the approved public MySQL-backed API."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Election
from election.server.db import make_engine
from election.server.lifecycle_models import ActiveElection
from tests.configuration_support import create_constituency, create_election

INITIAL_PASSWORD = "Polling-Initial-Test-42!"
READY_PASSWORD = "Polling-Ready-Test-84!"


@dataclass(frozen=True)
class PollingScope:
    election: dict[str, Any]
    constituency: dict[str, Any]
    stations: list[dict[str, Any]]
    schedule: dict[str, Any]

    @property
    def path(self) -> str:
        return f"/api/workspace/stations/{self.stations[0]['id']}/polling"


def polling_scope(admin: TestClient, *, activate: bool = True) -> PollingScope:
    election = create_election(admin)
    constituency = create_constituency(admin, election["id"])
    base = f"/api/elections/{election['id']}/constituencies/{constituency['id']}"
    candidate = admin.post(
        base + "/candidates",
        json={"name": "票站流程測試候選人", "ballot_number": 1, "request_id": str(uuid4())},
    )
    assert candidate.status_code == 201
    stations = []
    for code in ("P1", "P2"):
        created = admin.post(
            base + "/stations",
            json={"name": "流程測試票站 " + code, "code": code, "request_id": str(uuid4())},
        )
        assert created.status_code == 201
        station = created.json()
        counter = admin.post(
            f"{base}/stations/{station['id']}/counters",
            json={"name": "流程測試櫃台", "code": "C1", "request_id": str(uuid4())},
        )
        assert counter.status_code == 201
        stations.append(station)
    # Deliberately past dates permit actual-event checks without depending on host time.
    planned = admin.put(
        f"/api/elections/{election['id']}/schedule",
        json={
            "election_date": "2025-11-15",
            "planned_opening_at": "2025-11-15T07:30:00+08:00",
            "planned_closing_at": "2025-11-15T22:30:00+08:00",
            "reporting_interval_minutes": 30,
            "revision": 0,
        },
    )
    assert planned.status_code == 200
    if activate:
        activated = admin.post(
            f"/api/elections/{election['id']}/activate",
            json={"election_revision": election["revision"], "schedule_revision": 1},
        )
        assert activated.status_code == 200
        election = activated.json()["election"]
    return PollingScope(election, constituency, stations, planned.json())


@contextmanager
def ready_polling_staff(
    admin: TestClient,
    database_url: str,
    role: str,
    station_ids: list[int],
    *,
    password: str = READY_PASSWORD,
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    created = admin.post(
        "/api/accounts",
        json={
            "username": "polling_event_" + uuid4().hex[:12],
            "display_name": "票站流程測試職員",
            "role": role,
            "station_ids": station_ids,
            "temporary_password": INITIAL_PASSWORD,
        },
    )
    assert created.status_code == 201
    account = created.json()
    with TestClient(create_app(database_url)) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": account["username"], "password": INITIAL_PASSWORD},
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = client.post(
            "/api/auth/password",
            json={"current_password": INITIAL_PASSWORD, "new_password": password},
        )
        assert changed.status_code == 200
        client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        yield client, changed.json()["account"]


def draft_payload(revision: int = 0, **changes: object) -> dict[str, object]:
    return {
        "revision": revision,
        "request_id": str(uuid4()),
        "event_at": None,
        "estimated_clear_at": None,
        "reason": "",
        **changes,
    }


def transition_payload(revision: int, **changes: object) -> dict[str, object]:
    return {"revision": revision, "request_id": str(uuid4()), **changes}


def arrange_retained_polling_election(database_url: str, election_id: int) -> None:
    """Arrange history without claiming Ticket 24's unimplemented finalization flow."""
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
