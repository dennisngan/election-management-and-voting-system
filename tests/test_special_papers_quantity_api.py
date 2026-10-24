"""Legal per-series quantities remain exact in aggregate saved accounting and CSV."""

import csv
from io import StringIO
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff

FIRST_TOTALS = {
    "received_quantity": 19999999999999999980,
    "ordinary_issued_quantity": 19999999999999999720,
    "replacement_issued_quantity": 60,
    "spoilt_original_quantity": 60,
    "tendered_issued_quantity": 40,
    "retrieved_refused_quantity": 20,
    "retrieved_found_quantity": 20,
    "retrieved_held_quantity": 20,
    "retrieved_unused_quantity": 60,
    "ordinary_unissued_quantity": 100,
    "replacement_unissued_quantity": 20,
    "tendered_unissued_quantity": 40,
    "never_issued_quantity": 160,
    "estimated_box_papers_quantity": 19999999999999999660,
}
FIRST_SERIES_TOTALS = {
    "received_quantity": 999999999999999999,
    "ordinary_issued_quantity": 999999999999999986,
    "replacement_issued_quantity": 3,
    "spoilt_original_quantity": 3,
    "tendered_issued_quantity": 2,
    "retrieved_refused_quantity": 1,
    "retrieved_found_quantity": 1,
    "retrieved_held_quantity": 1,
    "retrieved_unused_quantity": 3,
    "ordinary_unissued_quantity": 5,
    "replacement_unissued_quantity": 1,
    "tendered_unissued_quantity": 2,
    "never_issued_quantity": 8,
    "estimated_box_papers_quantity": 999999999999999983,
}
SECOND_TOTALS = {
    **FIRST_TOTALS,
    "retrieved_found_quantity": 0,
    "retrieved_unused_quantity": 40,
    "estimated_box_papers_quantity": 19999999999999999680,
}
SECOND_SERIES_TOTALS = {
    **FIRST_SERIES_TOTALS,
    "retrieved_found_quantity": 0,
    "retrieved_unused_quantity": 2,
    "estimated_box_papers_quantity": 999999999999999984,
}
CSV_LABELS = {
    "received_quantity": "Total papers received",
    "ordinary_issued_quantity": "Stock-derived ordinary issuance",
    "replacement_issued_quantity": "Replacement papers issued",
    "spoilt_original_quantity": (
        "Surrendered/cancelled spoilt originals "
        "(paired with replacements; not deducted twice)"
    ),
    "tendered_issued_quantity": "Tendered papers issued",
    "retrieved_refused_quantity": "Retrieved unused papers refused by electors",
    "retrieved_found_quantity": "Retrieved unused papers found within station",
    "retrieved_held_quantity": "Retrieved unused papers held pending elector's return",
    "retrieved_unused_quantity": "Retrieved-unused papers total",
    "ordinary_unissued_quantity": "Never-issued ordinary papers remaining",
    "replacement_unissued_quantity": "Unused replacement reserve",
    "tendered_unissued_quantity": "Unused tendered reserve",
    "never_issued_quantity": "Never-issued stock total",
    "estimated_box_papers_quantity": "Estimated box papers from stock",
}


def assert_exact_quantities(actual: dict, expected: dict[str, int]) -> None:
    for field, quantity in expected.items():
        assert type(actual[field]) is int, (field, actual[field])
        assert actual[field] == quantity, (field, actual[field], quantity)


def test_large_special_paper_totals_preserve_exact_history_replay_and_historical_csv(
    admin: TestClient, database_url: str,
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/special-papers"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        options = officer.get(base + "/allocations")
        assert options.status_code == 200 and options.json()["items"] == []
        counter_id = options.json()["counters"][0]["id"]
        turnout_before = officer.get(scope["path"])
        assert turnout_before.status_code == 200
        receipts = []
        remaining = []
        entered = []
        for number in range(1, 21):
            series = f"Special quantity series {number:02d}"
            receipt = officer.post(base + "/stock", json=stock_payload(
                series=series,
                ordinary_quantity=999999999999999991,
                replacement_quantity=4,
                tendered_quantity=4,
                ranges=[
                    {"pool": "ordinary", "serial_from": "000000000000000001",
                     "serial_to": "999999999999999991"},
                    {"pool": "replacement", "serial_from": "999999999999999992",
                     "serial_to": "999999999999999995"},
                    {"pool": "tendered", "serial_from": "999999999999999996",
                     "serial_to": "999999999999999999"},
                ],
            ))
            assert receipt.status_code == 201
            receipts.append(receipt.json())
            assert receipt.json()["total_quantity"] == 999999999999999999
            allocated = officer.post(base + "/allocations", json={
                "request_id": str(uuid4()), "counter_id": counter_id, "series": series,
                "serial_from": "000000000000000001", "serial_to": "999999999999999991",
                "event_at": "2026-11-15T09:00:00+08:00",
            })
            assert allocated.status_code == 201
            assert allocated.json()["quantity"] == 999999999999999991
            remaining.append({
                "series": series, "serial_from": "999999999999999987",
                "serial_to": "999999999999999991",
            })
            entered.append({
                "series": series,
                "replacement_issued_quantity": 3, "spoilt_original_quantity": 3,
                "tendered_issued_quantity": 2,
                "retrieved_refused_quantity": 1, "retrieved_found_quantity": 1,
                "retrieved_held_quantity": 1,
            })
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{"counter_id": counter_id, "ranges": remaining}],
        })
        assert observed.status_code == 201
        ordinary = observed.json()
        assert ordinary["complete"] is True
        assert ordinary["ordinary_issued_quantity"] == 19999999999999999720
        assert type(ordinary["ordinary_issued_quantity"]) is int
        assert ordinary["ordinary_remaining_quantity"] == 100
        command = {
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:45:17.123456+08:00",
            "stock_snapshot_id": ordinary["id"], "stock_snapshot_revision": 1,
            "series": entered,
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert_exact_quantities(original, FIRST_TOTALS)
        assert original["revision"] == 1 and original["actor_id"] == account["id"]
        assert original["event_at"] == "2026-11-15T01:45:17.123456Z"
        assert original["stock_snapshot_id"] == ordinary["id"]
        assert original["stock_snapshot_revision"] == 1
        assert original["stock_snapshot_event_at"] == "2026-11-15T01:30:17.123456Z"
        assert original["receipt_basis"] == [
            {"receipt_id": row["id"], "revision": 1} for row in receipts
        ]
        assert len(original["received_ranges"]) == 60
        assert [row["series"] for row in original["series"]] == [
            row["series"] for row in entered
        ]
        for row in original["series"]:
            assert_exact_quantities(row, FIRST_SERIES_TOTALS)
        assert type(original["stock_snapshot_data"]["ordinary_issued_quantity"]) is int
        assert original["stock_snapshot_data"]["ordinary_issued_quantity"] == 19999999999999999720
        target = path + f"/{original['id']}"
        with TestClient(create_app(database_url, now=clock)) as peer:
            peer.headers.update(officer.headers)
            reopened = peer.get(target)
            assert reopened.status_code == 200 and reopened.json() == original
            assert_exact_quantities(reopened.json(), FIRST_TOTALS)
            history = peer.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [original]
            assert_exact_quantities(history.json()["items"][0], FIRST_TOTALS)
            collection = peer.get(path)
            assert collection.status_code == 200
            assert collection.json()["items"] == [original]
            assert collection.json()["latest"] == original
            assert collection.json()["latest_basis_current"] is True
            assert_exact_quantities(collection.json()["latest"], FIRST_TOTALS)
        reason = "核對二十個系列的尋回選票數量。\n保留原始觀察時間及精確來源版本。"
        correction = {
            **command, "request_id": str(uuid4()), "revision": 1, "reason": reason,
            "series": [{**row, "retrieved_found_quantity": 0} for row in entered],
        }
        corrected = officer.put(target, json=correction)
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["id"] == original["id"] and second["revision"] == 2
        assert second["reason"] == reason and second["event_at"] == original["event_at"]
        assert second["receipt_basis"] == original["receipt_basis"]
        assert second["received_ranges"] == original["received_ranges"]
        assert second["stock_snapshot_data"] == original["stock_snapshot_data"]
        assert_exact_quantities(second, SECOND_TOTALS)
        for row in second["series"]:
            assert_exact_quantities(row, SECOND_SERIES_TOTALS)
        replay = officer.post(path, json=command)
        assert replay.status_code == 200 and replay.json() == original
        with TestClient(create_app(database_url, now=clock)) as peer:
            peer.headers.update(officer.headers)
            current = peer.get(target)
            assert current.status_code == 200 and current.json() == second
            assert_exact_quantities(current.json(), SECOND_TOTALS)
            old = peer.get(target, params={"revision": 1})
            assert old.status_code == 200 and old.json() == original
            assert_exact_quantities(old.json(), FIRST_TOTALS)
            history = peer.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [original, second]
            assert_exact_quantities(history.json()["items"][0], FIRST_TOTALS)
            assert_exact_quantities(history.json()["items"][1], SECOND_TOTALS)
            collection = peer.get(path)
            assert collection.status_code == 200
            assert collection.json()["items"] == [second] and collection.json()["latest"] == second
            assert_exact_quantities(collection.json()["latest"], SECOND_TOTALS)
            params = {"snapshot_id": original["id"], "revision": 1, "locale": "en"}
            statement = peer.get(path + "/statement", params=params)
            assert statement.status_code == 200
            assert statement.json()["items"] == [original]
            assert statement.json()["revision_state"] == "historical"
            assert statement.json()["availability"] is None
            assert_exact_quantities(statement.json()["items"][0], FIRST_TOTALS)
            exported = peer.get(path + "/statement.csv", params=params)
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("text/csv")
            assert exported.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
            assert rows[0] == ["Special ballot stock accounting"]
            for field, value in FIRST_TOTALS.items():
                assert [CSV_LABELS[field], str(value)] in rows
            for expected in (
                ["Revision state", "Historical revision"],
                ["Special ballot observation ID", str(original["id"])],
                ["Revision", "1"],
                ["P(12) snapshot ID", str(ordinary["id"])],
                ["P(12) snapshot revision", "1"],
                ["Original special ballot observation time (Hong Kong time)",
                 "2026-11-15 09:45:17.123456 HKT"],
                ["Original P(12) observation time (Hong Kong time)",
                 "2026-11-15 09:30:17.123456 HKT"],
            ):
                assert expected in rows
            assert reason not in [cell for row in rows for cell in row]
            for receipt in receipts:
                assert [str(receipt["id"]), "1"] in rows
                assert [
                    str(receipt["id"]), "1", receipt["series"], "Ordinary papers",
                    "000000000000000001", "999999999999999991", "999999999999999991",
                ] in rows
            snapshot_after = peer.get(base + f"/stock-snapshots/{ordinary['id']}")
            assert snapshot_after.status_code == 200 and snapshot_after.json() == ordinary
            turnout_after = peer.get(scope["path"])
            assert turnout_after.status_code == 200
            assert turnout_after.json() == turnout_before.json()
