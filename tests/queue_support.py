"""Public queue arrangements with a controlled server clock."""

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
from tests.lifecycle_support import prepared_election

INITIAL_PASSWORD = "Queue-Initial-Test-42!"
READY_PASSWORD = "Queue-Ready-Test-84!"


@dataclass
class QueueClock:
    value: datetime = field(default_factory=lambda: datetime(2026, 11, 15, 0, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.value


def active_queue_stations(admin: TestClient) -> list[dict]:
    election, schedule = prepared_election(admin)
    activated = admin.post(
        f"/api/elections/{election['id']}/activate",
        json={
            "election_revision": election["revision"],
            "schedule_revision": schedule["revision"],
        },
    )
    assert activated.status_code == 200
    contexts = admin.get("/api/accounts/station-options")
    assert contexts.status_code == 200
    return [row for row in contexts.json()["items"] if row["election"]["id"] == election["id"]]


def queue_account(admin: TestClient, station_ids: list[int], role: str = "polling_officer") -> dict:
    response = admin.post(
        "/api/accounts",
        json={
            "username": "queue_" + uuid4().hex[:12],
            "display_name": "輪候紀錄測試職員",
            "role": role,
            "temporary_password": INITIAL_PASSWORD,
            "enabled": True,
            "station_ids": station_ids,
        },
    )
    assert response.status_code == 201
    return response.json()


@contextmanager
def queue_client(
    database_url: str, account: dict, clock: QueueClock, *, ready: bool = True
) -> Iterator[TestClient]:
    with TestClient(create_app(database_url, now=clock), base_url="https://testserver") as client:
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
        yield client


def observation(clock: QueueClock, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "event_at": clock.value.isoformat(),
        "band": "under_30",
        "reason": "",
        **changes,
    }


def arrange_retained_queue_election(database_url: str, election_id: int) -> None:
    """Arrange retained history without implementing the future finalization workflow."""
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
