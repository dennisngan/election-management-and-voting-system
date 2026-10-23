"""Independent clients contend through the real MySQL-backed allocation interface."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.stock_support import ready_client, staff_account, stock_payload, stock_stations
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


def parallel_commands(database_url: str, headers: dict, commands: list[tuple]) -> list[tuple]:
    barrier = Barrier(len(commands))

    def submit(command: tuple) -> tuple:
        method, path, payload = command
        with TestClient(create_app(database_url)) as client:
            client.headers.update(headers)
            barrier.wait(timeout=5)
            result = client.request(method, path, json=payload)
            return result.status_code, result.json()

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        return list(pool.map(submit, commands))


@pytest.mark.parametrize("kind", ["same_request", "overlap", "changed_request", "disjoint"])
def test_concurrent_creates_preserve_one_current_owner_per_serial(
    allocation_setup: dict, database_url: str, kind: str
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    first = allocation_payload(setup["counter"]["id"])
    if kind == "same_request":
        second = dict(first)
    elif kind == "changed_request":
        second = {**first, "serial_to": "000004"}
    elif kind == "overlap":
        second = allocation_payload(
            setup["counter"]["id"], serial_from="000003", serial_to="000005"
        )
    else:
        second = allocation_payload(
            setup["counter"]["id"], serial_from="000004", serial_to="000006"
        )
    outcomes = parallel_commands(
        database_url, dict(officer.headers), [("POST", path, first), ("POST", path, second)]
    )
    expected = (
        [200, 201] if kind == "same_request" else [201, 201] if kind == "disjoint" else [201, 409]
    )
    assert sorted(code for code, _ in outcomes) == expected
    view = officer.get(path).json()
    if kind == "same_request":
        assert outcomes[0][1] == outcomes[1][1]
        assert view["items"] == [outcomes[0][1]]
        assert view["availability"][0]["allocated_quantity"] == 3
    elif kind == "disjoint":
        assert len(view["items"]) == 2
        assert view["availability"][0]["allocated_quantity"] == 6
        assert view["availability"][0]["available_quantity"] == 2
        assert view["availability"][0]["ranges"][0]["serial_from"] == "000007"
    else:
        conflict = next(body for code, body in outcomes if code == 409)
        assert conflict == {
            "detail": {
                "code": "request_conflict" if kind == "changed_request" else "allocation_overlap"
            }
        }
        winner = next(body for code, body in outcomes if code == 201)
        assert view["items"] == [winner]
        assert view["availability"][0]["allocated_quantity"] == winner["quantity"]
        assert view["availability"][0]["available_quantity"] == 8 - winner["quantity"]


def test_competing_amendments_accept_only_one_expected_revision(
    allocation_setup: dict, database_url: str
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    created = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    target = path + f"/{created.json()['id']}"
    commands = [
        allocation_payload(
            setup["counter"]["id"],
            revision=1,
            reason=f"核對紙本 {index}",
            serial_from=first,
            serial_to=last,
        )
        for index, (first, last) in enumerate([("000001", "000004"), ("000002", "000005")])
    ]
    outcomes = parallel_commands(
        database_url, dict(officer.headers), [("PUT", target, command) for command in commands]
    )
    assert sorted(code for code, _ in outcomes) == [200, 409]
    winner = next(body for code, body in outcomes if code == 200)
    assert winner["revision"] == 2
    assert next(body for code, body in outcomes if code == 409) == {
        "detail": {"code": "revision_conflict"}
    }
    assert officer.get(target).json() == winner
    assert officer.get(target + "/history").json()["items"] == [created.json(), winner]
    assert officer.get(path).json()["availability"][0]["allocated_quantity"] == 4


def test_receipt_correction_and_allocation_cannot_commit_an_uncovered_owner(
    allocation_setup: dict, database_url: str
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    correction = stock_payload(
        revision=1,
        reason="核對交接文件",
        ordinary_quantity=7,
        ranges=[
            {"pool": "ordinary", "serial_from": "000002", "serial_to": "000008"},
            {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
            {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
        ],
    )
    outcomes = parallel_commands(
        database_url,
        dict(officer.headers),
        [
            ("POST", path, allocation_payload(setup["counter"]["id"])),
            ("PUT", setup["base"] + f"/stock/{setup['receipt']['id']}", correction),
        ],
    )
    codes = tuple(code for code, _ in outcomes)
    assert codes in ((201, 409), (409, 200))
    view = officer.get(path).json()
    if codes[0] == 201:
        assert outcomes[1][1] == {"detail": {"code": "stock_allocations_conflict"}}
        assert view["items"] == [outcomes[0][1]]
        assert view["availability"][0]["ordinary_received_quantity"] == 8
        assert view["availability"][0]["available_quantity"] == 5
    else:
        assert outcomes[0][1] == {"detail": {"code": "allocation_outside_stock"}}
        assert view["items"] == []
        assert view["availability"][0]["ordinary_received_quantity"] == 7
        assert view["availability"][0]["available_quantity"] == 7


def counter_at(admin: TestClient, station: dict) -> dict:
    response = admin.post(
        f"/api/elections/{station['election_id']}/constituencies/"
        f"{station['constituency_id']}/stations/{station['id']}/counters",
        json={"code": "C1", "name": "獨立範圍櫃台", "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


def test_global_request_collision_across_elections_has_one_allocation_effect(
    allocation_setup: dict, admin: TestClient, database_url: str
) -> None:
    setup = allocation_setup
    other_station = stock_stations(admin)[0]
    other_counter = counter_at(admin, other_station)
    other_base = f"/api/workspace/stations/{other_station['id']}"
    account = staff_account(admin, [setup["station"]["id"], other_station["id"]])
    with ready_client(database_url, account) as officer:
        received = officer.post(other_base + "/stock", json=stock_payload())
        assert received.status_code == 201
        request_id = str(uuid4())
        paths = [setup["base"] + "/allocations", other_base + "/allocations"]
        outcomes = parallel_commands(
            database_url,
            dict(officer.headers),
            [
                (
                    "POST",
                    paths[0],
                    allocation_payload(setup["counter"]["id"], request_id=request_id),
                ),
                ("POST", paths[1], allocation_payload(other_counter["id"], request_id=request_id)),
            ],
        )
        assert sorted(code for code, _ in outcomes) == [201, 409]
        assert next(body for code, body in outcomes if code == 409) == {
            "detail": {"code": "request_conflict"}
        }
        views = [officer.get(path).json() for path in paths]
        assert sum(len(view["items"]) for view in views) == 1
        assert sum(view["availability"][0]["allocated_quantity"] for view in views) == 3


@pytest.mark.parametrize("context", ["series", "constituency", "election"])
def test_identical_numeric_serials_in_distinct_physical_contexts_remain_independent(
    allocation_setup: dict, admin: TestClient, database_url: str, context: str
) -> None:
    setup = allocation_setup
    if context == "series":
        other_station, other_counter = setup["station"], setup["counter"]
        other_series = "普通系列 a"
    else:
        other_station = (
            setup["stations"][2] if context == "constituency" else stock_stations(admin)[0]
        )
        other_counter = counter_at(admin, other_station)
        other_series = "普通系列 A"
    other_base = f"/api/workspace/stations/{other_station['id']}"
    station_ids = sorted({setup["station"]["id"], other_station["id"]})
    account = staff_account(admin, station_ids)
    with ready_client(database_url, account) as officer:
        received = officer.post(other_base + "/stock", json=stock_payload(series=other_series))
        assert received.status_code == 201
        paths = [setup["base"] + "/allocations", other_base + "/allocations"]
        outcomes = parallel_commands(
            database_url,
            dict(officer.headers),
            [
                ("POST", paths[0], allocation_payload(setup["counter"]["id"])),
                ("POST", paths[1], allocation_payload(other_counter["id"], series=other_series)),
            ],
        )
        assert [code for code, _ in outcomes] == [201, 201]
        views = [officer.get(path).json() for path in dict.fromkeys(paths)]
        assert sum(len(view["items"]) for view in views) == 2
        assert all(
            (row["serial_from"], row["serial_to"], row["quantity"]) == ("000001", "000003", 3)
            for view in views
            for row in view["items"]
        )
        assert sum(row["allocated_quantity"] for view in views for row in view["availability"]) == 6
