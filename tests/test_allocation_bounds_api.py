"""Allocation bounds use current ordinary receipts through the public API."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url
from tests.stock_support import stock_payload
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup  # noqa: F401


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.mark.parametrize(
    ("first", "last"),
    [
        pytest.param("000009", "000009", id="replacement-reserve"),
        pytest.param("000010", "000010", id="tendered-reserve"),
        pytest.param("000000", "000003", id="starts-before-received-stock"),
        pytest.param("000007", "000011", id="ends-after-received-stock"),
    ],
)
def test_reserved_or_unreceived_papers_cannot_be_allocated(
    allocation_setup: dict, first: str, last: str
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    before = officer.get(path).json()
    rejected = officer.post(
        path,
        json=allocation_payload(setup["counter"]["id"], serial_from=first, serial_to=last),
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "allocation_outside_stock"
    after = officer.get(path)
    assert after.status_code == 200
    assert after.json() == before
    assert after.json()["items"] == []
    assert after.json()["availability"][0]["available_quantity"] == 8


def test_an_interval_cannot_bridge_a_gap_between_received_ordinary_ranges(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    receipt = officer.put(
        setup["base"] + f"/stock/{setup['receipt']['id']}",
        json=stock_payload(
            revision=1,
            reason="核對接收單，第四號選票未有接收",
            ordinary_quantity=7,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000003"},
                {"pool": "ordinary", "serial_from": "000005", "serial_to": "000008"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert receipt.status_code == 200
    before = officer.get(path).json()
    rejected = officer.post(
        path,
        json=allocation_payload(setup["counter"]["id"], serial_from="000002", serial_to="000006"),
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "allocation_outside_stock"
    assert officer.get(path).json() == before
    assert before["items"] == []
    assert before["availability"][0]["available_quantity"] == 7


def test_a_counter_from_another_station_is_not_found_in_the_selected_station(
    allocation_setup: dict, admin: TestClient
) -> None:
    setup = allocation_setup
    foreign_station = setup["stations"][1]
    foreign_counter = admin.post(
        f"/api/elections/{foreign_station['election_id']}/constituencies/"
        f"{foreign_station['constituency_id']}/stations/{foreign_station['id']}/counters",
        json={"code": "C2", "name": "另一票站的發票櫃台", "request_id": str(uuid4())},
    )
    assert foreign_counter.status_code == 201
    officer, path = setup["officer"], setup["base"] + "/allocations"
    before = officer.get(path).json()
    rejected = officer.post(path, json=allocation_payload(foreign_counter.json()["id"]))
    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "counter_not_found"
    assert officer.get(path).json() == before
    assert before["items"] == []


def test_an_allocation_can_cross_adjacent_received_lines_and_records_both_bases(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    receipt = officer.put(
        setup["base"] + f"/stock/{setup['receipt']['id']}",
        json=stock_payload(
            revision=1,
            reason="按交接單分列兩個連續範圍",
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000004"},
                {"pool": "ordinary", "serial_from": "000005", "serial_to": "000008"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert receipt.status_code == 200
    created = officer.post(
        path,
        json=allocation_payload(setup["counter"]["id"], serial_from="000004", serial_to="000005"),
    )
    assert created.status_code == 201
    allocation = created.json()
    assert (allocation["serial_from"], allocation["serial_to"], allocation["quantity"]) == (
        "000004",
        "000005",
        2,
    )
    assert allocation["receipt_basis"] == [
        {"receipt_id": receipt.json()["id"], "revision": 2, "range_line": 0},
        {"receipt_id": receipt.json()["id"], "revision": 2, "range_line": 1},
    ]
    view = officer.get(path).json()
    assert view["items"] == [allocation]
    availability = view["availability"][0]
    assert (
        availability["ordinary_received_quantity"],
        availability["allocated_quantity"],
        availability["available_quantity"],
    ) == (8, 2, 6)
    assert [
        (row["serial_from"], row["serial_to"], row["quantity"]) for row in availability["ranges"]
    ] == [("000001", "000003", 3), ("000006", "000008", 3)]


def test_eighteen_digit_serials_keep_exact_large_quantities_without_paper_enumeration(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    receipt = officer.put(
        setup["base"] + f"/stock/{setup['receipt']['id']}",
        json=stock_payload(
            revision=1,
            reason="改正接收單的完整十八位數系列",
            ranges=[
                {
                    "pool": "ordinary",
                    "serial_from": "100000000000000000",
                    "serial_to": "999999999999999999",
                }
            ],
            ordinary_quantity=900000000000000000,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert receipt.status_code == 200
    created = officer.post(
        path,
        json=allocation_payload(
            setup["counter"]["id"],
            serial_from="100000000000000000",
            serial_to="999999999999999997",
        ),
    )
    assert created.status_code == 201
    allocation = created.json()
    assert (allocation["serial_from"], allocation["serial_to"], allocation["quantity"]) == (
        "100000000000000000",
        "999999999999999997",
        899999999999999998,
    )
    assert allocation["receipt_basis"] == [
        {"receipt_id": receipt.json()["id"], "revision": 2, "range_line": 0}
    ]
    availability = officer.get(path).json()["availability"][0]
    assert (
        availability["ordinary_received_quantity"],
        availability["allocated_quantity"],
        availability["available_quantity"],
        availability["replacement_quantity"],
        availability["tendered_quantity"],
    ) == (900000000000000000, 899999999999999998, 2, 0, 0)
    assert availability["ranges"] == [
        {
            "serial_from": "999999999999999998",
            "serial_to": "999999999999999999",
            "quantity": 2,
            "receipt_id": receipt.json()["id"],
            "receipt_revision": 2,
        }
    ]
