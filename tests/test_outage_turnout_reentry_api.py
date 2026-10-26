"""Paper turnout entries use the existing authenticated turnout API seam."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_turnout_api import clear_private_active_pointer as clear_private_active_pointer
from tests.test_turnout_api import database_url as database_url
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


def test_paper_turnout_save_submit_replay_and_approval_separation(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    outage_path = f"/api/workspace/stations/{station_id}/outages"
    outage_start = "2026-11-15T09:00:00+08:00"
    outage_end = "2026-11-15T10:00:00+08:00"
    event_at = "2026-11-15T09:30:00+08:00"

    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, officer_account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        outage = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "N1 turnout paper outage " + uuid4().hex[:8],
                "kind": "network",
                "started_at": outage_start,
                "ended_at": outage_end,
                "notes": "Turnout service was unavailable; staff used signed paper records.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_record_path = outage_path + f"/{outage_id}"

        save_reference = "N1-TURNOUT-SAVE-" + uuid4().hex[:10]
        save_paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": save_reference,
                "workflow": "turnout",
                "action": "save",
                "original_event_at": event_at,
                "target": {"period_index": 1},
                "notes": "Signed paper turnout worksheet for period one.",
            },
        )
        assert save_paper.status_code == 201, save_paper.text
        save_paper_id = save_paper.json()["id"]
        assert save_paper.json()["status"] == "pending"

        invalid_quantity = turnout_draft(
            supplied_hourly=-1,
            event_at=event_at,
            source_context="Signed period-one turnout worksheet.",
            paper_record_id=save_paper_id,
        )
        rejected = officer.put(path + "/1", json=invalid_quantity)
        assert rejected.status_code == 422, rejected.text
        pending = officer.get(outage_record_path).json()["record"]["paper_records"]
        assert next(row for row in pending if row["id"] == save_paper_id)["status"] == "pending"

        mismatched_time = turnout_draft(
            supplied_hourly=7,
            event_at="2026-11-15T09:31:00+08:00",
            source_context="Signed period-one turnout worksheet.",
            paper_record_id=save_paper_id,
        )
        time_conflict = officer.put(path + "/1", json=mismatched_time)
        assert time_conflict.status_code == 409, time_conflict.text
        assert time_conflict.json()["detail"]["code"] == "paper_record_time_conflict"
        pending = officer.get(outage_record_path).json()["record"]["paper_records"]
        assert next(row for row in pending if row["id"] == save_paper_id)["status"] == "pending"

        save_command = turnout_draft(
            supplied_hourly=7,
            supplied_cumulative=7,
            event_at=event_at,
            source_context="Signed period-one turnout worksheet.",
            paper_record_id=save_paper_id,
        )
        saved = officer.put(path + "/1", json=save_command)
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "draft"
        replay = officer.put(path + "/1", json=save_command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == saved.json()
        save_paper_view = officer.get(outage_record_path).json()["record"]["paper_records"]
        entered_save = next(row for row in save_paper_view if row["id"] == save_paper_id)
        assert entered_save["status"] == "entered"
        assert entered_save["original_event_at"] == "2026-11-15T01:30:00Z"
        assert entered_save["entered_at"] != entered_save["original_event_at"]
        assert entered_save["reentry"]["request_id"] == save_command["request_id"]
        assert entered_save["reentry"]["actor_id"] == officer_account["id"]
        assert entered_save["reentry"]["record"] == saved.json()

        duplicate_effect = officer.put(
            path + "/1",
            json={
                **save_command,
                "request_id": str(uuid4()),
                "expected_revision": saved.json()["revision"],
            },
        )
        assert duplicate_effect.status_code == 409, duplicate_effect.text
        assert len(officer.get(path + "/1/history").json()["items"]) == 1

        duplicate_reference = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": save_reference,
                "workflow": "turnout",
                "action": "save",
                "original_event_at": event_at,
                "target": {"period_index": 1},
                "notes": "Duplicate physical paper reference.",
            },
        )
        assert duplicate_reference.status_code == 409, duplicate_reference.text

        submit_reference = "N1-TURNOUT-SUBMIT-" + uuid4().hex[:10]
        submit_paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": submit_reference,
                "workflow": "turnout",
                "action": "submit",
                "original_event_at": event_at,
                "target": {"period_index": 1},
                "notes": "Signed paper turnout submission for period one.",
            },
        )
        assert submit_paper.status_code == 201, submit_paper.text
        submit_paper_id = submit_paper.json()["id"]
        submit_command = {
            "request_id": str(uuid4()),
            "expected_revision": saved.json()["revision"],
            "expected_schedule_revision": 1,
            "paper_record_id": submit_paper_id,
        }
        submitted = officer.post(path + "/1/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        submit_replay = officer.post(path + "/1/submit", json=submit_command)
        assert submit_replay.status_code == 200, submit_replay.text
        assert submit_replay.json() == submitted.json()
        submit_paper_view = officer.get(outage_record_path).json()["record"]["paper_records"]
        entered_submit = next(row for row in submit_paper_view if row["id"] == submit_paper_id)
        assert entered_submit["status"] == "entered"
        assert entered_submit["reentry"]["request_id"] == submit_command["request_id"]
        assert entered_submit["reentry"]["record"] == submitted.json()
        assert len(officer.get(path + "/1/history").json()["items"]) == 1

        approval_with_paper_flag = supervisor.post(
            path + "/1/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted.json()["revision"],
                "expected_schedule_revision": 1,
                "password": READY_PASSWORD,
                "paper_record_id": submit_paper_id,
            },
        )
        assert approval_with_paper_flag.status_code == 422, approval_with_paper_flag.text
