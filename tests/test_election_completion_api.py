"""Election completion is assessed through authenticated HTTP and real MySQL."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_staff
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
from tests.test_local_recount_exports_history_api import complete_required_round


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


def test_supervisor_finalizes_reviewed_election_and_clears_active_pointer_atomically(
    admin: TestClient, database_url: str
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        reviewed = response.json()
        assert reviewed["can_finalize"] is True
        election_id = setup["election"]["id"]
        request_id = str(uuid4())
        finalized = supervisor.post(
            f"/api/workspace/elections/{election_id}/finalizations",
            json={
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
            },
        )
        assert finalized.status_code == 201, finalized.text
        receipt = finalized.json()
        assert receipt["request_id"] == request_id
        assert receipt["active_election_id"] is None
        assert receipt["election"] == {
            **reviewed["election"], "status": "finalized",
            "revision": reviewed["election"]["revision"] + 1,
        }
        event = receipt["event"]
        assert event["id"] > 0 and event["kind"] == "finalization"
        assert event["election_id"] == election_id
        assert event["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert event["election_revision"] == receipt["election"]["revision"]
        assert event["accepted_at"] == "2026-11-15T16:00:00Z"
        assert event["reason"] == "" and event["previous_finalization_id"] is None
        assert event["basis_digest"] == reviewed["basis_digest"]
        assert event["outcome"]["sources"] == reviewed["sources"]
        assert event["outcome"]["election"] == receipt["election"]
        assert [
            [row["quantity"] for row in result["candidate_totals"]]
            for result in event["outcome"]["results"]
        ] == [[6, 4], [4, 1]]
        assert [result["winner_candidate_id"] for result in event["outcome"]["results"]] == [
            result["candidate_totals"][0]["candidate_id"]
            for result in reviewed["sources"]["constituencies"]
        ]
        active = supervisor.get("/api/active-election")
        assert active.status_code == 200, active.text
        assert active.json()["election"] is None
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["election"] == receipt["election"]
        assert current.json()["active_election_id"] is None
        assert current.json()["can_finalize"] is False


def test_original_completion_outcome_and_replay_survive_cleared_active_election(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        request_id = str(uuid4())
        outcome_path = base + f"/request-outcomes/{request_id}?workflow=election_completion"
        missing = supervisor.get(outcome_path)
        assert missing.status_code == 200, missing.text
        not_found = {
            "request_id": request_id, "workflow": "election_completion", "status": "not_found",
        }
        assert missing.json() == not_found
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        reviewed = response.json()
        assert reviewed["can_finalize"] is True
        original = {
            "request_id": request_id,
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        }
        finalized = supervisor.post(base + "/finalizations", json=original)
        assert finalized.status_code == 201, finalized.text
        receipt = finalized.json()
        assert receipt["request_id"] == request_id
        assert receipt["election"]["id"] == election_id
        assert receipt["election"]["status"] == "finalized"
        assert receipt["election"]["revision"] == reviewed["election"]["revision"] + 1
        assert receipt["active_election_id"] is None
        committed = {
            "request_id": request_id, "workflow": "election_completion",
            "status": "committed", "record": receipt,
        }
        recovered = supervisor.get(outcome_path)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == committed
        wrong_password = supervisor.post(base + "/finalizations", json={
            **original, "password": "Wrong-Completion-Replay-42!",
        })
        assert wrong_password.status_code == 401, wrong_password.text
        assert wrong_password.json() == {"detail": {"code": "invalid_credentials"}}
        replay = supervisor.post(base + "/finalizations", json=original)
        assert replay.status_code == 201, replay.text
        assert replay.json() == receipt
        changed = supervisor.post(base + "/finalizations", json={
            **original, "expected_election_revision": receipt["election"]["revision"],
        })
        assert changed.status_code == 409, changed.text
        assert changed.json() == {"detail": {"code": "request_conflict"}}
        station_ids = [row["id"] for row in setup["stations"].values()]
        with box_staff(
            admin, database_url, setup["clock"], "supervisor", station_ids,
        ) as (other_supervisor, _):
            authorized = other_supervisor.get(setup["completion_path"])
            assert authorized.status_code == 200, authorized.text
            assert authorized.json()["election"] == receipt["election"]
            private = other_supervisor.get(outcome_path)
            assert private.status_code == 200, private.text
            assert private.json() == not_found
        retained = supervisor.get(outcome_path)
        assert retained.status_code == 200, retained.text
        assert retained.json() == committed
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["election"] == receipt["election"]
        assert current.json()["active_election_id"] is None
        assert current.json()["can_finalize"] is False
        active = supervisor.get("/api/active-election")
        assert active.status_code == 200, active.text
        assert active.json()["election"] is None


def test_authorized_reopening_waits_for_active_slot_and_preserves_original_outcome(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        reviewed_response = supervisor.get(setup["completion_path"])
        assert reviewed_response.status_code == 200, reviewed_response.text
        reviewed = reviewed_response.json()
        assert reviewed["can_finalize"] is True
        finalization_command = {
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        }
        finalized = supervisor.post(base + "/finalizations", json=finalization_command)
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        original_outcome_path = (
            base + f"/request-outcomes/{original['request_id']}?workflow=election_completion"
        )
        original_recovery = {
            "request_id": original["request_id"], "workflow": "election_completion",
            "status": "committed", "record": original,
        }
        recovered = supervisor.get(original_outcome_path)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == original_recovery
        active = supervisor.get("/api/active-election")
        assert active.status_code == 200, active.text
        assert active.json()["election"] is None
        reason = "Reopen for an authorized review while preserving the signed result."
        reopening_command = {
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": original["event"]["id"],
            "reason": reason, "password": BOX_READY_PASSWORD,
        }
        wrong_password = supervisor.post(base + "/reopenings", json={
            **reopening_command, "password": "Wrong-Reopening-Test-42!",
        })
        assert wrong_password.status_code == 401, wrong_password.text
        assert wrong_password.json() == {"detail": {"code": "invalid_credentials"}}
        blank_reason = supervisor.post(base + "/reopenings", json={
            **reopening_command, "reason": "   ",
        })
        assert blank_reason.status_code == 422, blank_reason.text
        unchanged = supervisor.get(setup["completion_path"])
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["election"] == original["election"]
        assert unchanged.json()["active_election_id"] is None
        with reviewed_election_setup(admin, database_url) as competing:
            other_supervisor = competing["clients"]["supervisor"]
            other_id = competing["election"]["id"]
            assert other_id != election_id
            active = supervisor.get("/api/active-election")
            assert active.status_code == 200, active.text
            assert active.json()["election"]["id"] == other_id
            conflict = supervisor.post(base + "/reopenings", json=reopening_command)
            assert conflict.status_code == 409, conflict.text
            assert conflict.json() == {"detail": {"code": "active_election_conflict"}}
            unchanged = supervisor.get(setup["completion_path"])
            assert unchanged.status_code == 200, unchanged.text
            assert unchanged.json()["election"] == original["election"]
            assert unchanged.json()["active_election_id"] == other_id
            retained = supervisor.get(original_outcome_path)
            assert retained.status_code == 200, retained.text
            assert retained.json() == original_recovery
            other_review_response = other_supervisor.get(competing["completion_path"])
            assert other_review_response.status_code == 200, other_review_response.text
            other_review = other_review_response.json()
            assert other_review["can_finalize"] is True
            other_finalized = other_supervisor.post(
                f"/api/workspace/elections/{other_id}/finalizations", json={
                    "request_id": str(uuid4()),
                    "expected_election_revision": other_review["election"]["revision"],
                    "basis_digest": other_review["basis_digest"],
                    "password": BOX_READY_PASSWORD,
                },
            )
            assert other_finalized.status_code == 201, other_finalized.text
            assert other_finalized.json()["active_election_id"] is None
        reopened = supervisor.post(base + "/reopenings", json=reopening_command)
        assert reopened.status_code == 201, reopened.text
        receipt = reopened.json()
        assert receipt["request_id"] == reopening_command["request_id"]
        assert receipt["active_election_id"] == election_id
        assert receipt["election"] == {
            **original["election"], "status": "active",
            "revision": original["election"]["revision"] + 1,
        }
        event = receipt["event"]
        assert event["id"] != original["event"]["id"]
        assert event["election_id"] == election_id and event["kind"] == "reopening"
        assert event["election_revision"] == receipt["election"]["revision"]
        assert event["previous_finalization_id"] == original["event"]["id"]
        assert event["reason"] == reason
        assert event["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert event["accepted_at"] == "2026-11-15T16:00:00Z"
        active = supervisor.get("/api/active-election")
        assert active.status_code == 200, active.text
        assert active.json()["election"]["id"] == election_id
        assert active.json()["election"]["status"] == "active"
        assert active.json()["election"]["revision"] == receipt["election"]["revision"]
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["election"] == receipt["election"]
        assert current.json()["active_election_id"] == election_id
        retained = supervisor.get(original_outcome_path)
        assert retained.status_code == 200, retained.text
        assert retained.json() == original_recovery
        original_replay = supervisor.post(base + "/finalizations", json=finalization_command)
        assert original_replay.status_code == 201, original_replay.text
        assert original_replay.json() == original
        still_reopened = supervisor.get(setup["completion_path"])
        assert still_reopened.status_code == 200, still_reopened.text
        assert still_reopened.json()["election"] == receipt["election"]
        assert still_reopened.json()["active_election_id"] == election_id


def test_reopened_recount_refinalization_preserves_the_original_finalized_outcome(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        counter = setup["clients"]["receiveronly"]
        election_id = setup["election"]["id"]
        constituency_id = setup["constituency_id"]
        base = f"/api/workspace/elections/{election_id}"
        before_response = supervisor.get(setup["completion_path"])
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["can_finalize"] is True
        original_command = {
            "request_id": str(uuid4()),
            "expected_election_revision": before["election"]["revision"],
            "basis_digest": before["basis_digest"], "password": BOX_READY_PASSWORD,
        }
        first_response = supervisor.post(base + "/finalizations", json=original_command)
        assert first_response.status_code == 201, first_response.text
        first = first_response.json()
        first_north = next(
            row for row in first["event"]["outcome"]["results"]
            if row["constituency"]["id"] == constituency_id
        )
        assert [row["quantity"] for row in first_north["candidate_totals"]] == [6, 4]
        assert first["event"]["outcome"]["sources"] == before["sources"]
        reopened_response = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": first["election"]["revision"],
            "previous_finalization_id": first["event"]["id"],
            "reason": "Reopen to recount the N1 received-box scope after signed review.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened_response.status_code == 201, reopened_response.text
        reopened = reopened_response.json()
        assert reopened["active_election_id"] == election_id
        prior = setup["n1_round"]["selected"]
        setup["clock"].value += timedelta(minutes=10)
        recount_path = (
            f"/api/workspace/stations/{setup['stations']['N1']['id']}"
            f"/counting-scopes/{setup['scope']['id']}/recounts"
        )
        instructed_response = supervisor.post(recount_path, json={
            "request_id": str(uuid4()), "scope_revision": setup["scope"]["revision"],
            "expected_selection_revision": prior["selection"]["revision"],
            "source_round_id": prior["id"], "source_round_revision": prior["revision"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Retally the same received boxes while retaining the signed first tally.",
            "password": BOX_READY_PASSWORD,
        })
        assert instructed_response.status_code == 201, instructed_response.text
        blank = instructed_response.json()["round"]
        pending_response = supervisor.get(setup["completion_path"])
        assert pending_response.status_code == 200, pending_response.text
        assert pending_response.json()["can_finalize"] is False
        assert any(
            row["code"] == "recount_pending" and row["scope_id"] == setup["scope"]["id"]
            for row in pending_response.json()["blockers"]
        )
        replacement = complete_required_round(setup, blank, prior["selection"]["revision"])
        assert replacement["id"] != prior["id"]
        assert replacement["round_number"] == 2 and replacement["approval_valid"] is True
        assert [row["quantity"] for row in replacement["final_candidate_votes"]] == [8, 2]
        assert replacement["scope_basis"] == prior["scope_basis"]
        reviewed_response = supervisor.get(setup["completion_path"])
        assert reviewed_response.status_code == 200, reviewed_response.text
        reviewed = reviewed_response.json()
        assert reviewed["election"] == reopened["election"]
        assert reviewed["can_finalize"] is True
        assert reviewed["basis_digest"] != before["basis_digest"]
        second_response = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert second_response.status_code == 201, second_response.text
        second = second_response.json()
        assert second["event"]["id"] not in {first["event"]["id"], reopened["event"]["id"]}
        assert second["event"]["kind"] == "finalization"
        assert second["election"]["revision"] == reopened["election"]["revision"] + 1
        assert second["active_election_id"] is None
        assert second["event"]["outcome"]["sources"] == reviewed["sources"]
        second_north = next(
            row for row in second["event"]["outcome"]["results"]
            if row["constituency"]["id"] == constituency_id
        )
        assert [row["quantity"] for row in second_north["candidate_totals"]] == [8, 2]
        assert any(
            row["scope_id"] == setup["scope"]["id"] and row["round_id"] == replacement["id"]
            for row in second_north["contributions"]
        )
        for receipt in (first, second):
            recovered = supervisor.get(
                base + f"/request-outcomes/{receipt['request_id']}?workflow=election_completion"
            )
            assert recovered.status_code == 200, recovered.text
            assert recovered.json() == {
                "request_id": receipt["request_id"], "workflow": "election_completion",
                "status": "committed", "record": receipt,
            }
        original_replay = supervisor.post(base + "/finalizations", json=original_command)
        assert original_replay.status_code == 201, original_replay.text
        assert original_replay.json() == first
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["election"] == second["election"]
        assert current.json()["active_election_id"] is None
        old_round = counter.get(f"{setup['rounds_path']}/{prior['id']}")
        assert old_round.status_code == 200, old_round.text
        old_votes = old_round.json()["record"]["final_candidate_votes"]
        assert [row["quantity"] for row in old_votes] == [6, 4]
        assert old_round.json()["record"]["approved_at"] == prior["approved_at"]
