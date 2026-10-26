"""Link a pre-existing turnout-save receipt to a later paper record."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.test_turnout_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_turnout_api import database_url as database_url
from tests.turnout_support import (
    TurnoutClock,
    approve_period,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


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


def test_existing_turnout_submit_receipt_can_be_linked_without_overwriting_its_observation(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()

    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        saved_event_at = "2026-11-15T09:30:00+08:00"
        save_command = turnout_draft(
            supplied_hourly=7,
            supplied_cumulative=7,
            event_at=saved_event_at,
            source_context="Signed external turnout worksheet for period one.",
        )
        save_request_id = save_command["request_id"]
        assert "paper_record_id" not in save_command
        saved = officer.put(path + "/1", json=save_command)
        assert saved.status_code == 200, saved.text
        saved_record = saved.json()
        assert saved_record["status"] == "draft"
        assert saved_record["event_at"] == "2026-11-15T01:30:00Z"
        assert saved_record["entered_at"] == "2026-11-15T04:00:00Z"

        save_outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{save_request_id}"
        )
        save_outcome = officer.get(save_outcome_path, params={"workflow": "turnout"})
        assert save_outcome.status_code == 200, save_outcome.text
        assert save_outcome.json() == {
            "request_id": save_request_id,
            "workflow": "turnout",
            "status": "committed",
            "record": saved_record,
        }

        clock.value += timedelta(minutes=5)
        submit_command = turnout_command(saved_record["revision"])
        submit_request_id = submit_command["request_id"]
        assert "paper_record_id" not in submit_command
        submitted = officer.post(path + "/1/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        submitted_record = submitted.json()
        assert submitted_record["status"] == "submitted"
        assert submitted_record["event_at"] == saved_record["event_at"]
        assert submitted_record["entered_at"] == saved_record["entered_at"]
        assert submitted_record["submitted_at"] == "2026-11-15T04:05:00Z"

        submit_outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{submit_request_id}"
        )
        submit_outcome = officer.get(submit_outcome_path, params={"workflow": "turnout"})
        assert submit_outcome.status_code == 200, submit_outcome.text
        assert submit_outcome.json() == {
            "request_id": submit_request_id,
            "workflow": "turnout",
            "status": "committed",
            "record": submitted_record,
        }
        record_path = path + "/1"
        record_before_link = officer.get(record_path)
        assert record_before_link.status_code == 200, record_before_link.text
        history_path = record_path + "/history"
        history_before_link = officer.get(history_path)
        assert history_before_link.status_code == 200, history_before_link.text
        history_snapshot = history_before_link.json()
        assert history_snapshot["items"] == [submitted_record]
        snapshot_before_link = officer.get(path)
        assert snapshot_before_link.status_code == 200, snapshot_before_link.text
        turnout_snapshot = snapshot_before_link.json()

        clock.value += timedelta(minutes=30)
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 turnout submit receipt " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T09:30:00+08:00",
                "ended_at": "2026-11-15T10:00:00+08:00",
                "notes": "The paper completion time differs from the original saved observation.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_record_path = outage_path + f"/{outage.json()['id']}"
        paper_event_at = "2026-11-15T09:45:00+08:00"
        paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-TURNOUT-SUBMIT-" + uuid4().hex[:10],
                "workflow": "turnout",
                "action": "submit",
                "original_event_at": paper_event_at,
                "target": {"period_index": 1},
                "notes": (
                    "Register the paper completion time after the turnout receipt committed."
                ),
            },
        )
        assert paper.status_code == 201, paper.text
        paper_record = paper.json()
        assert paper_record["status"] == "pending"
        assert paper_record["original_event_at"] == "2026-11-15T01:45:00Z"
        assert paper_record["original_event_at"] != submitted_record["event_at"]
        assert submitted_record["event_at"] == "2026-11-15T01:30:00Z"
        assert submitted_record["submitted_at"] == "2026-11-15T04:05:00Z"
        assert (
            submitted_record["event_at"]
            < paper_record["original_event_at"]
            < submitted_record["submitted_at"]
        )
        assert paper_record["entered_at"] == "2026-11-15T04:35:00Z"

        paper_path = outage_record_path + f"/paper-records/{paper_record['id']}"
        preview = officer.get(
            paper_path + "/receipt",
            params={"request_id": submit_request_id},
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["request_id"] == submit_request_id
        assert preview_body["workflow"] == "turnout"
        assert preview_body["status"] == "committed"
        assert preview_body["record"] == submitted_record

        clock.value += timedelta(minutes=15)
        link_command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "expected_paper_revision": 1,
            "original_request_id": submit_request_id,
            "expected_receipt_digest": preview_body["receipt_digest"],
            "reason": (
                "Link the existing turnout submit receipt without replacing the saved observation."
            ),
        }
        assert link_command["request_id"] != submit_request_id
        linked = officer.post(paper_path + "/link-receipt", json=link_command)
        assert linked.status_code == 200, linked.text
        linked_paper = linked.json()
        assert linked_paper["status"] == "entered"
        assert linked_paper["original_event_at"] == paper_record["original_event_at"]
        assert linked_paper["original_event_at"] != submitted_record["event_at"]
        assert linked_paper["entered_at"] == paper_record["entered_at"]
        assert linked_paper["revision"] == paper_record["revision"]
        assert linked_paper["history"] == paper_record["history"]
        reentry = linked_paper["reentry"]
        assert reentry["request_id"] == submit_request_id
        assert reentry["record"] == submitted_record
        assert reentry["entered_at"] == "2026-11-15T04:50:00Z"
        assert reentry["link"]["request_id"] == link_command["request_id"]
        assert reentry["link"]["reason"] == link_command["reason"]
        assert reentry["link"]["receipt_digest"] == preview_body["receipt_digest"]
        assert reentry["link"]["linked_at"] == reentry["entered_at"]
        assert reentry["link"]["linked_at"] > paper_record["entered_at"]

        outage_after_link = officer.get(outage_record_path)
        assert outage_after_link.status_code == 200, outage_after_link.text
        assert outage_after_link.json()["record"]["paper_records"] == [linked_paper]
        replay = officer.post(paper_path + "/link-receipt", json=link_command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == linked_paper

        save_outcome_after = officer.get(
            save_outcome_path,
            params={"workflow": "turnout"},
        )
        assert save_outcome_after.status_code == 200, save_outcome_after.text
        assert save_outcome_after.json() == save_outcome.json()
        submit_outcome_after = officer.get(
            submit_outcome_path,
            params={"workflow": "turnout"},
        )
        assert submit_outcome_after.status_code == 200, submit_outcome_after.text
        assert submit_outcome_after.json() == submit_outcome.json()
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


def test_turnout_submitted_after_paper_registration_cannot_be_linked_as_an_existing_receipt(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()

    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        saved = officer.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=7,
                supplied_cumulative=7,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="Signed turnout worksheet recorded before paper registration.",
            ),
        )
        assert saved.status_code == 200, saved.text
        saved_record = saved.json()
        assert saved_record["entered_at"] == "2026-11-15T04:00:00Z"

        clock.value += timedelta(minutes=30)
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 later turnout submit " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T09:00:00+08:00",
                "ended_at": "2026-11-15T10:00:00+08:00",
                "notes": "Register the paper before the pending report is submitted.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_record_path = outage_path + f"/{outage.json()['id']}"
        paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-LATER-SUBMIT-" + uuid4().hex[:10],
                "workflow": "turnout",
                "action": "submit",
                "original_event_at": "2026-11-15T09:45:00+08:00",
                "target": {"period_index": 1},
                "notes": "A later submit must use the normal paper reentry workflow.",
            },
        )
        assert paper.status_code == 201, paper.text
        paper_record = paper.json()
        assert paper_record["entered_at"] == "2026-11-15T04:30:00Z"
        assert paper_record["status"] == "pending"

        clock.value += timedelta(minutes=5)
        submit_command = turnout_command(saved_record["revision"])
        submitted = officer.post(path + "/1/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        submitted_record = submitted.json()
        assert submitted_record["entered_at"] == saved_record["entered_at"]
        assert submitted_record["submitted_at"] == "2026-11-15T04:35:00Z"
        assert (
            submitted_record["entered_at"]
            < paper_record["entered_at"]
            < submitted_record["submitted_at"]
        )

        paper_path = outage_record_path + f"/paper-records/{paper_record['id']}"
        preview = officer.get(
            paper_path + "/receipt",
            params={"request_id": submit_command["request_id"]},
        )
        assert preview.status_code == 409, preview.text
        assert preview.json()["detail"]["code"] == "paper_receipt_mismatch"
        refreshed = officer.get(outage_record_path)
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["record"]["paper_records"] == [paper_record]
        record_after_preview = officer.get(path + "/1")
        assert record_after_preview.status_code == 200, record_after_preview.text
        assert record_after_preview.json() == submitted_record


def _register_later_turnout_paper(
    officer: TestClient,
    station_id: int,
    clock: TurnoutClock,
    action: str,
    original_event_at: str,
) -> tuple[str, dict]:
    clock.value += timedelta(minutes=30)
    outage_path = f"/api/workspace/stations/{station_id}/outages"
    outage = officer.post(
        outage_path,
        json={
            "request_id": str(uuid4()),
            "reference": "T25 preserved turnout receipt " + uuid4().hex[:8],
            "kind": "network",
            "started_at": "2026-11-15T09:00:00+08:00",
            "ended_at": "2026-11-15T10:00:00+08:00",
            "notes": "Register the original paper after the operational command committed.",
        },
    )
    assert outage.status_code == 201, outage.text
    outage_record_path = outage_path + f"/{outage.json()['id']}"
    paper = officer.post(
        outage_record_path + "/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": "T25-PRESERVED-" + uuid4().hex[:10],
            "workflow": "turnout",
            "action": action,
            "original_event_at": original_event_at,
            "target": {"period_index": 1},
            "notes": "Keep the original receipt beside later paper linkage metadata.",
        },
    )
    assert paper.status_code == 201, paper.text
    paper_record = paper.json()
    assert paper_record["status"] == "pending"
    return outage_record_path + f"/paper-records/{paper_record['id']}", paper_record


def test_existing_turnout_submit_receipt_remains_linkable_after_supervisor_approval(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        saved = officer.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=7,
                supplied_cumulative=7,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="Signed turnout worksheet approved before paper registration.",
            ),
        )
        assert saved.status_code == 200, saved.text
        submit_command = turnout_command(saved.json()["revision"])
        submitted = officer.post(path + "/1/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        original_record = submitted.json()
        assert original_record["status"] == "submitted"
        clock.value += timedelta(minutes=5)
        approved_record = approve_period(supervisor, path, 1, original_record["revision"])
        assert approved_record["status"] == "approved"
        assert approved_record["id"] == original_record["id"]
        assert approved_record["revision"] == original_record["revision"]
        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/"
            + submit_command["request_id"]
        )
        original_outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json()["record"] == original_record
        history_before = officer.get(path + "/1/history")
        assert history_before.status_code == 200, history_before.text
        paper_path, paper_record = _register_later_turnout_paper(
            officer, station_id, clock, "submit", "2026-11-15T09:45:00+08:00"
        )
        preview = officer.get(
            paper_path + "/receipt", params={"request_id": submit_command["request_id"]}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["record"] == original_record
        linked = officer.post(
            paper_path + "/link-receipt",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "expected_paper_revision": paper_record["revision"],
                "original_request_id": submit_command["request_id"],
                "expected_receipt_digest": preview.json()["receipt_digest"],
                "reason": "Link the preserved submission while retaining its later approval.",
            },
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["status"] == "entered"
        assert linked.json()["reentry"]["record"] == original_record
        assert linked.json()["reentry"]["request_id"] == submit_command["request_id"]
        after_outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert after_outcome.status_code == 200, after_outcome.text
        assert after_outcome.json() == original_outcome.json()
        current = officer.get(path + "/1")
        assert current.status_code == 200, current.text
        assert current.json() == approved_record
        history_after = officer.get(path + "/1/history")
        assert history_after.status_code == 200, history_after.text
        assert history_after.json() == history_before.json()


def test_turnout_submit_receipt_belongs_to_the_submitter_rather_than_the_draft_author(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (author, author_account),
        turnout_staff(admin, database_url, clock, [station_id]) as (submitter, submitter_account),
    ):
        saved = author.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=7,
                supplied_cumulative=7,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="One assigned officer prepares the report for another to submit.",
            ),
        )
        assert saved.status_code == 200, saved.text
        clock.value += timedelta(minutes=5)
        submit_command = turnout_command(saved.json()["revision"])
        submitted = submitter.post(path + "/1/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        original_record = submitted.json()
        assert original_record["status"] == "submitted"
        assert original_record["actor_id"] == author_account["id"]
        assert original_record["submitted_by"] == submitter_account["id"]
        assert original_record["actor_id"] != original_record["submitted_by"]
        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/"
            + submit_command["request_id"]
        )
        original_outcome = submitter.get(outcome_path, params={"workflow": "turnout"})
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json()["record"] == original_record
        author_outcome = author.get(outcome_path, params={"workflow": "turnout"})
        assert author_outcome.status_code == 200, author_outcome.text
        assert author_outcome.json() == {
            "request_id": submit_command["request_id"],
            "workflow": "turnout",
            "status": "not_found",
        }
        paper_path, paper_record = _register_later_turnout_paper(
            submitter, station_id, clock, "submit", "2026-11-15T09:45:00+08:00"
        )
        author_preview = author.get(
            paper_path + "/receipt", params={"request_id": submit_command["request_id"]}
        )
        assert author_preview.status_code == 404, author_preview.text
        assert author_preview.json()["detail"]["code"] == "request_not_found"
        preview = submitter.get(
            paper_path + "/receipt", params={"request_id": submit_command["request_id"]}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["record"] == original_record
        linked = submitter.post(
            paper_path + "/link-receipt",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "expected_paper_revision": paper_record["revision"],
                "original_request_id": submit_command["request_id"],
                "expected_receipt_digest": preview.json()["receipt_digest"],
                "reason": "The submitting officer links their own original submission receipt.",
            },
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["status"] == "entered"
        assert linked.json()["reentry"]["record"] == original_record
        assert linked.json()["reentry"]["link"]["actor_id"] == submitter_account["id"]
        after_outcome = submitter.get(outcome_path, params={"workflow": "turnout"})
        assert after_outcome.status_code == 200, after_outcome.text
        assert after_outcome.json() == original_outcome.json()
        current = submitter.get(path + "/1")
        assert current.status_code == 200, current.text
        assert current.json() == original_record


@pytest.mark.parametrize("current_status", ["submitted", "approved"])
def test_existing_turnout_save_receipt_remains_linkable_after_its_later_workflow_transitions(
    admin: TestClient,
    database_url: str,
    current_status: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        save_command = turnout_draft(
            supplied_hourly=7,
            supplied_cumulative=7,
            event_at="2026-11-15T09:30:00+08:00",
            source_context="Preserve the draft-save receipt when the report progresses.",
        )
        saved = officer.put(path + "/1", json=save_command)
        assert saved.status_code == 200, saved.text
        original_record = saved.json()
        assert original_record["status"] == "draft"
        assert original_record["submitted_at"] is None
        assert original_record["approved_at"] is None
        clock.value += timedelta(minutes=5)
        submitted = officer.post(
            path + "/1/submit", json=turnout_command(original_record["revision"])
        )
        assert submitted.status_code == 200, submitted.text
        current_record = submitted.json()
        if current_status == "approved":
            clock.value += timedelta(minutes=5)
            current_record = approve_period(supervisor, path, 1, original_record["revision"])
        assert current_record["status"] == current_status
        assert current_record["id"] == original_record["id"]
        assert current_record["revision"] == original_record["revision"]
        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/" + save_command["request_id"]
        )
        original_outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json()["record"] == original_record
        history_before = officer.get(path + "/1/history")
        assert history_before.status_code == 200, history_before.text
        paper_path, paper_record = _register_later_turnout_paper(
            officer, station_id, clock, "save", "2026-11-15T09:30:00+08:00"
        )
        preview = officer.get(
            paper_path + "/receipt", params={"request_id": save_command["request_id"]}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["record"] == original_record
        linked = officer.post(
            paper_path + "/link-receipt",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "expected_paper_revision": paper_record["revision"],
                "original_request_id": save_command["request_id"],
                "expected_receipt_digest": preview.json()["receipt_digest"],
                "reason": "Link the original save receipt without replacing its later workflow.",
            },
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["status"] == "entered"
        assert linked.json()["reentry"]["record"] == original_record
        after_outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert after_outcome.status_code == 200, after_outcome.text
        assert after_outcome.json() == original_outcome.json()
        current = officer.get(path + "/1")
        assert current.status_code == 200, current.text
        assert current.json() == current_record
        history_after = officer.get(path + "/1/history")
        assert history_after.status_code == 200, history_after.text
        assert history_after.json() == history_before.json()
