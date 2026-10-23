"""Backdated stock changes preserve later observed ordinary issuance."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.stock_support import stock_payload
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


def test_backdated_return_cannot_release_papers_later_observed_as_issued(
    admin: TestClient, database_url: str,
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
        snapshot_path = base + "/stock-snapshots"
        observed = officer.post(
            snapshot_path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:00+08:00",
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
        saved = observed.json()
        assert saved["complete"] is True and saved["ordinary_issued_quantity"] == 3
        assert saved["ordinary_allocated_quantity"] == 6
        assert saved["ordinary_remaining_quantity"] == 3
        assert saved["return_basis"] == []
        target = snapshot_path + f"/{saved['id']}"
        return_path = base + "/stock-returns"
        report_path = base + "/allocations/statement"
        returns_before = officer.get(return_path)
        p14_before = officer.get(report_path, params={"locale": "en"})
        selected_before = officer.get(target, params={"revision": 1})
        history_before = officer.get(target + "/history")
        collection_before = officer.get(snapshot_path)
        assert all(
            response.status_code == 200
            for response in (
                returns_before, p14_before, selected_before, history_before, collection_before,
            )
        )
        assert returns_before.json()["items"] == []
        assert p14_before.json()["availability"][0]["allocated_quantity"] == 6
        assert p14_before.json()["availability"][0]["available_quantity"] == 2
        assert selected_before.json() == saved
        assert history_before.json()["items"] == [saved]
        assert collection_before.json()["latest_basis_current"] is True
        assert collection_before.json()["current_ordinary_issued_quantity"] == 3

        rejected = officer.post(
            return_path,
            json={
                "request_id": str(uuid4()),
                "counter_id": counter_id,
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000003",
                "event_at": "2026-11-15T09:30:00+08:00",
            },
        )
        returns_after = officer.get(return_path)
        p14_after = officer.get(report_path, params={"locale": "en"})
        selected_after = officer.get(target, params={"revision": 1})
        history_after = officer.get(target + "/history")
        collection_after = officer.get(snapshot_path)
        assert all(
            response.status_code == 200
            for response in (
                returns_after, p14_after, selected_after, history_after, collection_after,
            )
        )
        assert rejected.status_code == 409, {
            "status": rejected.status_code,
            "return_count": len(returns_after.json()["items"]),
            "p14_allocated_quantity": p14_after.json()["availability"][0]["allocated_quantity"],
            "p14_available_quantity": p14_after.json()["availability"][0]["available_quantity"],
            "latest_basis_current": collection_after.json()["latest_basis_current"],
            "current_ordinary_issued_quantity": collection_after.json()[
                "current_ordinary_issued_quantity"
            ],
        }
        assert returns_after.json() == returns_before.json()
        assert p14_after.json() == p14_before.json()
        assert selected_after.json() == saved
        assert history_after.json() == history_before.json()
        assert collection_after.json() == collection_before.json()
        assert collection_after.json()["current_ordinary_issued_quantity"] == 3


def test_earlier_snapshot_correction_cannot_issue_papers_retained_by_a_later_snapshot(
    admin: TestClient, database_url: str,
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
        path = base + "/stock-snapshots"
        counter_balance = [
            {
                "counter_id": counter_id,
                "ranges": [
                    {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                ],
            }
        ]
        original = []
        for event_at in ("2026-11-15T09:30:00+08:00", "2026-11-15T10:00:00+08:00"):
            response = officer.post(
                path,
                json={
                    "request_id": str(uuid4()),
                    "event_at": event_at,
                    "counters": counter_balance,
                },
            )
            assert response.status_code == 201
            saved = response.json()
            assert saved["revision"] == 1 and saved["complete"] is True
            assert saved["ordinary_allocated_quantity"] == 6
            assert saved["ordinary_remaining_quantity"] == 3
            assert saved["ordinary_issued_quantity"] == 3
            original.append(saved)
        targets = [path + f"/{saved['id']}" for saved in original]
        collection_before = officer.get(path)
        report_path = base + "/allocations/statement"
        p14_before = officer.get(report_path, params={"locale": "en"})
        assert collection_before.status_code == 200 and p14_before.status_code == 200
        assert collection_before.json()["latest"] == original[1]
        assert collection_before.json()["latest_basis_current"] is True
        assert collection_before.json()["current_ordinary_issued_quantity"] == 3
        for target, saved in zip(targets, original, strict=True):
            head = officer.get(target)
            history = officer.get(target + "/history")
            assert head.status_code == 200 and head.json() == saved
            assert history.status_code == 200 and history.json()["items"] == [saved]

        rejected = officer.put(
            targets[0],
            json={
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "覆核早段結餘，只餘第六號，不能推翻稍後仍持有第四及第五號的觀察",
                "event_at": "2026-11-15T09:30:00+08:00",
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
        heads_after = [officer.get(target) for target in targets]
        histories_after = [officer.get(target + "/history") for target in targets]
        collection_after = officer.get(path)
        p14_after = officer.get(report_path, params={"locale": "en"})
        assert all(
            response.status_code == 200
            for response in [*heads_after, *histories_after, collection_after, p14_after]
        )
        assert rejected.status_code == 409, {
            "status": rejected.status_code,
            "earlier_revision": heads_after[0].json()["revision"],
            "earlier_issued": heads_after[0].json()["ordinary_issued_quantity"],
            "later_issued": heads_after[1].json()["ordinary_issued_quantity"],
            "later_remaining": heads_after[1].json()["ordinary_remaining_quantity"],
        }
        for head, history, saved in zip(heads_after, histories_after, original, strict=True):
            assert head.json() == saved
            assert history.json()["items"] == [saved]
        assert collection_after.json() == collection_before.json()
        assert collection_after.json()["latest_basis_current"] is True
        assert collection_after.json()["current_ordinary_issued_quantity"] == 3
        assert p14_after.json() == p14_before.json()


def test_returned_allocation_cannot_mask_released_issued_stock_in_a_later_lineage(
    admin: TestClient, database_url: str,
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
        first_command = {
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": "2026-11-15T09:00:00+08:00",
        }
        allocated = officer.post(base + "/allocations", json=first_command)
        assert allocated.status_code == 201
        first = allocated.json()
        returned = officer.post(
            base + "/stock-returns",
            json={
                **first_command,
                "request_id": str(uuid4()),
                "serial_from": "000004",
                "event_at": "2026-11-15T09:15:00+08:00",
            },
        )
        assert returned.status_code == 201
        original_return = returned.json()
        assert original_return["quantity"] == 3
        assert [row["allocation_id"] for row in original_return["allocation_basis"]] == [
            first["id"]
        ]
        second_command = {
            **first_command,
            "request_id": str(uuid4()),
            "serial_from": "000004",
            "event_at": "2026-11-15T09:20:00+08:00",
        }
        reallocated = officer.post(base + "/allocations", json=second_command)
        assert reallocated.status_code == 201
        second = reallocated.json()
        assert first["id"] != second["id"] and second["quantity"] == 3
        observed = officer.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:00+08:00",
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
        assert observed.status_code == 201
        snapshot = observed.json()
        assert snapshot["complete"] is True
        assert snapshot["ordinary_allocated_quantity"] == 9
        assert snapshot["ordinary_returned_quantity"] == 3
        assert snapshot["ordinary_net_allocated_quantity"] == 6
        assert snapshot["ordinary_remaining_quantity"] == 1
        assert snapshot["ordinary_issued_quantity"] == 5
        second_target = base + f"/allocations/{second['id']}"
        resources = {
            "allocations": base + "/allocations",
            "first_allocation": base + f"/allocations/{first['id']}",
            "first_history": base + f"/allocations/{first['id']}/history",
            "second_allocation": second_target,
            "second_history": second_target + "/history",
            "return": base + f"/stock-returns/{original_return['id']}",
            "return_history": base + f"/stock-returns/{original_return['id']}/history",
            "returns": base + "/stock-returns",
            "snapshot": base + f"/stock-snapshots/{snapshot['id']}",
            "snapshot_history": base + f"/stock-snapshots/{snapshot['id']}/history",
            "snapshots": base + "/stock-snapshots",
            "p14": base + "/allocations/statement?locale=en",
        }

        def read_public_state() -> dict:
            state = {}
            for key, path in resources.items():
                response = officer.get(path)
                assert response.status_code == 200
                state[key] = response.json()
            return state

        before = read_public_state()
        assert before["first_allocation"] == first and before["first_history"]["items"] == [first]
        assert before["second_allocation"] == second
        assert before["second_history"]["items"] == [second]
        assert before["return"] == original_return
        assert before["return_history"]["items"] == [original_return]
        assert before["returns"]["items"] == [original_return]
        assert before["snapshot"] == snapshot and before["snapshot_history"]["items"] == [snapshot]
        assert before["snapshots"]["latest_basis_current"] is True
        assert before["snapshots"]["current_ordinary_issued_quantity"] == 5
        assert before["p14"]["availability"][0]["allocated_quantity"] == 6
        assert before["p14"]["availability"][0]["available_quantity"] == 2

        rejected = officer.put(
            second_target,
            json={
                **second_command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "覆核第二次派發，只保留第四號，不能釋放已觀察為發出的第五號",
                "serial_to": "000004",
            },
        )
        after = read_public_state()
        assert rejected.status_code == 409, {
            "status": rejected.status_code,
            "second_revision": after["second_allocation"]["revision"],
            "second_quantity": after["second_allocation"]["quantity"],
            "p14_allocated_quantity": after["p14"]["availability"][0]["allocated_quantity"],
            "p14_available_quantity": after["p14"]["availability"][0]["available_quantity"],
            "latest_basis_current": after["snapshots"]["latest_basis_current"],
            "current_ordinary_issued_quantity": after["snapshots"][
                "current_ordinary_issued_quantity"
            ],
        }
        assert after == before
        assert after["snapshots"]["latest_basis_current"] is True
        assert after["snapshots"]["current_ordinary_issued_quantity"] == 5
