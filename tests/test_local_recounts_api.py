"""A Supervisor instructs a blank recount without replacing the preserved count."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
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
