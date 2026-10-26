"""Link an already committed count receipt to a later paper record by public APIs."""

import re
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_rounds_api import database_url as database_url


def test_existing_count_receipt_can_be_linked_to_paper_without_another_count_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter = setup["counter"]
        rounds_path = setup["rounds_path"]
        options = counter.get(rounds_path).json()

        f1_command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=5,
        )
        f1_command["candidate_votes"][0]["quantity"] = 5
        f1_saved = counter.post(rounds_path, json=f1_command)
        assert f1_saved.status_code == 201, f1_saved.text

        round_path = rounds_path + f"/{f1_saved.json()['id']}"
        f2_saved = counter.put(
            round_path + "/f2",
            json=complete_f2_command(options, determination_started_at=None),
        )
        assert f2_saved.status_code == 200, f2_saved.text
        submit_command = {
            "request_id": str(uuid4()),
            "expected_revision": f2_saved.json()["revision"],
            "scope_revision": setup["scope"]["revision"],
        }
        assert "paper_record_id" not in submit_command
        submitted = counter.post(round_path + "/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        submitted_record = submitted.json()
        assert submitted_record["status"] == "submitted"
        assert submitted_record["entered_at"] == "2026-11-15T16:00:00Z"

        station_id = setup["stations"]["N1"]["id"]
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        setup["clock"].value += timedelta(minutes=30)
        outage = counter.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "N1 pre-existing count receipt " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T15:10:00Z",
                "ended_at": "2026-11-15T15:20:00Z",
                "notes": "Count submission was committed before the paper record was registered.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_record_path = outage_path + f"/{outage_id}"

        original_event_at = "2026-11-15T15:15:12.123456Z"
        paper_registered = counter.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "N1-COUNT-" + uuid4().hex[:10],
                "workflow": "count",
                "action": "submit",
                "original_event_at": original_event_at,
                "target": {
                    "scope_id": setup["scope"]["id"],
                    "round_id": submitted_record["id"],
                },
                "notes": "Register the paper reference after the count was already committed.",
            },
        )
        assert paper_registered.status_code == 201, paper_registered.text
        pending_paper = paper_registered.json()
        assert pending_paper["status"] == "pending"

        request_id = submit_command["request_id"]
        original_outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
        )
        original_outcome = counter.get(
            original_outcome_path,
            params={"workflow": "count"},
        )
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json() == {
            "request_id": request_id,
            "workflow": "count",
            "status": "committed",
            "record": submitted_record,
        }
        count_before_link = counter.get(round_path)
        assert count_before_link.status_code == 200, count_before_link.text

        paper_path = outage_record_path + f"/paper-records/{pending_paper['id']}"
        preview = counter.get(
            paper_path + "/receipt",
            params={"request_id": request_id},
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["request_id"] == request_id
        assert preview_body["workflow"] == "count"
        assert preview_body["status"] == "committed"
        assert preview_body["record"] == submitted_record
        receipt_digest = preview_body["receipt_digest"]
        assert re.fullmatch(r"[0-9a-f]{64}", receipt_digest)

        setup["clock"].value += timedelta(minutes=30)
        link_command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "expected_paper_revision": 1,
            "original_request_id": request_id,
            "expected_receipt_digest": receipt_digest,
            "reason": "Link the previously committed count receipt to its paper record.",
        }
        linked = counter.post(paper_path + "/link-receipt", json=link_command)
        assert linked.status_code == 200, linked.text
        linked_paper = linked.json()
        assert linked_paper["status"] == "entered"
        assert linked_paper["original_event_at"] == original_event_at
        assert original_event_at < submitted_record["entered_at"]
        assert linked_paper["entered_at"] == pending_paper["entered_at"]
        assert linked_paper["reentry"] == {
            "workflow": "count",
            "request_id": link_command["request_id"],
            "actor_id": submitted_record["actor_id"],
            "entered_at": "2026-11-15T17:00:00Z",
            "paper_revision_id": linked_paper["revision_id"],
            "record": submitted_record,
        }
        assert linked_paper["reentry"]["entered_at"] > submitted_record["entered_at"]
        assert linked_paper["revision"] == pending_paper["revision"]
        assert linked_paper["history"] == pending_paper["history"]

        outage_after_link = counter.get(outage_record_path)
        assert outage_after_link.status_code == 200, outage_after_link.text
        canonical_paper = outage_after_link.json()["record"]["paper_records"][0]
        assert canonical_paper == linked_paper

        outcome_after_link = counter.get(
            original_outcome_path,
            params={"workflow": "count"},
        )
        assert outcome_after_link.status_code == 200, outcome_after_link.text
        assert outcome_after_link.json() == original_outcome.json()
        count_after_link = counter.get(round_path)
        assert count_after_link.status_code == 200, count_after_link.text
        assert count_after_link.json() == count_before_link.json()

        replay = counter.post(paper_path + "/link-receipt", json=link_command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == linked_paper
