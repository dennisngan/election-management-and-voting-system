"""Public API arrangements for complaint catalogs and station case work."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import box_stations


@dataclass
class ComplaintClock:
    value: datetime = field(default_factory=lambda: datetime(2026, 11, 15, 16, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.value


def complaint_stations(admin: TestClient, *, activate: bool = True) -> dict:
    return box_stations(admin, activate=activate)


@contextmanager
def complaint_staff(
    admin: TestClient,
    database_url: str,
    clock: ComplaintClock,
    role: str,
    station_ids: list[int],
    *,
    ready: bool = True,
) -> Iterator[tuple[TestClient, dict]]:
    initial, password = "Complaint-Initial-Test-42!", "Complaint-Ready-Test-84!"
    created = admin.post(
        "/api/accounts",
        json={
            "username": "complaint_" + uuid4().hex[:12],
            "display_name": "投訴測試職員",
            "role": role,
            "temporary_password": initial,
            "station_ids": station_ids,
        },
    )
    assert created.status_code == 201
    account = created.json()
    with TestClient(create_app(database_url, now=clock), base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login", json={"username": account["username"], "password": initial}
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        if ready:
            changed = client.post(
                "/api/auth/password",
                json={"current_password": initial, "new_password": password},
            )
            assert changed.status_code == 200
            client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        yield client, account


def complaint_payload(category: dict, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "case_reference": "投訴 0001",
        "received_at": "2026-11-15T08:15:00+08:00",
        "category_id": category["id"],
        "expected_category_revision": category["revision"],
        "description": "投票站入口安排需要協助。",
        "work_status": "in_progress",
        "completed_at": None,
        "reason": "",
        **changes,
    }


def station_categories(client: TestClient, station_id: int) -> list[dict]:
    response = client.get(f"/api/workspace/stations/{station_id}/complaint-categories")
    assert response.status_code == 200
    return response.json()["items"]


def category_edit(category: dict, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": category["revision"],
        "label_en": category["label_en"],
        "label_tc": category["label_tc"],
        "label_sc": category["label_sc"],
        "enabled": category["enabled"],
        "description_required": category["description_required"],
        **changes,
    }
