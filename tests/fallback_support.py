"""Public turnout and ordinary-stock sources for the approved fallback example."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.stock_support import stock_payload
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    approve_period,
    submit_period,
    turnout_command,
    turnout_scope,
    turnout_staff,
)


@contextmanager
def fallback_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope = turnout_scope(
        admin,
        planned_opening_at="2026-11-15T10:00:00+08:00",
        planned_closing_at="2026-11-15T13:00:00+08:00",
        reporting_interval_minutes=60,
    )
    clock = TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (
            supervisor, supervisor_account,
        ),
    ):
        submitted = submit_period(
            officer, scope["path"], 1,
            supplied_hourly=100, supplied_cumulative=100,
            source_context="Confirmed supplied register total: 100 at 11:00 before fallback.",
            event_at="2026-11-15T11:00:00+08:00",
        )
        assert submitted["supplied_hourly"] == submitted["supplied_cumulative"] == 100
        approved = approve_period(supervisor, scope["path"], 1)
        assert approved["status"] == "approved"
        assert approved["derived_hourly"] == approved["derived_cumulative_end"] == 100
        received = officer.post(base + "/stock", json=stock_payload(
            event_at="2026-11-15T10:00:00+08:00",
            ordinary_quantity=200, replacement_quantity=3, tendered_quantity=2,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000200"},
                {"pool": "replacement", "serial_from": "000201", "serial_to": "000203"},
                {"pool": "tendered", "serial_from": "000204", "serial_to": "000205"},
            ],
        ))
        assert received.status_code == 201
        receipt = received.json()
        assert (receipt["ordinary_quantity"], receipt["replacement_quantity"],
                receipt["tendered_quantity"], receipt["total_quantity"]) == (200, 3, 2, 205)
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = options.json()["counters"][0]["id"]
        allocated = officer.post(base + "/allocations", json={
            "request_id": str(uuid4()), "counter_id": counter_id, "series": "普通系列 A",
            "serial_from": "000001", "serial_to": "000200",
            "event_at": "2026-11-15T10:00:00+08:00",
        })
        assert allocated.status_code == 201
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T11:20:00+08:00",
            "counters": [{"counter_id": counter_id, "ranges": [{
                "series": "普通系列 A", "serial_from": "000111", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        snapshot = observed.json()
        assert snapshot["complete"] is True
        assert snapshot["ordinary_issued_quantity"] == 110
        assert snapshot["ordinary_remaining_quantity"] == 90
        assert snapshot["event_at"] == "2026-11-15T03:20:00Z"
        assert len(snapshot["counters"]) == 1
        assert snapshot["counters"][0]["ordinary_issued_quantity"] == 110
        assert snapshot["counters"][0]["ordinary_remaining_quantity"] == 90
        assert snapshot["counters"][0]["ranges"] == [{
            "series": "普通系列 A", "serial_from": "000111", "serial_to": "000200",
            "quantity": 90,
        }]
        turnout = officer.get(scope["path"])
        assert turnout.status_code == 200
        assert turnout.json()["approved_prefix"]["cumulative_end"] == 100
        yield {
            "scope": scope, "clock": clock, "base": base, "path": base + "/fallback",
            "officer": officer, "account": account, "supervisor": supervisor,
            "supervisor_account": supervisor_account, "counter_id": counter_id,
            "receipt": receipt, "snapshot": snapshot, "turnout": turnout.json(),
            "command": {
                "request_id": str(uuid4()), "expected_schedule_revision": 1,
                "kind": "activation", "event_at": "2026-11-15T11:20:00+08:00",
                "cumulative_quantity": 110,
                "stock_snapshot_id": snapshot["id"], "stock_snapshot_revision": 1,
                "source_context": (
                    "Confirmed register total: 110 when EPR fallback starts at 11:20."
                ),
            },
        }


def confirm_fallback_activation(setup: dict) -> dict:
    """Confirm the supplied activation through the assigned staff's public API."""
    created = setup["officer"].post(setup["path"], json=setup["command"])
    assert created.status_code == 201
    activation = created.json()
    assert activation["revision"] == 1 and activation["status"] == "draft"
    assert activation["cumulative_quantity"] == 110
    assert activation["stock_snapshot"] == setup["snapshot"]
    target = setup["path"] + f"/{activation['id']}"
    submitted = setup["officer"].post(target + "/submit", json=turnout_command(1))
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    confirmed = setup["supervisor"].post(
        target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
    )
    assert confirmed.status_code == 200
    approved = confirmed.json()
    assert approved["revision"] == 1 and approved["status"] == "approved"
    assert approved["approved_by"] == setup["supervisor_account"]["id"]
    assert approved["stock_snapshot"] == setup["snapshot"]
    return approved


def approved_mixed_period(setup: dict) -> dict:
    """Approve the literal 115 turnout example using the public ordinary-stock basis."""
    officer, base = setup["officer"], setup["base"]
    activation = confirm_fallback_activation(setup)
    observed = officer.post(base + "/stock-snapshots", json={
        "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
        "counters": [{"counter_id": setup["counter_id"], "ranges": [{
            "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
        }]}],
    })
    assert observed.status_code == 201
    endpoint = observed.json()
    assert endpoint["complete"] is True
    assert endpoint["ordinary_issued_quantity"] == 115
    assert endpoint["ordinary_remaining_quantity"] == 85
    assert endpoint["event_at"] == "2026-11-15T04:00:00Z"
    special = officer.post(base + "/special-papers", json={
        "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
        "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
        "series": [{
            "series": "普通系列 A", "replacement_issued_quantity": 3,
            "spoilt_original_quantity": 3, "tendered_issued_quantity": 2,
            "retrieved_refused_quantity": 0, "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }],
    })
    assert special.status_code == 201
    assert special.json()["replacement_issued_quantity"] == 3
    assert special.json()["spoilt_original_quantity"] == 3
    assert special.json()["tendered_issued_quantity"] == 2
    assert special.json()["ordinary_issued_quantity"] == 115
    unchanged = officer.get(base + f"/stock-snapshots/{endpoint['id']}")
    assert unchanged.status_code == 200 and unchanged.json() == endpoint
    path = setup["scope"]["path"]
    submitted = submit_period(
        officer, path, 2,
        mode="fallback", fallback_activation_id=activation["id"],
        fallback_activation_revision=1, stock_snapshot_id=endpoint["id"],
        stock_snapshot_revision=1, event_at="2026-11-15T12:00:00+08:00",
        supplied_hourly=None, supplied_cumulative=None,
        source_context="Normal 11:00-11:20 then ordinary-stock fallback through noon.",
    )
    assert submitted["provenance"] == "mixed"
    approved = approve_period(setup["supervisor"], path, 2)
    assert approved["status"] == "approved" and approved["revision"] == 1
    assert approved["derived_cumulative_start"] == 100
    assert approved["derived_hourly"] == 15
    assert approved["derived_cumulative_end"] == 115
    assert approved["source_basis"]["ordinary_issued_since_activation_quantity"] == 5
    assert approved["source_basis"]["stock_derived_cumulative_quantity"] == 115
    current = officer.get(path)
    assert current.status_code == 200
    assert current.json()["approved_prefix"]["periods"] == 2
    assert current.json()["approved_prefix"]["cumulative_end"] == 115
    assert current.json()["items"][1]["record"] == approved
    return {"activation": activation, "endpoint": endpoint, "approved": approved}
