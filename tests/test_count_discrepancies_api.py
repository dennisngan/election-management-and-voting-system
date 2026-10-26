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


def _accepted_submission(setup: dict, *, actual: int = 0) -> tuple[dict, str, dict]:
    counter, supervisor = setup["counter"], setup["clients"]["supervisor"]
    path = setup["rounds_path"]
    options = counter.get(path).json()
    initial = complete_f1_command(options, actual_counted_quantity=actual)
    initial["candidate_votes"][0]["quantity"] = actual
    created = counter.post(path, json=initial)
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
    accepted = supervisor.post(
        target + "/physical-differences/stock/accept",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
            "expected_decision_revision": 0,
            "password": READY_PASSWORD,
            "reason": "Reviewed the exact physical figures against the signed paper log.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return options, target, accepted.json()


def test_later_physical_review_does_not_change_an_earlier_count_revision(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, target, accepted = _accepted_submission(setup)
        assert accepted["revision"] == 3
        old = setup["clients"]["supervisor"].get(target + "/revisions/2")
        assert old.status_code == 200, old.text
        historical = old.json()
        assert historical["revision"] == 2 and historical["status"] == "draft"
        stock = next(row for row in historical["physical_comparisons"] if row["source"] == "stock")
        assert stock["status"] == "pending"
        assert "acceptance" not in stock
        assert historical["physical_decisions"][0]["reviewed_revision"] == 3
        assert historical["physical_decisions"][0]["valid"] is False


def test_physical_decision_preserves_large_quantities_in_history_and_approval(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        actual = 900719925474099312345
        options, target, accepted = _accepted_submission(setup, actual=actual)
        expected_difference = 900719925474099312340
        stock = next(row for row in accepted["physical_comparisons"] if row["source"] == "stock")
        assert stock["actual_quantity"] == actual
        assert stock["difference_quantity"] == expected_difference
        decision = stock["acceptance"]
        assert type(decision["actual_quantity"]) is int
        assert decision["actual_quantity"] == actual
        assert decision["difference_quantity"] == expected_difference
        approved = setup["clients"]["supervisor"].post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        record = setup["clients"]["supervisor"].get(target).json()["record"]
        assert record["approval_valid"] is True
        assert record["actual_counted_quantity"] == actual
        assert record["physical_decisions"][0]["difference_quantity"] == expected_difference
        report = setup["clients"]["supervisor"].get(target + "/revisions/4/f4").json()
        assert report["record"]["physical_decisions"][0]["actual_quantity"] == actual


def test_approved_physical_snapshot_survives_a_successor_scope_basis(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, target, accepted = _accepted_submission(setup)
        supervisor, counter = setup["clients"]["supervisor"], setup["counter"]
        approved = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        original = approved.json()
        assert original["approved_physical_decisions"] == accepted["physical_decisions"]
        scope_path = setup["paths"]["n1_counting_scopes"] + f"/{setup['scope']['id']}"
        amended = counter.put(
            scope_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": setup["scope"]["revision"],
                "reference": setup["scope"]["reference"],
                "event_at": "2026-11-15T23:30:00+08:00",
                "box_revisions": [
                    {
                        "box_id": setup["boxes"]["local_n1"]["id"],
                        "revision": setup["boxes"]["local_n1"]["revision"],
                    }
                ],
                "accounting_revisions": [
                    {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
                ],
                "amendment_reason": "Corrected scope context from the retained handover log.",
            },
        )
        assert amended.status_code == 200, amended.text
        historical = supervisor.get(target + "/revisions/4")
        assert historical.status_code == 200, historical.text
        record = historical.json()
        assert record["status"] == "approved" and record["approval_valid"] is False
        assert record["source_current"] is False
        assert record["approved_physical_decisions"] == original["approved_physical_decisions"]
        assert record["reviewed_physical_comparisons"] == original["physical_comparisons"]
        frozen = record["approved_physical_decisions"][0]
        assert frozen["difference_quantity"] == -5
        assert frozen["reason"] == accepted["physical_decisions"][0]["reason"]
        assert frozen["reviewed_revision"] == 3
