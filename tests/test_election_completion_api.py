"""Election completion is assessed through authenticated HTTP and real MySQL."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import draft_payload, polling_scope, ready_polling_staff


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_sees_actual_polling_completion_missing_for_each_required_station(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with ready_polling_staff(
        admin, database_url, "supervisor", station_ids
    ) as (supervisor, _):
        response = supervisor.get(
            f"/api/workspace/elections/{scope.election['id']}/completion"
        )
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["election"]["id"] == scope.election["id"]
        assert assessment["can_finalize"] is False
        missing = [
            row for row in assessment["blockers"]
            if row["code"] == "polling_completion_missing"
        ]
        assert missing == [
            {
                "code": "polling_completion_missing",
                "station_id": scope.stations[0]["id"],
                "constituency_id": scope.constituency["id"],
            },
            {
                "code": "polling_completion_missing",
                "station_id": scope.stations[1]["id"],
                "constituency_id": scope.constituency["id"],
            },
        ]
        assert assessment["sources"]["polling_completion"] == [
            {"station_id": scope.stations[0]["id"], "record": None},
            {"station_id": scope.stations[1]["id"], "record": None},
        ]


def test_draft_polling_completion_requires_current_approval(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station = scope.stations[0]
    station_ids = [row["id"] for row in scope.stations]
    with (
        ready_polling_staff(
            admin, database_url, "polling_officer", station_ids
        ) as (officer, _),
        ready_polling_staff(
            admin, database_url, "supervisor", station_ids
        ) as (supervisor, _),
    ):
        saved = officer.put(
            scope.path + "/service_completion",
            json=draft_payload(event_at="2025-11-15T22:40:00+08:00"),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "draft"
        response = supervisor.get(
            f"/api/workspace/elections/{scope.election['id']}/completion"
        )
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is False
        assert {
            "code": "polling_completion_approval_required",
            "station_id": station["id"],
            "constituency_id": scope.constituency["id"],
            "revision": 1,
            "status": "draft",
        } in assessment["blockers"]
        source = next(
            row["record"] for row in assessment["sources"]["polling_completion"]
            if row["station_id"] == station["id"]
        )
        assert source["revision"] == 1
        assert source["event_at"] == "2025-11-15T14:40:00Z"
        assert source["approved_at"] is None
        assert source["approved_by"] is None
