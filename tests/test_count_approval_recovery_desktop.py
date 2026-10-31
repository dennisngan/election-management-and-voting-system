"""A Supervisor approval receipt preserves F1 ownership and settles client recovery."""

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_approval_settles_recovery_and_preserves_the_original_f1_actor(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-commands"))
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter = setup["counter"]
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        scope_id = setup["scope"]["id"]
        counting_officer_id = setup["accounts"]["receiveronly"]["id"]
        supervisor_id = setup["accounts"]["supervisor"]["id"]
        assert counting_officer_id != supervisor_id
        rounds_path = setup["rounds_path"]
        options_response = counter.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        initial = complete_f1_command(
            options, actual_counted_quantity=5, notes="Original Counting Officer observation."
        )
        initial["candidate_votes"][0]["quantity"] = 5
        created = counter.post(rounds_path, json=initial)
        assert created.status_code == 201, created.text
        assert created.json()["actor_id"] == counting_officer_id
        target = rounds_path + f"/{created.json()['id']}"
        outcomes = counter.put(target + "/f2", json=complete_f2_command(options))
        assert outcomes.status_code == 200, outcomes.text
        assert outcomes.json()["f2_complete"] is True
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": outcomes.json()["revision"],
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        before = submitted.json()
        assert before["revision"] == 3 and before["status"] == "submitted"
        assert before["actor_id"] == counting_officer_id
        assert before["source_current"] is True and before["count_inputs_complete"] is True
        assert before["approval_blockers"] == []
        assert before["physical_decisions"] == []
        stock = next(row for row in before["physical_comparisons"] if row["source"] == "stock")
        assert stock["expected_quantity"] == stock["actual_quantity"] == 5
        assert stock["difference_quantity"] == 0 and stock["status"] == "matching"
        approval_path = target + "/approve"
        frozen_fields = (
            "id", "round_number", "scope_id", "scope_revision", "candidate_votes",
            "invalid_papers", "questionable_quantity", "actual_counted_quantity", "f2",
            "scope_basis", "event_at", "entered_at", "actor_id", "notes", "amendment_reason",
        )
        frozen_observation = {key: before[key] for key in frozen_fields}

        with f1_editor(
            https_server, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            assert_public_business_fields(editor.property("state")["selected"], before)
            assert https_server.request_count("POST", approval_path) == 0
            editor.approveCount(READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)

            # Establish the real committed approval before local receipt assertions.
            persisted_response = supervisor.get(target)
            assert persisted_response.status_code == 200, persisted_response.text
            history = persisted_response.json()
            persisted = history["record"]
            assert persisted["revision"] == 4 and persisted["status"] == "approved"
            assert persisted["revision_id"] != before["revision_id"]
            assert persisted["approval_valid"] is True
            assert persisted["actor_id"] == counting_officer_id
            assert persisted["revision_actor_id"] == persisted["approved_by"] == supervisor_id
            assert persisted["approved_at"] is not None
            assert persisted["revision_event_at"] == persisted["approved_at"]
            assert persisted["reviewed_revision"] == before["revision"]
            assert persisted["reviewed_revision_id"] == before["revision_id"]
            assert_public_business_fields(
                {key: persisted[key] for key in frozen_fields}, frozen_observation
            )
            assert persisted["physical_decisions"] == []
            assert [row["revision"] for row in history["history"]] == [4, 3, 2, 1]

            recovery = client.property("recovery")
            assert recovery is not None
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = [row for row in recovery.property("state")["commands"]
                        if row["path"] == approval_path]
            assert len(commands) == 1
            # Keep the normal-ACK state distinct from the later explicit outcome check.
            acknowledged = deepcopy(commands[0])
            request_id = acknowledged["request_id"]
            assert acknowledged["actor_id"] == supervisor_id
            assert acknowledged["station_id"] == station_id
            assert acknowledged["workflow"] == "count"
            assert acknowledged["method"] == "POST"
            assert acknowledged["confirmation_required"] is True
            assert acknowledged["payload"] == {
                "request_id": request_id,
                "expected_revision": before["revision"],
                "scope_revision": before["scope_revision"],
            }
            assert READY_PASSWORD not in json.dumps(acknowledged)
            assert "password" not in json.dumps(acknowledged["payload"]).lower()
            outcome_path = (
                f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            )
            public_outcome = supervisor.get(outcome_path + "?workflow=count")
            assert public_outcome.status_code == 200, public_outcome.text
            outcome = public_outcome.json()
            assert outcome["request_id"] == request_id
            assert outcome["workflow"] == "count" and outcome["status"] == "committed"
            assert outcome["record"] == persisted

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            checked = next(row for row in recovery.property("state")["commands"]
                           if row["request_id"] == request_id)
            assert acknowledged["status"] == checked["status"] == "committed", {
                "ack_status": acknowledged["status"],
                "ack_error": acknowledged["error"],
                "checked_status": checked["status"],
                "checked_error": checked["error"],
            }
            assert acknowledged["error"] == checked["error"] == ""
            assert_public_business_fields(acknowledged["receipt"]["record"], outcome["record"])
            assert_public_business_fields(checked["receipt"]["record"], outcome["record"])
            assert recovery.property("state")["error"] == ""
            state = editor.property("state")
            assert state["error"] == "" and state["uncertain_save"] is False
            assert state["notice"] == "count_approved"
            assert_public_business_fields(state["selected"], persisted)
            after_check = supervisor.get(target)
            assert after_check.status_code == 200, after_check.text
            assert after_check.json() == history
            assert https_server.request_count("POST", approval_path) == 1
            assert https_server.request_count("GET", outcome_path) == 1
