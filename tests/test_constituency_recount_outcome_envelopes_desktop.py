"""A contradictory not-found envelope cannot authorize retrying a committed wide command.

Requires the companion aggregate-receipt fixture change that adds the one-shot
contradict_next_outcome_path and altered_outcome_count boundary controls.
"""

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
from tests.test_constituency_recount_receipts_desktop import AggregateReceiptBoundary
from tests.test_constituency_recount_receipts_desktop import (
    aggregate_receipt_boundary as aggregate_receipt_boundary,
)
from tests.test_constituency_recount_restart_desktop import (
    _assert_credential_free,
    _results_client,
)
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_not_found_with_an_actual_committed_record_stays_unknown_and_cannot_be_retried(
    admin: TestClient,
    database_url: str,
    aggregate_receipt_boundary: AggregateReceiptBoundary,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-contradictory-outcome-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        actor = setup["accounts"]["supervisor"]
        station_id, constituency_id = setup["stations"]["N1"]["id"], setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        priors = [saved, setup["n3_round"]]
        source_views = []
        for prior in priors:
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            source_views.append(response.json())
        endpoint = aggregate_receipt_boundary
        setup["clock"].value += timedelta(minutes=10)
        endpoint.clock.value = setup["clock"].value
        forms = {
            "event_at": "2026-11-16 00:05:42.123456",
            "reason": (
                "Check an ambiguous original outcome without repeating a committed instruction."
            ),
        }

        with _results_client(endpoint, qt_app, actor, station_id) as (client, results, child):
            initial = deepcopy(child.property("state"))
            assert initial["can_instruct"] is True and len(initial["scope_sources"]) == 2
            for field, value in forms.items():
                child.setField(field, value)
            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            with endpoint.lock:
                endpoint.alter_next_post_path = target
                endpoint.post_fault = "truncated_candidates"
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            unknown = child.property("state")
            assert endpoint.altered_response_count == 1
            assert endpoint.delivered_candidate_ids == endpoint.original_candidate_ids[:-1]
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
            assert parent["member_count"] == 2 and len(parent["members"]) == 2
            assert parent["actor_id"] == actor["id"] and parent["reason"] == forms["reason"]
            outcome_path = (
                f"/api/workspace/constituencies/{constituency_id}/request-outcomes/{request_id}"
            )
            station_outcome = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            canonical_response = supervisor.get(outcome_path, params={
                "workflow": "constituency_recount",
            })
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical["request_id"] == request_id and canonical["status"] == "committed"
            assert canonical["workflow"] == "constituency_recount"
            assert len(canonical["record"]["members"]) == 2
            assert [row["round"]["revision"] for row in canonical["record"]["members"]] == [1, 1]

            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            original = deepcopy(commands[0])
            assert original["status"] == "uncertain"
            assert original["workflow"] == "constituency_recount" and original["path"] == target
            expected_payload = {
                "request_id": request_id, "basis_digest": initial["basis_digest"],
                "scope_sources": initial["scope_sources"],
                "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": forms["reason"],
            }
            assert original["payload"] == expected_payload
            prior_receipt = deepcopy(original["receipt"])
            assert len(prior_receipt["record"]["members"][0]["round"]["candidate_votes"]) == 1
            files = list(journal_directory.glob("*.json"))
            assert len(files) == 1
            durable_before = json.loads(files[0].read_text(encoding="utf-8"))
            assert durable_before["payload"] == expected_payload
            _assert_credential_free(durable_before)
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 0
            assert endpoint.request_count("GET", station_outcome) == 0

            with endpoint.lock:
                endpoint.contradict_next_outcome_path = outcome_path
            child.checkOutcome()
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, child)
            checked = recovery.property("state")["commands"]
            assert len(checked) == 1
            checked = checked[0]
            assert endpoint.altered_outcome_count == 1
            assert endpoint.contradict_next_outcome_path == ""
            assert endpoint.request_count("GET", outcome_path) == 1
            assert checked["status"] == "uncertain"
            # Intended first RED: matching UUID/workflow cannot make a not_found
            # status canonical when the same real response includes a committed record.
            assert checked["error"] == "recovery_outcome_invalid"
            assert recovery.property("state")["error"] == "recovery_outcome_invalid"
            assert recovery.property("state")["notice"] == ""
            assert checked["payload"] == expected_payload and checked["receipt"] == prior_receipt
            for field in ("request_id", "server_url", "actor_id", "station_id", "workflow",
                          "path", "method", "confirmation_required", "created_at"):
                assert checked[field] == original[field]
            still_unknown = child.property("state")
            assert still_unknown["uncertain_save"] is True and still_unknown["dirty"] is True
            assert still_unknown["pending_request_id"] == request_id
            assert still_unknown["forms"] == forms
            assert still_unknown["scope_sources"] == initial["scope_sources"]
            assert still_unknown["basis_digest"] == initial["basis_digest"]
            assert client.property("workspace").property("unresolvedRequest") is True
            assert instructed.count() == 0
            durable_invalid = json.loads(files[0].read_text(encoding="utf-8"))
            assert durable_invalid["status"] == "uncertain"
            assert durable_invalid["error"] == "recovery_outcome_invalid"
            assert durable_invalid["receipt"] == durable_before["receipt"]
            assert durable_invalid["payload"] == expected_payload

            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "recovery_retry_unavailable"
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 1
            assert child.property("state")["pending_request_id"] == request_id
            assert child.property("state")["forms"] == forms and instructed.count() == 0

            child.checkOutcome()
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            settled_command = recovery.property("state")["commands"]
            assert len(settled_command) == 1
            settled_command = settled_command[0]
            assert settled_command["status"] == "committed" and settled_command["error"] == ""
            assert settled_command["payload"] == expected_payload
            assert_public_business_fields(settled_command["receipt"]["record"], canonical["record"])
            assert recovery.property("state")["error"] == ""
            settled = child.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["pending_request_id"] == "" and settled["forms"] == {
                "event_at": "", "reason": "",
            }
            assert instructed.count() == 1
            assert client.property("workspace").property("unresolvedRequest") is False
            assert endpoint.altered_outcome_count == 1
            assert endpoint.request_count("GET", outcome_path) == 2
            assert endpoint.request_count("GET", station_outcome) == 0
            assert endpoint.request_count("POST", target) == 1
            durable_after = json.loads(files[0].read_text(encoding="utf-8"))
            assert durable_after["status"] == "committed"
            assert durable_after["payload"] == expected_payload
            assert durable_after["receipt"]["record"] == canonical["record"]
            _assert_credential_free(durable_after)

        final = supervisor.get(target)
        assert final.status_code == 200 and final.json() == committed_view
        unchanged_outcome = supervisor.get(outcome_path, params={
            "workflow": "constituency_recount",
        })
        assert unchanged_outcome.status_code == 200 and unchanged_outcome.json() == canonical
        for member, prior, original_source in zip(
            canonical["record"]["members"], priors, source_views, strict=True,
        ):
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            listed = supervisor.get(rounds_path)
            assert listed.status_code == 200, listed.text
            assert [row["id"] for row in listed.json()["rounds"]] == [
                prior["selected"]["id"], member["round"]["id"],
            ]
            blank = supervisor.get(f"{rounds_path}/{member['round']['id']}")
            assert blank.status_code == 200 and blank.json()["record"] == member["round"]
            assert len(blank.json()["history"]) == 1
            source = supervisor.get(prior["round_path"])
            assert source.status_code == 200, source.text
            assert [row["revision_id"] for row in source.json()["history"]] == [
                row["revision_id"] for row in original_source["history"]
            ]
            for field in ("candidate_votes", "invalid_papers", "f2", "scope_basis", "event_at",
                          "entered_at", "actor_id", "approved_at", "approved_by"):
                assert source.json()["record"][field] == original_source["record"][field]
        assert endpoint.request_count("POST", target) == 1
