"""Counter allocations cross the public API and real MySQL transaction seam."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.stock_support import ready_client, staff_account, stock_payload, stock_stations


def allocation_payload(counter_id: int, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "counter_id": counter_id,
        "series": "普通系列 A",
        "serial_from": "000001",
        "serial_to": "000003",
        "event_at": "2026-11-08T08:05:00+08:00",
        **changes,
    }


@pytest.fixture
def allocation_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    stations = stock_stations(admin)
    station = stations[0]
    counter_base = (
        f"/api/elections/{station['election_id']}/constituencies/"
        f"{station['constituency_id']}/stations/{station['id']}/counters"
    )
    counter_response = admin.post(
        counter_base,
        json={"code": "C1", "name": "發票櫃台一", "request_id": str(uuid4())},
    )
    assert counter_response.status_code == 201
    account = staff_account(admin, [station["id"]])
    base = f"/api/workspace/stations/{station['id']}"
    with ready_client(database_url, account) as officer:
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201
        yield {
            "stations": stations,
            "station": station,
            "counter": counter_response.json(),
            "counter_base": counter_base,
            "officer": officer,
            "base": base,
            "account": account,
            "receipt": received.json(),
        }


def test_officer_allocates_an_ordinary_range_and_another_client_reads_shared_availability(
    admin: TestClient, database_url: str
) -> None:
    station = stock_stations(admin)[0]
    counter_response = admin.post(
        f"/api/elections/{station['election_id']}/constituencies/"
        f"{station['constituency_id']}/stations/{station['id']}/counters",
        json={"code": "C1", "name": "發票櫃台一", "request_id": str(uuid4())},
    )
    assert counter_response.status_code == 201
    counter = counter_response.json()
    account = staff_account(admin, [station["id"]])
    base = f"/api/workspace/stations/{station['id']}"
    with ready_client(database_url, account) as officer:
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201
        response = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000003",
                "event_at": "2026-11-08T08:05:00+08:00",
            },
        )
        assert response.status_code == 201
        allocation = response.json()
        assert allocation["revision"] == 1 and allocation["status"] == "recorded"
        assert allocation["counter"] == {"id": counter["id"], "code": "C1", "name": "發票櫃台一"}
        assert (allocation["serial_from"], allocation["serial_to"], allocation["quantity"]) == (
            "000001",
            "000003",
            3,
        )
        assert allocation["event_at"] == "2026-11-08T00:05:00Z"
        assert allocation["actor_id"] == account["id"]
        assert allocation["entered_at"] and allocation["reason"] == ""
        assert allocation["receipt_basis"] == [
            {"receipt_id": received.json()["id"], "revision": 1, "range_line": 0}
        ]
        with TestClient(create_app(database_url)) as other:
            other.headers.update(officer.headers)
            reopened = other.get(base + f"/allocations/{allocation['id']}")
            assert reopened.status_code == 200 and reopened.json() == allocation
            shared = other.get(base + "/allocations")
            assert shared.status_code == 200
            view = shared.json()
            assert view["scope"]["station"]["id"] == station["id"]
            assert view["items"] == [allocation]
            assert view["availability"] == [
                {
                    "series": "普通系列 A",
                    "ordinary_received_quantity": 8,
                    "allocated_quantity": 3,
                    "available_quantity": 5,
                    "replacement_quantity": 1,
                    "tendered_quantity": 1,
                    "ranges": [
                        {
                            "serial_from": "000004",
                            "serial_to": "000008",
                            "quantity": 5,
                            "receipt_id": received.json()["id"],
                            "receipt_revision": 1,
                        }
                    ],
                }
            ]


def test_two_counters_cannot_own_the_same_inclusive_serial(
    allocation_setup: dict, admin: TestClient
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    first = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert first.status_code == 201
    counter2 = admin.post(
        setup["counter_base"],
        json={"code": "C2", "name": "發票櫃台二", "request_id": str(uuid4())},
    )
    assert counter2.status_code == 201
    overlapping = officer.post(
        path,
        json=allocation_payload(counter2.json()["id"], serial_from="000003", serial_to="000005"),
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["detail"]["code"] == "allocation_overlap"
    after_error = officer.get(path).json()
    assert after_error["items"] == [first.json()]
    assert after_error["availability"][0]["available_quantity"] == 5
    adjacent = officer.post(
        path,
        json=allocation_payload(counter2.json()["id"], serial_from="000004", serial_to="000005"),
    )
    assert adjacent.status_code == 201
    view = officer.get(path).json()
    assert len(view["items"]) == 2
    assert view["availability"][0]["allocated_quantity"] == 5
    assert view["availability"][0]["available_quantity"] == 3
    assert view["availability"][0]["ranges"][0]["serial_from"] == "000006"


def test_exact_create_retry_has_one_effect_and_changed_payload_is_a_conflict(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    command = allocation_payload(setup["counter"]["id"])
    created = officer.post(path, json=command)
    assert created.status_code == 201
    repeated = officer.post(path, json=command)
    assert repeated.status_code == 200
    assert repeated.json() == created.json()
    conflict = officer.post(path, json={**command, "serial_to": "000004"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "request_conflict"
    view = officer.get(path).json()
    assert view["items"] == [created.json()]
    assert view["availability"][0]["allocated_quantity"] == 3
    assert view["availability"][0]["available_quantity"] == 5


def test_reasoned_amendment_preserves_history_and_releases_only_the_old_current_range(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    create_command = allocation_payload(setup["counter"]["id"])
    created = officer.post(path, json=create_command)
    assert created.status_code == 201
    target = path + f"/{created.json()['id']}"
    correction = allocation_payload(
        setup["counter"]["id"],
        revision=1,
        serial_from="000002",
        serial_to="000004",
        event_at="2026-11-08T08:06:00+08:00",
        reason="核對派票單，更正範圍",
    )
    changed = officer.put(target, json=correction)
    assert changed.status_code == 200
    current = changed.json()
    assert current["revision"] == 2
    assert (current["serial_from"], current["serial_to"], current["quantity"]) == (
        "000002",
        "000004",
        3,
    )
    assert current["reason"] == "核對派票單，更正範圍"
    assert officer.get(target).json() == current
    assert officer.get(target + "?revision=1").json() == created.json()
    history = officer.get(target + "/history")
    assert history.status_code == 200
    assert history.json()["items"] == [created.json(), current]
    assert officer.put(target, json=correction).json() == current
    original_replay = officer.post(path, json=create_command)
    assert original_replay.status_code == 200 and original_replay.json() == created.json()
    stale = officer.put(target, json={**correction, "request_id": str(uuid4())})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    ranges = officer.get(path).json()["availability"][0]["ranges"]
    assert [(row["serial_from"], row["serial_to"], row["quantity"]) for row in ranges] == [
        ("000001", "000001", 1),
        ("000005", "000008", 4),
    ]


def test_receipt_correction_cannot_remove_stock_already_owned_by_a_counter(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    created = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    stock_target = setup["base"] + f"/stock/{setup['receipt']['id']}"
    removed_owned_paper = officer.put(
        stock_target,
        json=stock_payload(
            revision=1,
            reason="核對交接文件",
            ordinary_quantity=7,
            ranges=[
                {"pool": "ordinary", "serial_from": "000002", "serial_to": "000008"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert removed_owned_paper.status_code == 409
    assert removed_owned_paper.json()["detail"]["code"] == "stock_allocations_conflict"
    assert officer.get(stock_target).json() == setup["receipt"]
    assert officer.get(stock_target + "/history").json()["items"] == [setup["receipt"]]
    view = officer.get(path).json()
    assert view["items"] == [created.json()]
    assert view["availability"][0]["ordinary_received_quantity"] == 8
    assert view["availability"][0]["available_quantity"] == 5
