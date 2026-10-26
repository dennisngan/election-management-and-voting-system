"""Allocation paper references link to the original public receipt exactly once."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import BoxClock, box_staff, box_stations
from tests.lifecycle_support import lifecycle_database_url
from tests.stock_support import stock_payload


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def _station_rows(admin: TestClient) -> list[dict]:
    active = admin.get("/api/active-election")
    assert active.status_code == 200, active.text
    election = active.json()["election"]
    if election is None:
        prepared = box_stations(admin)
        return [prepared["N1"]]

    rows: list[dict] = []
    constituencies = admin.get(f"/api/elections/{election['id']}/constituencies")
    assert constituencies.status_code == 200, constituencies.text
    for constituency in constituencies.json()["items"]:
        response = admin.get(
            f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations"
        )
        assert response.status_code == 200, response.text
        rows.extend(response.json()["items"])
    assert rows, "The active election must already have a station for this isolated test."
    return rows


@pytest.fixture
def allocation_paper_setup(
    admin: TestClient, database_url: str
) -> Iterator[dict]:
    stations = _station_rows(admin)
    clock = BoxClock()
    with box_staff(
        admin,
        database_url,
        clock,
        "polling_officer",
        [row["id"] for row in stations],
    ) as (polling, account):
        selected: tuple[dict, dict] | None = None
        for station in stations:
            options = polling.get(f"/api/workspace/stations/{station['id']}/allocations")
            assert options.status_code == 200, options.text
            counters = options.json()["counters"]
            if counters:
                selected = (station, counters[0])
                break
        assert selected is not None, "The active election needs an existing issuance counter."
        station, counter = selected
        series = "T25-" + uuid4().hex[:12]
        received = polling.post(
            f"/api/workspace/stations/{station['id']}/stock",
            json=stock_payload(
                series=series,
                event_at="2026-11-15T08:00:00+08:00",
            ),
        )
        assert received.status_code == 201, received.text
        yield {
            "polling": polling,
            "station": station,
            "counter": counter,
            "account": account,
            "series": series,
            "base": f"/api/workspace/stations/{station['id']}",
            "clock": clock,
        }


def _register_outage(setup: dict) -> str:
    polling = setup["polling"]
    outage_path = setup["base"] + "/outages"
    outage = polling.post(
        outage_path,
        json={
            "request_id": str(uuid4()),
            "reference": "T25 network outage " + uuid4().hex[:10],
            "kind": "network",
            "started_at": "2026-11-15T08:00:00+08:00",
            "ended_at": "2026-11-15T08:30:00+08:00",
            "notes": "Staff retained the signed paper allocation return.",
        },
    )
    assert outage.status_code == 201, outage.text
    return outage_path + f"/{outage.json()['id']}"


def _register_allocation_paper(
    setup: dict,
    outage_path: str,
    *,
    action: str,
    target: dict,
    event_at: str,
) -> dict:
    paper = setup["polling"].post(
        outage_path + "/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": "T25-PAPER-" + uuid4().hex[:12],
            "workflow": "allocation",
            "action": action,
            "original_event_at": event_at,
            "target": target,
            "notes": "Signed paper ballot allocation record.",
        },
    )
    assert paper.status_code == 201, paper.text
    assert paper.json()["status"] == "pending"
    return paper.json()


def _allocation_command(setup: dict, *, event_at: str, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "counter_id": setup["counter"]["id"],
        "series": setup["series"],
        "serial_from": "000001",
        "serial_to": "000002",
        "event_at": event_at,
        **changes,
    }


def test_existing_allocation_receipt_can_be_linked_to_create_paper_without_second_effect(
    allocation_paper_setup: dict,
) -> None:
    setup = allocation_paper_setup
    polling, base = setup["polling"], setup["base"]
    allocation_path = base + "/allocations"
    event_at = "2026-11-15T08:05:00+08:00"
    command = _allocation_command(setup, event_at=event_at)
    created = polling.post(allocation_path, json=command)
    assert created.status_code == 201, created.text
    original_receipt = created.json()

    outage_path = _register_outage(setup)
    paper = _register_allocation_paper(
        setup,
        outage_path,
        action="create",
        target={"counter_id": setup["counter"]["id"]},
        event_at=event_at,
    )
    linked = polling.post(
        allocation_path,
        json={**command, "paper_record_id": paper["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json() == original_receipt

    replay = polling.post(
        allocation_path,
        json={**command, "paper_record_id": paper["id"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == original_receipt
    duplicate_effect = polling.post(
        allocation_path,
        json={**_allocation_command(setup, event_at=event_at), "paper_record_id": paper["id"]},
    )
    assert duplicate_effect.status_code == 409, duplicate_effect.text
    assert duplicate_effect.json()["detail"]["code"] == "paper_record_already_entered"

    current = polling.get(outage_path)
    assert current.status_code == 200, current.text
    entered = current.json()["record"]["paper_records"][0]
    assert entered["status"] == "entered"
    assert entered["reentry"]["request_id"] == command["request_id"]
    assert entered["reentry"]["record"] == original_receipt
    allocations = polling.get(allocation_path).json()["items"]
    assert [row for row in allocations if row["series"] == setup["series"]] == [
        original_receipt
    ]

    correction_time = "2026-11-15T08:06:00+08:00"
    amendment = _register_allocation_paper(
        setup,
        outage_path,
        action="amend",
        target={
            "counter_id": setup["counter"]["id"],
            "allocation_id": original_receipt["id"],
        },
        event_at=correction_time,
    )
    correction = _allocation_command(
        setup,
        event_at=correction_time,
        request_id=str(uuid4()),
        revision=1,
        serial_from="000002",
        serial_to="000004",
        reason="Re-entered from the signed amended allocation return.",
        paper_record_id=amendment["id"],
    )
    corrected = polling.put(
        allocation_path + f"/{original_receipt['id']}",
        json=correction,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["revision"] == 2
    assert polling.put(
        allocation_path + f"/{original_receipt['id']}", json=correction
    ).json() == corrected.json()
    history = polling.get(allocation_path + f"/{original_receipt['id']}/history")
    assert history.status_code == 200, history.text
    assert [row["revision"] for row in history.json()["items"]] == [1, 2]
    record = polling.get(outage_path).json()["record"]
    amended_paper = next(
        row for row in record["paper_records"] if row["id"] == amendment["id"]
    )
    assert amended_paper["status"] == "entered"
    assert amended_paper["reentry"]["record"] == corrected.json()


def test_create_paper_target_time_and_stock_failures_leave_it_pending_then_enter_once(
    allocation_paper_setup: dict,
) -> None:
    setup = allocation_paper_setup
    polling, base = setup["polling"], setup["base"]
    allocation_path = base + "/allocations"
    event_at = "2026-11-15T08:05:00+08:00"
    outage_path = _register_outage(setup)
    paper = _register_allocation_paper(
        setup,
        outage_path,
        action="create",
        target={"counter_id": setup["counter"]["id"]},
        event_at=event_at,
    )

    wrong_target = polling.post(
        allocation_path,
        json={
            **_allocation_command(
                setup,
                event_at=event_at,
                counter_id=setup["counter"]["id"] + 99999,
            ),
            "paper_record_id": paper["id"],
        },
    )
    assert wrong_target.status_code == 409, wrong_target.text
    assert wrong_target.json()["detail"]["code"] == "paper_record_target_conflict"

    wrong_time = polling.post(
        allocation_path,
        json={
            **_allocation_command(
                setup,
                event_at="2026-11-15T08:06:00+08:00",
            ),
            "paper_record_id": paper["id"],
        },
    )
    assert wrong_time.status_code == 409, wrong_time.text
    assert wrong_time.json()["detail"]["code"] == "paper_record_time_conflict"

    outside_received_stock = polling.post(
        allocation_path,
        json={
            **_allocation_command(
                setup,
                event_at=event_at,
                serial_from="900000",
                serial_to="900001",
            ),
            "paper_record_id": paper["id"],
        },
    )
    assert outside_received_stock.status_code == 409, outside_received_stock.text
    assert outside_received_stock.json()["detail"]["code"] == "allocation_outside_stock"

    pending = polling.get(outage_path)
    assert pending.status_code == 200, pending.text
    pending_paper = pending.json()["record"]["paper_records"][0]
    assert pending_paper["status"] == "pending"
    assert pending_paper["reentry"] is None

    command = _allocation_command(
        setup,
        event_at=event_at,
        paper_record_id=paper["id"],
    )
    created = polling.post(allocation_path, json=command)
    assert created.status_code == 201, created.text
    assert created.json()["quantity"] == 2
    replay = polling.post(allocation_path, json=command)
    assert replay.status_code == 200, replay.text
    assert replay.json() == created.json()
    duplicate_paper = polling.post(
        allocation_path,
        json={
            **_allocation_command(setup, event_at=event_at),
            "paper_record_id": paper["id"],
        },
    )
    assert duplicate_paper.status_code == 409, duplicate_paper.text
    assert duplicate_paper.json()["detail"]["code"] == "paper_record_already_entered"

    allocations = polling.get(allocation_path).json()["items"]
    assert [row for row in allocations if row["series"] == setup["series"]] == [
        created.json()
    ]
    record = polling.get(outage_path).json()["record"]["paper_records"][0]
    assert record["status"] == "entered"
    assert record["reentry"]["record"] == created.json()


def test_existing_allocation_create_paper_link_requires_the_original_receipt_owner(
    allocation_paper_setup: dict,
    admin: TestClient,
    database_url: str,
) -> None:
    setup = allocation_paper_setup
    polling, allocation_path = setup["polling"], setup["base"] + "/allocations"
    event_at = "2026-11-15T08:05:00+08:00"
    command = _allocation_command(setup, event_at=event_at)
    created = polling.post(allocation_path, json=command)
    assert created.status_code == 201, created.text
    original_receipt = created.json()
    outage_path = _register_outage(setup)
    paper = _register_allocation_paper(
        setup, outage_path, action="create",
        target={"counter_id": setup["counter"]["id"]}, event_at=event_at,
    )

    with box_staff(
        admin, database_url, setup["clock"], "polling_officer", [setup["station"]["id"]],
    ) as (other, _):
        ordinary_replay = other.post(allocation_path, json=command)
        assert ordinary_replay.status_code == 200, ordinary_replay.text
        assert ordinary_replay.json() == original_receipt
        wrong_owner = other.post(
            allocation_path, json={**command, "paper_record_id": paper["id"]},
        )
        assert wrong_owner.status_code == 409, wrong_owner.text
        assert wrong_owner.json() == {"detail": {"code": "request_conflict"}}

    after_rejection = polling.get(outage_path)
    assert after_rejection.status_code == 200, after_rejection.text
    pending = after_rejection.json()["record"]["paper_records"][0]
    assert pending["status"] == "pending"
    assert pending["reentry"] is None
    linked = polling.post(
        allocation_path, json={**command, "paper_record_id": paper["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json() == original_receipt
    current = polling.get(outage_path).json()["record"]["paper_records"][0]
    assert current["status"] == "entered"
    assert current["reentry"]["actor_id"] == setup["account"]["id"]
    assert current["reentry"]["request_id"] == command["request_id"]
    assert current["reentry"]["record"] == original_receipt
    allocations = polling.get(allocation_path).json()["items"]
    assert [row for row in allocations if row["series"] == setup["series"]] == [original_receipt]
