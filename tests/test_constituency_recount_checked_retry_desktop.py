"""A pre-dispatch wide recount requires a checked original retry after reconnection."""

import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from tests.box_support import READY_PASSWORD
from tests.desktop_support import wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_recount_restart_desktop import (
    _assert_credential_free,
    _results_client,
)
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
from tests.test_recount_checked_retry_desktop import ReconnectableRecountServer
from tests.test_recount_checked_retry_desktop import (
    reconnectable_recount_server as reconnectable_recount_server,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_pre_dispatch_wide_disconnect_requires_not_found_then_one_original_password_retry(
    admin: TestClient,
    database_url: str,
    reconnectable_recount_server: ReconnectableRecountServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-checked-retry-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        account = setup["accounts"]["supervisor"]
        station_id, constituency_id = setup["stations"]["N1"]["id"], setup["constituency_id"]
        base = f"/api/workspace/constituencies/{constituency_id}"
        target, result_path = base + "/recounts", base + "/results"
        priors = [saved, setup["n3_round"]]
        source_views, round_options = [], []
        for prior in priors:
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            source_views.append(response.json())
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            response = supervisor.get(rounds_path)
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()["rounds"]] == [prior["selected"]["id"]]
            round_options.append(response.json())
        before_result = supervisor.get(result_path)
        assert before_result.status_code == 200, before_result.text
        assert before_result.json()["complete"] is True
        assert [row["quantity"] for row in before_result.json()["candidate_totals"]] == [6, 4]
        before_wide = supervisor.get(target)
        assert before_wide.status_code == 200, before_wide.text
        assert before_wide.json()["can_instruct"] is True
        assert before_wide.json()["instructions"] == []
        setup["clock"].value += timedelta(minutes=10)
        endpoint = reconnectable_recount_server
        endpoint.clock.value = setup["clock"].value
        origin = endpoint.url
        forms = {
            "event_at": "2026-11-16 00:05:42.123456",
            "reason": "Only an explicitly checked original wide command may be retried.",
        }
        with _results_client(endpoint, qt_app, account, station_id) as (client, results, child):
            initial = deepcopy(child.property("state"))
            assert initial["can_instruct"] is True and initial["instructions"] == []
            assert initial["scope_sources"] == before_wide.json()["scope_sources"]
            assert len(initial["scope_sources"]) == 2
            for name, value in forms.items():
                child.setField(name, value)
            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            assert endpoint.request_count("POST", target) == 0
            # The existing fixture closes its opaque TLS listener and connections;
            # the application never receives this first attempt.
            endpoint.disconnect_proxy()
            try:
                child.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, child)
                unknown = deepcopy(child.property("state"))
                assert unknown["error"] == "disconnected"
                assert unknown["uncertain_save"] is True and unknown["dirty"] is True
                assert unknown["forms"] == forms and instructed.count() == 0
                request_id = unknown["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert endpoint.request_count("POST", target) == 0
            finally:
                # Restore the same origin before outcome inspection or client cleanup.
                endpoint.reconnect_proxy()
            assert endpoint.url == origin
            recovery = client.property("recovery")
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
            assert original["request_id"] == request_id and original["payload"] == expected_payload
            assert original["workflow"] == "constituency_recount" and original["method"] == "POST"
            assert original["actor_id"] == account["id"] and original["station_id"] == station_id
            assert original["server_url"] == origin and original["path"] == target
            assert original["status"] == "uncertain" and original["error"] == "disconnected"
            assert original["confirmation_required"] is True and original["receipt"] is None
            journal_files = list(journal_directory.glob("*.json"))
            assert len(journal_files) == 1
            durable_before = journal_files[0].read_bytes()
            assert_public_business_fields(original, json.loads(durable_before))
            _assert_credential_free(json.loads(durable_before))
            workspace = client.property("workspace")
            assert workspace.property("unresolvedRequest") is True

            # A genuine successful read after reconnection cannot resend a write or
            # replace the retained capsules with a new command.
            child.reload()
            wait_for_editor_idle(qt_app, child)
            restored = child.property("state")
            for key in ("forms", "basis_digest", "scope_sources", "pending_request_id"):
                assert restored[key] == unknown[key]
            assert restored["uncertain_save"] is True
            assert endpoint.request_count("POST", target) == 0
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            assert child.property("state")["error"] == "constituency_recount_not_ready"
            assert child.property("state")["pending_request_id"] == request_id
            assert child.property("state")["forms"] == forms
            assert endpoint.request_count("POST", target) == 0 and instructed.count() == 0
            assert journal_files[0].read_bytes() == durable_before

            outcome_path = base + f"/request-outcomes/{request_id}"
            station_outcome = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            missing = {"request_id": request_id, "workflow": "constituency_recount",
                       "status": "not_found"}
            absent = supervisor.get(outcome_path, params={"workflow": "constituency_recount"})
            assert absent.status_code == 200 and absent.json() == missing
            unchanged = supervisor.get(target)
            assert unchanged.status_code == 200 and unchanged.json() == before_wide.json()
            unchanged_result = supervisor.get(result_path)
            assert unchanged_result.status_code == 200
            assert unchanged_result.json() == before_result.json()
            for prior, before_source, before_options in zip(
                priors, source_views, round_options, strict=True,
            ):
                unchanged_source = supervisor.get(prior["round_path"])
                assert unchanged_source.status_code == 200
                assert unchanged_source.json() == before_source
                rounds_path = prior["round_path"].rsplit("/", 1)[0]
                unchanged_rounds = supervisor.get(rounds_path)
                assert unchanged_rounds.status_code == 200
                assert unchanged_rounds.json() == before_options
                local = supervisor.get(rounds_path.removesuffix("/rounds") + "/recounts")
                assert local.status_code == 200 and local.json()["instructions"] == []
            assert endpoint.request_count("GET", outcome_path) == 0
            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "recovery_retry_unavailable"
            assert endpoint.request_count("POST", target) == 0
            assert journal_files[0].read_bytes() == durable_before

            child.checkOutcome()
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, child)
            checked = recovery.property("state")["commands"]
            assert len(checked) == 1
            checked = checked[0]
            assert checked["status"] == "uncertain" and checked["error"] == "request_not_found"
            for key in ("request_id", "workflow", "server_url", "actor_id", "station_id",
                        "path", "method", "payload", "confirmation_required", "created_at"):
                assert checked[key] == original[key]
            assert child.property("state")["uncertain_save"] is True
            assert child.property("state")["forms"] == forms
            assert child.property("state")["pending_request_id"] == request_id
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("GET", station_outcome) == 0
            assert endpoint.request_count("POST", target) == 0 and instructed.count() == 0
            durable_checked = journal_files[0].read_bytes()
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            assert child.property("state")["error"] == "constituency_recount_not_ready"
            assert child.property("state")["pending_request_id"] == request_id
            assert endpoint.request_count("POST", target) == 0
            assert journal_files[0].read_bytes() == durable_checked
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "invalid_credentials"
            assert endpoint.request_count("POST", target) == 0
            assert journal_files[0].read_bytes() == durable_checked

            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            committed = recovery.property("state")["commands"]
            assert len(committed) == 1
            committed = committed[0]
            assert committed["status"] == "committed" and committed["error"] == ""
            for key in ("request_id", "workflow", "server_url", "actor_id", "station_id",
                        "path", "method", "payload", "confirmation_required", "created_at"):
                assert committed[key] == original[key]
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("GET", station_outcome) == 0
            settled = child.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert settled["forms"] == {"event_at": "", "reason": ""}
            assert instructed.count() == 1 and workspace.property("unresolvedRequest") is False
            canonical_response = supervisor.get(outcome_path, params={
                "workflow": "constituency_recount",
            })
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical["status"] == "committed" and canonical["request_id"] == request_id
            assert canonical["workflow"] == "constituency_recount"
            assert_public_business_fields(committed["receipt"]["record"], canonical["record"])
            durable = json.loads(journal_files[0].read_text(encoding="utf-8"))
            assert durable["status"] == "committed" and durable["payload"] == expected_payload
            assert durable["receipt"]["record"] == canonical["record"]
            for value in (durable, client.property("state"), settled, recovery.property("state")):
                _assert_credential_free(value)

        history = supervisor.get(target)
        assert history.status_code == 200, history.text
        assert len(history.json()["instructions"]) == 1
        parent = history.json()["instructions"][0]
        assert parent["request_id"] == request_id and parent["actor_id"] == account["id"]
        assert parent["reason"] == forms["reason"]
        assert parent["scope_sources"] == initial["scope_sources"]
        assert parent["member_count"] == 2 and len(parent["members"]) == 2
        assert len({row["new_round_id"] for row in parent["members"]}) == 2
        for member, prior, before_source, before_options in zip(
            parent["members"], priors, source_views, round_options, strict=True,
        ):
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            response = supervisor.get(rounds_path)
            assert response.status_code == 200, response.text
            assert len(response.json()["rounds"]) == 2
            assert {row["id"] for row in response.json()["rounds"]} == {
                prior["selected"]["id"], member["new_round_id"],
            }
            assert response.json()["selection"] == before_options["selection"]
            response = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
            assert response.status_code == 200, response.text
            blank = response.json()["record"]
            assert len(response.json()["history"]) == 1
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft"
            assert blank["scope_basis"] == prior["selected"]["scope_basis"]
            assert blank["f1_complete"] is False and blank["approval_valid"] is False
            assert blank["selected"] is False and blank["physical_decisions"] == []
            assert all(blank[key] is None for key in (
                "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                "questionable_quantity", "f2", "completed_at",
            ))
            assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
            assert all(row["quantity"] is None for row in blank["invalid_papers"])
            preserved = supervisor.get(prior["round_path"])
            assert preserved.status_code == 200, preserved.text
            assert [row["revision_id"] for row in preserved.json()["history"]] == [
                row["revision_id"] for row in before_source["history"]
            ]
            for key in (
                "id", "revision", "revision_id", "status", "candidate_votes", "invalid_papers",
                "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                "approved_at", "approved_by",
            ):
                assert preserved.json()["record"][key] == before_source["record"][key]
        result = supervisor.get(result_path)
        assert result.status_code == 200, result.text
        assert result.json()["complete"] is False and result.json()["provisional"] is True
        assert result.json()["contributions"] == []
        assert [row["quantity"] for row in result.json()["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result.json()["pending"]} == {
            setup["scope"]["id"], setup["n3_scope"]["id"],
        }
        assert {row["code"] for row in result.json()["pending"]} == {"recount_pending"}
        assert endpoint.request_count("POST", target) == 1
