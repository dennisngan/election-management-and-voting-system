"""Immutable completion-event reports retain the exact finalized source facts."""

import csv
from collections.abc import Iterator
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.complaint_support import complaint_payload, station_categories
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _csv_rows(response: Response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].partition(";")[0] == "text/csv"
    assert response.headers["content-disposition"].lower().startswith("attachment;")
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))


def _has_pair(rows: list[list[str]], label: str, value: object) -> bool:
    return any(
        row[index:index + 2] == [label, str(value)]
        for row in rows for index in range(len(row) - 1)
    )


def test_original_completion_csv_keeps_finalized_facts_after_reopening_and_complaint_edit(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        officer = setup["clients"]["polling"]
        election_id = setup["election"]["id"]
        station_id = setup["stations"]["N1"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        complaints_path = f"/api/workspace/stations/{station_id}/complaints"
        category = station_categories(officer, station_id)[0]
        case_reference = "completion-csv-" + uuid4().hex[:12]
        created = officer.post(complaints_path, json=complaint_payload(
            category, case_reference=case_reference,
        ))
        assert created.status_code == 201, created.text
        complaint = created.json()
        assert complaint["work_status"] == "in_progress" and complaint["completed_at"] is None
        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        reviewed = assessment_response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        event = original["event"]
        assert event["kind"] == "finalization"
        assert {
            "station_id": station_id, "records": [complaint],
        } in event["outcome"]["sources"]["complaints"]
        results = event["outcome"]["results"]
        assert [[row["quantity"] for row in result["candidate_totals"]]
                for result in results] == [[6, 4], [4, 1]]
        report_path = base + f"/completion/history/{event['id']}/statement.csv"
        # First meaningful RED is the real missing report route returning404.
        before = _csv_rows(supervisor.get(report_path, params={"locale": "en"}))
        for label, value in (
            ("Election ID", election_id), ("Election", original["election"]["name"]),
            ("Event ID", event["id"]), ("Status", "Finalized"),
            ("Revision", event["election_revision"]), ("Basis digest", event["basis_digest"]),
            ("Actor ID", event["actor_id"]),
        ):
            assert _has_pair(before, label, value), (label, value, before)
        for result in results:
            for candidate in result["candidate_totals"]:
                assert any(
                    str(candidate["candidate_id"]) in row and candidate["name"] in row
                    and str(candidate["quantity"]) in row for row in before
                ), (candidate, before)
        assert any(case_reference in row and "In progress" in row for row in before), before
        generated_before = [row for row in before if row and row[0] == "Generated at"]
        assert len(generated_before) == 1 and len(generated_before[0]) == 2
        assert generated_before[0][1].endswith(" HKT")
        frozen_rows = [row for row in before if not row or row[0] != "Generated at"]
        reopened = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": event["id"],
            "reason": "Review later complaint progress without replacing the signed outcome.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened.status_code == 201, reopened.text
        assert reopened.json()["election"]["status"] == "active"
        updated = officer.put(f"{complaints_path}/{complaint['id']}", json=complaint_payload(
            category, case_reference=case_reference, expected_revision=complaint["revision"],
            work_status="completed", completed_at="2026-11-15T09:00:00+08:00",
            description="Progress recorded only after the election was reopened.",
        ))
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == complaint["revision"] + 1
        assert updated.json()["work_status"] == "completed"
        current = officer.get(f"{complaints_path}/{complaint['id']}")
        assert current.status_code == 200 and current.json() == updated.json()
        # Approved controlled fixture time; no sleep or production time-control route.
        setup["clock"].value += timedelta(minutes=1)
        after = _csv_rows(supervisor.get(report_path, params={"locale": "en"}))
        generated_after = [row for row in after if row and row[0] == "Generated at"]
        assert len(generated_after) == 1 and len(generated_after[0]) == 2
        assert generated_after[0][1].endswith(" HKT")
        assert generated_after != generated_before
        assert [row for row in after if not row or row[0] != "Generated at"] == frozen_rows
        history = supervisor.get(base + "/completion/history")
        assert history.status_code == 200, history.text
        retained = next(row for row in history.json()["events"] if row["id"] == event["id"])
        assert retained == event
