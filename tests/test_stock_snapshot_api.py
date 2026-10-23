"""Remaining-stock snapshots retain their real allocation basis across clients."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_support import stock_payload
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_officer_records_remaining_stock_and_another_client_reads_its_exact_saved_basis(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        response = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:17.123456+08:00",
                "counters": [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000004",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 201
        saved = response.json()
        assert type(saved["id"]) is int and saved["id"] > 0
        assert saved["station_id"] == station_id
        assert saved["status"] == "recorded" and saved["revision"] == 1
        assert saved["event_at"] == "2026-11-15T01:30:17.123456Z"
        assert saved["entered_at"] == "2026-11-15T04:00:00Z"
        assert saved["actor_id"] == account["id"] and saved["reason"] == ""
        assert saved["complete"] is True
        assert saved["ordinary_allocated_quantity"] == 6
        assert saved["ordinary_returned_quantity"] == 0
        assert saved["ordinary_net_allocated_quantity"] == 6
        assert saved["ordinary_remaining_quantity"] == 3
        assert saved["ordinary_issued_quantity"] == 3
        assert [(row["receipt_id"], row["revision"]) for row in saved["receipt_basis"]] == [
            (received.json()["id"], 1)
        ]
        assert [(row["allocation_id"], row["revision"]) for row in saved["allocation_basis"]] == [
            (allocated.json()["id"], 1)
        ]
        assert saved["return_basis"] == []
        with TestClient(create_app(database_url, now=clock)) as another:
            another.headers.update(officer.headers)
            reopened = another.get(base + f"/stock-snapshots/{saved['id']}")
            assert reopened.status_code == 200
            assert reopened.json() == saved
        turnout = officer.get(scope["path"])
        assert turnout.status_code == 200
        periods = turnout.json()["items"]
        assert periods
        assert all(row["status"] == "missing" and row["record"] is None for row in periods)


def test_reasoned_snapshot_correction_keeps_history_and_exact_replay_after_later_revision(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        path = base + "/stock-snapshots"
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": counter_id,
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert original["revision"] == 1 and original["ordinary_issued_quantity"] == 3
        target = path + f"/{original['id']}"
        correction = {
            **command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對紙本櫃台結餘，第4號已發出",
            "counters": [
                {
                    "counter_id": counter_id,
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000005", "serial_to": "000006"}
                    ],
                }
            ],
        }
        corrected = officer.put(target, json=correction)
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["id"] == original["id"] and second["revision"] == 2
        assert second["ordinary_remaining_quantity"] == 2
        assert second["ordinary_issued_quantity"] == 4
        assert second["actor_id"] == account["id"]
        assert second["event_at"] == "2026-11-15T01:30:17.123456Z"
        assert second["entered_at"] == "2026-11-15T04:00:00Z"
        assert second["reason"] == correction["reason"]
        assert [(row["receipt_id"], row["revision"]) for row in second["receipt_basis"]] == [
            (receipt.json()["id"], 1)
        ]
        assert [(row["allocation_id"], row["revision"]) for row in second["allocation_basis"]] == [
            (allocation.json()["id"], 1)
        ]
        assert second["return_basis"] == []
        historical = officer.get(target, params={"revision": 1})
        assert historical.status_code == 200 and historical.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, second]
        stale = officer.put(target, json={**correction, "request_id": str(uuid4())})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"

        later = officer.put(
            target,
            json={
                **correction,
                "request_id": str(uuid4()),
                "revision": 2,
                "reason": "再次核對，第5號亦已發出",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000006", "serial_to": "000006"}
                        ],
                    }
                ],
            },
        )
        assert later.status_code == 200
        third = later.json()
        assert third["revision"] == 3 and third["ordinary_issued_quantity"] == 5
        replay = officer.put(target, json=correction)
        assert replay.status_code == 200 and replay.json() == second
        assert officer.get(target).json() == third
        assert officer.get(target, params={"revision": 1}).json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, second, third]


def test_returned_unissued_paper_can_move_to_another_counter_without_creating_a_voter(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station = scope["stations"][0]
    station_id = station["id"]
    base = f"/api/workspace/stations/{station_id}"
    station_options = admin.get("/api/accounts/station-options")
    assert station_options.status_code == 200
    constituency_id = next(
        row["constituency"]["id"] for row in station_options.json()["items"]
        if row["station"]["id"] == station_id
    )
    second_counter = admin.post(
        f"/api/elections/{scope['election']['id']}/constituencies/"
        f"{constituency_id}/stations/{station_id}/counters",
        json={"request_id": str(uuid4()), "code": "C2", "name": "第二發票櫃台"},
    )
    assert second_counter.status_code == 201
    activated = admin.post(
        f"/api/elections/{scope['election']['id']}/activate",
        json={
            "election_revision": scope["election"]["revision"],
            "schedule_revision": scope["schedule"]["revision"],
        },
    )
    assert activated.status_code == 200
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counters = {row["code"]: row for row in options.json()["counters"]}
        first_id, second_id = counters["C1"]["id"], counters["C2"]["id"]
        assert second_id == second_counter.json()["id"]
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": first_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        first_snapshot = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
                "counters": [
                    {
                        "counter_id": first_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                        ],
                    },
                    {"counter_id": second_id, "ranges": []},
                ],
            },
        )
        assert first_snapshot.status_code == 201
        original = first_snapshot.json()
        assert original["complete"] is True and original["ordinary_issued_quantity"] == 3
        returned = officer.post(
            base + "/stock-returns",
            json={
                "request_id": str(uuid4()),
                "counter_id": first_id,
                "series": "普通系列 A",
                "serial_from": "000006",
                "serial_to": "000006",
                "event_at": "2026-11-15T10:00:00+08:00",
            },
        )
        assert returned.status_code == 201
        saved_return = returned.json()
        assert saved_return["status"] == "recorded" and saved_return["revision"] == 1
        assert saved_return["quantity"] == 1 and saved_return["counter"] == counters["C1"]
        assert [
            (
                row["allocation_id"], row["revision"], row["serial_from"],
                row["serial_to"], row["quantity"],
            )
            for row in saved_return["allocation_basis"]
        ] == [(allocation.json()["id"], 1, "000006", "000006", 1)]
        available = officer.get(base + "/allocations")
        assert available.status_code == 200
        balance = next(
            row for row in available.json()["availability"] if row["series"] == "普通系列 A"
        )
        assert balance["available_quantity"] == 3
        assert [
            (row["serial_from"], row["serial_to"], row["quantity"]) for row in balance["ranges"]
        ] == [("000006", "000008", 3)]
        reallocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": second_id,
                "series": "普通系列 A",
                "serial_from": "000006",
                "serial_to": "000006",
                "event_at": "2026-11-15T10:05:00+08:00",
            },
        )
        assert reallocated.status_code == 201
        later = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:30:00+08:00",
                "counters": [
                    {
                        "counter_id": first_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000005"}
                        ],
                    },
                    {
                        "counter_id": second_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000006", "serial_to": "000006"}
                        ],
                    },
                ],
            },
        )
        assert later.status_code == 201
        snapshot = later.json()
        fields = (
            "ordinary_allocated_quantity", "ordinary_returned_quantity",
            "ordinary_net_allocated_quantity", "ordinary_remaining_quantity",
            "ordinary_issued_quantity",
        )
        assert snapshot["complete"] is True
        assert tuple(snapshot[field] for field in fields) == (7, 1, 6, 3, 3)
        by_counter = {row["counter"]["id"]: row for row in snapshot["counters"]}
        assert tuple(by_counter[first_id][field] for field in fields) == (6, 1, 5, 2, 3)
        assert tuple(by_counter[second_id][field] for field in fields) == (1, 0, 1, 1, 0)
        reopened = officer.get(base + f"/stock-snapshots/{original['id']}")
        assert reopened.status_code == 200 and reopened.json() == original


def test_allocation_correction_cannot_release_papers_already_observed_as_issued(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": "2026-11-15T09:00:00+08:00",
        }
        allocated = officer.post(base + "/allocations", json=command)
        assert allocated.status_code == 201
        original_allocation = allocated.json()
        observed = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                        ],
                    }
                ],
            },
        )
        assert observed.status_code == 201
        original_snapshot = observed.json()
        assert original_snapshot["ordinary_issued_quantity"] == 3
        target = base + f"/allocations/{original_allocation['id']}"
        removed_issued = officer.put(
            target,
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "更正派發範圍，只保留第四至六號",
                "serial_from": "000004",
            },
        )
        assert removed_issued.status_code == 409
        assert removed_issued.json()["detail"]["code"] == "stock_observations_conflict"
        current = officer.get(target)
        assert current.status_code == 200 and current.json() == original_allocation
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original_allocation]
        snapshot = officer.get(base + f"/stock-snapshots/{original_snapshot['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == original_snapshot


def test_p14_current_availability_accounts_for_returns_without_rewriting_exact_allocation(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": "2026-11-15T09:00:00+08:00",
        }
        allocated = officer.post(base + "/allocations", json=command)
        assert allocated.status_code == 201
        returned = officer.post(
            base + "/stock-returns",
            json={
                **command,
                "request_id": str(uuid4()),
                "serial_from": "000006",
                "event_at": "2026-11-15T10:00:00+08:00",
            },
        )
        assert returned.status_code == 201
        current = officer.get(base + "/allocations")
        assert current.status_code == 200
        balance = current.json()["availability"][0]
        assert balance["ordinary_received_quantity"] == 8
        assert balance["allocated_quantity"] == 5
        assert balance["available_quantity"] == 3
        assert balance["replacement_quantity"] == 1 and balance["tendered_quantity"] == 1
        assert [
            (row["serial_from"], row["serial_to"], row["quantity"]) for row in balance["ranges"]
        ] == [("000006", "000008", 3)]

        statement = officer.get(base + "/allocations/statement", params={"locale": "en"})
        assert statement.status_code == 200
        report = statement.json()
        assert report["report_scope"] == "station_current"
        assert report["availability"][0]["available_quantity"] == 3
        assert report["availability"][0]["ordinary_received_quantity"] == 8
        assert report["availability"][0]["allocated_quantity"] == 5
        assert report["availability"][0]["replacement_quantity"] == 1
        assert report["availability"][0]["tendered_quantity"] == 1
        assert report["availability"] == current.json()["availability"]
        selected = officer.get(
            base + "/allocations/statement",
            params={"allocation_id": allocated.json()["id"], "revision": 1, "locale": "en"},
        )
        assert selected.status_code == 200
        exact = selected.json()
        assert exact["report_scope"] == "allocation_revision"
        assert exact["allocation_id"] == allocated.json()["id"] and exact["revision"] == 1
        assert exact["items"][0]["quantity"] == 6
        assert exact["availability"] is None


def test_later_new_snapshot_cannot_restore_papers_previously_observed_as_issued(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        path = base + "/stock-snapshots"
        first = officer.post(
            path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                        ],
                    }
                ],
            },
        )
        assert first.status_code == 201
        original = first.json()
        assert original["complete"] is True and original["ordinary_issued_quantity"] == 3
        restored_issued = officer.post(
            path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:00+08:00",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000001", "serial_to": "000006"}
                        ],
                    }
                ],
            },
        )
        assert restored_issued.status_code == 409
        assert restored_issued.json()["detail"]["code"] == "stock_already_issued"
        previous = officer.get(path + f"/{original['id']}")
        assert previous.status_code == 200 and previous.json() == original
        turnout = officer.get(scope["path"])
        assert turnout.status_code == 200
        periods = turnout.json()["items"]
        assert periods
        assert all(row["status"] == "missing" and row["record"] is None for row in periods)


def test_snapshot_collection_distinguishes_missing_unreported_counter_and_explicit_zero(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        path = base + "/stock-snapshots"
        missing = officer.get(path)
        assert missing.status_code == 200
        empty = missing.json()
        assert empty["snapshot_state"] == "missing"
        assert empty["latest"] is None and empty["items"] == []
        assert empty["counters"] == options.json()["counters"]
        assert empty["scope"] == options.json()["scope"]
        unreported = officer.post(
            path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
                "counters": [],
            },
        )
        assert unreported.status_code == 201
        incomplete = unreported.json()
        assert incomplete["complete"] is False
        assert incomplete["ordinary_remaining_quantity"] is None
        assert incomplete["ordinary_issued_quantity"] is None
        assert len(incomplete["counters"]) == 1
        assert incomplete["counters"][0]["counter"]["id"] == counter_id
        assert incomplete["counters"][0]["reported"] is False
        assert incomplete["counters"][0]["ranges"] is None
        assert incomplete["counters"][0]["ordinary_remaining_quantity"] is None
        assert incomplete["counters"][0]["ordinary_issued_quantity"] is None
        after_unreported = officer.get(path)
        assert after_unreported.status_code == 200
        assert after_unreported.json()["snapshot_state"] == "incomplete"
        assert after_unreported.json()["latest"] == incomplete
        assert after_unreported.json()["items"] == [incomplete]

        explicit_zero = officer.post(
            path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:45:00+08:00",
                "counters": [{"counter_id": counter_id, "ranges": []}],
            },
        )
        assert explicit_zero.status_code == 201
        complete = explicit_zero.json()
        assert complete["complete"] is True
        assert complete["ordinary_remaining_quantity"] == 0
        assert complete["ordinary_issued_quantity"] == 6
        assert len(complete["counters"]) == 1
        assert complete["counters"][0]["counter"]["id"] == counter_id
        assert complete["counters"][0]["reported"] is True
        assert complete["counters"][0]["ranges"] == []
        assert complete["counters"][0]["ordinary_remaining_quantity"] == 0
        assert complete["counters"][0]["ordinary_issued_quantity"] == 6
        after_zero = officer.get(path)
        assert after_zero.status_code == 200
        collection = after_zero.json()
        assert collection["snapshot_state"] == "complete"
        assert collection["latest"] == complete
        assert len(collection["items"]) == 2
        assert {row["id"]: row for row in collection["items"]} == {
            incomplete["id"]: incomplete, complete["id"]: complete,
        }
        retained = officer.get(path + f"/{incomplete['id']}")
        assert retained.status_code == 200 and retained.json() == incomplete


def test_backdated_allocation_invalidates_current_snapshot_basis_until_reasoned_revision(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        first_allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert first_allocation.status_code == 201
        path = base + "/stock-snapshots"
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:00+08:00",
            "counters": [
                {
                    "counter_id": counter_id,
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert original["ordinary_issued_quantity"] == 3
        target = path + f"/{original['id']}"
        initial = officer.get(path)
        assert initial.status_code == 200
        baseline = initial.json()
        assert "latest_basis_current" in baseline
        assert baseline["latest_basis_current"] is True
        assert baseline["current_ordinary_issued_quantity"] == 3
        assert baseline["latest"] == original
        assert "latest_basis_current" not in original
        assert "current_ordinary_issued_quantity" not in original

        backdated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000007",
                "serial_to": "000008",
                "event_at": "2026-11-15T09:15:00+08:00",
            },
        )
        assert backdated.status_code == 201
        stale_basis = officer.get(path)
        assert stale_basis.status_code == 200
        changed = stale_basis.json()
        assert changed["snapshot_state"] == "complete"
        assert changed["latest"] == original
        assert changed["latest_basis_current"] is False
        assert changed["current_ordinary_issued_quantity"] is None
        retained = officer.get(target)
        assert retained.status_code == 200 and retained.json() == original

        corrected = officer.put(
            target,
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "補登九時十五分加派兩張，核對原快照結餘",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000008"}
                        ],
                    }
                ],
            },
        )
        assert corrected.status_code == 200
        revised = corrected.json()
        assert revised["revision"] == 2
        assert revised["ordinary_allocated_quantity"] == 8
        assert revised["ordinary_remaining_quantity"] == 5
        assert revised["ordinary_issued_quantity"] == 3
        assert len(revised["allocation_basis"]) == 2
        assert {(row["allocation_id"], row["revision"]) for row in revised["allocation_basis"]} == {
            (first_allocation.json()["id"], 1), (backdated.json()["id"], 1),
        }
        refreshed = officer.get(path)
        assert refreshed.status_code == 200
        assert refreshed.json()["latest"] == revised
        assert refreshed.json()["latest_basis_current"] is True
        assert refreshed.json()["current_ordinary_issued_quantity"] == 3
        historical = officer.get(target, params={"revision": 1})
        assert historical.status_code == 200 and historical.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, revised]


def test_counter_return_correction_preserves_history_replay_and_separate_unissued_kind(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        path = base + "/stock-returns"
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert original["revision"] == 1 and original["quantity"] == 1
        assert original["kind"] == "unissued_counter_to_pro"
        retry = officer.post(path, json=command)
        assert retry.status_code == 200 and retry.json() == original
        target = path + f"/{original['id']}"
        reopened = officer.get(target)
        assert reopened.status_code == 200 and reopened.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original]

        correction = {
            **command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對交收單，未發出退回範圍應包括第五號",
            "serial_from": "000005",
        }
        corrected = officer.put(target, json=correction)
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["id"] == original["id"] and second["revision"] == 2
        assert second["quantity"] == 2 and second["status"] == "recorded"
        assert second["kind"] == "unissued_counter_to_pro"
        assert second["counter"] == counter and second["series"] == "普通系列 A"
        assert (second["serial_from"], second["serial_to"]) == ("000005", "000006")
        assert second["actor_id"] == account["id"]
        assert second["event_at"] == "2026-11-15T02:00:00Z"
        assert second["entered_at"] == "2026-11-15T04:00:00Z"
        assert second["reason"] == correction["reason"]
        assert [
            (
                row["allocation_id"], row["revision"], row["serial_from"],
                row["serial_to"], row["quantity"],
            )
            for row in second["allocation_basis"]
        ] == [(allocated.json()["id"], 1, "000005", "000006", 2)]
        historical = officer.get(target, params={"revision": 1})
        assert historical.status_code == 200 and historical.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, second]
        replay = officer.put(target, json=correction)
        assert replay.status_code == 200 and replay.json() == second
        current = officer.get(target)
        assert current.status_code == 200 and current.json() == second
        availability = officer.get(base + "/allocations")
        assert availability.status_code == 200
        balance = availability.json()["availability"][0]
        assert balance["allocated_quantity"] == 4 and balance["available_quantity"] == 4
        assert [
            (row["serial_from"], row["serial_to"], row["quantity"]) for row in balance["ranges"]
        ] == [("000005", "000008", 4)]


@pytest.mark.parametrize("mode", ["range", "time"])
def test_return_correction_cannot_restore_ownership_after_paper_is_reallocated(
    admin: TestClient, database_url: str, mode: str
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    station_options = admin.get("/api/accounts/station-options")
    assert station_options.status_code == 200
    constituency_id = next(
        row["constituency"]["id"] for row in station_options.json()["items"]
        if row["station"]["id"] == station_id
    )
    second_counter = admin.post(
        f"/api/elections/{scope['election']['id']}/constituencies/"
        f"{constituency_id}/stations/{station_id}/counters",
        json={"request_id": str(uuid4()), "code": "C2", "name": "第二發票櫃台"},
    )
    assert second_counter.status_code == 201
    activated = admin.post(
        f"/api/elections/{scope['election']['id']}/activate",
        json={
            "election_revision": scope["election"]["revision"],
            "schedule_revision": scope["schedule"]["revision"],
        },
    )
    assert activated.status_code == 200
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_ids = {row["code"]: row["id"] for row in options.json()["counters"]}
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_ids["C1"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter_ids["C1"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        returned = officer.post(base + "/stock-returns", json=command)
        assert returned.status_code == 201
        original = returned.json()
        reallocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_ids["C2"],
                "series": "普通系列 A",
                "serial_from": "000006",
                "serial_to": "000006",
                "event_at": "2026-11-15T10:05:00+08:00",
            },
        )
        assert reallocated.status_code == 201
        second_allocation = reallocated.json()
        target = base + f"/stock-returns/{original['id']}"
        changes = (
            {"serial_from": "000005", "serial_to": "000005"}
            if mode == "range" else {"event_at": "2026-11-15T10:10:00+08:00"}
        )
        corrected = officer.put(
            target,
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "核對紙本退回範圍及時間",
                **changes,
            },
        )
        assert corrected.status_code == 409
        assert corrected.json()["detail"]["code"] == "stock_returns_conflict"
        retained = officer.get(target)
        assert retained.status_code == 200 and retained.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original]
        second = officer.get(base + f"/allocations/{second_allocation['id']}")
        assert second.status_code == 200 and second.json() == second_allocation
        availability = officer.get(base + "/allocations")
        assert availability.status_code == 200
        balance = availability.json()["availability"][0]
        assert balance["ordinary_received_quantity"] == 8
        assert balance["allocated_quantity"] == 6 and balance["available_quantity"] == 2
        assert [
            (row["serial_from"], row["serial_to"], row["quantity"]) for row in balance["ranges"]
        ] == [("000007", "000008", 2)]


@pytest.mark.parametrize("has_reallocation", [False, True])
def test_compatible_allocation_revision_preserves_return_lineage_and_current_availability(
    admin: TestClient, database_url: str, has_reallocation: bool
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    station_options = admin.get("/api/accounts/station-options")
    assert station_options.status_code == 200
    constituency_id = next(
        row["constituency"]["id"] for row in station_options.json()["items"]
        if row["station"]["id"] == station_id
    )
    counter_response = admin.post(
        f"/api/elections/{scope['election']['id']}/constituencies/"
        f"{constituency_id}/stations/{station_id}/counters",
        json={"request_id": str(uuid4()), "code": "C2", "name": "第二發票櫃台"},
    )
    assert counter_response.status_code == 201
    activated = admin.post(
        f"/api/elections/{scope['election']['id']}/activate",
        json={
            "election_revision": scope["election"]["revision"],
            "schedule_revision": scope["schedule"]["revision"],
        },
    )
    assert activated.status_code == 200
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counters = {row["code"]: row for row in options.json()["counters"]}
        command = {
            "request_id": str(uuid4()),
            "counter_id": counters["C1"]["id"],
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": "2026-11-15T09:00:00+08:00",
        }
        allocated = officer.post(base + "/allocations", json=command)
        assert allocated.status_code == 201
        original = allocated.json()
        returned = officer.post(
            base + "/stock-returns",
            json={
                **command,
                "request_id": str(uuid4()),
                "serial_from": "000006",
                "event_at": "2026-11-15T10:00:00+08:00",
            },
        )
        assert returned.status_code == 201
        original_return = returned.json()
        assert [
            (row["allocation_id"], row["revision"])
            for row in original_return["allocation_basis"]
        ] == [(original["id"], 1)]
        claimed = None
        if has_reallocation:
            response = officer.post(
                base + "/allocations",
                json={
                    **command,
                    "request_id": str(uuid4()),
                    "counter_id": counters["C2"]["id"],
                    "serial_from": "000006",
                    "event_at": "2026-11-15T10:05:00+08:00",
                },
            )
            assert response.status_code == 201
            claimed = response.json()
        target = base + f"/allocations/{original['id']}"
        correction = {
            **command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對紙本交收資料，原範圍及派發時間確認無誤",
        }
        corrected = officer.put(target, json=correction)
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["id"] == original["id"] and second["revision"] == 2
        assert second["counter"] == counters["C1"] and second["series"] == "普通系列 A"
        assert (second["serial_from"], second["serial_to"], second["quantity"]) == (
            "000001", "000006", 6,
        )
        assert second["event_at"] == "2026-11-15T01:00:00Z"
        assert second["actor_id"] == account["id"] and second["reason"] == correction["reason"]
        assert [(row["receipt_id"], row["revision"]) for row in second["receipt_basis"]] == [
            (receipt.json()["id"], 1)
        ]
        frozen_return = officer.get(base + f"/stock-returns/{original_return['id']}")
        assert frozen_return.status_code == 200 and frozen_return.json() == original_return
        historical = officer.get(target, params={"revision": 1})
        assert historical.status_code == 200 and historical.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, second]
        availability = officer.get(base + "/allocations")
        assert availability.status_code == 200
        balance = availability.json()["availability"][0]
        assert balance["ordinary_received_quantity"] == 8
        assert balance["replacement_quantity"] == 1 and balance["tendered_quantity"] == 1
        if has_reallocation:
            assert balance["allocated_quantity"] == 6 and balance["available_quantity"] == 2
            expected = [("000007", "000008", 2)]
        else:
            assert balance["allocated_quantity"] == 5 and balance["available_quantity"] == 3
            expected = [("000006", "000008", 3)]
        assert [
            (row["serial_from"], row["serial_to"], row["quantity"]) for row in balance["ranges"]
        ] == expected
        if claimed is not None:
            retained = officer.get(base + f"/allocations/{claimed['id']}")
            assert retained.status_code == 200 and retained.json() == claimed


def test_counter_return_collection_lists_stable_current_heads_and_retains_revision_history(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        path = base + "/stock-returns"
        initial = officer.get(path)
        assert initial.status_code == 200
        assert initial.json()["items"] == []
        assert initial.json()["counters"] == options.json()["counters"]
        assert initial.json()["scope"] == options.json()["scope"]
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        first = officer.post(path, json=command)
        assert first.status_code == 201
        original = first.json()
        second = officer.post(
            path,
            json={
                **command,
                "request_id": str(uuid4()),
                "serial_from": "000005",
                "serial_to": "000005",
                "event_at": "2026-11-15T10:15:00+08:00",
            },
        )
        assert second.status_code == 201
        other = second.json()
        assert original["id"] < other["id"]
        listed = officer.get(path)
        assert listed.status_code == 200
        assert listed.json()["items"] == [original, other]
        assert listed.json()["counters"] == options.json()["counters"]
        assert listed.json()["scope"] == options.json()["scope"]
        target = path + f"/{original['id']}"
        corrected = officer.put(
            target,
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "交收資料覆核，原範圍及退回時間確認無誤",
            },
        )
        assert corrected.status_code == 200
        revised = corrected.json()
        assert revised["id"] == original["id"] and revised["revision"] == 2
        current = officer.get(path)
        assert current.status_code == 200
        assert current.json()["items"] == [revised, other]
        assert current.json()["counters"] == options.json()["counters"]
        assert current.json()["scope"] == options.json()["scope"]
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, revised]
