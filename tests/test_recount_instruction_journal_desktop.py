"""A recount instruction retains one canonical nested durable command receipt."""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_recount_instruction_ack_and_exact_outcome_keep_the_same_nested_journal_receipt(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "recount-command-journal"))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor, counter = setup["clients"]["supervisor"], setup["clients"]["receiveronly"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        actor_id = setup["accounts"]["supervisor"]["id"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        source_before_response = counter.get(source_path)
        assert source_before_response.status_code == 200, source_before_response.text
        source_history_ids = [row["revision_id"]
                              for row in source_before_response.json()["history"]]
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        event_time = "2026-11-16 00:05:42.123456"
        reason = "A single reviewed recount instruction must retain its exact durable receipt."
        with f1_editor(
            https_server, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            recounts = editor.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            assert recounts.property("state")["can_instruct"] is True
            recounts.setField("event_at", event_time)
            recounts.setField("reason", reason)
            assert editor.property("state")["dirty"] is False
            recounts.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, recounts)
            wait_for_editor_idle(qt_app, editor)

            # Establish one actual backend effect before asserting journal coverage.
            state_response = supervisor.get(recount_path)
            assert state_response.status_code == 200, state_response.text
            state = state_response.json()
            assert len(state["instructions"]) == 1
            instruction = state["instructions"][0]
            request_id = instruction["request_id"]
            assert str(UUID(request_id)) == request_id
            assert instruction["actor_id"] == actor_id
            assert instruction["scope_id"] == scope_id
            assert instruction["scope_revision"] == setup["scope"]["revision"]
            assert instruction["scope_revision_id"] == setup["scope"]["revision_id"]
            assert instruction["source_round_id"] == prior["id"]
            assert instruction["source_round_revision"] == prior["revision"]
            assert instruction["source_round_revision_id"] == prior["revision_id"]
            assert instruction["reason"] == reason
            assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
            assert instruction["new_round_number"] == 2
            new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
            new_response = counter.get(new_path)
            assert new_response.status_code == 200, new_response.text
            new_view = new_response.json()
            blank = new_view["record"]
            assert len(new_view["history"]) == 1 and blank["revision"] == 1
            assert blank["scope_id"] == scope_id and blank["status"] == "draft"
            assert all(blank[key] is None for key in ("event_at", "entered_at", "actor_id"))
            assert blank["revision_actor_id"] == actor_id
            assert blank["revision_event_at"] == instruction["event_at"]
            assert blank["revision_entered_at"] == instruction["entered_at"]
            assert blank["scope_basis"] == prior["scope_basis"]
            assert blank["actual_counted_quantity"] is None and blank["f2"] is None
            assert blank["f1_complete"] is False and blank["selected"] is False
            assert all(row["quantity"] is None for row in blank["candidate_votes"])
            assert https_server.request_count("POST", recount_path) == 1

            recovery = client.property("recovery")
            assert recovery is not None
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            matching = [row for row in recovery.property("state")["commands"]
                        if row["path"] == recount_path and row["request_id"] == request_id]
            # Expected first RED at4c816c7: command_workflow excludes /recounts.
            assert len(matching) == 1, "The actual recount POST must have one durable command"
            acknowledged = matching[0]
            assert acknowledged["actor_id"] == actor_id
            assert acknowledged["station_id"] == station_id
            assert acknowledged["server_url"] == https_server.url
            assert acknowledged["workflow"] == "count" and acknowledged["method"] == "POST"
            assert acknowledged["confirmation_required"] is True
            assert acknowledged["payload"] == {
                "request_id": request_id,
                "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": prior["selection"]["revision"],
                "source_round_id": prior["id"],
                "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": reason,
            }
            assert "password" not in json.dumps(acknowledged["payload"]).lower()
            assert READY_PASSWORD not in json.dumps(acknowledged)

            outcome_path = (
                f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            )
            outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            assert outcome["request_id"] == request_id
            assert outcome["workflow"] == "count" and outcome["status"] == "committed"
            wrapper = outcome["record"]
            assert set(wrapper) == {"instruction", "round"}
            assert wrapper == {"instruction": instruction, "round": blank}
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            checked = next(row for row in recovery.property("state")["commands"]
                           if row["request_id"] == request_id)
            # A matcher-only change would next fail the flat id/revision validator here.
            assert acknowledged["status"] == checked["status"] == "committed", {
                "ack_status": acknowledged["status"], "ack_error": acknowledged["error"],
                "checked_status": checked["status"], "checked_error": checked["error"],
            }
            assert_public_business_fields(acknowledged["receipt"]["record"], wrapper)
            assert_public_business_fields(checked["receipt"]["record"], wrapper)
            assert recovery.property("state")["error"] == ""
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))
            assert https_server.request_count("GET", outcome_path) == 1
            assert https_server.request_count("POST", recount_path) == 1

            settled = recounts.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["error"] == "" and settled["pending_request_id"] == ""
            assert settled["latest_instruction"]["request_id"] == request_id
            assert editor.property("state")["selected"]["id"] == prior["id"]
            assert editor.property("state")["selected"]["revision"] == prior["revision"]
            assert editor.property("state")["dirty"] is False
            assert any(row["id"] == instruction["new_round_id"]
                       for row in editor.property("state")["rounds"])
            final_state_response = supervisor.get(recount_path)
            assert final_state_response.status_code == 200, final_state_response.text
            assert final_state_response.json()["instructions"] == state["instructions"]
            final_new_response = counter.get(new_path)
            assert final_new_response.status_code == 200, final_new_response.text
            assert final_new_response.json() == new_view
            final_outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert final_outcome_response.status_code == 200, final_outcome_response.text
            assert final_outcome_response.json() == outcome
            source_after_response = counter.get(source_path)
            assert source_after_response.status_code == 200, source_after_response.text
            preserved = source_after_response.json()
            assert [row["revision_id"] for row in preserved["history"]] == source_history_ids
            for key in ("candidate_votes", "invalid_papers", "scope_basis", "f2",
                        "event_at", "entered_at", "actor_id", "approved_at", "approved_by"):
                assert preserved["record"][key] == prior[key]
            assert https_server.request_count("POST", recount_path) == 1
