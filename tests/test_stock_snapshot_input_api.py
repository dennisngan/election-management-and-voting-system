"""Malformed snapshot/return input must fail at the public API without changing history."""

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


@pytest.fixture
def saved_stock_records(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
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
        snapshot = officer.post(base + "/stock-snapshots", json=snapshot_command)
        assert snapshot.status_code == 201
        return_command = {
            "request_id": str(uuid4()), "counter_id": counter_id,
            "series": "普通系列 A", "serial_from": "000006", "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        }
        returned = officer.post(base + "/stock-returns", json=return_command)
        assert returned.status_code == 201
        balances = officer.get(base + "/allocations")
        assert balances.status_code == 200
        yield {
            "officer": officer, "base": base, "clock": clock,
            "counter_id": counter_id, "availability": balances.json()["availability"],
            "snapshot": {
                "command": snapshot_command, "saved": snapshot.json(),
                "path": base + "/stock-snapshots",
                "target": base + f"/stock-snapshots/{snapshot.json()['id']}",
            },
            "return": {
                "command": return_command, "saved": returned.json(),
                "path": base + "/stock-returns",
                "target": base + f"/stock-returns/{returned.json()['id']}",
            },
        }


@pytest.mark.parametrize(
    ("resource", "method", "invalid_kind"),
    [
        pytest.param("snapshot", "PUT", "utc-underflow", id="snapshot-correction-utc-underflow"),
        pytest.param("snapshot", "POST", "mysql-year", id="snapshot-create-unsupported-year"),
        pytest.param("return", "POST", "mysql-year", id="return-create-unsupported-year"),
        pytest.param("return", "POST", "utc-underflow", id="return-create-utc-underflow"),
        pytest.param("return", "PUT", "utc-overflow", id="return-correction-utc-overflow"),
        pytest.param("snapshot", "PUT", "unknown-field", id="snapshot-derived-field-forbidden"),
        pytest.param("return", "PUT", "unknown-field", id="return-source-basis-forbidden"),
        pytest.param("snapshot", "POST", "reversed-range", id="snapshot-reversed-range"),
        pytest.param("return", "POST", "reversed-range", id="return-reversed-range"),
    ],
)
def test_malformed_stock_commands_return_validation_error_and_preserve_public_history(
    saved_stock_records: dict,
    database_url: str,
    resource: str,
    method: str,
    invalid_kind: str,
) -> None:
    state = saved_stock_records
    record = state[resource]
    payload = {**record["command"], "request_id": str(uuid4())}
    path = record["path"]
    if method == "PUT":
        path = record["target"]
        payload.update(revision=1, reason="核對原始交收文件後修訂紀錄。")
    elif resource == "snapshot":
        payload.update(
            event_at="2026-11-15T10:30:00+08:00",
            counters=[
                {
                    "counter_id": state["counter_id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000005"}
                    ],
                }
            ],
        )
    else:
        payload.update(serial_from="000005", serial_to="000005")

    if invalid_kind == "utc-underflow":
        payload["event_at"] = "0001-01-01T00:00:00+23:59"
    elif invalid_kind == "utc-overflow":
        payload["event_at"] = "9999-12-31T23:59:59-23:59"
    elif invalid_kind == "mysql-year":
        payload["event_at"] = "0001-01-01T00:00:00Z"
        if resource == "snapshot":
            # An incomplete snapshot with no reported counters is a valid shape;
            # no remaining-range ownership error should mask this invalid year.
            payload["counters"] = []
    elif invalid_kind == "unknown-field":
        if resource == "snapshot":
            payload["ordinary_issued_quantity"] = 999
        else:
            payload["allocation_basis"] = []
    elif invalid_kind == "reversed-range":
        if resource == "snapshot":
            payload["counters"][0]["ranges"][0].update(serial_from="000006", serial_to="000004")
        else:
            payload.update(serial_from="000006", serial_to="000005")
    else:
        raise AssertionError("Unknown malformed-input case")

    # Observe actual HTTP failures rather than allowing an unhandled application
    # exception to replace the public response with a TestClient-side exception.
    with TestClient(
        create_app(database_url, now=state["clock"]), raise_server_exceptions=False
    ) as peer:
        peer.headers.update(state["officer"].headers)
        rejected = peer.request(method, path, json=payload)
        for name in ("snapshot", "return"):
            expected = state[name]
            current = peer.get(expected["target"])
            assert current.status_code == 200 and current.json() == expected["saved"]
            history = peer.get(expected["target"] + "/history")
            assert history.status_code == 200
            assert history.json()["items"] == [expected["saved"]]
        balances = peer.get(state["base"] + "/allocations")
        assert balances.status_code == 200
        assert balances.json()["availability"] == state["availability"]

    assert rejected.status_code == 422, {
        "resource": resource, "method": method, "invalid_kind": invalid_kind,
        "actual_status": rejected.status_code, "actual_body": rejected.text,
    }
    assert rejected.json()["detail"]["code"] == "validation_error"
