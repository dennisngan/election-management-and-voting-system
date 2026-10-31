"""A restarted Qt client checks a lost wide receipt without repeating its command."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtTest import QSignalSpy

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
from tests.test_recount_instruction_restart_desktop import (
    lost_recount_response as lost_recount_response,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def _results_client(
    endpoint: HttpsServer, qt_app: QCoreApplication, account: dict, station_id: int,
) -> Iterator[tuple[DesktopController, QObject, QObject]]:
    client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(endpoint.url, account["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for_editor_idle(qt_app, workspace)
        workspace.selectStation(station_id)
        wait_for_editor_idle(qt_app, workspace)
        assert workspace.property("state")["selected"]["station"]["id"] == station_id
        results = client.property("constituencyResults")
        results.open()
        wait_for_editor_idle(qt_app, results)
        recounts = results.property("recounts")
        assert isinstance(recounts, QObject)
        wait_for_editor_idle(qt_app, recounts)
        yield client, results, recounts
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def _assert_credential_free(value: object) -> None:
    if isinstance(value, dict):
        assert not {
            "password", "current_password", "new_password", "temporary_password",
            "token", "authorization", "secret", "access_token", "refresh_token",
        } & {str(key).lower() for key in value}
        for nested in value.values():
            _assert_credential_free(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_credential_free(nested)
    elif isinstance(value, str):
        assert READY_PASSWORD not in value


def test_wide_instruction_survives_controller_restart_until_its_original_outcome_is_checked(
    admin: TestClient,
    database_url: str,
    lost_recount_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-recount-restart-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        account = setup["accounts"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        other_station_id = setup["stations"]["S1"]["id"]
        constituency_id = setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        other_station_path = f"/api/workspace/stations/{other_station_id}"
        priors = [saved, setup["n3_round"]]
        source_views = []
        for prior in priors:
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            source_views.append(response.json())
        setup["clock"].value += timedelta(minutes=10)
        endpoint = lost_recount_response
        endpoint.clock.value = setup["clock"].value
        forms = {
            "event_at": "2026-11-16 00:05:42.123456",
            "reason": "Check the original constituency instruction after restarting this client.",
        }

        with _results_client(endpoint, qt_app, account, station_id) as (first, results, child):
            first_destroyed = QSignalSpy(first.destroyed)
            instructed = QSignalSpy(child.instructed)
            assert first_destroyed.isValid() and instructed.isValid()
            initial = deepcopy(child.property("state"))
            assert initial["can_instruct"] is True and initial["instructions"] == []
            assert [row["scope_id"] for row in initial["scope_sources"]] == [
                setup["scope"]["id"], setup["n3_scope"]["id"],
            ]
            for field, value in forms.items():
                child.setField(field, value)
            with endpoint.lock:
                endpoint.drop_path = target
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            unknown = child.property("state")
            assert unknown["uncertain_save"] is True and unknown["dirty"] is True
            assert unknown["forms"] == forms and instructed.count() == 0
            committed_response = supervisor.get(target)
            assert committed_response.status_code == 200, committed_response.text
            committed_view = committed_response.json()
            assert len(committed_view["instructions"]) == 1
            parent = committed_view["instructions"][0]
            request_id = parent["request_id"]
            assert str(UUID(request_id)) == request_id
            assert unknown["pending_request_id"] == request_id
            assert parent["actor_id"] == account["id"]
            assert parent["member_count"] == 2 and len(parent["members"]) == 2
            assert parent["reason"] == forms["reason"]
            blank_views = []
            for member, prior in zip(parent["members"], priors, strict=True):
                rounds_path = prior["round_path"].rsplit("/", 1)[0]
                response = supervisor.get(rounds_path)
                assert response.status_code == 200, response.text
                assert [row["id"] for row in response.json()["rounds"]] == [
                    prior["selected"]["id"], member["new_round_id"],
                ]
                response = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
                assert response.status_code == 200, response.text
                blank_view = response.json()
                assert len(blank_view["history"]) == 1
                assert blank_view["record"]["revision"] == 1
                assert blank_view["record"]["status"] == "draft"
                assert [row["quantity"] for row in blank_view["record"]["candidate_votes"]] == [
                    None, None,
                ]
                blank_views.append(blank_view)
            recovery = first.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            original = deepcopy(commands[0])
            expected_payload = {
                "request_id": request_id, "basis_digest": initial["basis_digest"],
                "scope_sources": initial["scope_sources"],
                "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": forms["reason"],
            }
            assert original["workflow"] == "constituency_recount"
            assert original["path"] == target and original["method"] == "POST"
            assert original["server_url"] == endpoint.url
            assert original["actor_id"] == account["id"] and original["station_id"] == station_id
            assert original["request_id"] == request_id and original["payload"] == expected_payload
            assert original["status"] == "uncertain" and original["receipt"] is None
            assert original["confirmation_required"] is True
            journal_files = list(journal_directory.glob("*.json"))
            assert len(journal_files) == 1
            durable_before = journal_files[0].read_bytes()
            durable = json.loads(durable_before)
            assert_public_business_fields(original, durable)
            _assert_credential_free(durable)
            assert first.property("workspace").property("unresolvedRequest") is True
            assert endpoint.request_count("POST", target) == 1
        assert first_destroyed.count() == 1

        outcome_path = (
            f"/api/workspace/constituencies/{constituency_id}/request-outcomes/{request_id}"
        )
        station_outcome = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
        with _results_client(endpoint, qt_app, account, station_id) as (fresh, results, child):
            restored = child.property("state")
            assert restored["uncertain_save"] is True and restored["dirty"] is True
            assert restored["pending_request_id"] == request_id and restored["forms"] == forms
            assert restored["basis_digest"] == initial["basis_digest"]
            assert restored["scope_sources"] == initial["scope_sources"]
            assert restored["account_id"] == account["id"]
            assert restored["station_id"] == station_id
            assert restored["constituency_id"] == constituency_id
            assert restored["can_instruct"] is False
            recovery, workspace = fresh.property("recovery"), fresh.property("workspace")
            # The original station has already restored its guard before opening Recovery.
            assert workspace.property("unresolvedRequest") is True
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"] == [original]
            assert journal_files[0].read_bytes() == durable_before
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 0
            assert endpoint.request_count("GET", station_outcome) == 0
            target_reads = endpoint.request_count("GET", other_station_path)
            workspace.selectStation(other_station_id, True)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert workspace.property("state")["error"] == "workspace_uncertain_request"
            assert endpoint.request_count("GET", other_station_path) == target_reads
            assert child.property("state")["pending_request_id"] == request_id
            assert child.property("state")["forms"] == forms

            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            child.checkOutcome()
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            checked = recovery.property("state")["commands"]
            assert len(checked) == 1
            checked = checked[0]
            assert checked["status"] == "committed" and checked["error"] == ""
            for field in ("request_id", "workflow", "server_url", "actor_id", "station_id",
                          "path", "method", "payload", "confirmation_required", "created_at"):
                assert checked[field] == original[field]
            canonical_response = supervisor.get(outcome_path, params={
                "workflow": "constituency_recount",
            })
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical["request_id"] == request_id and canonical["status"] == "committed"
            assert canonical["workflow"] == "constituency_recount"
            assert len(canonical["record"]["members"]) == 2
            assert_public_business_fields(checked["receipt"]["record"], canonical["record"])
            settled = child.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert settled["forms"] == {"event_at": "", "reason": ""}
            assert instructed.count() == 1 and workspace.property("unresolvedRequest") is False
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("GET", station_outcome) == 0
            assert endpoint.request_count("POST", target) == 1
            stored = json.loads(journal_files[0].read_text(encoding="utf-8"))
            assert stored["status"] == "committed" and stored["payload"] == expected_payload
            assert stored["receipt"]["record"] == canonical["record"]
            _assert_credential_free(stored)
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))
            workspace.selectStation(other_station_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == other_station_id
            assert endpoint.request_count("GET", other_station_path) == target_reads + 1

        final = supervisor.get(target)
        assert final.status_code == 200 and final.json() == committed_view
        for member, prior, blank_view, source_view in zip(
            parent["members"], priors, blank_views, source_views, strict=True,
        ):
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            response = supervisor.get(rounds_path)
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()["rounds"]] == [
                prior["selected"]["id"], member["new_round_id"],
            ]
            response = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
            assert response.status_code == 200 and response.json() == blank_view
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            preserved = response.json()
            assert [row["revision_id"] for row in preserved["history"]] == [
                row["revision_id"] for row in source_view["history"]
            ]
            for field in ("candidate_votes", "invalid_papers", "scope_basis", "f2", "event_at",
                          "entered_at", "actor_id", "approved_at", "approved_by"):
                assert preserved["record"][field] == source_view["record"][field]
        assert endpoint.request_count("POST", target) == 1
