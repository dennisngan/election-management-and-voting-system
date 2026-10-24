"""Reserve-only receipt chronology preserves consumed counts and frozen statements."""

from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import TurnoutClock, submit_period, turnout_scope, turnout_staff


def test_reserve_receipt_times_cannot_remove_consumed_replacement_or_tendered_papers(
    admin: TestClient, database_url: str,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        ordinary = officer.post(base + "/stock", json=stock_payload(
            ordinary_quantity=10, replacement_quantity=0, tendered_quantity=0,
            ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": "000010"}],
        ))
        assert ordinary.status_code == 201
        ordinary = ordinary.json()
        reserve_commands = [
            stock_payload(
                event_at="2026-11-15T09:10:11.223344+08:00",
                ordinary_quantity=0, replacement_quantity=3, tendered_quantity=0,
                ranges=[{
                    "pool": "replacement", "serial_from": "000011", "serial_to": "000013",
                }],
            ),
            stock_payload(
                event_at="2026-11-15T09:20:22.334455+08:00",
                ordinary_quantity=0, replacement_quantity=0, tendered_quantity=2,
                ranges=[{
                    "pool": "tendered", "serial_from": "000014", "serial_to": "000015",
                }],
            ),
        ]
        reserves = []
        for command in reserve_commands:
            response = officer.post(base + "/stock", json=command)
            assert response.status_code == 201
            reserves.append(response.json())
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = options.json()["counters"][0]["id"]
        allocation = officer.post(base + "/allocations", json={
            "request_id": str(uuid4()), "counter_id": counter_id, "series": "普通系列 A",
            "serial_from": "000001", "serial_to": "000010",
            "event_at": "2026-11-15T09:00:00+08:00",
        })
        assert allocation.status_code == 201
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{"counter_id": counter_id, "ranges": [{
                "series": "普通系列 A", "serial_from": "000006", "serial_to": "000010",
            }]}],
        })
        assert observed.status_code == 201
        snapshot = observed.json()
        submitted = submit_period(
            officer, scope["path"], 1, supplied_hourly=5, supplied_cumulative=5,
            source_context="Supplied register figure stays five during reserve receipt checks.",
            event_at="2026-11-15T09:30:00+08:00",
        )
        assert submitted["supplied_cumulative"] == 5
        path = base + "/special-papers"
        created = officer.post(path, json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:45:17.123456+08:00",
            "stock_snapshot_id": snapshot["id"], "stock_snapshot_revision": 1,
            "series": [{
                "series": "普通系列 A", "replacement_issued_quantity": 2,
                "spoilt_original_quantity": 2, "tendered_issued_quantity": 1,
                "retrieved_refused_quantity": 1, "retrieved_found_quantity": 1,
                "retrieved_held_quantity": 1,
            }],
        })
        assert created.status_code == 201
        saved = created.json()
        assert saved["ordinary_issued_quantity"] == 5
        assert saved["replacement_issued_quantity"] == 2
        assert saved["tendered_issued_quantity"] == 1
        assert saved["receipt_basis"] == [
            {"receipt_id": row["id"], "revision": 1} for row in [ordinary, *reserves]
        ]
        special_path = path + f"/{saved['id']}"
        snapshot_path = base + f"/stock-snapshots/{snapshot['id']}"
        receipt_paths = [base + f"/stock/{row['id']}" for row in [ordinary, *reserves]]
        read_paths = [
            *[target for receipt_path in receipt_paths
              for target in (receipt_path, receipt_path + "/history")],
            path, special_path, special_path + "/history",
            base + "/stock-snapshots", snapshot_path, snapshot_path + "/history",
            base + "/turnout", base + "/turnout/1/history",
        ]

        def readback() -> dict:
            result = {}
            for target in read_paths:
                response = officer.get(target)
                assert response.status_code == 200, target
                result[target] = response.json()
            return result

        before = readback()
        assert before[path]["latest_basis_current"] is True
        for command, receipt in zip(reserve_commands, reserves, strict=True):
            denied = officer.put(base + f"/stock/{receipt['id']}", json={
                **command, "request_id": str(uuid4()), "revision": 1,
                "reason": "Proposed receipt time is later than the recorded reserve consumption.",
                "event_at": "2026-11-15T10:00:33.445566+08:00",
            })
            assert denied.status_code == 409
            assert denied.json()["detail"]["code"] == "special_paper_stock_conflict"
            assert readback() == before

        replacement_path = receipt_paths[1]
        reason = "Explain the reserve receipt without changing its stock or original time."
        allowed = officer.put(replacement_path, json={
            **reserve_commands[0], "request_id": str(uuid4()), "revision": 1, "reason": reason,
        })
        assert allowed.status_code == 200
        amended = allowed.json()
        assert amended["revision"] == 2 and amended["reason"] == reason
        assert amended["event_at"] == "2026-11-15T01:10:11.223344Z"
        assert (amended["ordinary_quantity"], amended["replacement_quantity"],
                amended["tendered_quantity"], amended["total_quantity"]) == (0, 3, 0, 3)
        assert amended["ranges"] == [{
            "pool": "replacement", "serial_from": "000011", "serial_to": "000013", "quantity": 3,
        }]
        expected = deepcopy(before)
        expected[replacement_path] = amended
        expected[replacement_path + "/history"]["items"] = [reserves[0], amended]
        expected[path]["latest_basis_current"] = False
        assert readback() == expected
        assert officer.get(replacement_path, params={"revision": 1}).json() == reserves[0]
        report = officer.get(path + "/statement", params={
            "snapshot_id": saved["id"], "revision": 1, "locale": "en",
        })
        assert report.status_code == 200
        selected = report.json()
        assert selected["items"] == [saved]
        assert selected["revision_state"] == "current"
        frozen = selected["items"][0]
        assert frozen["receipt_basis"] == saved["receipt_basis"]
        assert frozen["received_ranges"] == saved["received_ranges"]
        assert frozen["stock_snapshot_id"] == snapshot["id"]
        assert frozen["stock_snapshot_revision"] == 1
        assert frozen["stock_snapshot_event_at"] == "2026-11-15T01:30:17.123456Z"
        assert frozen["event_at"] == "2026-11-15T01:45:17.123456Z"
        assert readback() == expected
