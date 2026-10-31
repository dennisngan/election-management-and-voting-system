"""A Supervisor instructs a blank recount without replacing the preserved count."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.results_support import save_result_round
from tests.tally_support import complete_f1_command
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_local_recount_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_starts_a_blank_local_recount_and_preserves_the_selected_round(
    admin: TestClient,
    database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        counter = setup["clients"]["receiveronly"]
        supervisor = setup["clients"]["supervisor"]
        prior = saved["selected"]
        scope = setup["scope"]
        station_id = setup["stations"]["N1"]["id"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before_response = supervisor.get(result_path)
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["complete"] is True, before["pending"]
        assert [row["quantity"] for row in before["candidate_totals"]] == [6, 4]
        assert prior["round_number"] == 1
        assert prior["status"] == "approved"
        assert prior["approval_valid"] is True
        assert prior["selected"] is True
        prior_path = f"{setup['rounds_path']}/{prior['id']}"
        prior_history_response = counter.get(prior_path)
        assert prior_history_response.status_code == 200, prior_history_response.text
        prior_history = prior_history_response.json()["history"]

        setup["clock"].value += timedelta(minutes=10)
        reason = "The Supervisor instructs a fresh physical recount of the same received boxes."
        command = {
            "request_id": str(uuid4()),
            "scope_revision": scope["revision"],
            "expected_selection_revision": prior["selection"]["revision"],
            "source_round_id": prior["id"],
            "source_round_revision": prior["revision"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": reason,
            "password": READY_PASSWORD,
        }
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope['id']}/recounts"
        )
        response = supervisor.post(recount_path, json=command)
        assert response.status_code == 201, response.text
        instruction = response.json()["instruction"]
        recount = response.json()["round"]
        assert type(instruction["id"]) is int and instruction["id"] > 0
        assert instruction["request_id"] == command["request_id"]
        assert instruction["scope_id"] == scope["id"]
        assert instruction["scope_revision"] == scope["revision"]
        assert instruction["scope_revision_id"] == scope["revision_id"]
        assert instruction["source_round_id"] == prior["id"]
        assert instruction["source_round_revision"] == prior["revision"]
        assert instruction["source_round_revision_id"] == prior["revision_id"]
        assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert instruction["reason"] == reason
        assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
        assert instruction["entered_at"] == "2026-11-15T16:10:00Z"
        assert instruction["status"] == "pending"
        assert instruction["new_round_id"] == recount["id"]
        assert instruction["new_round_number"] == 2
        assert recount["id"] != prior["id"]
        assert recount["round_number"] == 2
        assert recount["revision"] == 1
        assert recount["status"] == "draft"
        assert recount["event_at"] is None
        assert recount["entered_at"] is None
        assert recount["actor_id"] is None
        assert recount["revision_event_at"] == instruction["event_at"]
        assert recount["revision_entered_at"] == instruction["entered_at"]
        assert recount["revision_actor_id"] == instruction["actor_id"]
        assert recount["scope_id"] == scope["id"]
        assert recount["scope_revision"] == prior["scope_revision"]
        assert recount["scope_basis"]["revision_id"] == prior["scope_basis"]["revision_id"]
        for basis_key in ("box_basis", "accounting_basis"):
            assert [(row["id"], row["revision"]) for row in recount["scope_basis"][basis_key]] == [
                (row["id"], row["revision"]) for row in prior["scope_basis"][basis_key]
            ]
        assert [row["candidate_id"] for row in recount["candidate_votes"]] == [
            row["candidate_id"] for row in prior["candidate_votes"]
        ]
        assert all(row["quantity"] is None for row in recount["candidate_votes"])
        assert all(row["quantity"] is None for row in recount["invalid_papers"])
        assert recount["questionable_quantity"] is None
        assert recount["actual_counted_quantity"] is None
        assert recount["f1_complete"] is False
        assert recount["f2"] is None
        assert recount["completed_at"] is None
        assert recount.get("approved_at") is None
        assert recount["approval_valid"] is False
        assert recount["selected"] is False
        assert recount["physical_decisions"] == []
        fresh_response = counter.get(f"{setup['rounds_path']}/{recount['id']}")
        assert fresh_response.status_code == 200, fresh_response.text
        assert fresh_response.json()["record"] == recount

        preserved_response = counter.get(prior_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == [
            row["revision_id"] for row in prior_history
        ]
        for key in (
            "id", "round_number", "revision", "revision_id", "status", "candidate_votes",
            "invalid_papers", "f2", "scope_basis", "approved_at", "approved_by",
        ):
            assert preserved["record"][key] == prior[key]
        after_response = supervisor.get(result_path)
        assert after_response.status_code == 200, after_response.text
        after = after_response.json()
        assert after["complete"] is False
        assert after["provisional"] is True
        pending = next(row for row in after["pending"] if row["code"] == "recount_pending")
        assert pending["scope_id"] == scope["id"]
        assert pending["instruction_id"] == instruction["id"]
        assert pending["new_round_id"] == recount["id"]
        assert pending["source_round_id"] == prior["id"]
        assert [row["scope_id"] for row in after["contributions"]] == [setup["n3_scope"]["id"]]
        assert [row["quantity"] for row in after["candidate_totals"]] == [0, 0]


def test_required_recount_replaces_six_four_only_after_fresh_approval_and_selection(
    admin: TestClient,
    database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        counter = setup["clients"]["receiveronly"]
        supervisor = setup["clients"]["supervisor"]
        prior = saved["selected"]
        scope = setup["scope"]
        rounds_path = setup["rounds_path"]
        prior_path = f"{rounds_path}/{prior['id']}"
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        recount_path = (
            f"/api/workspace/stations/{setup['stations']['N1']['id']}"
            f"/counting-scopes/{scope['id']}/recounts"
        )
        original_history_response = counter.get(prior_path)
        assert original_history_response.status_code == 200, original_history_response.text
        original_history = original_history_response.json()["history"]
        before_response = supervisor.get(result_path)
        assert before_response.status_code == 200, before_response.text
        assert before_response.json()["complete"] is True
        assert [row["quantity"] for row in before_response.json()["candidate_totals"]] == [6, 4]
        assert prior["approval_valid"] is True and prior["selected"] is True
        prior_selection = prior["selection"]
        assert prior_selection["revision"] == 1

        setup["clock"].value += timedelta(minutes=10)
        instructed_response = supervisor.post(
            recount_path,
            json={
                "request_id": str(uuid4()),
                "scope_revision": scope["revision"],
                "expected_selection_revision": prior_selection["revision"],
                "source_round_id": prior["id"],
                "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": "A fresh physical recount must determine the replacement result.",
                "password": READY_PASSWORD,
            },
        )
        assert instructed_response.status_code == 201, instructed_response.text
        instruction = instructed_response.json()["instruction"]
        blank = instructed_response.json()["round"]
        replacement_path = f"{rounds_path}/{blank['id']}"
        assert blank["id"] != prior["id"] and blank["round_number"] == 2
        assert blank["revision"] == 1 and blank["status"] == "draft"
        assert all(row["quantity"] is None for row in blank["candidate_votes"])
        assert blank["actual_counted_quantity"] is None and blank["f2"] is None
        assert blank["scope_basis"] == prior["scope_basis"]

        def assert_replacement_pending() -> None:
            state_response = supervisor.get(recount_path)
            assert state_response.status_code == 200, state_response.text
            state = state_response.json()
            latest = state["latest_instruction"]
            assert state["pending"] is True
            assert latest["id"] == instruction["id"]
            assert latest["status"] == "pending" and latest["current_satisfied"] is False
            assert latest["completion_selection_id"] is None
            assert state["selection"]["id"] == prior_selection["id"]
            result_response = supervisor.get(result_path)
            assert result_response.status_code == 200, result_response.text
            result = result_response.json()
            assert result["complete"] is False and result["provisional"] is True
            assert [row["quantity"] for row in result["candidate_totals"]] == [0, 0]
            pending = next(row for row in result["pending"] if row["code"] == "recount_pending")
            assert pending["instruction_id"] == instruction["id"]
            assert pending["scope_id"] == scope["id"]
            assert pending["new_round_id"] == blank["id"]
            assert [row["scope_id"] for row in result["contributions"]] == [
                setup["n3_scope"]["id"]
            ]

        assert_replacement_pending()
        # A fresh UUID and current CAS prevent a cached reply or stale-CAS rejection
        # from disguising the required-round rule. This guard is absent in b7b7c52.
        old_selection_attempt = supervisor.post(
            prior_path + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": prior["revision"],
                "scope_revision": scope["revision"],
                "expected_selection_revision": prior_selection["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert old_selection_attempt.status_code == 409, old_selection_attempt.text
        assert_replacement_pending()

        options_response = counter.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1_command = complete_f1_command(
            options,
            expected_revision=blank["revision"],
            event_at="2026-11-16T00:06:12.123456+08:00",
            questionable_quantity=0,
            actual_counted_quantity=10,
        )
        for row, quantity in zip(f1_command["candidate_votes"], [8, 2], strict=True):
            row["quantity"] = quantity
        f1_response = counter.put(replacement_path, json=f1_command)
        assert f1_response.status_code == 200, f1_response.text
        f1 = f1_response.json()
        assert f1["revision"] == 2 and f1["f1_complete"] is True
        assert [row["quantity"] for row in f1["candidate_votes"]] == [8, 2]
        assert f1["actual_counted_quantity"] == 10
        assert f1["scope_basis"] == prior["scope_basis"]
        assert f1["f2"] is None
        assert_replacement_pending()

        f2_response = counter.put(
            replacement_path + "/f2",
            json=complete_f2_command(
                options,
                expected_revision=f1["revision"],
                event_at="2026-11-16T00:07:17.654321+08:00",
            ),
        )
        assert f2_response.status_code == 200, f2_response.text
        f2 = f2_response.json()
        assert f2["revision"] == 3 and f2["count_inputs_complete"] is True
        assert [row["quantity"] for row in f2["final_candidate_votes"]] == [8, 2]
        assert f2["approval_valid"] is False and f2["selected"] is False
        assert_replacement_pending()

        submitted_response = counter.post(
            replacement_path + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": f2["revision"],
                "scope_revision": scope["revision"],
            },
        )
        assert submitted_response.status_code == 200, submitted_response.text
        submitted = submitted_response.json()
        assert submitted["revision"] == 4 and submitted["status"] == "submitted"
        assert submitted["completed_at"] is not None
        assert submitted["approval_valid"] is False and submitted["selected"] is False
        assert_replacement_pending()

        approved_response = supervisor.post(
            replacement_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted["revision"],
                "scope_revision": scope["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        assert approved["revision"] == 5 and approved["status"] == "approved"
        assert approved["approval_valid"] is True and approved["selected"] is False
        assert approved["approved_by"] == setup["accounts"]["supervisor"]["id"]
        assert approved["reviewed_revision_id"] == submitted["revision_id"]
        assert approved["revision_id"] != prior["revision_id"]
        assert_replacement_pending()

        selection_command = {
            "expected_revision": approved["revision"],
            "scope_revision": scope["revision"],
            "password": READY_PASSWORD,
        }
        stale_selection = supervisor.post(
            replacement_path + "/select",
            json={
                **selection_command,
                "request_id": str(uuid4()),
                "expected_selection_revision": prior_selection["revision"] - 1,
            },
        )
        assert stale_selection.status_code == 409, stale_selection.text
        assert stale_selection.json()["detail"]["code"] == "selection_revision_conflict"
        assert_replacement_pending()
        selected_response = supervisor.post(
            replacement_path + "/select",
            json={
                **selection_command,
                "request_id": str(uuid4()),
                "expected_selection_revision": prior_selection["revision"],
            },
        )
        assert selected_response.status_code == 200, selected_response.text
        selected = selected_response.json()
        assert selected["revision"] == approved["revision"]
        assert selected["revision_id"] == approved["revision_id"]
        assert selected["selected"] is True and selected["contributes_to_result"] is True
        assert selected["selection"]["revision"] == prior_selection["revision"] + 1

        state_response = supervisor.get(recount_path)
        assert state_response.status_code == 200, state_response.text
        state = state_response.json()
        assert state["pending"] is False
        completed = next(row for row in state["instructions"] if row["id"] == instruction["id"])
        assert completed == state["latest_instruction"]
        assert completed["status"] == "completed" and completed["current_satisfied"] is True
        assert completed["completed_at"] == selected["selection"]["selected_at"]
        assert completed["completion_selection_id"] == selected["selection"]["id"]
        assert completed["completion_selection_revision"] == selected["selection"]["revision"]
        assert completed["completion_round_revision_id"] == approved["revision_id"]
        assert completed["source_round_revision_id"] == prior["revision_id"]
        assert completed["new_round_id"] == blank["id"]

        result_response = supervisor.get(result_path)
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()
        assert result["context"]["election"]["status"] == "active"
        assert result["complete"] is True and result["provisional"] is True
        assert [row["quantity"] for row in result["candidate_totals"]] == [8, 2]
        assert result["pending"] == []
        affected = [row for row in result["contributions"] if row["scope_id"] == scope["id"]]
        assert len(affected) == 1
        assert affected[0]["round_id"] == blank["id"]
        assert affected[0]["round_revision_id"] == approved["revision_id"]
        assert [row["quantity"] for row in affected[0]["final_candidate_votes"]] == [8, 2]
        assert all(row["round_id"] != prior["id"] for row in result["contributions"])

        preserved_response = counter.get(prior_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == [
            row["revision_id"] for row in original_history
        ]
        for key in (
            "id", "round_number", "revision", "revision_id", "status", "candidate_votes",
            "invalid_papers", "f2", "scope_basis", "approved_at", "approved_by",
        ):
            assert preserved["record"][key] == prior[key]
        assert [row["quantity"] for row in preserved["record"]["candidate_votes"]] == [6, 4]
        assert preserved["record"]["approval_valid"] is True
        assert preserved["record"]["selected"] is False
        assert preserved["record"]["contributes_to_result"] is False
        replacement_history_response = counter.get(replacement_path)
        assert replacement_history_response.status_code == 200, replacement_history_response.text
        replacement_history = replacement_history_response.json()["history"]
        assert [row["revision"] for row in replacement_history] == [5, 4, 3, 2, 1]
        assert replacement_history[-1]["revision_id"] == blank["revision_id"]
        assert all(row["quantity"] is None for row in replacement_history[-1]["candidate_votes"])
        assert replacement_history[0]["recount_instruction"]["status"] == "completed"
