"""Supervisor physical decisions preserve exact observations through public HTTP."""

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_acceptance_preserves_observations_and_allows_exact_revision_approval(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, supervisor = setup["counter"], setup["clients"]["supervisor"]
        path = setup["rounds_path"]
        options = counter.get(path).json()
        created = counter.post(path, json=complete_f1_command(options))
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        outcomes = counter.put(target + "/f2", json=complete_f2_command(options))
        assert outcomes.status_code == 200, outcomes.text
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        before = submitted.json()
        command = {
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
            "expected_decision_revision": 0,
            "password": READY_PASSWORD,
            "reason": "紙本覆核確認實點零張；接受與凍結庫存估算五張的差異。",
        }
        accepted = supervisor.post(target + "/physical-differences/stock/accept", json=command)
        assert accepted.status_code == 200, accepted.text
        record = accepted.json()
        assert record["revision"] == 3 and record["status"] == "submitted"
        for field in ("candidate_votes", "invalid_papers", "f2", "scope_basis"):
            assert record[field] == before[field]
        assert record["actual_counted_quantity"] == 0
        stock = next(row for row in record["physical_comparisons"] if row["source"] == "stock")
        assert stock["expected_quantity"] == 5 and stock["actual_quantity"] == 0
        assert stock["difference_quantity"] == -5 and stock["status"] == "accepted"
        decision = stock["acceptance"]
        assert decision["revision"] == 1 and decision["reviewed_revision"] == 3
        assert decision["reviewed_revision_id"] == before["revision_id"]
        assert decision["reason"] == command["reason"] and decision["valid"] is True
        assert decision["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert decision["accepted_at"] == "2026-11-15T16:00:00Z"
        assert len(record["physical_decisions"]) == 1
        assert record["approval_blockers"] == []
        approval = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approval.status_code == 200, approval.text
        assert approval.json()["revision"] == 4 and approval.json()["approval_valid"] is True
        assert approval.json()["actual_counted_quantity"] == 0
        assert (
            next(
                row for row in approval.json()["physical_comparisons"] if row["source"] == "stock"
            )["difference_quantity"]
            == -5
        )
        selected = supervisor.post(
            target + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["selected"] is True
        replay = supervisor.post(target + "/physical-differences/stock/accept", json=command)
        assert replay.status_code == 200 and replay.json() == record
        history = supervisor.get(target).json()
        assert len(history["history"]) == 4
        assert len(history["record"]["physical_decisions"]) == 1
        assert READY_PASSWORD not in json.dumps(history)
