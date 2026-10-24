"""Ticket 17 source and received-box arrangements through public APIs only."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import (
    READY_PASSWORD,
    BoxClock,
    box_staff,
    box_stations,
    event_command,
    prepared_box,
)
from tests.stock_support import stock_payload


def _prepare_source_accounting(
    polling: TestClient,
    counter: TestClient,
    supervisor: TestClient,
    station: dict,
) -> dict:
    """Receive, allocate, snapshot, and approve one current P(18) for a source station."""
    station_id = station["id"]
    first_serial = 1 if station["code"] == "N1" else 11
    last_serial = first_serial + 9
    ordinary_range = {
        "pool": "ordinary",
        "serial_from": f"{first_serial:06d}",
        "serial_to": f"{last_serial:06d}",
    }
    ordinary_remaining = {
        "series": "普通系列 A",
        "serial_from": f"{first_serial + 5:06d}",
        "serial_to": f"{last_serial:06d}",
    }
    base = f"/api/workspace/stations/{station_id}"
    received = polling.post(
        base + "/stock",
        json=stock_payload(
            event_at="2026-11-15T08:00:00+08:00",
            ordinary_quantity=10,
            replacement_quantity=0,
            tendered_quantity=0,
            ranges=[ordinary_range],
        ),
    )
    assert received.status_code == 201, received.text

    available = polling.get(base + "/allocations")
    assert available.status_code == 200, available.text
    counter_id = available.json()["counters"][0]["id"]
    allocation = polling.post(
        base + "/allocations",
        json={
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": ordinary_range["serial_from"],
            "serial_to": ordinary_range["serial_to"],
            "event_at": "2026-11-15T09:00:00+08:00",
        },
    )
    assert allocation.status_code == 201, allocation.text
    stock_snapshot = polling.post(
        base + "/stock-snapshots",
        json={
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17+08:00",
            "counters": [
                {
                    "counter_id": counter_id,
                    "ranges": [ordinary_remaining],
                }
            ],
        },
    )
    assert stock_snapshot.status_code == 201, stock_snapshot.text
    assert stock_snapshot.json()["ordinary_issued_quantity"] == 5
    assert stock_snapshot.json()["ordinary_remaining_quantity"] == 5

    special_path = base + "/special-papers"
    special_command = {
        "request_id": str(uuid4()),
        "event_at": "2026-11-15T09:45:17+08:00",
        "stock_snapshot_id": stock_snapshot.json()["id"],
        "stock_snapshot_revision": 1,
        "series": [
            {
                "series": "普通系列 A",
                "replacement_issued_quantity": 0,
                "spoilt_original_quantity": 0,
                "tendered_issued_quantity": 0,
                "retrieved_refused_quantity": 0,
                "retrieved_found_quantity": 0,
                "retrieved_held_quantity": 0,
            }
        ],
    }
    special = polling.post(special_path, json=special_command)
    assert special.status_code == 201, special.text

    accounting_path = base + "/accounting"
    selected = counter.put(
        accounting_path,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "special_paper_id": special.json()["id"],
            "special_paper_revision": special.json()["revision"],
        },
    )
    assert selected.status_code == 200, selected.text
    submitted = counter.post(
        accounting_path + "/submit",
        json={"request_id": str(uuid4()), "expected_revision": selected.json()["revision"]},
    )
    assert submitted.status_code == 200, submitted.text
    approved = supervisor.post(
        accounting_path + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": submitted.json()["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    record = approved.json()
    assert record["status"] == "approved"
    assert record["approval_valid"] is True
    assert record["source_current"] is True
    assert record["summary"]["ordinary_issued_quantity"] == 5
    assert record["summary"]["replacement_issued_quantity"] == 0
    assert record["summary"]["tendered_issued_quantity"] == 0
    assert record["summary"]["retrieved_unused_quantity"] == 0
    assert record["summary"]["estimated_box_from_stock_quantity"] == 5
    assert record["summary"]["observed_counted_quantity"] is None
    return {
        "path": accounting_path,
        "record": record,
        "special_papers": special.json(),
        "stock_snapshot": stock_snapshot.json(),
        "receipt": received.json(),
    }


@contextmanager
def counting_setup(
    admin: TestClient, database_url: str, *, candidates_per_constituency: int = 1,
) -> Iterator[dict]:
    """Provide a live single-election received-box and approved-source P(18) context.

    All setup writes use the same authenticated public API journeys as staff clients.
    The returned paths and IDs are intended for Ticket 17 API and Qt acceptance tests.
    """
    stations = box_stations(admin, candidates_per_constituency=candidates_per_constituency)
    clock = BoxClock()
    station_ids = [stations[code]["id"] for code in ("N1", "N2", "N3", "S1")]
    with ExitStack() as stack:
        polling, polling_account = stack.enter_context(
            box_staff(admin, database_url, clock, "polling_officer", station_ids)
        )
        both_counting, both_counting_account = stack.enter_context(
            box_staff(
                admin,
                database_url,
                clock,
                "counting_officer",
                [stations["N1"]["id"], stations["N2"]["id"]],
            )
        )
        receiver_only, receiver_account = stack.enter_context(
            box_staff(admin, database_url, clock, "counting_officer", [stations["N1"]["id"]])
        )
        supervisor, supervisor_account = stack.enter_context(
            box_staff(admin, database_url, clock, "supervisor", station_ids)
        )

        source_accounting = {
            code: _prepare_source_accounting(
                polling, both_counting, supervisor, stations[code]
            )
            for code in ("N1", "N2")
        }

        # Local N1 box: prepared and explicitly acknowledged by the receiver.
        local_path = f"/api/workspace/stations/{stations['N1']['id']}/boxes"
        local_prepared = polling.post(
            local_path,
            json=prepared_box(box_reference="Ticket 17 local N1"),
        )
        assert local_prepared.status_code == 201, local_prepared.text
        local_received = receiver_only.post(
            f"{local_path}/{local_prepared.json()['id']}/receipt",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert local_received.status_code == 201, local_received.text

        # N2 is configured to send to N1. Record departure and receipt separately.
        transfer_source = f"/api/workspace/stations/{stations['N2']['id']}/boxes"
        transferred = polling.post(
            transfer_source,
            json=prepared_box(box_reference="Ticket 17 transfer N2"),
        )
        assert transferred.status_code == 201, transferred.text
        box_id = transferred.json()["id"]
        departure = polling.post(
            f"{transfer_source}/{box_id}/departure",
            json=event_command(1, "2026-11-15T22:50:00+08:00"),
        )
        assert departure.status_code == 201, departure.text
        transferred_received = receiver_only.post(
            f"{local_path}/{box_id}/receipt",
            json=event_command(2, "2026-11-15T23:05:00+08:00"),
        )
        assert transferred_received.status_code == 201, transferred_received.text

        # An additional prepared box remains unreceived for missing-receipt cases.
        transfer_unreceived = polling.post(
            transfer_source,
            json=prepared_box(box_reference="Ticket 17 unreceived N2"),
        )
        assert transfer_unreceived.status_code == 201, transfer_unreceived.text
        assert transfer_unreceived.json()["status"] == "prepared"

        yield {
            "clients": {
                "polling": polling,
                "bothcounting": both_counting,
                "receiveronly": receiver_only,
                "supervisor": supervisor,
            },
            "accounts": {
                "polling": polling_account,
                "bothcounting": both_counting_account,
                "receiveronly": receiver_account,
                "supervisor": supervisor_account,
            },
            "election": stations["election"],
            "stations": {code: stations[code] for code in ("N1", "N2", "N3", "S1")},
            "boxes": {
                "local_n1": local_received.json(),
                "transferred_n2": transferred_received.json(),
                "unreceived_n2": transfer_unreceived.json(),
            },
            "accounting": source_accounting,
            "paths": {
                "n1_boxes": local_path,
                "n2_boxes": transfer_source,
                "n1_accounting": source_accounting["N1"]["path"],
                "n2_accounting": source_accounting["N2"]["path"],
                "n1_counting_scopes": (
                    f"/api/workspace/stations/{stations['N1']['id']}/counting-scopes"
                ),
            },
            "clock": clock,
        }
