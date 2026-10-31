"""Wide commands distinguish refused preparation from an unrecorded committed outcome."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from tests.box_support import READY_PASSWORD
from tests.desktop_support import wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_recount_restart_desktop import (
    _assert_credential_free,
    _results_client,
)
from tests.test_constituency_tie_api import complete_tie_setup
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
def _ready_wide_context(
    admin: TestClient, database_url: str, endpoint: CompletedWriteServer,
) -> Iterator[dict]:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        target = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        snapshots = {}
        for path in (target, target.removesuffix("/recounts") + "/results"):
            response = supervisor.get(path)
            assert response.status_code == 200, response.text
            snapshots[path] = response.json()
        priors = [saved, setup["n3_round"]]
        for prior in priors:
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            local_path = rounds_path.removesuffix("/rounds") + "/recounts"
            for path in (rounds_path, local_path, prior["round_path"]):
                response = supervisor.get(path)
                assert response.status_code == 200, response.text
                snapshots[path] = response.json()
            assert len(snapshots[rounds_path]["rounds"]) == 1
            assert snapshots[local_path]["instructions"] == []
        setup["clock"].value += timedelta(minutes=10)
        endpoint.clock.value = setup["clock"].value
        yield {**setup, "target": target, "snapshots": snapshots, "priors": priors}


def _assert_sources_preserved(setup: dict) -> None:
    supervisor = setup["clients"]["supervisor"]
    for prior in setup["priors"]:
        path = prior["round_path"]
        response = supervisor.get(path)
        assert response.status_code == 200, response.text
        original, current = setup["snapshots"][path], response.json()
        assert [row["revision_id"] for row in current["history"]] == [
            row["revision_id"] for row in original["history"]
        ]
        for before, after in zip(original["history"], current["history"], strict=True):
            for field in ("id", "revision", "revision_id", "status", "candidate_votes",
                          "invalid_papers", "f2", "scope_basis", "event_at", "entered_at",
                          "actor_id", "approved_at", "approved_by"):
                assert after.get(field) == before.get(field)


def _assert_one_wide_effect(setup: dict, receipt: dict) -> None:
    supervisor = setup["clients"]["supervisor"]
    response = supervisor.get(setup["target"])
    assert response.status_code == 200, response.text
    assert len(response.json()["instructions"]) == 1
    assert response.json()["instructions"][0]["id"] == receipt["instruction"]["id"]
    assert receipt["instruction"]["member_count"] == 2 and len(receipt["members"]) == 2
    for member, prior in zip(receipt["members"], setup["priors"], strict=True):
        rounds_path = prior["round_path"].rsplit("/", 1)[0]
        listed = supervisor.get(rounds_path)
        assert listed.status_code == 200, listed.text
        assert [row["id"] for row in listed.json()["rounds"]] == [
            prior["selected"]["id"], member["round"]["id"],
        ]
        assert listed.json()["selection"] == setup["snapshots"][rounds_path]["selection"]
        blank = supervisor.get(f"{rounds_path}/{member['round']['id']}")
        assert blank.status_code == 200, blank.text
        assert len(blank.json()["history"]) == 1 and blank.json()["record"] == member["round"]
        assert member["round"]["revision"] == 1 and member["round"]["status"] == "draft"
        assert [row["quantity"] for row in member["round"]["candidate_votes"]] == [None, None]
        local = supervisor.get(rounds_path.removesuffix("/rounds") + "/recounts")
        assert local.status_code == 200, local.text
        assert local.json()["instructions"] == [member["instruction"]]
    _assert_sources_preserved(setup)


def test_wide_journal_prepare_refusal_preserves_correctable_forms_without_dispatch(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    endpoint = completed_write_server
    with _ready_wide_context(admin, database_url, endpoint) as setup:
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        target = setup["target"]
        forms = {
            "event_at": "2026-11-16 00:05:42.123456",
            "reason": "Keep this unsent wide instruction correctable while storage is unavailable.",
        }
        corrected_reason = "Explicitly instruct both scopes after restoring only owned storage."
        with _results_client(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id,
        ) as (client, results, child):
            for field, value in forms.items():
                child.setField(field, value)
            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            assert not private_command_directory.exists()
            marker = "Owned wide-recount journal-directory obstruction."
            private_command_directory.write_text(marker, encoding="utf-8")
            private_command_directory.chmod(0o600)
            try:
                child.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, child)
                assert endpoint.request_count("POST", target) == 0
                refused = child.property("state")
                assert refused["error"] == "recovery_journal_unavailable"
                assert refused["uncertain_save"] is False and refused["dirty"] is True
                assert refused["forms"] == forms and refused["pending_request_id"] == ""
                assert refused["can_instruct"] is True and instructed.count() == 0
                assert client.property("workspace").property("unresolvedRequest") is False
                for path, original in setup["snapshots"].items():
                    response = supervisor.get(path)
                    assert response.status_code == 200 and response.json() == original

                child.setField("reason", corrected_reason)
                assert child.property("state")["forms"] == {
                    "event_at": forms["event_at"], "reason": corrected_reason,
                }
                assert private_command_directory.read_text(encoding="utf-8") == marker
                private_command_directory.unlink()
                private_command_directory.mkdir(mode=0o700)
                assert endpoint.request_count("POST", target) == 0
                unchanged = supervisor.get(target)
                assert unchanged.status_code == 200 and unchanged.json()["instructions"] == []

                child.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, child)
                wait_for_editor_idle(qt_app, results)
                settled = child.property("state")
                assert settled["error"] == "" and settled["uncertain_save"] is False
                assert settled["dirty"] is False and settled["pending_request_id"] == ""
                assert settled["forms"] == {"event_at": "", "reason": ""}
                assert instructed.count() == 1 and endpoint.request_count("POST", target) == 1
                assert client.property("workspace").property("unresolvedRequest") is False
                files = list(private_command_directory.glob("*.json"))
                assert len(files) == 1
                durable = json.loads(files[0].read_text(encoding="utf-8"))
                assert durable["status"] == "committed"
                assert durable["workflow"] == "constituency_recount"
                assert durable["payload"]["reason"] == corrected_reason
                assert str(UUID(durable["request_id"])) == durable["request_id"]
                assert durable["receipt"]["record"]["instruction"]["reason"] == corrected_reason
                _assert_credential_free(durable)
                _assert_one_wide_effect(setup, durable["receipt"]["record"])
            finally:
                # Restore only this case's sentinel file, never a product journal.
                if private_command_directory.is_file():
                    assert private_command_directory.read_text(encoding="utf-8") == marker
                    private_command_directory.unlink()
                    private_command_directory.mkdir(mode=0o700)


def test_wide_commit_keeps_original_command_unknown_until_journal_restoration_and_outcome_check(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    endpoint = completed_write_server
    with _ready_wide_context(admin, database_url, endpoint) as setup:
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        target = setup["target"]
        other_station_id = setup["stations"]["S1"]["id"]
        other_station_path = f"/api/workspace/stations/{other_station_id}"
        statement_path = target.removesuffix("/recounts") + "/results/statement"
        forms = {
            "event_at": "2026-11-16 00:05:42.123456",
            "reason": "Retain this exact wide instruction while its committed receipt cannot save.",
        }
        with _results_client(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id,
        ) as (client, results, child):
            initial = deepcopy(child.property("state"))
            for field, value in forms.items():
                child.setField(field, value)
            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            with endpoint.lock:
                endpoint.hold_path = target
            child.instruct(READY_PASSWORD)
            try:
                wait_for(qt_app, endpoint.entered.is_set)
                pending = child.property("state")
                request_id = pending["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert pending["busy"] is True and pending["uncertain_save"] is False
                assert endpoint.release.is_set() is False
                files = list(private_command_directory.glob("*.json"))
                assert len(files) == 1
                journal_path = files[0]
                original = json.loads(journal_path.read_text(encoding="utf-8"))
                expected_payload = {
                    "request_id": request_id, "basis_digest": initial["basis_digest"],
                    "scope_sources": initial["scope_sources"],
                    "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": forms["reason"],
                }
                assert original["request_id"] == request_id and original["status"] == "pending"
                assert original["workflow"] == "constituency_recount" and original["path"] == target
                assert original["actor_id"] == setup["accounts"]["supervisor"]["id"]
                assert original["station_id"] == station_id
                assert original["server_url"] == endpoint.url
                assert original["payload"] == expected_payload
                _assert_credential_free(original)
                outcome_path = (
                    target.removesuffix("/recounts") + f"/request-outcomes/{request_id}"
                )
                outcome_response = supervisor.get(outcome_path, params={
                    "workflow": "constituency_recount",
                })
                assert outcome_response.status_code == 200, outcome_response.text
                outcome = outcome_response.json()
                assert outcome["request_id"] == request_id and outcome["status"] == "committed"
                assert outcome["workflow"] == "constituency_recount"
                receipt = outcome["record"]
                assert receipt["instruction"]["member_count"] == 2 and len(receipt["members"]) == 2
                workspace = client.property("workspace")
                target_reads = endpoint.request_count("GET", other_station_path)
                report_reads = endpoint.request_count("GET", statement_path)

                with obstructed_journal_file(journal_path, endpoint) as restore_journal:
                    endpoint.release.set()
                    wait_for_editor_idle(qt_app, child)
                    wait_for_editor_idle(qt_app, results)
                    unknown = child.property("state")
                    assert unknown["error"] == "recovery_journal_outcome_unavailable"
                    assert unknown["notice"] == ""
                    assert unknown["uncertain_save"] is True and unknown["dirty"] is True
                    assert unknown["pending_request_id"] == request_id and unknown["forms"] == forms
                    assert unknown["scope_sources"] == initial["scope_sources"]
                    assert unknown["basis_digest"] == initial["basis_digest"]
                    assert instructed.count() == 0 and endpoint.request_count("POST", target) == 1
                    assert workspace.property("unresolvedRequest") is True
                    workspace.selectStation(other_station_id, True)
                    wait_for_editor_idle(qt_app, workspace)
                    assert workspace.property("state")["selected"]["station"]["id"] == station_id
                    assert workspace.property("state")["error"] == "workspace_uncertain_request"
                    assert endpoint.request_count("GET", other_station_path) == target_reads
                    results.preview("en")
                    wait_for_editor_idle(qt_app, results)
                    assert results.property("state")["error"] == (
                        "constituency_recount_changes_pending"
                    )
                    assert results.property("state")["report"] == {}
                    assert endpoint.request_count("GET", statement_path) == report_reads
                    _assert_one_wide_effect(setup, receipt)

                    restore_journal()
                    assert child.property("state")["uncertain_save"] is True
                    assert instructed.count() == 0 and endpoint.request_count("POST", target) == 1
                    recovery = client.property("recovery")
                    recovery.open()
                    wait_for_editor_idle(qt_app, recovery)
                    commands = recovery.property("state")["commands"]
                    assert len(commands) == 1 and commands[0]["status"] == "pending"
                    assert commands[0]["payload"] == expected_payload
                    assert endpoint.request_count("GET", outcome_path) == 0
                    child.checkOutcome()
                    wait_for_editor_idle(qt_app, recovery)
                    wait_for_editor_idle(qt_app, child)
                    wait_for_editor_idle(qt_app, results)
                    checked = recovery.property("state")["commands"]
                    assert len(checked) == 1
                    checked = checked[0]
                    assert checked["status"] == "committed" and checked["error"] == ""
                    assert checked["request_id"] == request_id
                    assert checked["payload"] == expected_payload
                    assert_public_business_fields(checked["receipt"]["record"], receipt)
                    settled = child.property("state")
                    assert settled["error"] == "" and settled["uncertain_save"] is False
                    assert settled["dirty"] is False and settled["pending_request_id"] == ""
                    assert settled["forms"] == {"event_at": "", "reason": ""}
                    assert instructed.count() == 1
                    assert workspace.property("unresolvedRequest") is False
                    assert endpoint.request_count("POST", target) == 1
                    assert endpoint.request_count("GET", outcome_path) == 1
                    durable = json.loads(journal_path.read_text(encoding="utf-8"))
                    assert durable["payload"] == expected_payload
                    assert durable["status"] == "committed"
                    assert durable["receipt"]["record"] == receipt
                    _assert_credential_free(durable)
                    results.preview("en")
                    wait_for_editor_idle(qt_app, results)
                    assert results.property("state")["report"]["locale"] == "en"
                    assert endpoint.request_count("GET", statement_path) == report_reads + 1
                    workspace.selectStation(other_station_id)
                    wait_for_editor_idle(qt_app, workspace)
                    assert workspace.property("state")["selected"]["station"]["id"] == (
                        other_station_id
                    )
                    assert endpoint.request_count("GET", other_station_path) == target_reads + 1
                    _assert_one_wide_effect(setup, receipt)
                    final = supervisor.get(outcome_path, params={
                        "workflow": "constituency_recount",
                    })
                    assert final.status_code == 200 and final.json() == outcome
            finally:
                # The reused obstruction helper restores original owned bytes even on failure.
                endpoint.release.set()
