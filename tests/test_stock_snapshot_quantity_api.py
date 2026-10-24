"""Frozen stock totals remain exact across independently legal large series."""

import csv
from io import BytesIO, StringIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader

from election.server.app import create_app
from tests.stock_support import stock_payload
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


def allocate_large_series(
    officer: TestClient, base: str, counter_series_counts: list[tuple[int, int]],
) -> dict[int, list[dict[str, str]]]:
    ranges: dict[int, list[dict[str, str]]] = {}
    number = 0
    for counter_id, count in counter_series_counts:
        ranges[counter_id] = []
        for _ in range(count):
            number += 1
            series = f"Aggregate stock series {number:02d}"
            received = officer.post(
                base + "/stock",
                json=stock_payload(
                    series=series,
                    ordinary_quantity=999999999999999999,
                    replacement_quantity=0,
                    tendered_quantity=0,
                    ranges=[{
                        "pool": "ordinary", "serial_from": "1", "serial_to": "999999999999999999",
                    }],
                ),
            )
            assert received.status_code == 201
            allocated = officer.post(
                base + "/allocations",
                json={
                    "request_id": str(uuid4()),
                    "counter_id": counter_id,
                    "series": series,
                    "serial_from": "1",
                    "serial_to": "999999999999999999",
                    "event_at": "2026-11-15T09:00:00+08:00",
                },
            )
            assert allocated.status_code == 201
            ranges[counter_id].append({
                "series": series, "serial_from": "1", "serial_to": "999999999999999999",
            })
    return ranges


def assert_quantities(row: dict, *, remaining: int, issued: int) -> None:
    expected = {
        "ordinary_allocated_quantity": 19999999999999999980,
        "ordinary_returned_quantity": 0,
        "ordinary_net_allocated_quantity": 19999999999999999980,
        "ordinary_remaining_quantity": remaining,
        "ordinary_issued_quantity": issued,
    }
    for actual in (row, row["counters"][0]):
        for field, quantity in expected.items():
            assert type(actual[field]) is int, (field, actual[field])
            assert actual[field] == quantity


def test_aggregate_totals_above_json_integer_size_preserve_revisions_and_exact_replay(
    admin: TestClient, database_url: str,
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = options.json()["counters"][0]["id"]
        allocate_large_series(officer, base, [(counter_id, 20)])
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{"counter_id": counter_id, "ranges": []}],
        }
        path = base + "/stock-snapshots"
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert_quantities(original, remaining=0, issued=19999999999999999980)
        assert original["complete"] is True
        assert original["counters"][0]["reported"] is True
        assert original["counters"][0]["ranges"] == []
        assert original["event_at"] == "2026-11-15T01:30:17.123456Z"
        assert len(original["allocation_basis"]) == len(original["receipt_basis"]) == 20
        assert len(original["counters"][0]["issued_ranges"]) == 20
        assert all(
            type(row["quantity"]) is int and row["quantity"] == 999999999999999999
            and row["serial_from"] == "1" and row["serial_to"] == "999999999999999999"
            for row in original["counters"][0]["issued_ranges"]
        )
        target = path + f"/{original['id']}"
        with TestClient(create_app(database_url, now=clock)) as another:
            another.headers.update(officer.headers)
            reopened = another.get(target)
            assert reopened.status_code == 200 and reopened.json() == original
            history = another.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [original]
            collection = another.get(path)
            assert collection.status_code == 200
            assert collection.json()["items"] == [original]
            current = collection.json()["current_ordinary_issued_quantity"]
            assert type(current) is int and current == 19999999999999999980
        correction = {
            **command,
            "request_id": str(uuid4()),
            "revision": 1,
            "reason": "核對第一個系列仍有一張。\n保留原始觀察時間及精確數量。",
            "counters": [{
                "counter_id": counter_id,
                "ranges": [{
                    "series": "Aggregate stock series 01", "serial_from": "1", "serial_to": "1",
                }],
            }],
        }
        corrected = officer.put(target, json=correction)
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["revision"] == 2 and second["reason"] == correction["reason"]
        assert second["event_at"] == original["event_at"]
        assert_quantities(second, remaining=1, issued=19999999999999999979)
        later = officer.put(
            target,
            json={
                **command, "request_id": str(uuid4()), "revision": 2,
                "reason": "再次核對已沒有剩餘選票。",
            },
        )
        assert later.status_code == 200
        third = later.json()
        assert third["revision"] == 3
        assert_quantities(third, remaining=0, issued=19999999999999999980)
        replay = officer.put(target, json=correction)
        assert replay.status_code == 200 and replay.json() == second
        create_replay = officer.post(path, json=command)
        assert create_replay.status_code == 200 and create_replay.json() == original
        assert officer.get(target).json() == third
        assert officer.get(target, params={"revision": 1}).json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original, second, third]
        params = {"snapshot_id": original["id"], "revision": 2, "locale": "en"}
        selected = officer.get(path + "/statement", params=params)
        assert selected.status_code == 200
        assert selected.json()["items"] == [second]
        assert selected.json()["revision_state"] == "historical"
        assert selected.json()["availability"] is None
        exported_csv = officer.get(path + "/statement.csv", params=params)
        assert exported_csv.status_code == 200
        assert exported_csv.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(exported_csv.content.decode("utf-8-sig"))))
        assert ["Gross ordinary allocations", "19999999999999999980"] in rows
        assert ["Stock-derived ordinary issuance", "19999999999999999979"] in rows
        assert ["Ordinary papers remaining", "1"] in rows
        exported_pdf = officer.get(path + "/statement.pdf", params=params)
        assert exported_pdf.status_code == 200 and exported_pdf.content.startswith(b"%PDF")
        text = "".join(
            page.extract_text() for page in PdfReader(BytesIO(exported_pdf.content)).pages
        )
        assert "19999999999999999980" in text
        assert "19999999999999999979" in text
        assert "2026-11-15 09:30:17.123456 HKT" in text


def test_station_remaining_total_stays_exact_across_individually_valid_counters(
    admin: TestClient, database_url: str,
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    options = admin.get("/api/accounts/station-options")
    assert options.status_code == 200
    constituency_id = next(
        row["constituency"]["id"] for row in options.json()["items"]
        if row["station"]["id"] == station_id
    )
    for code in ("C2", "C3"):
        configured = admin.post(
            f"/api/elections/{scope['election']['id']}/constituencies/"
            f"{constituency_id}/stations/{station_id}/counters",
            json={"request_id": str(uuid4()), "code": code, "name": "發票櫃台 " + code},
        )
        assert configured.status_code == 201
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counters = options.json()["counters"]
        assert [row["code"] for row in counters] == ["C1", "C2", "C3"]
        remaining = allocate_large_series(officer, base, [(row["id"], 7) for row in counters])
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {"counter_id": row["id"], "ranges": remaining[row["id"]]} for row in counters
            ],
        }
        path = base + "/stock-snapshots"
        response = officer.post(path, json=command)
        assert response.status_code == 201
        saved = response.json()
        assert saved["complete"] is True
        for key in (
            "ordinary_allocated_quantity", "ordinary_net_allocated_quantity",
            "ordinary_remaining_quantity",
        ):
            assert type(saved[key]) is int and saved[key] == 20999999999999999979
        assert type(saved["ordinary_issued_quantity"]) is int
        assert saved["ordinary_issued_quantity"] == 0
        for row in saved["counters"]:
            assert row["reported"] is True
            assert len(row["ranges"]) == 7
            assert row["issued_ranges"] == []
            for key in (
                "ordinary_allocated_quantity", "ordinary_net_allocated_quantity",
                "ordinary_remaining_quantity",
            ):
                assert type(row[key]) is int and row[key] == 6999999999999999993
            assert type(row["ordinary_issued_quantity"]) is int
            assert row["ordinary_issued_quantity"] == 0
            assert all(type(part["quantity"]) is int for part in row["ranges"])
        with TestClient(create_app(database_url, now=clock)) as another:
            another.headers.update(officer.headers)
            target = path + f"/{saved['id']}"
            read = another.get(target)
            assert read.status_code == 200 and read.json() == saved
            history = another.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [saved]
            collection = another.get(path)
            assert collection.status_code == 200 and collection.json()["items"] == [saved]
            assert type(collection.json()["current_ordinary_issued_quantity"]) is int
            assert collection.json()["current_ordinary_issued_quantity"] == 0
