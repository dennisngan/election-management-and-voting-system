"""Shared special-paper arrangements through existing public API journeys."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.stock_support import stock_payload
from tests.turnout_support import TurnoutClock, submit_period, turnout_scope, turnout_staff


@contextmanager
def special_paper_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        received = officer.post(
            base + "/stock",
            json=stock_payload(
                ordinary_quantity=10,
                replacement_quantity=3,
                tendered_quantity=2,
                ranges=[
                    {"pool": "ordinary", "serial_from": "000001", "serial_to": "000010"},
                    {"pool": "replacement", "serial_from": "000011", "serial_to": "000013"},
                    {"pool": "tendered", "serial_from": "000014", "serial_to": "000015"},
                ],
            ),
        )
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = options.json()["counters"][0]["id"]
        allocated = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000010",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocated.status_code == 201
        observed = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:17.123456+08:00",
                "counters": [{
                    "counter_id": counter_id,
                    "ranges": [{
                        "series": "普通系列 A", "serial_from": "000006", "serial_to": "000010",
                    }],
                }],
            },
        )
        assert observed.status_code == 201
        snapshot = observed.json()
        assert snapshot["complete"] is True
        assert snapshot["ordinary_issued_quantity"] == 5
        assert snapshot["ordinary_remaining_quantity"] == 5
        submitted = submit_period(
            officer,
            scope["path"],
            1,
            supplied_hourly=5,
            supplied_cumulative=5,
            source_context="Synthetic supplied register figure; five ordinary voters.",
            event_at="2026-11-15T09:30:00+08:00",
        )
        assert submitted["status"] == "submitted"
        assert submitted["supplied_hourly"] == submitted["supplied_cumulative"] == 5
        turnout_before = officer.get(scope["path"])
        assert turnout_before.status_code == 200
        entered_series = {
            "series": "普通系列 A",
            "replacement_issued_quantity": 2,
            "spoilt_original_quantity": 2,
            "tendered_issued_quantity": 1,
            "retrieved_refused_quantity": 1,
            "retrieved_found_quantity": 1,
            "retrieved_held_quantity": 1,
        }
        yield {
            "officer": officer,
            "account": account,
            "base": base,
            "path": base + "/special-papers",
            "receipt": received.json(),
            "snapshot": snapshot,
            "turnout": turnout_before.json(),
            "entered_series": entered_series,
            "command": {
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:45:17.123456+08:00",
                "stock_snapshot_id": snapshot["id"],
                "stock_snapshot_revision": 1,
                "series": [entered_series],
            },
            "clock": clock,
        }
