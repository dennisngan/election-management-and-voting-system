"""Retain one recount identity across real TLS trust failure and recovery."""

import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtTest import QSignalSpy

from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_count_paper_certificate_recovery_desktop import (
    RestartableHttpsServer,
    _untrusted_localhost_certificate,
)
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_recount_certificate_error_retains_original_command_until_checked_and_retried(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "recount-cert-journal"))
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare the existing local TLS fixture first"
    untrusted_certificate, untrusted_key = _untrusted_localhost_certificate(tmp_path)
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        counter, supervisor = setup["clients"]["receiveronly"], setup["clients"]["supervisor"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        target_id = setup["stations"]["S1"]["id"]
        assert target_id != station_id
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        target_path = f"/api/workspace/stations/{target_id}"
        source_before = counter.get(source_path)
        assert source_before.status_code == 200, source_before.text
        history_ids = [row["revision_id"] for row in source_before.json()["history"]]
        setup["clock"].value += timedelta(minutes=10)
        clock = ControlledClock()
        clock.value = setup["clock"].value
        server = RestartableHttpsServer(database_url, clock, qt_app)
        try:
            server.start(TLS_DIRECTORY / "server.pem", TLS_DIRECTORY / "server-key.pem")
            origin = server.url
            with f1_editor(
                server, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
            ) as (client, editor):
                recounts = editor.property("recounts")
                assert isinstance(recounts, QObject)
                wait_for_editor_idle(qt_app, recounts)
                assert recounts.property("state")["can_instruct"] is True
                event_time = "2026-11-16 00:05:42.123456"
                reason = "Retain the reviewed source until trusted transport confirms this request."
                recounts.setField("event_at", event_time)
                recounts.setField("reason", reason)
                original_forms = deepcopy(recounts.property("state")["forms"])
                instructed = QSignalSpy(recounts.instructed)
                assert instructed.isValid()
                assert server.request_count("POST", recount_path) == 0

                # Existing proven helper changes the real peer certificate at one origin.
                server.stop()
                server.start(untrusted_certificate, untrusted_key)
                assert server.url == origin
                recounts.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, recounts)
                failed = deepcopy(recounts.property("state"))
                workspace = client.property("workspace")
                locked_before_recovery = workspace.property("unresolvedRequest")
                assert failed["error"] == "certificate_error"
                assert failed["forms"] == original_forms and failed["dirty"] is True
                request_id = failed["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert instructed.count() == 0
                # A rejected TLS handshake never reached the real HTTP route.
                assert server.request_count("POST", recount_path) == 0
                no_effect = supervisor.get(recount_path)
                assert no_effect.status_code == 200, no_effect.text
                assert no_effect.json()["instructions"] == []
                no_round = counter.get(setup["rounds_path"])
                assert no_round.status_code == 200, no_round.text
                assert [row["id"] for row in no_round.json()["rounds"]] == [prior["id"]]

                # This opens only local journal data, without trusting the new certificate.
                recovery = client.property("recovery")
                recovery.open()
                wait_for_editor_idle(qt_app, recovery)
                original = deepcopy(next(row for row in recovery.property("state")["commands"]
                                         if row["path"] == recount_path
                                         and row["request_id"] == request_id))
                original_payload = deepcopy(original["payload"])
                assert original["status"] == "uncertain"
                assert original["error"] == "certificate_error"
                assert original["actor_id"] == setup["accounts"]["supervisor"]["id"]
                assert original["station_id"] == station_id and original["server_url"] == origin
                assert original["workflow"] == "count" and original["method"] == "POST"
                assert original["confirmation_required"] is True
                assert original_payload == {
                    "request_id": request_id,
                    "scope_revision": setup["scope"]["revision"],
                    "expected_selection_revision": prior["selection"]["revision"],
                    "source_round_id": prior["id"],
                    "source_round_revision": prior["revision"],
                    "event_at": "2026-11-16T00:05:42.123456+08:00",
                    "reason": reason,
                }
                assert "password" not in json.dumps(original_payload).lower()
                assert READY_PASSWORD not in json.dumps(original)
                # Expected first product RED: immediate child state omits certificate uncertainty.
                assert failed["uncertain_save"] is True, {
                    "child_error": failed["error"],
                    "child_unknown": failed["uncertain_save"],
                    "journal_status": original["status"],
                    "strict_lock_before_recovery": locked_before_recovery,
                }
                assert failed["can_instruct"] is False
                assert locked_before_recovery is True
                assert recounts.property("state")["uncertain_save"] is True
                assert recounts.property("state")["pending_request_id"] == request_id

                # Restore the original certificate/CA relationship; never ignore SSL errors.
                server.stop()
                server.start(TLS_DIRECTORY / "server.pem", TLS_DIRECTORY / "server-key.pem")
                assert server.url == origin
                wait_for_editor_idle(qt_app, editor)
                assert server.request_count("POST", recount_path) == 0
                assert instructed.count() == 0
                target_reads = server.request_count("GET", target_path)
                workspace.selectStation(target_id, True)
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == station_id
                assert workspace.property("state")["error"] == "workspace_uncertain_request"
                assert server.request_count("GET", target_path) == target_reads

                outcome_path = (
                    f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
                )
                assert server.request_count("GET", outcome_path) == 0
                recovery.checkOutcome(request_id)
                wait_for_editor_idle(qt_app, recovery)
                wait_for_editor_idle(qt_app, recounts)
                checked = next(row for row in recovery.property("state")["commands"]
                               if row["request_id"] == request_id)
                assert checked["status"] == "uncertain"
                assert checked["error"] == "request_not_found"
                assert checked["payload"] == original_payload
                assert recounts.property("state")["uncertain_save"] is True
                assert recounts.property("state")["forms"] == original_forms
                assert recounts.property("state")["pending_request_id"] == request_id
                assert recounts.property("state")["can_instruct"] is False
                assert workspace.property("unresolvedRequest") is True
                assert server.request_count("GET", outcome_path) == 1
                assert server.request_count("POST", recount_path) == 0

                # Fresh transient own-password, original path/UUID/body; one explicit retry.
                recovery.retry(request_id, READY_PASSWORD)
                wait_for_editor_idle(qt_app, recovery)
                wait_for_editor_idle(qt_app, recounts)
                wait_for_editor_idle(qt_app, editor)
                committed = next(row for row in recovery.property("state")["commands"]
                                 if row["request_id"] == request_id)
                assert committed["status"] == "committed" and committed["error"] == ""
                assert committed["request_id"] == request_id
                assert committed["payload"] == original_payload
                state_response = supervisor.get(recount_path)
                assert state_response.status_code == 200, state_response.text
                assert len(state_response.json()["instructions"]) == 1
                instruction = state_response.json()["instructions"][0]
                assert instruction["request_id"] == request_id
                assert instruction["reason"] == reason
                assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
                assert instruction["source_round_id"] == prior["id"]
                assert instruction["source_round_revision_id"] == prior["revision_id"]
                assert state_response.json()["selection"]["round_id"] == prior["id"]
                assert state_response.json()["selection"]["revision"] == (
                    prior["selection"]["revision"]
                )
                new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
                new_response = counter.get(new_path)
                assert new_response.status_code == 200, new_response.text
                blank = new_response.json()["record"]
                assert len(new_response.json()["history"]) == 1
                assert blank["round_number"] == 2
                assert blank["revision"] == 1 and blank["status"] == "draft"
                assert blank["scope_basis"] == prior["scope_basis"]
                assert all(blank[key] is None for key in (
                    "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                    "questionable_quantity", "f2",
                ))
                assert all(row["quantity"] is None for row in blank["candidate_votes"])
                assert all(row["quantity"] is None for row in blank["invalid_papers"])
                assert blank["physical_decisions"] == []
                public_outcome = supervisor.get(outcome_path + "?workflow=count")
                assert public_outcome.status_code == 200, public_outcome.text
                wrapper = {"instruction": instruction, "round": blank}
                assert public_outcome.json()["status"] == "committed"
                assert public_outcome.json()["record"] == wrapper
                assert_public_business_fields(committed["receipt"]["record"], wrapper)
                settled = recounts.property("state")
                assert settled["uncertain_save"] is False and settled["dirty"] is False
                assert settled["error"] == "" and settled["pending_request_id"] == ""
                assert settled["latest_instruction"]["request_id"] == request_id
                assert instructed.count() == 1
                assert workspace.property("unresolvedRequest") is False
                assert editor.property("state")["selected"]["id"] == prior["id"]
                assert editor.property("state")["selected"]["revision"] == prior["revision"]
                assert editor.property("state")["dirty"] is False
                assert server.request_count("POST", recount_path) == 1
                assert server.request_count("GET", outcome_path) == 1
                assert READY_PASSWORD not in json.dumps(recovery.property("state"))
                preserved_response = counter.get(source_path)
                assert preserved_response.status_code == 200, preserved_response.text
                preserved = preserved_response.json()
                assert [row["revision_id"] for row in preserved["history"]] == history_ids
                for key in ("id", "revision", "revision_id", "candidate_votes", "invalid_papers",
                            "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                            "approved_at", "approved_by"):
                    assert preserved["record"][key] == prior[key]
                workspace.selectStation(target_id)
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == target_id
                assert server.request_count("GET", target_path) == target_reads + 1
        finally:
            server.stop()
