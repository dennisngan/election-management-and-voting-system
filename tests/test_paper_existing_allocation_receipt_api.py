"""Link an existing allocation-create receipt to a later paper record."""

import re
from datetime import timedelta
from uuid import uuid4

from tests.test_counting_rounds_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_rounds_api import database_url as database_url
from tests.test_outage_allocation_reentry_api import (
    _allocation_command as allocation_command,
)
from tests.test_outage_allocation_reentry_api import (
    _register_allocation_paper as register_allocation_paper,
)
from tests.test_outage_allocation_reentry_api import (
    _register_outage as register_outage,
)
from tests.test_outage_allocation_reentry_api import (
    allocation_paper_setup as allocation_paper_setup,
)


def test_existing_allocation_create_receipt_can_be_linked_without_a_second_allocation(
    allocation_paper_setup: dict,
    database_url: str,
) -> None:
    setup = allocation_paper_setup
    polling = setup["polling"]
    allocation_path = setup["base"] + "/allocations"
    event_at = "2026-11-15T08:05:00+08:00"
    create_command = allocation_command(setup, event_at=event_at)
    original_request_id = create_command["request_id"]
    assert "paper_record_id" not in create_command

    created = polling.post(allocation_path, json=create_command)
    assert created.status_code == 201, created.text
    original_receipt = created.json()
    assert original_receipt["event_at"] == "2026-11-15T00:05:00Z"
    assert original_receipt["entered_at"] == "2026-11-15T16:00:00Z"

    allocations_before_link_response = polling.get(allocation_path)
    assert allocations_before_link_response.status_code == 200, (
        allocations_before_link_response.text
    )
    allocations_before_link = allocations_before_link_response.json()["items"]
    assert [row for row in allocations_before_link if row["series"] == setup["series"]] == [
        original_receipt
    ]
    history_path = allocation_path + f"/{original_receipt['id']}/history"
    history_before_link_response = polling.get(history_path)
    assert history_before_link_response.status_code == 200, history_before_link_response.text
    history_before_link = history_before_link_response.json()
    assert [row["revision"] for row in history_before_link["items"]] == [1]

    outcome_path = (
        f"/api/workspace/stations/{setup['station']['id']}"
        f"/request-outcomes/{original_request_id}"
    )
    outcome_before_link = polling.get(outcome_path, params={"workflow": "allocation"})
    assert outcome_before_link.status_code == 200, outcome_before_link.text
    assert outcome_before_link.json() == {
        "request_id": original_request_id,
        "workflow": "allocation",
        "status": "committed",
        "record": original_receipt,
    }

    setup["clock"].value += timedelta(minutes=30)
    outage_path = register_outage(setup)
    paper = register_allocation_paper(
        setup,
        outage_path,
        action="create",
        target={"counter_id": setup["counter"]["id"]},
        event_at=event_at,
    )
    assert paper["status"] == "pending"
    assert paper["target"] == {"counter_id": setup["counter"]["id"]}
    assert paper["original_event_at"] == original_receipt["event_at"]
    assert paper["entered_at"] == "2026-11-15T16:30:00Z"

    paper_path = outage_path + f"/paper-records/{paper['id']}"
    preview = polling.get(
        paper_path + "/receipt",
        params={"request_id": original_request_id},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["request_id"] == original_request_id
    assert preview_body["workflow"] == "allocation"
    assert preview_body["status"] == "committed"
    assert preview_body["record"] == original_receipt
    receipt_digest = preview_body["receipt_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", receipt_digest)

    setup["clock"].value += timedelta(minutes=30)
    link_command = {
        "request_id": str(uuid4()),
        "expected_outage_revision": 1,
        "expected_paper_revision": 1,
        "original_request_id": original_request_id,
        "expected_receipt_digest": receipt_digest,
        "reason": "Link the previously committed allocation create receipt to its paper record.",
    }
    assert link_command["request_id"] != original_request_id
    linked = polling.post(paper_path + "/link-receipt", json=link_command)
    assert linked.status_code == 200, linked.text
    linked_paper = linked.json()
    assert linked_paper["status"] == "entered"
    assert linked_paper["original_event_at"] == "2026-11-15T00:05:00Z"
    assert linked_paper["entered_at"] == paper["entered_at"]
    assert linked_paper["revision"] == paper["revision"]
    assert linked_paper["history"] == paper["history"]
    reentry = linked_paper["reentry"]
    assert reentry["workflow"] == "allocation"
    assert reentry["request_id"] == original_request_id
    assert reentry["record"] == original_receipt
    assert reentry["entered_at"] == "2026-11-15T17:00:00Z"
    assert reentry["link"]["request_id"] == link_command["request_id"]
    assert reentry["link"]["reason"] == link_command["reason"]
    times = [
        original_receipt["event_at"],
        original_receipt["entered_at"],
        paper["entered_at"],
        reentry["entered_at"],
    ]
    assert len(set(times)) == 4
    assert times == sorted(times)

    outage_after_link = polling.get(outage_path)
    assert outage_after_link.status_code == 200, outage_after_link.text
    assert outage_after_link.json()["record"]["paper_records"] == [linked_paper]

    replay = polling.post(paper_path + "/link-receipt", json=link_command)
    assert replay.status_code == 200, replay.text
    assert replay.json() == linked_paper

    outcome_after_link = polling.get(outcome_path, params={"workflow": "allocation"})
    assert outcome_after_link.status_code == 200, outcome_after_link.text
    assert outcome_after_link.json() == outcome_before_link.json()
    allocations_after_link = polling.get(allocation_path)
    assert allocations_after_link.status_code == 200, allocations_after_link.text
    assert allocations_after_link.json()["items"] == allocations_before_link
    history_after_link = polling.get(history_path)
    assert history_after_link.status_code == 200, history_after_link.text
    assert history_after_link.json() == history_before_link


def test_existing_allocation_amend_receipt_can_be_linked_without_changing_ranges(
    allocation_paper_setup: dict,
    database_url: str,
) -> None:
    setup = allocation_paper_setup
    polling = setup["polling"]
    allocation_path = setup["base"] + "/allocations"

    create_event_at = "2026-11-15T08:05:00+08:00"
    create_command = allocation_command(setup, event_at=create_event_at)
    assert "paper_record_id" not in create_command
    created = polling.post(allocation_path, json=create_command)
    assert created.status_code == 201, created.text
    created_receipt = created.json()

    amend_event_at = "2026-11-15T08:06:00+08:00"
    amend_command = allocation_command(
        setup,
        event_at=amend_event_at,
        request_id=str(uuid4()),
        revision=1,
        serial_from="000002",
        serial_to="000004",
        reason="Corrected from the signed allocation amendment return.",
    )
    assert "paper_record_id" not in amend_command
    assert amend_command["request_id"] != create_command["request_id"]
    amended = polling.put(
        allocation_path + f"/{created_receipt['id']}",
        json=amend_command,
    )
    assert amended.status_code == 200, amended.text
    amended_receipt = amended.json()
    assert amended_receipt["revision"] == 2
    assert amended_receipt["event_at"] == "2026-11-15T00:06:00Z"
    assert amended_receipt["entered_at"] == "2026-11-15T16:00:00Z"

    create_outcome_path = (
        f"/api/workspace/stations/{setup['station']['id']}"
        f"/request-outcomes/{create_command['request_id']}"
    )
    amend_outcome_path = (
        f"/api/workspace/stations/{setup['station']['id']}"
        f"/request-outcomes/{amend_command['request_id']}"
    )
    create_outcome_before = polling.get(
        create_outcome_path,
        params={"workflow": "allocation"},
    )
    assert create_outcome_before.status_code == 200, create_outcome_before.text
    assert create_outcome_before.json()["record"] == created_receipt
    amend_outcome_before = polling.get(
        amend_outcome_path,
        params={"workflow": "allocation"},
    )
    assert amend_outcome_before.status_code == 200, amend_outcome_before.text
    assert amend_outcome_before.json() == {
        "request_id": amend_command["request_id"],
        "workflow": "allocation",
        "status": "committed",
        "record": amended_receipt,
    }

    current_allocation_path = allocation_path + f"/{created_receipt['id']}"
    current_before_link = polling.get(current_allocation_path)
    assert current_before_link.status_code == 200, current_before_link.text
    assert current_before_link.json() == amended_receipt
    history_path = current_allocation_path + "/history"
    history_before_link = polling.get(history_path)
    assert history_before_link.status_code == 200, history_before_link.text
    assert [row["revision"] for row in history_before_link.json()["items"]] == [2, 1]
    allocations_before_link = polling.get(allocation_path)
    assert allocations_before_link.status_code == 200, allocations_before_link.text
    assert [
        row
        for row in allocations_before_link.json()["items"]
        if row["series"] == setup["series"]
    ] == [amended_receipt]

    setup["clock"].value += timedelta(minutes=30)
    outage_path = register_outage(setup)
    paper = register_allocation_paper(
        setup,
        outage_path,
        action="amend",
        target={
            "counter_id": setup["counter"]["id"],
            "allocation_id": created_receipt["id"],
        },
        event_at=amend_event_at,
    )
    assert paper["status"] == "pending"
    assert paper["target"] == {
        "counter_id": setup["counter"]["id"],
        "allocation_id": created_receipt["id"],
    }
    assert paper["original_event_at"] == amended_receipt["event_at"]
    assert paper["entered_at"] == "2026-11-15T16:30:00Z"

    paper_path = outage_path + f"/paper-records/{paper['id']}"
    preview = polling.get(
        paper_path + "/receipt",
        params={"request_id": amend_command["request_id"]},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["request_id"] == amend_command["request_id"]
    assert preview_body["workflow"] == "allocation"
    assert preview_body["status"] == "committed"
    assert preview_body["record"] == amended_receipt
    receipt_digest = preview_body["receipt_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", receipt_digest)

    setup["clock"].value += timedelta(minutes=30)
    link_command = {
        "request_id": str(uuid4()),
        "expected_outage_revision": 1,
        "expected_paper_revision": 1,
        "original_request_id": amend_command["request_id"],
        "expected_receipt_digest": receipt_digest,
        "reason": "Link the existing allocation amendment receipt to its paper record.",
    }
    assert link_command["request_id"] != amend_command["request_id"]
    linked = polling.post(paper_path + "/link-receipt", json=link_command)
    assert linked.status_code == 200, linked.text
    linked_paper = linked.json()
    assert linked_paper["status"] == "entered"
    assert linked_paper["original_event_at"] == amended_receipt["event_at"]
    assert linked_paper["entered_at"] == paper["entered_at"]
    assert linked_paper["revision"] == paper["revision"]
    assert linked_paper["history"] == paper["history"]
    reentry = linked_paper["reentry"]
    assert reentry["workflow"] == "allocation"
    assert reentry["request_id"] == amend_command["request_id"]
    assert reentry["record"] == amended_receipt
    assert reentry["entered_at"] == "2026-11-15T17:00:00Z"
    assert reentry["link"]["request_id"] == link_command["request_id"]
    assert reentry["link"]["reason"] == link_command["reason"]
    times = [
        amended_receipt["event_at"],
        amended_receipt["entered_at"],
        paper["entered_at"],
        reentry["entered_at"],
    ]
    assert len(set(times)) == 4
    assert times == sorted(times)

    outage_after_link = polling.get(outage_path)
    assert outage_after_link.status_code == 200, outage_after_link.text
    assert outage_after_link.json()["record"]["paper_records"] == [linked_paper]
    replay = polling.post(paper_path + "/link-receipt", json=link_command)
    assert replay.status_code == 200, replay.text
    assert replay.json() == linked_paper

    create_outcome_after = polling.get(
        create_outcome_path,
        params={"workflow": "allocation"},
    )
    assert create_outcome_after.status_code == 200, create_outcome_after.text
    assert create_outcome_after.json() == create_outcome_before.json()
    amend_outcome_after = polling.get(
        amend_outcome_path,
        params={"workflow": "allocation"},
    )
    assert amend_outcome_after.status_code == 200, amend_outcome_after.text
    assert amend_outcome_after.json() == amend_outcome_before.json()
    current_after_link = polling.get(current_allocation_path)
    assert current_after_link.status_code == 200, current_after_link.text
    assert current_after_link.json() == current_before_link.json()
    history_after_link = polling.get(history_path)
    assert history_after_link.status_code == 200, history_after_link.text
    assert history_after_link.json() == history_before_link.json()
    allocations_after_link = polling.get(allocation_path)
    assert allocations_after_link.status_code == 200, allocations_after_link.text
    assert allocations_after_link.json() == allocations_before_link.json()
