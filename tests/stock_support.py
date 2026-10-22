"""Public-API arrangements for received-stock journeys."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.configuration_support import create_constituency, create_election

INITIAL_PASSWORD = "Stock-Initial-Test-42!"
READY_PASSWORD = "Stock-Ready-Test-84!"


def stock_payload(**changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "series": "普通系列 A",
        "event_at": "2026-11-08T08:00:00+08:00",
        "ranges": [
            {"pool": "ordinary", "serial_from": "000001", "serial_to": "000008"},
            {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
            {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
        ],
        "ordinary_quantity": 8,
        "replacement_quantity": 1,
        "tendered_quantity": 1,
        **changes,
    }


def stock_stations(admin: TestClient) -> list[dict]:
    election = create_election(admin)
    rows = []
    for constituency_code, station_codes in (("N", ("N1", "N2")), ("S", ("S1",))):
        constituency = create_constituency(admin, election["id"], constituency_code)
        base = f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations"
        for code in station_codes:
            response = admin.post(
                base, json={"name": "收票測試站 " + code, "code": code, "request_id": str(uuid4())}
            )
            assert response.status_code == 201
            rows.append(response.json())
    return rows


def staff_account(admin: TestClient, station_ids: list[int], role: str = "polling_officer") -> dict:
    response = admin.post(
        "/api/accounts",
        json={
            "username": "stock_" + uuid4().hex[:12],
            "display_name": "選票接收測試職員",
            "role": role,
            "temporary_password": INITIAL_PASSWORD,
            "enabled": True,
            "station_ids": station_ids,
        },
    )
    assert response.status_code == 201
    return response.json()


@contextmanager
def ready_client(database_url: str, account: dict) -> Iterator[TestClient]:
    with TestClient(create_app(database_url), base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login", json={"username": account["username"], "password": INITIAL_PASSWORD}
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = client.post(
            "/api/auth/password",
            json={"current_password": INITIAL_PASSWORD, "new_password": READY_PASSWORD},
        )
        assert changed.status_code == 200
        client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        yield client
