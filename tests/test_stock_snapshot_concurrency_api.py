"""Independent public API clients serialize snapshot and unissued-return commands."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("resource", ["snapshot", "return"])
@pytest.mark.parametrize("operation", ["same_uuid_create", "competing_corrections"])
def test_concurrent_stock_commands_have_one_effect_and_exact_public_history(
    admin: TestClient, database_url: str, resource: str, operation: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        received = officer.post(
            base + "/stock",
            json=stock_payload(
                ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": "000006"}],
                ordinary_quantity=6,
                replacement_quantity=0,
                tendered_quantity=0,
            ),
        )
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = next(row["id"] for row in options.json()["counters"] if row["code"] == "C1")
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()), "counter_id": counter_id,
                "series": "普通系列 A", "serial_from": "000001", "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        snapshot_command = {
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
        return_command = {
            "request_id": str(uuid4()), "counter_id": counter_id,
            "series": "普通系列 A", "serial_from": "000006", "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        snapshot_original = None
        if resource == "return":
            snapshot = officer.post(base + "/stock-snapshots", json=snapshot_command)
            assert snapshot.status_code == 201
            snapshot_original = snapshot.json()
        command = snapshot_command if resource == "snapshot" else return_command
        path = base + ("/stock-snapshots" if resource == "snapshot" else "/stock-returns")
        before = officer.get(path)
        assert before.status_code == 200 and before.json()["items"] == []
        original = None
        if operation == "same_uuid_create":
            method, target = "POST", path
            commands = [command, dict(command)]
        else:
            created = officer.post(path, json=command)
            assert created.status_code == 201
            original = created.json()
            method, target = "PUT", path + f"/{original['id']}"
            commands = [
                {
                    **command, "request_id": str(uuid4()), "revision": 1,
                    "reason": "核對紙本交收單，確認原有範圍。",
                },
                {
                    **command, "request_id": str(uuid4()), "revision": 1,
                    "reason": "核對第二份紙本交收單，更正範圍。",
                },
            ]
            if resource == "snapshot":
                commands[1]["counters"] = [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000005", "serial_to": "000006",
                            }
                        ],
                    }
                ]
            else:
                commands[1]["serial_from"] = "000005"

        barrier = Barrier(2)

        def submit(payload: dict) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=clock)) as peer:
                peer.headers.update(officer.headers)
                barrier.wait(timeout=5)
                response = peer.request(method, target, json=payload)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, commands))
        expected_statuses = [200, 201] if original is None else [200, 409]
        assert sorted(status for status, _ in outcomes) == expected_statuses
        winning_status = 201 if original is None else 200
        winner_index = next(index for index, (status, _) in enumerate(outcomes)
                            if status == winning_status)
        winner = outcomes[winner_index][1]
        if original is None:
            assert outcomes[0][1] == outcomes[1][1]
            assert winner["revision"] == 1
            expected_history = [winner]
        else:
            assert next(body for status, body in outcomes if status == 409) == {
                "detail": {"code": "revision_conflict"}
            }
            assert winner["revision"] == 2 and winner["id"] == original["id"]
            assert winner["reason"] == commands[winner_index]["reason"]
            expected_history = [original, winner]
        assert winner["station_id"] == station_id and winner["actor_id"] == account["id"]
        record_path = path + f"/{winner['id']}"

        # A third client verifies persisted effects independently of either writer.
        with TestClient(create_app(database_url, now=clock)) as witness:
            witness.headers.update(officer.headers)
            listed = witness.get(path)
            assert listed.status_code == 200 and listed.json()["items"] == [winner]
            current = witness.get(record_path)
            assert current.status_code == 200 and current.json() == winner
            history = witness.get(record_path + "/history")
            assert history.status_code == 200 and history.json()["items"] == expected_history
            retry = witness.request(method, target, json=commands[winner_index])
            assert retry.status_code == 200 and retry.json() == winner
            retained_history = witness.get(record_path + "/history")
            assert retained_history.status_code == 200
            assert retained_history.json()["items"] == expected_history
            availability = witness.get(base + "/allocations")
            assert availability.status_code == 200
            balance = availability.json()["availability"][0]
            assert balance["ordinary_received_quantity"] == 6
            assert balance["replacement_quantity"] == balance["tendered_quantity"] == 0
            if resource == "snapshot":
                remaining, issued = (
                    (2, 4) if original is not None and winner_index == 1 else (3, 3)
                )
                assert winner["ordinary_allocated_quantity"] == 6
                assert winner["ordinary_remaining_quantity"] == remaining
                assert winner["ordinary_issued_quantity"] == issued
                assert balance["allocated_quantity"] == 6 and balance["available_quantity"] == 0
                assert balance["ranges"] == []
                assert listed.json()["latest"] == winner
                assert listed.json()["current_ordinary_issued_quantity"] == issued
            else:
                quantity, net, first = (
                    (2, 4, "000005") if original is not None and winner_index == 1
                    else (1, 5, "000006")
                )
                assert winner["quantity"] == quantity
                assert winner["kind"] == "unissued_counter_to_pro"
                assert balance["allocated_quantity"] == net
                assert balance["available_quantity"] == quantity
                assert [
                    (row["serial_from"], row["serial_to"], row["quantity"])
                    for row in balance["ranges"]
                ] == [(first, "000006", quantity)]
                snapshot_path = base + f"/stock-snapshots/{snapshot_original['id']}"
                snapshot = witness.get(snapshot_path)
                assert snapshot.status_code == 200 and snapshot.json() == snapshot_original
                snapshot_history = witness.get(snapshot_path + "/history")
                assert snapshot_history.status_code == 200
                assert snapshot_history.json()["items"] == [snapshot_original]
