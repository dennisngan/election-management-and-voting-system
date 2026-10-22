"""Public-API arrangements for local and transferred ballot boxes."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.configuration_support import create_constituency, create_election
from tests.lifecycle_support import schedule_payload

INITIAL_PASSWORD = "Box-Initial-Test-42!"
READY_PASSWORD = "Box-Ready-Test-84!"


@dataclass
class BoxClock:
    value: datetime = field(default_factory=lambda: datetime(2026, 11, 15, 16, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.value


def box_stations(admin: TestClient, *, activate: bool = True) -> dict:
    election = create_election(admin)
    rows = {}
    for code, station_codes in (("N", ("N1", "N2", "N3")), ("S", ("S1",))):
        constituency = create_constituency(admin, election["id"], code)
        base = f"/api/elections/{election['id']}/constituencies/{constituency['id']}"
        candidate = admin.post(
            base + "/candidates",
            json={"name": "票箱測試候選人", "ballot_number": 1, "request_id": str(uuid4())},
        )
        assert candidate.status_code == 201
        for station_code in station_codes:
            payload = {
                "name": "票箱測試站 " + station_code,
                "code": station_code,
                "request_id": str(uuid4()),
            }
            if station_code == "N2":
                payload.update(counting_mode="send", destination_station_id=rows["N1"]["id"])
            station = admin.post(base + "/stations", json=payload)
            assert station.status_code == 201
            rows[station_code] = station.json()
            counter = admin.post(
                f"{base}/stations/{station.json()['id']}/counters",
                json={"name": "票箱測試櫃台", "code": "C1", "request_id": str(uuid4())},
            )
            assert counter.status_code == 201
    schedule = admin.put(f"/api/elections/{election['id']}/schedule", json=schedule_payload())
    assert schedule.status_code == 200
    if activate:
        activated = admin.post(
            f"/api/elections/{election['id']}/activate",
            json={"election_revision": election["revision"], "schedule_revision": 1},
        )
        assert activated.status_code == 200
    return {"election": election, **rows}


@contextmanager
def box_staff(
    admin: TestClient,
    database_url: str,
    clock: BoxClock,
    role: str,
    station_ids: list[int],
    *,
    ready: bool = True,
) -> Iterator[tuple[TestClient, dict]]:
    response = admin.post(
        "/api/accounts",
        json={
            "username": "box_" + uuid4().hex[:12],
            "display_name": "票箱測試職員",
            "role": role,
            "temporary_password": INITIAL_PASSWORD,
            "station_ids": station_ids,
        },
    )
    assert response.status_code == 201
    account = response.json()
    with TestClient(create_app(database_url, now=clock), base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={"username": account["username"], "password": INITIAL_PASSWORD},
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


def prepared_box(**changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "box_reference": "票箱 0001",
        "seal_reference": "封條 000099",
        "prepared_at": "2026-11-15T22:40:00+08:00",
        **changes,
    }


def event_command(revision: int, at: str, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "event_at": at,
        "reason": "",
        **changes,
    }
