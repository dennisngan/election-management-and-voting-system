"""Questionable-paper determination through authenticated real-MySQL workflows."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_counting_officer_saves_and_resumes_partial_f2_without_changing_f1(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        command = complete_f1_command(options, questionable_quantity=3, actual_counted_quantity=5)
        command["candidate_votes"][0]["quantity"] = 2
        first = client.post(path, json=command)
        assert first.status_code == 201, first.text
        f1 = first.json()
        options = client.get(path).json()
        reasons = options["f2_invalid_reasons"]
        assert {row["code"] for row in reasons} == {
            "gc-f2-h",
            "gc-f2-i",
            "gc-f2-j",
            "gc-f2-k",
            "other-f2",
        }
        identifying = next(row for row in reasons if row["code"] == "gc-f2-h")
        assert identifying["source_english"] == (
            "With writing or mark by which the elector can possibly be identified"
        )
        assert identifying["reference_page"] == 119
        assert identifying["reference_printed_page"] == 120
        payload = {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "scope_revision": setup["scope"]["revision"],
            "event_at": "2026-11-15T23:20:17.654321+08:00",
            "determination_started_at": "2026-11-15T23:18:12.123456+08:00",
            "accepted_votes": [],
            "rejected_papers": [],
            "notes": "開始判定問題選票；尚未完成各項觀察。",
        }
        saved = client.put(path + f"/{f1['id']}/f2", json=payload)
        assert saved.status_code == 200, saved.text
        record = saved.json()
        assert record["revision"] == 2 and record["status"] == "draft"
        assert record["f1_complete"] is True and record["f2_complete"] is False
        assert record["count_complete"] is False
        assert record["questionable_quantity"] == 3 and record["actual_counted_quantity"] == 5
        assert record["event_at"] == f1["event_at"]
        assert record["entered_at"] == f1["entered_at"]
        assert record["candidate_votes"] == f1["candidate_votes"]
        assert record["scope_basis"] == f1["scope_basis"]
        assert record["f2"]["event_at"] == "2026-11-15T15:20:17.654321Z"
        assert record["f2"]["determination_started_at"] == "2026-11-15T15:18:12.123456Z"
        assert record["f2"]["accepted_votes"][0]["quantity"] is None
        assert all(row["quantity"] is None for row in record["f2"]["rejected_papers"])
        assert record["final_accounted_quantity"] is None
        resumed = client.get(path + f"/{f1['id']}")
        assert resumed.status_code == 200
        assert resumed.json()["record"] == record
        assert [row["revision"] for row in resumed.json()["history"]] == [2, 1]
        assert resumed.json()["history"][1]["candidate_votes"] == f1["candidate_votes"]
        replay = client.put(path + f"/{f1['id']}/f2", json=payload)
        assert replay.status_code == 200 and replay.json() == record


def test_balanced_f2_derives_f3_f4_without_double_counting_questionable_papers(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1_command = complete_f1_command(
            options, questionable_quantity=3, actual_counted_quantity=5
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        first = client.post(path, json=f1_command)
        assert first.status_code == 201, first.text
        f1 = first.json()
        command = complete_f2_command(
            options, determination_started_at="2026-11-15T23:18:12.123456+08:00"
        )
        command["accepted_votes"][0]["quantity"] = 2
        uncertainty = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        next(row for row in command["rejected_papers"] if row["reason_id"] == uncertainty["id"])[
            "quantity"
        ] = 1
        saved = client.put(path + f"/{f1['id']}/f2", json=command)
        assert saved.status_code == 200, saved.text
        record = saved.json()
        assert record["status"] == "draft"
        assert record["f2_complete"] is True
        # Reconciled inputs do not complete the workflow before submission.
        assert record["count_complete"] is False
        assert record["count_inputs_complete"] is True
        assert record["accepted_questionable_quantity"] == 2
        assert record["rejected_questionable_quantity"] == 1
        assert record["final_candidate_votes"][0]["quantity"] == 4
        assert record["final_valid_quantity"] == 4
        assert record["final_invalid_quantity"] == 1
        assert record["final_accounted_quantity"] == 5
        assert record["actual_counted_quantity"] == 5
        assert record["final_arithmetic_valid"] is True
        assert record["completed_at"] is None
        assert record["blockers"] == []
        assert record["event_at"] == f1["event_at"]
        resumed = client.get(path + f"/{f1['id']}")
        assert resumed.status_code == 200 and resumed.json()["record"] == record
