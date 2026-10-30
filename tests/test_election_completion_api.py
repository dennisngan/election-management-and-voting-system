"""Election completion is assessed through authenticated HTTP and real MySQL."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.complaint_support import complaint_payload, station_categories
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import (
    READY_PASSWORD,
    draft_payload,
    polling_scope,
    ready_polling_staff,
    transition_payload,
)


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


def test_approved_polling_still_requires_each_stations_box_handover(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_ids = [row["id"] for row in scope.stations]
    with (
        ready_polling_staff(
            admin, database_url, "polling_officer", station_ids
        ) as (officer, _),
        ready_polling_staff(
            admin, database_url, "supervisor", station_ids
        ) as (supervisor, _),
    ):
        for station_id in station_ids:
            path = f"/api/workspace/stations/{station_id}/polling/service_completion"
            saved = officer.put(
                path, json=draft_payload(event_at="2025-11-15T22:40:00+08:00")
            )
            assert saved.status_code == 200, saved.text
            submitted = officer.post(path + "/submit", json=transition_payload(1))
            assert submitted.status_code == 200, submitted.text
            approved = supervisor.post(
                path + "/approve",
                json=transition_payload(1, password=READY_PASSWORD),
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
        response = supervisor.get(
            f"/api/workspace/elections/{scope.election['id']}/completion"
        )
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is False
        assert not any(
            row["code"].startswith("polling_completion_")
            for row in assessment["blockers"]
        )
        assert [
            row for row in assessment["blockers"]
            if row["code"] == "station_boxes_missing"
        ] == [
            {
                "code": "station_boxes_missing",
                "station_id": station_id,
                "constituency_id": scope.constituency["id"],
                "box_ids": [],
            }
            for station_id in station_ids
        ]


def test_fully_reviewed_active_election_is_ready_despite_provisional_display(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        response = setup["clients"]["supervisor"].get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["election"]["status"] == "active"
        assert assessment["active_election_id"] == setup["election"]["id"]
        assert assessment["blockers"] == []
        results = assessment["sources"]["constituencies"]
        assert len(results) == 2
        assert all(result["complete"] for result in results)
        assert all(result["provisional"] for result in results)
        assert [
            [candidate["quantity"] for candidate in result["candidate_totals"]]
            for result in results
        ] == [[6, 4], [4, 1]]
        assert assessment["can_finalize"] is True


def test_result_affecting_tie_requires_current_supervisor_resolution(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url, n1_quantities=(5, 5)) as setup:
        supervisor = setup["clients"]["supervisor"]
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        north = assessment["sources"]["constituencies"][0]
        assert north["complete"] is True
        assert [row["quantity"] for row in north["candidate_totals"]] == [5, 5]
        assert north["resolved_candidate_id"] is None
        assert assessment["can_finalize"] is False
        assert {
            "code": "result_tie_resolution_required",
            "constituency_id": setup["constituency_id"],
            "candidate_ids": north["tie_candidate_ids"],
        } in assessment["blockers"]
        resolved = supervisor.post(
            f"/api/workspace/constituencies/{setup['constituency_id']}"
            "/results/tie-resolutions",
            json={
                "request_id": str(uuid4()), "expected_resolution_revision": 0,
                "basis_digest": north["basis_digest"],
                "candidate_id": north["tie_candidate_ids"][0],
                "reason": "Record the authorized tie outcome before finalization.",
                "password": BOX_READY_PASSWORD,
            },
        )
        assert resolved.status_code == 200, resolved.text
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["blockers"] == []
        assert current.json()["can_finalize"] is True
        assert current.json()["basis_digest"] != assessment["basis_digest"]


def test_completion_retains_unresolved_complaint_status_without_inventing_resolution(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        officer = setup["clients"]["polling"]
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        category = station_categories(officer, station_id)[0]
        created = officer.post(
            f"/api/workspace/stations/{station_id}/complaints",
            json=complaint_payload(category),
        )
        assert created.status_code == 201, created.text
        complaint = created.json()
        assert complaint["work_status"] == "in_progress"
        assert complaint["completed_at"] is None
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is True
        assert assessment["blockers"] == []
        assert {
            "station_id": station_id, "records": [complaint],
        } in assessment["sources"]["complaints"]
        current = officer.get(
            f"/api/workspace/stations/{station_id}/complaints/{complaint['id']}"
        )
        assert current.status_code == 200, current.text
        assert current.json() == complaint
