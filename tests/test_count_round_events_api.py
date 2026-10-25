"""Round-owned events retain identity without implying station completion."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_box_timeline_preserves_round_determination_corrections_and_workflow_completion(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, supervisor, path = (
            setup["counter"],
            setup["clients"]["supervisor"],
            setup["rounds_path"],
        )
        options = client.get(path).json()
        initial = complete_f1_command(options, questionable_quantity=3, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 2
        created = client.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        f2 = complete_f2_command(
            options, determination_started_at="2026-11-15T23:18:12.123456+08:00"
        )
        f2["accepted_votes"][0]["quantity"] = 2
        uncertainty = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        next(row for row in f2["rejected_papers"] if row["reason_id"] == uncertainty["id"])[
            "quantity"
        ] = 1
        first = client.put(target + "/f2", json=f2)
        assert first.status_code == 200, first.text
        second = client.put(
            target + "/f2",
            json={
                **f2,
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "determination_started_at": "2026-11-15T23:19:00.654321+08:00",
                "amendment_reason": "Corrected from paper time record",
            },
        )
        assert second.status_code == 200, second.text
        submitted = client.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        approved = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        selected = supervisor.post(
            target + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 5,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
                "expected_selection_revision": 0,
            },
        )
        assert selected.status_code == 200, selected.text
        box_path = f"/api/workspace/stations/{setup['stations']['N1']['id']}/boxes"
        snapshot = client.get(box_path).json()
        assert snapshot["count_completion"] is None
        events = snapshot["count_events"]
        assert len(events) == 3 and len({row["event_id"] for row in events}) == 3
        starts = sorted(
            (row for row in events if row["kind"] == "determination_start"),
            key=lambda row: row["round_revision"],
        )
        assert [row["event_at"] for row in starts] == [
            "2026-11-15T15:18:12.123456Z",
            "2026-11-15T15:19:00.654321Z",
        ]
        assert [row["is_current"] for row in starts] == [False, True]
        assert [row["round_revision_id"] for row in starts] == [
            first.json()["revision_id"],
            second.json()["revision_id"],
        ]
        completion = next(row for row in events if row["kind"] == "count_completion")
        assert completion["event_at"] == "2026-11-15T16:00:00Z"
        assert completion["round_revision_id"] == submitted.json()["revision_id"]
        assert completion["current_round_revision_id"] == approved.json()["revision_id"]
        assert completion["selected"] is True and completion["status"] == "approved"
        assert completion["scope_id"] == setup["scope"]["id"]
        assert completion["scope_revision"] == setup["scope"]["revision"]
        assert completion["scope_reference"] == setup["scope"]["reference"]
        assert completion["round_id"] == created.json()["id"] and completion["round_number"] == 1
        assert completion["source_current"] is True and completion["approval_valid"] is True
        source_only = setup["clients"]["polling"].get(
            f"/api/workspace/stations/{setup['stations']['N2']['id']}/boxes"
        )
        assert source_only.status_code == 200, source_only.text
        assert source_only.json()["count_events"] == []
