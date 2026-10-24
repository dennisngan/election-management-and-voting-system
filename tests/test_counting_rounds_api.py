"""F1 initial tally drafts through authenticated real-MySQL API journeys."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.tally_support import tally_setup
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
