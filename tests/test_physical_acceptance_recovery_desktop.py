"""A committed physical review settles recovery without rewriting count observations."""

import json
from collections.abc import Iterator
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


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_physical_acceptance_settles_recovery_without_revising_frozen_counts(
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
        supervisor_id = setup["accounts"]["supervisor"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = counter.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        initial = complete_f1_command(options, actual_counted_quantity=4)
        initial["candidate_votes"][0]["quantity"] = 4
        created = counter.post(rounds_path, json=initial)
        assert created.status_code == 201, created.text
        target = rounds_path + f"/{created.json()['id']}"
        outcomes = counter.put(target + "/f2", json=complete_f2_command(options))
        assert outcomes.status_code == 200, outcomes.text
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
        assert before["actor_id"] != supervisor_id
        stock_before = next(
            row for row in before["physical_comparisons"] if row["source"] == "stock"
        )
        assert stock_before["expected_quantity"] == 5
        assert stock_before["actual_quantity"] == 4
        assert stock_before["difference_quantity"] == -1
        assert stock_before["status"] == "pending"
        acceptance_path = target + "/physical-differences/stock/accept"
        frozen_fields = (
            "id", "revision", "revision_id", "status", "scope_id", "scope_revision",
            "candidate_votes", "invalid_papers", "questionable_quantity",
            "actual_counted_quantity", "f2", "scope_basis", "actor_id", "revision_actor_id",
        )
        frozen_count = {field: before[field] for field in frozen_fields}
        reason = "Sealed-box paper review confirms the observed four against stock five."

        with f1_editor(
            https_server, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            assert editor.property("state")["selected"]["revision_id"] == before["revision_id"]
            editor.acceptPhysicalDifference("stock", reason, READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)

            # Establish the committed public effect before checking local settlement.
            persisted_response = supervisor.get(target)
            assert persisted_response.status_code == 200, persisted_response.text
            history = persisted_response.json()
            persisted = history["record"]
            assert {field: persisted[field] for field in frozen_fields} == frozen_count
            assert [row["revision"] for row in history["history"]] == [3, 2, 1]
            stock = next(
                row for row in persisted["physical_comparisons"] if row["source"] == "stock"
            )
            assert stock["expected_quantity"] == 5 and stock["actual_quantity"] == 4
            assert stock["difference_quantity"] == -1 and stock["status"] == "accepted"
            decision = stock["acceptance"]
            assert len(persisted["physical_decisions"]) == 1
            assert decision["source"] == "stock" and decision["revision"] == 1
            assert decision["reviewed_revision"] == before["revision"]
            assert decision["reviewed_revision_id"] == before["revision_id"]
            assert decision["actor_id"] == supervisor_id
            assert decision["reason"] == reason and decision["valid"] is True

            recovery = client.property("recovery")
            assert recovery is not None
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = [
                row for row in recovery.property("state")["commands"]
                if row["path"] == acceptance_path
            ]
            assert len(commands) == 1
            acknowledged = commands[0]
            request_id = acknowledged["request_id"]
            assert acknowledged["actor_id"] == supervisor_id
            assert acknowledged["station_id"] == station_id
            assert acknowledged["workflow"] == "count"
            assert acknowledged["confirmation_required"] is True
            assert READY_PASSWORD not in json.dumps(acknowledged)
            assert "password" not in json.dumps(acknowledged["payload"]).lower()
            outcome_path = (
                f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            )
            outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            assert outcome["request_id"] == request_id
            assert outcome["workflow"] == "count" and outcome["status"] == "committed"
            assert {field: outcome["record"][field] for field in frozen_fields} == frozen_count
            assert outcome["record"]["physical_decisions"] == persisted["physical_decisions"]

            # A read-only outcome check must recognize the same immutable receipt.
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            checked = next(
                row for row in recovery.property("state")["commands"]
                if row["request_id"] == request_id
            )
            assert acknowledged["status"] == checked["status"] == "committed", {
                "ack_status": acknowledged["status"],
                "ack_error": acknowledged["error"],
                "checked_status": checked["status"],
                "checked_error": checked["error"],
            }
            assert acknowledged["receipt"]["record"] == outcome["record"]
            assert checked["receipt"]["record"] == outcome["record"]
            assert recovery.property("state")["error"] == ""
            editor_state = editor.property("state")
            assert editor_state["error"] == "" and editor_state["uncertain_save"] is False
            assert editor_state["notice"] == "physical_difference_accepted"
            selected = editor_state["selected"]
            assert {field: selected[field] for field in frozen_fields} == frozen_count
            assert selected["physical_decisions"] == persisted["physical_decisions"]
            assert https_server.request_count("POST", acceptance_path) == 1
            assert https_server.request_count("GET", outcome_path) == 1
