"""Application-outage paper count reentry through authenticated public APIs."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_paper_count_submission_reenters_once_and_supervisor_reconciles(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, rounds_path = setup["counter"], setup["rounds_path"]
        options = counter.get(rounds_path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = counter.post(rounds_path, json=f1)
        assert created.status_code == 201, created.text
        round_target = rounds_path + f"/{created.json()['id']}"
        f2 = counter.put(round_target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text

        station_id = setup["stations"]["N1"]["id"]
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = counter.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "N1 network outage " + uuid4().hex[:10],
                "kind": "network",
                "started_at": "2026-11-15T23:15:00+08:00",
                "ended_at": "2026-11-15T23:40:00+08:00",
                "notes": "Backend connection was unavailable; staff used paper records.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_record_path = f"{outage_path}/{outage_id}"
        paper_reference = "N1-PAPER-" + uuid4().hex[:12]
        paper_command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": paper_reference,
            "workflow": "count",
            "action": "submit",
            "original_event_at": "2026-11-15T23:35:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": created.json()["id"]},
            "notes": "Supervisor checklist references this signed paper return.",
        }
        paper = counter.post(outage_record_path + "/paper-records", json=paper_command)
        assert paper.status_code == 201, paper.text
        assert paper.json()["status"] == "pending"

        paper_request_id = str(uuid4())
        submission = {
            "request_id": paper_request_id,
            "expected_revision": 1,
            "scope_revision": options["scope"]["revision"],
            "paper_record_id": paper.json()["id"],
        }
        stale = counter.post(round_target + "/submit", json=submission)
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "revision_conflict"
        unchanged = counter.get(round_target)
        assert unchanged.status_code == 200, unchanged.text
        assert [row["revision"] for row in unchanged.json()["history"]] == [2, 1]
        pending = counter.get(outage_record_path)
        assert pending.status_code == 200, pending.text
        assert pending.json()["record"]["paper_records"][0]["status"] == "pending"

        submission["expected_revision"] = 2
        submitted = counter.post(round_target + "/submit", json=submission)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["revision"] == 3
        assert submitted.json()["status"] == "submitted"

        reentered = counter.get(outage_record_path)
        assert reentered.status_code == 200, reentered.text
        paper_row = reentered.json()["record"]["paper_records"][0]
        assert paper_row["paper_reference"] == paper_reference
        assert paper_row["workflow"] == "count" and paper_row["action"] == "submit"
        assert paper_row["status"] == "entered"
        assert paper_row["original_event_at"] == "2026-11-15T15:35:00Z"
        assert paper_row["entered_at"]
        assert paper_row["reentry"]["request_id"] == paper_request_id
        assert paper_row["reentry"]["actor_id"] == setup["accounts"]["receiveronly"]["id"]
        assert paper_row["reentry"]["entered_at"]
        assert paper_row["reentry"]["record"] == submitted.json()

        outage_state = reentered.json()["record"]
        duplicate_reference = counter.post(
            outage_record_path + "/paper-records",
            json={
                **paper_command,
                "request_id": str(uuid4()),
                "expected_outage_revision": outage_state["revision"],
            },
        )
        assert duplicate_reference.status_code == 409, duplicate_reference.text

        duplicate_effect = counter.post(
            round_target + "/submit",
            json={
                **submission,
                "request_id": str(uuid4()),
                "expected_revision": 3,
            },
        )
        assert duplicate_effect.status_code == 409, duplicate_effect.text
        count_history = counter.get(round_target).json()
        assert [row["revision"] for row in count_history["history"]] == [3, 2, 1]
        assert counter.get(outage_record_path).json()["record"]["paper_records"] == [paper_row]

        supervisor = setup["clients"]["supervisor"]
        reconciled = supervisor.post(
            outage_record_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": outage_state["revision"],
                "expected_reconciliation_revision": 0,
                "paper_revisions": [{"paper_id": paper_row["id"], "revision": 1}],
                "password": READY_PASSWORD,
                "reason": "Supervisor compared the entered count with the signed paper return.",
            },
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["record"]["reconciled"] is True
        assert reconciled.json()["record"]["reconciliation"]["valid"] is True
        current_count = counter.get(round_target).json()["record"]
        assert current_count["status"] == "submitted"
        assert current_count["approval_valid"] is False
        assert current_count.get("approved_at") is None
