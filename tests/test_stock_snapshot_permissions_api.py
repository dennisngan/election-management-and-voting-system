"""P(12) snapshot and unissued-return permissions use the real public MySQL API."""

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
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize(
    ("role", "assigned", "ready", "read_error", "write_error"),
    [
        pytest.param(
            "counting_officer", True, True, None, "operational_role_required",
            id="assigned-counting-officer",
        ),
        pytest.param(
            "supervisor", True, True, None, "operational_role_required",
            id="assigned-supervisor",
        ),
        pytest.param(
            "polling_officer", False, True, "station_access_denied", "station_access_denied",
            id="other-station-polling-officer",
        ),
        pytest.param(
            "administrator", False, True, "operational_role_required", "operational_role_required",
            id="administrator",
        ),
        pytest.param(
            "polling_officer", True, False, "password_change_required", "password_change_required",
            id="first-password-change-required",
        ),
    ],
)
def test_only_ready_assigned_polling_officers_can_write_or_replay_snapshots_and_returns(
    admin: TestClient,
    database_url: str,
    role: str,
    assigned: bool,
    ready: bool,
    read_error: str | None,
    write_error: str,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(
            base + "/stock",
            json=stock_payload(
                ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": "000006"}],
                ordinary_quantity=6,
                replacement_quantity=0,
                tendered_quantity=0,
            ),
        )
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

        snapshots_path = base + "/stock-snapshots"
        snapshot_command = {
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
        saved = officer.post(snapshots_path, json=snapshot_command)
        assert saved.status_code == 201
        snapshot_original = saved.json()
        snapshot_target = snapshots_path + f"/{snapshot_original['id']}"
        snapshot_correction = {
            **snapshot_command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對 P(12) 紙本結餘，保留原始觀察時間及範圍。",
        }
        corrected = officer.put(snapshot_target, json=snapshot_correction)
        assert corrected.status_code == 200
        snapshot_current = corrected.json()
        assert snapshot_current["revision"] == 2
        assert snapshot_current["ordinary_allocated_quantity"] == 6
        assert snapshot_current["ordinary_remaining_quantity"] == 3
        assert snapshot_current["ordinary_issued_quantity"] == 3

        returns_path = base + "/stock-returns"
        return_command = {
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        saved_return = officer.post(returns_path, json=return_command)
        assert saved_return.status_code == 201
        return_original = saved_return.json()
        return_target = returns_path + f"/{return_original['id']}"
        return_correction = {
            **return_command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對櫃台向 PRO 交回的未發出選票交收單。",
        }
        corrected_return = officer.put(return_target, json=return_correction)
        assert corrected_return.status_code == 200
        return_current = corrected_return.json()
        assert return_current["revision"] == 2 and return_current["quantity"] == 1
        assert return_current["kind"] == "unissued_counter_to_pro"

        # These exact UUIDs are successful cached POST and PUT commands, including
        # original creation commands whose heads have since advanced to revision 2.
        cached_commands = (
            ("POST", snapshots_path, snapshot_command, snapshot_original),
            ("PUT", snapshot_target, snapshot_correction, snapshot_current),
            ("POST", returns_path, return_command, return_original),
            ("PUT", return_target, return_correction, return_current),
        )
        for method, path, command, expected in cached_commands:
            replay = officer.request(method, path, json=command)
            assert replay.status_code == 200 and replay.json() == expected

        readbacks = (
            (snapshot_target, snapshot_current),
            (snapshot_target + "?revision=1", snapshot_original),
            (snapshot_target + "/history", {"items": [snapshot_original, snapshot_current]}),
            (return_target, return_current),
            (return_target + "?revision=1", return_original),
            (return_target + "/history", {"items": [return_original, return_current]}),
        )
        allocated = officer.get(base + "/allocations")
        assert allocated.status_code == 200
        balances_before = allocated.json()["availability"]
        assert balances_before[0]["ordinary_received_quantity"] == 6
        assert balances_before[0]["allocated_quantity"] == 5
        assert balances_before[0]["available_quantity"] == 1

        station_ids = [] if role == "administrator" else [
            station_id if assigned else scope["stations"][1]["id"]
        ]
        with turnout_staff(
            admin, database_url, clock, station_ids, role, ready=ready
        ) as (actor, _):
            for path, expected in readbacks:
                response = actor.get(path)
                if read_error is None:
                    assert response.status_code == 200 and response.json() == expected
                else:
                    assert response.status_code == 403
                    assert response.json() == {"detail": {"code": read_error}}

            new_snapshot = {
                **snapshot_command,
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:30:00+08:00",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000004",
                                "serial_to": "000005",
                            }
                        ],
                    }
                ],
            }
            fresh_commands = (
                ("POST", snapshots_path, new_snapshot),
                (
                    "PUT", snapshot_target,
                    {**snapshot_correction, "request_id": str(uuid4()), "revision": 2},
                ),
                (
                    "POST", returns_path,
                    {
                        **return_command, "request_id": str(uuid4()),
                        "serial_from": "000005", "serial_to": "000005",
                        "event_at": "2026-11-15T10:15:00+08:00",
                    },
                ),
                (
                    "PUT", return_target,
                    {**return_correction, "request_id": str(uuid4()), "revision": 2},
                ),
            )
            for method, path, command in fresh_commands:
                denied = actor.request(method, path, json=command)
                assert denied.status_code == 403
                assert denied.json() == {"detail": {"code": write_error}}
            for method, path, command, _ in cached_commands:
                denied = actor.request(method, path, json=command)
                assert denied.status_code == 403
                assert denied.json() == {"detail": {"code": write_error}}

        # A separate public API client checks the immutable history and current
        # balances after every attempted new command, correction, and UUID replay.
        with TestClient(create_app(database_url, now=clock)) as witness:
            witness.headers.update(officer.headers)
            for path, expected in readbacks:
                response = witness.get(path)
                assert response.status_code == 200 and response.json() == expected
            balance = witness.get(base + "/allocations")
            assert balance.status_code == 200
            assert balance.json()["availability"] == balances_before
