"""F1 initial tally drafts through authenticated real-MySQL API journeys."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_counting_officer_opens_ready_scope_and_resumes_incomplete_initial_draft(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        available = client.get(path)
        assert available.status_code == 200, available.text
        options = available.json()
        assert options["scope"] == setup["scope"]
        assert len(options["candidates"]) == 1
        candidate = options["candidates"][0]
        assert candidate["constituency_id"] == setup["stations"]["N1"]["constituency_id"]
        assert candidate["ballot_number"] == 1
        assert len(options["invalid_reasons"]) == 8
        assert options["rounds"] == []
        payload = {
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "scope_revision": 1,
            "event_at": "2026-11-15T23:15:12.123456+08:00",
            "candidate_votes": [{"candidate_id": candidate["id"], "quantity": None}],
            "invalid_papers": [],
            "questionable_quantity": 3,
            "actual_counted_quantity": None,
            "notes": "先保存問題選票數量；空白仍未點算。",
        }
        saved = client.post(path, json=payload)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        assert record["round_number"] == 1 and record["revision"] == 1
        assert record["status"] == "draft" and record["f1_complete"] is False
        assert record["scope_basis"] == setup["scope"]
        assert record["candidate_votes"][0]["quantity"] is None
        assert record["questionable_quantity"] == 3
        assert record["actual_counted_quantity"] is None
        assert record["initial_valid_quantity"] is None
        assert record["initial_accounted_quantity"] is None
        assert record["initial_arithmetic_valid"] is None
        assert record["event_at"] == "2026-11-15T15:15:12.123456Z"
        assert {item["code"] for item in record["blockers"]} == {
            "f1_candidate_missing",
            "f1_invalid_reason_missing",
            "f1_actual_missing",
        }
        assert all(row["quantity"] is None for row in record["invalid_papers"])
        assert client.get(path).json()["rounds"] == [record]
        resumed = client.get(path + f"/{record['id']}")
        assert resumed.status_code == 200
        assert resumed.json() == {"record": record, "history": [record]}
        replay = client.post(path, json=payload)
        assert replay.status_code == 200 and replay.json() == record


def test_explicit_zero_and_questionable_papers_balance_without_using_stock_as_actual_count(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url, candidates_per_constituency=2) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        assert [row["ballot_number"] for row in options["candidates"]] == [1, 2]
        command = complete_f1_command(options)
        saved = client.post(path, json=command)
        assert saved.status_code == 201, saved.text
        original = saved.json()
        assert original["f1_complete"] is True and original["initial_arithmetic_valid"] is True
        assert original["actual_counted_quantity"] == 0
        assert original["initial_valid_quantity"] == 0
        assert original["clearly_invalid_quantity"] == 0
        assert original["initial_accounted_quantity"] == 0
        assert original["blockers"] == []
        assert original["scope_basis"]["estimated_box_from_stock_quantity"] == 5
        target = path + f"/{original['id']}"
        command.update(
            request_id=str(uuid4()),
            expected_revision=1,
            questionable_quantity=3,
            actual_counted_quantity=9,
        )
        command["candidate_votes"][0]["quantity"] = 4
        unmarked = next(row for row in options["invalid_reasons"] if row["source_letter"] == "d")
        next(row for row in command["invalid_papers"] if row["reason_id"] == unmarked["id"])[
            "quantity"
        ] = 1
        invalid = client.put(target, json=command)
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["detail"] == {
            "code": "f1_arithmetic_invalid",
            "accounted_quantity": 8,
            "actual_quantity": 9,
        }
        assert client.get(target).json() == {"record": original, "history": [original]}
        command.update(
            request_id=str(uuid4()),
            actual_counted_quantity=8,
            notes="四張候選人票、一張無標記票、三張問題選票。",
        )
        amended = client.put(target, json=command)
        assert amended.status_code == 200, amended.text
        record = amended.json()
        assert record["revision"] == 2 and record["f1_complete"] is True
        assert record["initial_valid_quantity"] == 4
        assert record["clearly_invalid_quantity"] == 1
        assert record["questionable_quantity"] == 3
        assert record["actual_counted_quantity"] == record["initial_accounted_quantity"] == 8
        assert record["source_current"] is True
        assert record["scope_basis"] == original["scope_basis"]
        assert record["candidate_votes"][1]["quantity"] == 0
        history = client.get(target).json()["history"]
        assert [row["revision"] for row in history] == [2, 1]
        assert history[1]["actual_counted_quantity"] == 0
        assert history[1]["is_current"] is False
        assert client.get(target + "/revisions/1").json() == history[1]


@pytest.mark.parametrize("quantity", [-1, True, 1.5, "3"])
def test_f1_rejects_non_integer_or_negative_observations_without_creating_a_round(
    admin: TestClient,
    database_url: str,
    quantity: object,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        command = complete_f1_command(options)
        command["candidate_votes"][0]["quantity"] = quantity
        rejected = client.post(path, json=command)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "validation_error"
        assert client.get(path).json()["rounds"] == []


def test_other_reason_needs_an_explanation_for_positive_papers_and_preserves_text(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        other = next(row for row in options["invalid_reasons"] if row["is_other"])
        command = complete_f1_command(options, actual_counted_quantity=2)
        entry = next(row for row in command["invalid_papers"] if row["reason_id"] == other["id"])
        entry["quantity"] = 2
        rejected = client.post(path, json=command)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "invalid_reason_explanation_required"
        assert client.get(path).json()["rounds"] == []
        entry["explanation"] = "紙本補充分類第一行。\n第二行：保留核對說明。"
        command["request_id"] = str(uuid4())
        saved = client.post(path, json=command)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        assert record["f1_complete"] is True and record["clearly_invalid_quantity"] == 2
        kept = next(row for row in record["invalid_papers"] if row["is_other"])
        assert kept["explanation"] == entry["explanation"]
        assert kept["verified_source"] is False and kept["source_letter"] is None
        assert kept["label_en"] == "Other" and kept["explanation_required"] is True
