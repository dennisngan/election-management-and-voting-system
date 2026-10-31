"""Recount journal failures at real Qt/TLS/MySQL seams."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtTest import QSignalSpy

from tests.box_support import READY_PASSWORD
from tests.desktop_support import wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_paper_journal_failure_desktop import CompletedWriteServer, obstructed_journal_file
from tests.test_paper_journal_failure_desktop import (
    completed_write_server as completed_write_server,
)
from tests.test_paper_journal_failure_desktop import (
    private_command_directory as private_command_directory,
)
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def selected_recount_source(
    admin: TestClient, database_url: str, endpoint: CompletedWriteServer
) -> Iterator[dict]:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        station_id = setup["stations"]["N1"]["id"]
        scope_id = setup["scope"]["id"]
        setup["clock"].value += timedelta(minutes=10)
        endpoint.clock.value = setup["clock"].value
        yield {
            **setup,
            "prior": prior,
            "station_id": station_id,
            "scope_id": scope_id,
            "source_path": f"{setup['rounds_path']}/{prior['id']}",
            "recount_path": (
                f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
            ),
        }


def assert_source_observations_preserved(setup: dict, original_history_ids: list[int]) -> None:
    response = setup["clients"]["receiveronly"].get(setup["source_path"])
    assert response.status_code == 200, response.text
    history = response.json()
    assert [row["revision_id"] for row in history["history"]] == original_history_ids
    for key in (
        "id", "revision", "revision_id", "candidate_votes", "invalid_papers", "f2",
        "scope_basis", "event_at", "entered_at", "actor_id", "approved_at", "approved_by",
    ):
        assert history["record"][key] == setup["prior"][key]


def test_recount_journal_prepare_failure_is_correctable_without_dispatch_or_unknown_lock(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    endpoint = completed_write_server
    with selected_recount_source(admin, database_url, endpoint) as setup:
        supervisor = setup["clients"]["supervisor"]
        source = setup["clients"]["receiveronly"].get(setup["source_path"])
        assert source.status_code == 200, source.text
        history_ids = [row["revision_id"] for row in source.json()["history"]]
        path = setup["recount_path"]
        event_time = "2026-11-16 00:05:42.123456"
        reason = "Retain this correctable instruction if durable preparation cannot start."
        corrected_reason = "The corrected instruction is explicitly sent after restoring storage."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"],
            setup["station_id"], setup["scope_id"],
        ) as (client, editor):
            recounts = editor.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            assert recounts.property("state")["can_instruct"] is True
            recounts.setField("event_at", event_time)
            recounts.setField("reason", reason)
            original_forms = recounts.property("state")["forms"]
            instructed = QSignalSpy(recounts.instructed)
            assert instructed.isValid()
            # The ordinary API arrangement and desktop reads created no journal.
            assert not private_command_directory.exists()
            marker = "Owned recount command-directory obstruction."
            private_command_directory.write_text(marker, encoding="utf-8")
            private_command_directory.chmod(0o600)
            try:
                recounts.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, recounts)
                assert endpoint.request_count("POST", path) == 0
                state = recounts.property("state")
                assert state["error"] == "recovery_journal_unavailable"
                assert state["uncertain_save"] is False and state["dirty"] is True
                assert state["forms"] == original_forms
                assert state["can_instruct"] is True
                assert instructed.count() == 0
                workspace = client.property("workspace")
                assert workspace.property("unresolvedRequest") is False
                assert editor.property("state")["dirty"] is False
                assert editor.property("state")["selected"]["id"] == setup["prior"]["id"]
                empty = supervisor.get(path)
                assert empty.status_code == 200, empty.text
                assert empty.json()["instructions"] == []
                rounds = supervisor.get(setup["rounds_path"])
                assert rounds.status_code == 200, rounds.text
                assert [row["id"] for row in rounds.json()["rounds"]] == [setup["prior"]["id"]]
                assert_source_observations_preserved(setup, history_ids)

                # A definite pre-dispatch failure permits correcting the draft.
                recounts.setField("reason", corrected_reason)
                assert recounts.property("state")["forms"]["reason"] == corrected_reason
                assert recounts.property("state")["dirty"] is True
                assert private_command_directory.read_text(encoding="utf-8") == marker
                private_command_directory.unlink()
                private_command_directory.mkdir(mode=0o700)
                wait_for_editor_idle(qt_app, editor)
                assert endpoint.request_count("POST", path) == 0
                still_empty = supervisor.get(path)
                assert still_empty.status_code == 200, still_empty.text
                assert still_empty.json()["instructions"] == []

                # Restoring the filesystem never submits; this explicit action does.
                recounts.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, recounts)
                wait_for_editor_idle(qt_app, editor)
                recorded = supervisor.get(path)
                assert recorded.status_code == 200, recorded.text
                assert len(recorded.json()["instructions"]) == 1
                instruction = recorded.json()["instructions"][0]
                assert str(UUID(instruction["request_id"])) == instruction["request_id"]
                assert instruction["reason"] == corrected_reason
                assert instruction["source_round_id"] == setup["prior"]["id"]
                assert instruction["new_round_id"] != setup["prior"]["id"]
                settled = recounts.property("state")
                assert settled["error"] == "" and settled["uncertain_save"] is False
                assert settled["dirty"] is False and settled["pending_request_id"] == ""
                assert instructed.count() == 1
                assert workspace.property("unresolvedRequest") is False
                assert endpoint.request_count("POST", path) == 1
                assert editor.property("state")["selected"]["id"] == setup["prior"]["id"]
                assert_source_observations_preserved(setup, history_ids)
            finally:
                # Restore only the marker file owned by this case, never journal data.
                if private_command_directory.is_file():
                    assert private_command_directory.read_text(encoding="utf-8") == marker
                    private_command_directory.unlink()
                    private_command_directory.mkdir(mode=0o700)


def test_committed_recount_keeps_original_draft_until_journal_outcome_can_be_saved_and_checked(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    endpoint = completed_write_server
    with selected_recount_source(admin, database_url, endpoint) as setup:
        supervisor = setup["clients"]["supervisor"]
        counter = setup["clients"]["receiveronly"]
        source = counter.get(setup["source_path"])
        assert source.status_code == 200, source.text
        history_ids = [row["revision_id"] for row in source.json()["history"]]
        path = setup["recount_path"]
        target_id = setup["stations"]["S1"]["id"]
        target_path = f"/api/workspace/stations/{target_id}"
        event_time = "2026-11-16 00:05:42.123456"
        reason = "Keep the original instruction while its committed receipt cannot be stored."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"],
            setup["station_id"], setup["scope_id"],
        ) as (client, editor):
            recounts = editor.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            recounts.setField("event_at", event_time)
            recounts.setField("reason", reason)
            original_forms = recounts.property("state")["forms"]
            instructed = QSignalSpy(recounts.instructed)
            assert instructed.isValid()
            endpoint.hold_path = path
            recounts.instruct(READY_PASSWORD)
            try:
                wait_for(qt_app, endpoint.entered.is_set)
                pending = recounts.property("state")
                request_id = pending["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert pending["busy"] is True and pending["uncertain_save"] is False
                assert endpoint.release.is_set() is False
                files = list(private_command_directory.glob("*.json"))
                assert len(files) == 1
                journal_path = files[0]
                # Read only the actual prepared file; the helper alone obstructs it.
                original = json.loads(journal_path.read_text(encoding="utf-8"))
                assert original["request_id"] == request_id and original["status"] == "pending"
                assert original["path"] == path
                assert "password" not in json.dumps(original["payload"]).lower()
                assert READY_PASSWORD not in json.dumps(original)
                committed = supervisor.get(path)
                assert committed.status_code == 200, committed.text
                assert len(committed.json()["instructions"]) == 1
                instruction = committed.json()["instructions"][0]
                assert instruction["request_id"] == request_id
                assert instruction["reason"] == reason
                assert instruction["source_round_id"] == setup["prior"]["id"]
                new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
                blank_response = counter.get(new_path)
                assert blank_response.status_code == 200, blank_response.text
                blank_history = blank_response.json()
                assert blank_history["record"]["revision"] == 1
                outcome_path = (
                    f"/api/workspace/stations/{setup['station_id']}"
                    f"/request-outcomes/{request_id}"
                )
                outcome_response = supervisor.get(outcome_path + "?workflow=count")
                assert outcome_response.status_code == 200, outcome_response.text
                outcome = outcome_response.json()
                assert outcome["status"] == "committed" and outcome["request_id"] == request_id
                wrapper = {"instruction": instruction, "round": blank_history["record"]}
                assert outcome["record"] == wrapper
                workspace = client.property("workspace")
                target_reads = endpoint.request_count("GET", target_path)

                with obstructed_journal_file(journal_path, endpoint) as restore_journal:
                    endpoint.release.set()
                    wait_for_editor_idle(qt_app, recounts)
                    wait_for_editor_idle(qt_app, editor)
                    failed = recounts.property("state")
                    assert failed["error"] == "recovery_journal_outcome_unavailable"
                    assert failed["forms"] == original_forms
                    assert failed["dirty"] is True
                    assert failed["pending_request_id"] == request_id
                    assert instructed.count() == 0
                    assert endpoint.request_count("POST", path) == 1
                    # Expected product RED at e8f12eb: this error is omitted from NETWORK_ERRORS.
                    assert failed["uncertain_save"] is True, {
                        "error": failed["error"],
                        "uncertain_save": failed["uncertain_save"],
                        "strict_context_locked": workspace.property("unresolvedRequest"),
                    }
                    assert workspace.property("unresolvedRequest") is True
                    assert editor.property("state")["selected"]["id"] == setup["prior"]["id"]
                    workspace.selectStation(target_id, True)
                    wait_for_editor_idle(qt_app, workspace)
                    assert workspace.property("state")["selected"]["station"]["id"] == (
                        setup["station_id"]
                    )
                    assert workspace.property("state")["error"] == "workspace_uncertain_request"
                    assert endpoint.request_count("GET", target_path) == target_reads
                    assert recounts.property("state")["pending_request_id"] == request_id

                    restore_journal()
                    assert recounts.property("state")["uncertain_save"] is True
                    assert instructed.count() == 0
                    assert endpoint.request_count("POST", path) == 1
                    recovery = client.property("recovery")
                    recovery.open()
                    wait_for_editor_idle(qt_app, recovery)
                    command = next(row for row in recovery.property("state")["commands"]
                                   if row["request_id"] == request_id and row["path"] == path)
                    assert command["status"] == "pending"
                    assert command["payload"] == original["payload"]
                    assert endpoint.request_count("GET", outcome_path) == 0
                    assert instructed.count() == 0
                    recovery.checkOutcome(request_id)
                    wait_for_editor_idle(qt_app, recovery)
                    wait_for_editor_idle(qt_app, recounts)
                    wait_for_editor_idle(qt_app, editor)
                    checked = next(row for row in recovery.property("state")["commands"]
                                   if row["request_id"] == request_id)
                    assert checked["status"] == "committed" and checked["error"] == ""
                    assert_public_business_fields(checked["receipt"]["record"], wrapper)
                    settled = recounts.property("state")
                    assert settled["error"] == "" and settled["uncertain_save"] is False
                    assert settled["dirty"] is False and settled["pending_request_id"] == ""
                    assert settled["latest_instruction"]["request_id"] == request_id
                    assert instructed.count() == 1
                    assert workspace.property("unresolvedRequest") is False
                    assert editor.property("state")["selected"]["id"] == setup["prior"]["id"]
                    assert editor.property("state")["selected"]["revision"] == (
                        setup["prior"]["revision"]
                    )
                    assert any(row["id"] == instruction["new_round_id"]
                               for row in editor.property("state")["rounds"])
                    assert endpoint.request_count("POST", path) == 1
                    assert endpoint.request_count("GET", outcome_path) == 1
                    final_state = supervisor.get(path)
                    assert final_state.status_code == 200, final_state.text
                    assert final_state.json()["instructions"] == committed.json()["instructions"]
                    final_blank = counter.get(new_path)
                    assert final_blank.status_code == 200, final_blank.text
                    assert final_blank.json() == blank_history
                    final_outcome = supervisor.get(outcome_path + "?workflow=count")
                    assert final_outcome.status_code == 200, final_outcome.text
                    assert final_outcome.json() == outcome
                    assert_source_observations_preserved(setup, history_ids)
            finally:
                # The reused helper also restores the original bytes on every failure.
                endpoint.release.set()
