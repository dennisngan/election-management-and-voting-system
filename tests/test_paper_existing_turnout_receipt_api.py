"""Link a pre-existing turnout-save receipt to a later paper record."""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_turnout_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_turnout_api import database_url as database_url
from tests.turnout_support import TurnoutClock, turnout_draft, turnout_scope, turnout_staff


def test_existing_turnout_save_receipt_can_be_linked_without_a_second_turnout_write(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()

    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, officer_account):
        original_event_at = "2026-11-15T09:30:00+08:00"
        save_command = turnout_draft(
            supplied_hourly=7,
            supplied_cumulative=7,
            event_at=original_event_at,
            source_context="Signed external turnout worksheet for period one.",
        )
        original_request_id = save_command["request_id"]
        assert "paper_record_id" not in save_command
        saved = officer.put(path + "/1", json=save_command)
        assert saved.status_code == 200, saved.text
        original_record = saved.json()
        assert original_record["status"] == "draft"
        assert original_record["event_at"] == "2026-11-15T01:30:00Z"
        assert original_record["entered_at"] == "2026-11-15T04:00:00Z"

        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{original_request_id}"
        )
        original_outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json() == {
            "request_id": original_request_id,
            "workflow": "turnout",
            "status": "committed",
            "record": original_record,
        }
        record_path = path + "/1"
        record_before_link = officer.get(record_path)
        assert record_before_link.status_code == 200, record_before_link.text
        history_path = record_path + "/history"
        history_before_link = officer.get(history_path)
        assert history_before_link.status_code == 200, history_before_link.text
        history_snapshot = history_before_link.json()
        assert history_snapshot["items"] == [original_record]
        snapshot_before_link = officer.get(path)
        assert snapshot_before_link.status_code == 200, snapshot_before_link.text
        turnout_snapshot = snapshot_before_link.json()

        clock.value += timedelta(minutes=30)
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 turnout save receipt " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T09:00:00+08:00",
                "ended_at": "2026-11-15T10:00:00+08:00",
                "notes": (
                    "The turnout save was committed before its paper reference was registered."
                ),
            },
        )
        assert outage.status_code == 201, outage.text
        outage_record_path = outage_path + f"/{outage.json()['id']}"
        paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-TURNOUT-SAVE-" + uuid4().hex[:10],
                "workflow": "turnout",
                "action": "save",
                "original_event_at": original_event_at,
                "target": {"period_index": 1},
                "notes": "Register the signed turnout worksheet after its receipt was committed.",
            },
        )
        assert paper.status_code == 201, paper.text
        paper_record = paper.json()
        assert paper_record["status"] == "pending"
        assert paper_record["original_event_at"] == original_record["event_at"]
        assert paper_record["entered_at"] == "2026-11-15T04:30:00Z"

        paper_path = outage_record_path + f"/paper-records/{paper_record['id']}"
        preview = officer.get(
            paper_path + "/receipt",
            params={"request_id": original_request_id},
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["request_id"] == original_request_id
        assert preview_body["workflow"] == "turnout"
        assert preview_body["status"] == "committed"
        assert preview_body["record"] == original_record

        clock.value += timedelta(minutes=15)
        link_command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "expected_paper_revision": 1,
            "original_request_id": original_request_id,
            "expected_receipt_digest": preview_body["receipt_digest"],
            "reason": "Link the existing turnout save receipt to its paper worksheet.",
        }
        assert link_command["request_id"] != original_request_id
        linked = officer.post(paper_path + "/link-receipt", json=link_command)
        assert linked.status_code == 200, linked.text
        linked_paper = linked.json()
        assert linked_paper["status"] == "entered"
        assert linked_paper["original_event_at"] == original_record["event_at"]
        assert linked_paper["entered_at"] == paper_record["entered_at"]
        assert linked_paper["revision"] == paper_record["revision"]
        assert linked_paper["history"] == paper_record["history"]
        reentry = linked_paper["reentry"]
        assert reentry["workflow"] == "turnout"
        assert reentry["request_id"] == original_request_id
        assert reentry["record"] == original_record
        assert reentry["entered_at"] == "2026-11-15T04:45:00Z"
        assert reentry["link"]["request_id"] == link_command["request_id"]
        assert reentry["link"]["reason"] == link_command["reason"]
        assert reentry["link"]["actor_id"] == original_record["actor_id"]
        assert reentry["link"]["receipt_digest"] == preview_body["receipt_digest"]
        assert reentry["link"]["linked_at"] == reentry["entered_at"]
        assert reentry["link"]["linked_at"] > paper_record["entered_at"]
        timestamps = [
            original_record["event_at"],
            original_record["entered_at"],
            paper_record["entered_at"],
            reentry["entered_at"],
        ]
        assert len(set(timestamps)) == 4
        assert timestamps == sorted(timestamps)

        outage_after_link = officer.get(outage_record_path)
        assert outage_after_link.status_code == 200, outage_after_link.text
        assert outage_after_link.json()["record"]["paper_records"] == [linked_paper]
        replay = officer.post(paper_path + "/link-receipt", json=link_command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == linked_paper

        outcome_after_link = officer.get(outcome_path, params={"workflow": "turnout"})
        assert outcome_after_link.status_code == 200, outcome_after_link.text
        assert outcome_after_link.json() == original_outcome.json()
        record_after_link = officer.get(record_path)
        assert record_after_link.status_code == 200, record_after_link.text
        assert record_after_link.json() == record_before_link.json()
        history_after_link = officer.get(history_path)
        assert history_after_link.status_code == 200, history_after_link.text
        assert history_after_link.json() == history_snapshot
        snapshot_after_link = officer.get(path)
        assert snapshot_after_link.status_code == 200, snapshot_after_link.text
        after_snapshot = snapshot_after_link.json()
        for key in ("schedule", "period_count", "items", "approved_prefix"):
            assert after_snapshot[key] == turnout_snapshot[key]
