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
from tests.stock_support import stock_payload


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


def test_latest_instructed_constituency_recount_blocks_election_readiness(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        before = supervisor.get(setup["completion_path"])
        assert before.status_code == 200, before.text
        assert before.json()["can_finalize"] is True
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        options = supervisor.get(path)
        assert options.status_code == 200, options.text
        current = options.json()
        created = supervisor.post(path, json={
            "request_id": str(uuid4()), "basis_digest": current["basis_digest"],
            "scope_sources": current["scope_sources"],
            "event_at": "2026-11-16T00:00:00+08:00",
            "reason": "Require a fresh constituency count before finalization.",
            "password": BOX_READY_PASSWORD,
        })
        assert created.status_code == 201, created.text
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is False
        pending = [row for row in assessment["blockers"] if row["code"] == "recount_pending"]
        assert {row["scope_id"] for row in pending} == {
            setup["scope"]["id"], setup["n3_scope"]["id"],
        }
        assert {row["new_round_id"] for row in pending} == {
            member["round"]["id"] for member in created.json()["members"]
        }
        assert all(row["constituency_id"] == setup["constituency_id"] for row in pending)
        assert assessment["basis_digest"] != before.json()["basis_digest"]


def test_partial_tied_totals_do_not_demand_premature_tie_resolution(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url, n1_quantities=(5, 5)) as setup:
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        options = supervisor.get(base)
        assert options.status_code == 200, options.text
        source = next(
            row for row in options.json()["scope_sources"]
            if row["scope_id"] == setup["n3_scope"]["id"]
        )
        instructed = supervisor.post(
            f"/api/workspace/stations/{source['station_id']}"
            f"/counting-scopes/{source['scope_id']}/recounts",
            json={
                "request_id": str(uuid4()), "scope_revision": source["scope_revision"],
                "expected_selection_revision": source["expected_selection_revision"],
                "source_round_id": source["source_round_id"],
                "source_round_revision": source["source_round_revision"],
                "event_at": "2026-11-16T00:00:00+08:00",
                "reason": "Finish the instructed count before deciding the final tie.",
                "password": BOX_READY_PASSWORD,
            },
        )
        assert instructed.status_code == 201, instructed.text
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is False
        north = assessment["sources"]["constituencies"][0]
        assert north["complete"] is False
        assert [row["quantity"] for row in north["candidate_totals"]] == [5, 5]
        assert any(row["code"] == "recount_pending" for row in assessment["blockers"])
        assert not any(
            row["code"] == "result_tie_resolution_required"
            for row in assessment["blockers"]
        )


def test_later_stock_receipt_invalidates_reviewed_accounting_and_selected_count(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        before = supervisor.get(setup["completion_path"])
        assert before.status_code == 200, before.text
        assert before.json()["can_finalize"] is True
        station_id = setup["stations"]["N1"]["id"]
        changed = setup["clients"]["polling"].post(
            f"/api/workspace/stations/{station_id}/stock",
            json=stock_payload(
                event_at="2026-11-15T10:00:00+08:00", ordinary_quantity=5,
                replacement_quantity=0, tendered_quantity=0,
                ranges=[
                    {"pool": "ordinary", "serial_from": "000100", "serial_to": "000104"}
                ],
            ),
        )
        assert changed.status_code == 201, changed.text
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is False
        scope_blockers = [
            row for row in assessment["blockers"]
            if row.get("scope_id") == setup["scope"]["id"]
        ]
        assert {row["code"] for row in scope_blockers} == {
            "scope_not_ready", "selected_count_stale",
        }
        for blocker in scope_blockers:
            source = next(
                row for row in blocker["source_accounting_revisions"]
                if row["station_id"] == station_id
            )
            assert source["record_id"] == setup["accounting"]["N1"]["record"]["id"]
            assert source["revision"] == 1 and source["status"] == "approved"
            # These are the preserved scope's original approved source facts.
            assert source["source_current"] is True
            assert source["approval_valid"] is True
            current = next(
                row for row in blocker["current_source_accounting_revisions"]
                if row["station_id"] == station_id
            )
            assert current["record_id"] == source["record_id"]
            assert current["revision"] == 1 and current["status"] == "approved"
            assert current["source_current"] is False
            assert current["approval_valid"] is False
        current_accounting = next(
            row["record"] for row in assessment["sources"]["accounting"]
            if row["station_id"] == station_id
        )
        assert current_accounting["id"] == setup["accounting"]["N1"]["record"]["id"]
        assert current_accounting["source_current"] is False
        assert assessment["basis_digest"] != before.json()["basis_digest"]


def test_completion_preserves_selected_count_physical_disposition(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(
        admin, database_url, n1_quantities=(5, 3), n1_selected=False,
    ) as setup:
        supervisor = setup["clients"]["supervisor"]
        n1 = setup["n1_round"]
        target, submitted = n1["round_path"], n1["submitted"]
        scope_id = setup["scope"]["id"]
        scope_revision = n1["options"]["scope"]["revision"]
        assert submitted["revision"] == 3 and submitted["status"] == "submitted"
        stock = next(row for row in submitted["physical_comparisons"] if row["source"] == "stock")
        assert submitted["actual_counted_quantity"] == 8
        assert stock["expected_quantity"] == 10 and stock["actual_quantity"] == 8
        assert stock["difference_quantity"] == -2 and stock["status"] == "pending"
        before = supervisor.get(setup["completion_path"])
        assert before.status_code == 200, before.text
        assert before.json()["can_finalize"] is False
        assert any(
            row["code"] == "selected_count_missing" and row.get("scope_id") == scope_id
            for row in before.json()["blockers"]
        )
        other_sources = {
            row["scope_id"]: (row["round_id"], row["round_revision_id"])
            for result in before.json()["sources"]["constituencies"]
            for row in result["contributions"]
        }
        assert set(other_sources) == {setup["n3_scope"]["id"], setup["s1_scope"]["id"]}
        denied = supervisor.post(target + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": 3,
            "scope_revision": scope_revision, "password": BOX_READY_PASSWORD,
        })
        assert denied.status_code == 409, denied.text
        assert denied.json() == {"detail": {"code": "count_physical_difference_unaccepted"}}
        unchanged = supervisor.get(target)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["record"]["revision_id"] == submitted["revision_id"]
        assert unchanged.json()["record"]["actual_counted_quantity"] == 8
        reason = "Signed paper count confirms eight papers; accept the stock estimate difference."
        accepted = supervisor.post(target + "/physical-differences/stock/accept", json={
            "request_id": str(uuid4()), "expected_revision": 3,
            "scope_revision": scope_revision, "expected_decision_revision": 0,
            "reason": reason, "password": BOX_READY_PASSWORD,
        })
        assert accepted.status_code == 200, accepted.text
        accepted_record = accepted.json()
        assert accepted_record["revision"] == 3 and accepted_record["status"] == "submitted"
        for field in (
            "actual_counted_quantity", "candidate_votes", "invalid_papers", "f2", "scope_basis",
        ):
            assert accepted_record[field] == submitted[field]
        stock = next(
            row for row in accepted_record["physical_comparisons"] if row["source"] == "stock"
        )
        assert stock["expected_quantity"] == 10 and stock["actual_quantity"] == 8
        assert stock["difference_quantity"] == -2 and stock["status"] == "accepted"
        decision = stock["acceptance"]
        assert decision["id"] > 0 and decision["reason"] == reason
        assert decision["revision"] == 1 and decision["reviewed_revision"] == 3
        assert decision["reviewed_revision_id"] == submitted["revision_id"]
        assert decision["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert decision["valid"] is True
        approved = supervisor.post(target + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": 3,
            "scope_revision": scope_revision, "password": BOX_READY_PASSWORD,
        })
        assert approved.status_code == 200, approved.text
        assert approved.json()["revision"] == 4 and approved.json()["approval_valid"] is True
        assert approved.json()["actual_counted_quantity"] == 8
        assert approved.json()["approved_physical_decisions"] == [decision]
        selected = supervisor.post(target + "/select", json={
            "request_id": str(uuid4()), "expected_revision": 4,
            "scope_revision": scope_revision, "expected_selection_revision": 0,
            "password": BOX_READY_PASSWORD,
        })
        assert selected.status_code == 200, selected.text
        assert selected.json()["selected"] is True
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["can_finalize"] is True and assessment["blockers"] == []
        assert {
            row["scope_id"]: (row["round_id"], row["round_revision_id"])
            for result in assessment["sources"]["constituencies"]
            for row in result["contributions"] if row["scope_id"] != scope_id
        } == other_sources
        chosen = next(
            row["record"] for row in assessment["sources"]["selected_counts"]
            if row["scope_id"] == scope_id
        )
        assert chosen == selected.json()
        assert chosen["id"] == submitted["id"] and chosen["revision"] == 4
        assert chosen["revision_id"] == approved.json()["revision_id"]
        assert chosen["actual_counted_quantity"] == 8
        stock = next(row for row in chosen["physical_comparisons"] if row["source"] == "stock")
        assert stock["expected_quantity"] == 10 and stock["actual_quantity"] == 8
        assert stock["difference_quantity"] == -2 and stock["status"] == "accepted"
        assert stock["acceptance"]["id"] == decision["id"]
        assert stock["acceptance"]["reason"] == reason
        assert chosen["approved_physical_decisions"] == [decision]
