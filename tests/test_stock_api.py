"""Received stock is recorded and revised through the real MySQL-backed public API."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.stock_support import (
    INITIAL_PASSWORD,
    ready_client,
    staff_account,
    stock_payload,
    stock_stations,
)


@pytest.fixture
def stock_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    stations = stock_stations(admin)
    account = staff_account(admin, [row["id"] for row in stations])
    with ready_client(database_url, account) as officer:
        yield {
            "stations": stations,
            "account": account,
            "officer": officer,
            "path": f"/api/workspace/stations/{stations[0]['id']}/stock",
        }


def ordinary_payload(first: str = "000011", last: str = "000020", **changes: object) -> dict:
    return stock_payload(
        ranges=[{"pool": "ordinary", "serial_from": first, "serial_to": last}],
        ordinary_quantity=int(last) - int(first) + 1,
        replacement_quantity=0,
        tendered_quantity=0,
        **changes,
    )


def test_assigned_officer_receives_three_pools_and_reopens_original_serials_after_restart(
    admin: TestClient, database_url: str
) -> None:
    stations = stock_stations(admin)
    station = stations[0]
    account = staff_account(admin, [station["id"]])
    path = f"/api/workspace/stations/{station['id']}/stock"
    payload = stock_payload()
    with ready_client(database_url, account) as officer:
        created = officer.post(path, json=payload)
        assert created.status_code == 201
        receipt = created.json()
        assert receipt["revision"] == 1
        assert receipt["status"] == "recorded"
        assert receipt["station_id"] == station["id"]
        assert receipt["constituency_id"] == station["constituency_id"]
        assert receipt["election_id"] == station["election_id"]
        assert receipt["actor_id"] == account["id"]
        assert receipt["event_at"] == "2026-11-08T00:00:00Z"
        assert receipt["entered_at"]
        assert receipt["series"] == payload["series"]
        assert (
            receipt["ordinary_quantity"],
            receipt["replacement_quantity"],
            receipt["tendered_quantity"],
            receipt["total_quantity"],
        ) == (8, 1, 1, 10)
        assert [
            {key: row[key] for key in ("pool", "serial_from", "serial_to")}
            for row in receipt["ranges"]
        ] == payload["ranges"]
        assert [row["quantity"] for row in receipt["ranges"]] == [8, 1, 1]
        listed = officer.get(path)
        assert listed.status_code == 200
        assert listed.json()["items"] == [receipt]
        assert listed.json()["scope"]["station"]["id"] == station["id"]
        assert officer.get(f"{path}/{receipt['id']}").json() == receipt
        with TestClient(create_app(database_url)) as restarted:
            restarted.headers.update(officer.headers)
            assert restarted.get(path).json()["items"] == [receipt]
            assert restarted.get(f"{path}/{receipt['id']}?revision=1").json() == receipt


def test_corrections_preserve_originals_and_replay_the_exact_saved_revision(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    payload = stock_payload()
    original = officer.post(path, json=payload).json()
    receipt_path = f"{path}/{original['id']}"
    correction = ordinary_payload(revision=1, reason="  按實際接收記錄修正  ")
    changed = officer.put(receipt_path, json=correction)
    assert changed.status_code == 200
    current = changed.json()
    assert current["id"] == original["id"]
    assert current["revision"] == 2
    assert current["reason"] == correction["reason"]
    assert current["total_quantity"] == 10
    assert (
        current["ordinary_quantity"],
        current["replacement_quantity"],
        current["tendered_quantity"],
    ) == (10, 0, 0)
    assert officer.get(receipt_path).json() == current
    assert officer.get(receipt_path + "?revision=1").json() == original
    assert officer.get(receipt_path + "/history").json()["items"] == [original, current]
    assert officer.get(path).json()["items"] == [current]
    assert officer.put(receipt_path, json=correction).json() == current
    assert officer.post(path, json=payload).json() == original
    assert len(officer.get(receipt_path + "/history").json()["items"]) == 2
    changed_retry = officer.put(receipt_path, json={**correction, "reason": "Changed replay"})
    assert changed_retry.status_code == 409
    assert changed_retry.json() == {"detail": {"code": "request_conflict"}}
    stale = officer.put(receipt_path, json={**correction, "request_id": str(uuid4())})
    assert stale.status_code == 409
    assert stale.json() == {"detail": {"code": "revision_conflict"}}
    assert officer.get(receipt_path).json() == current


@pytest.mark.parametrize(
    "field", ["ordinary_quantity", "replacement_quantity", "tendered_quantity"]
)
@pytest.mark.parametrize("invalid", [-1, True, "1", 1.0, 9223372036854775808])
def test_pool_quantities_reject_negative_coercible_and_out_of_bound_values(
    stock_setup: dict, field: str, invalid: object
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    response = officer.post(path, json=stock_payload(**{field: invalid}))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json()["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"ordinary_quantity": 0, "replacement_quantity": 0, "tendered_quantity": 0},
        {"ordinary_quantity": 9},
        {"ordinary_quantity": 9, "replacement_quantity": 0},
        {"replacement_quantity": 2},
        {"tendered_quantity": 2},
        {"ranges": []},
        {"series": "   "},
        {"series": "A" * 65},
        {"event_at": "2026-11-08T08:00:00"},
    ],
)
def test_missing_or_inconsistent_starting_balances_leave_no_receipt(
    stock_setup: dict, changes: dict
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    response = officer.post(path, json=stock_payload(**changes))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json()["items"] == []


@pytest.mark.parametrize(
    ("first", "last"),
    [
        ("2", "1"),
        ("-1", "1"),
        ("1.0", "2"),
        ("1e2", "200"),
        ("１２", "１３"),
        ("A1", "A2"),
        (" 1", "2"),
        ("", "2"),
        (1, "2"),
        ("0" * 19, "1" * 19),
    ],
)
def test_serials_require_ordered_ascii_digit_strings_without_numeric_coercion(
    stock_setup: dict, first: object, last: object
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    response = officer.post(
        path,
        json=stock_payload(
            ranges=[{"pool": "ordinary", "serial_from": first, "serial_to": last}],
            ordinary_quantity=2,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json()["items"] == []


def test_zero_serial_and_large_exact_serials_keep_printed_digits_and_zero_reserves(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    zero = officer.post(path, json=ordinary_payload("000000", "000000"))
    assert zero.status_code == 201
    assert zero.json()["ranges"] == [
        {"pool": "ordinary", "serial_from": "000000", "serial_to": "000000", "quantity": 1}
    ]
    large = officer.post(path, json=ordinary_payload("999999999999999998", "999999999999999999"))
    assert large.status_code == 201
    assert large.json()["total_quantity"] == 2
    assert large.json()["ranges"][0]["serial_from"] == "999999999999999998"
    assert large.json()["ranges"][0]["serial_to"] == "999999999999999999"
    assert large.json()["replacement_quantity"] == large.json()["tendered_quantity"] == 0


def test_ranges_cannot_overlap_between_pools_even_when_declared_totals_add_up(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    payload = stock_payload(
        ranges=[
            {"pool": "ordinary", "serial_from": "000001", "serial_to": "000008"},
            {"pool": "replacement", "serial_from": "8", "serial_to": "8"},
            {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
        ]
    )
    response = officer.post(path, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json()["items"] == []


def test_overlap_spans_stations_and_pools_but_other_series_or_constituencies_are_independent(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    created = officer.post(path, json=stock_payload())
    assert created.status_code == 201
    second_station = stock_setup["stations"][1]
    second_path = f"/api/workspace/stations/{second_station['id']}/stock"
    overlap = officer.post(second_path, json=ordinary_payload("9", "11"))
    assert overlap.status_code == 409
    assert overlap.json() == {"detail": {"code": "stock_overlap"}}
    assert officer.get(second_path).json()["items"] == []
    different_series = officer.post(
        second_path, json=ordinary_payload("9", "11", series="Different series")
    )
    assert different_series.status_code == 201
    south_path = f"/api/workspace/stations/{stock_setup['stations'][2]['id']}/stock"
    assert officer.post(south_path, json=stock_payload()).status_code == 201
    assert officer.post(path, json=ordinary_payload()).status_code == 201
    assert len(officer.get(path).json()["items"]) == 2


def test_failed_overlapping_correction_leaves_revision_and_history_unchanged(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    first = officer.post(path, json=stock_payload()).json()
    second = officer.post(path, json=ordinary_payload()).json()
    receipt_path = f"{path}/{first['id']}"
    response = officer.put(receipt_path, json=ordinary_payload(revision=1, reason="Collision"))
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "stock_overlap"}}
    assert officer.get(receipt_path).json() == first
    assert officer.get(receipt_path + "/history").json()["items"] == [first]
    assert officer.get(path).json()["items"] == [first, second]


@pytest.mark.parametrize("reason", [None, "", "   ", "R" * 1001])
def test_corrections_require_a_meaningful_reason(stock_setup: dict, reason: str | None) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    payload = ordinary_payload(revision=1)
    if reason is not None:
        payload["reason"] = reason
    receipt_path = f"{path}/{original['id']}"
    response = officer.put(receipt_path, json=payload)
    assert response.status_code == 422
    assert officer.get(receipt_path).json() == original
    assert officer.get(receipt_path + "/history").json()["items"] == [original]


@pytest.mark.parametrize(
    "access",
    ["anonymous", "temporary", "unassigned", "administrator", "counting_officer", "supervisor"],
)
def test_stock_roles_and_station_scope_are_enforced_for_every_route(
    admin: TestClient, database_url: str, stock_setup: dict, access: str
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    receipt_path = f"{path}/{original['id']}"
    with TestClient(create_app(database_url)) as client:
        if access == "administrator":
            client.headers.update(admin.headers)
        elif access not in ("anonymous", "temporary"):
            role = "polling_officer" if access == "unassigned" else access
            ids = [] if access == "unassigned" else [stock_setup["stations"][0]["id"]]
            account = staff_account(admin, ids, role)
            with ready_client(database_url, account) as ready:
                client.headers.update(ready.headers)
        elif access == "temporary":
            account = staff_account(admin, [stock_setup["stations"][0]["id"]])
            login = client.post(
                "/api/auth/login",
                json={"username": account["username"], "password": INITIAL_PASSWORD},
            )
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
        for method, target, payload in (
            ("GET", path, None),
            ("POST", path, ordinary_payload()),
            ("GET", receipt_path, None),
            ("GET", receipt_path + "?revision=1", None),
            ("GET", receipt_path + "/history", None),
            ("PUT", receipt_path, ordinary_payload(revision=1, reason="Denied change")),
        ):
            response = client.request(method, target, json=payload)
            if access in ("counting_officer", "supervisor") and method == "GET":
                assert response.status_code == 200
                continue
            code = (
                "session_expired"
                if access == "anonymous"
                else "password_change_required"
                if access == "temporary"
                else "station_access_denied"
                if access == "unassigned"
                else "operational_role_required"
            )
            assert response.status_code == (401 if access == "anonymous" else 403)
            assert response.json() == {"detail": {"code": code}}
    assert officer.get(receipt_path).json() == original
    assert officer.get(receipt_path + "/history").json()["items"] == [original]


def test_wrong_station_or_revision_never_exposes_another_receipt(stock_setup: dict) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    wrong = f"/api/workspace/stations/{stock_setup['stations'][1]['id']}/stock/{original['id']}"
    for method, target, payload in (
        ("GET", wrong, None),
        ("GET", wrong + "/history", None),
        ("PUT", wrong, ordinary_payload(revision=1, reason="Wrong station")),
        ("GET", f"{path}/{original['id']}?revision=99", None),
    ):
        response = officer.request(method, target, json=payload)
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "stock_receipt_not_found"}}
    assert officer.get(f"{path}/{original['id']}").json() == original


@pytest.mark.parametrize("changed_payload", [False, True])
def test_concurrent_receipt_retries_have_one_effect(
    stock_setup: dict, database_url: str, changed_payload: bool
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    payload = stock_payload()
    start = Barrier(2)

    def submit(index: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(officer.headers)
            values = (
                {**payload, "event_at": "2026-11-08T09:00:00+08:00"}
                if changed_payload and index
                else payload
            )
            start.wait(timeout=5)
            result = client.post(path, json=values)
            return result.status_code, result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (0, 1)))
    assert sorted(code for code, _ in outcomes) == ([201, 409] if changed_payload else [200, 201])
    winner = next(body for code, body in outcomes if code == 201)
    if changed_payload:
        assert next(body for code, body in outcomes if code == 409) == {
            "detail": {"code": "request_conflict"}
        }
    else:
        assert outcomes[0][1] == outcomes[1][1]
    assert officer.get(path).json()["items"] == [winner]
    assert officer.get(f"{path}/{winner['id']}/history").json()["items"] == [winner]


def test_a_create_key_cannot_be_reused_at_another_assigned_station(stock_setup: dict) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    payload = stock_payload()
    original = officer.post(path, json=payload).json()
    target = f"/api/workspace/stations/{stock_setup['stations'][2]['id']}/stock"
    conflict = officer.post(target, json=payload)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "request_conflict"}}
    assert officer.get(target).json()["items"] == []
    assert officer.get(path).json()["items"] == [original]


def test_competing_cross_station_receipts_cannot_claim_the_same_constituency_serials(
    stock_setup: dict, database_url: str
) -> None:
    officer = stock_setup["officer"]
    paths = [
        f"/api/workspace/stations/{station['id']}/stock" for station in stock_setup["stations"][:2]
    ]
    start = Barrier(2)

    def submit(path: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(officer.headers)
            start.wait(timeout=5)
            result = client.post(path, json=stock_payload())
            return result.status_code, result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, paths))
    assert sorted(code for code, _ in outcomes) == [201, 409]
    assert next(body for code, body in outcomes if code == 409) == {
        "detail": {"code": "stock_overlap"}
    }
    assert sum(len(officer.get(path).json()["items"]) for path in paths) == 1


def test_competing_corrections_only_accept_one_expected_revision(
    stock_setup: dict, database_url: str
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    target = f"{path}/{original['id']}"
    start = Barrier(2)

    def submit(reason: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(officer.headers)
            start.wait(timeout=5)
            result = client.put(target, json=ordinary_payload(revision=1, reason=reason))
            return result.status_code, result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ("First correction", "Second correction")))
    assert sorted(code for code, _ in outcomes) == [200, 409]
    winner = next(body for code, body in outcomes if code == 200)
    assert next(body for code, body in outcomes if code == 409) == {
        "detail": {"code": "revision_conflict"}
    }
    assert winner["revision"] == 2
    assert officer.get(target).json() == winner
    assert officer.get(target + "/history").json()["items"] == [original, winner]


def test_only_current_revisions_own_serials_and_original_history_stays_intact(
    stock_setup: dict,
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original_payload = stock_payload()
    original = officer.post(path, json=original_payload).json()
    receipt_path = f"{path}/{original['id']}"
    corrected = officer.put(
        receipt_path, json=ordinary_payload(revision=1, reason="Correct printed serials")
    )
    assert corrected.status_code == 200
    received_again = officer.post(path, json=stock_payload())
    assert received_again.status_code == 201
    assert received_again.json()["id"] != original["id"]
    assert officer.get(receipt_path + "?revision=1").json() == original
    assert officer.get(receipt_path + "/history").json()["items"] == [original, corrected.json()]
    assert officer.get(path).json()["items"] == [corrected.json(), received_again.json()]


def test_concurrent_identical_correction_retries_append_one_immutable_revision(
    stock_setup: dict, database_url: str
) -> None:
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    target = f"{path}/{original['id']}"
    payload = ordinary_payload(revision=1, reason="Same correction request")
    start = Barrier(2)

    def submit(_: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(officer.headers)
            start.wait(timeout=5)
            response = client.put(target, json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (0, 1)))
    assert [status for status, _ in outcomes] == [200, 200]
    assert outcomes[0][1] == outcomes[1][1]
    assert officer.get(target + "/history").json()["items"] == [original, outcomes[0][1]]


def test_other_active_election_does_not_block_receipt_preparation_or_finalized_history_reads(
    admin: TestClient, database_url: str, stock_setup: dict
) -> None:
    from datetime import UTC, datetime

    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from election.server.configuration_models import Election
    from election.server.db import make_engine
    from election.server.lifecycle_models import ActiveElection
    from tests.configuration_support import create_election

    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql" and parsed.database.endswith("_test")
    officer, path = stock_setup["officer"], stock_setup["path"]
    original = officer.post(path, json=stock_payload()).json()
    receipt_path = f"{path}/{original['id']}"
    other = create_election(admin)
    engine = make_engine(database_url)
    initial_pointer = None
    original_status = None
    try:
        # Arrange only newly owned synthetic election states; lifecycle commands arrive in Ticket24.
        with Session(engine) as db:
            pointer = db.get(ActiveElection, 1)
            own = db.get(Election, original["election_id"])
            alternate = db.get(Election, other["id"])
            assert pointer is not None and own is not None and alternate is not None
            initial_pointer = (pointer.election_id, pointer.revision, pointer.updated_at)
            original_status = own.status
            alternate.status = "active"
            pointer.election_id, pointer.revision = alternate.id, pointer.revision + 1
            pointer.updated_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        assert officer.get(path).status_code == 200
        assert officer.get(receipt_path + "/history").json()["items"] == [original]
        future_preparation = officer.post(path, json=ordinary_payload())
        assert future_preparation.status_code == 201
        with Session(engine) as db:
            own = db.get(Election, original["election_id"])
            assert own is not None
            own.status = "finalized"
            db.commit()
        listed = officer.get(path)
        assert listed.status_code == 200
        assert listed.json()["scope"]["election"]["status"] == "finalized"
        assert officer.get(receipt_path + "?revision=1").json() == original
        assert officer.get(receipt_path + "/history").json()["items"] == [original]
        for response in (
            officer.post(path, json=ordinary_payload("000021", "000030")),
            officer.put(
                receipt_path,
                json=ordinary_payload("000021", "000030", revision=1, reason="Finalized attempt"),
            ),
        ):
            assert response.status_code == 409
            assert response.json() == {"detail": {"code": "election_read_only"}}
        assert officer.get(path).json()["items"] == [original, future_preparation.json()]
    finally:
        try:
            with Session(engine) as db:
                pointer = db.get(ActiveElection, 1)
                own = db.get(Election, original["election_id"])
                alternate = db.get(Election, other["id"])
                if initial_pointer is not None and pointer is not None:
                    pointer.election_id, pointer.revision, pointer.updated_at = initial_pointer
                if own is not None and original_status is not None:
                    own.status = original_status
                if alternate is not None:
                    alternate.status = "draft"
                db.commit()
        finally:
            engine.dispose()


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_cross_election_receipts_preserve_create_key_identity(
    admin: TestClient, database_url: str, stock_setup: dict, same_key: bool
) -> None:
    first = stock_setup["stations"][0]
    other = stock_stations(admin)[0]
    account = staff_account(admin, [first["id"], other["id"]])
    payload = stock_payload()
    start = Barrier(2)
    with ready_client(database_url, account) as officer:
        paths = [f"/api/workspace/stations/{row['id']}/stock" for row in (first, other)]

        def submit(path: str) -> tuple[int, dict]:
            with TestClient(create_app(database_url)) as client:
                client.headers.update(officer.headers)
                start.wait(timeout=5)
                values = payload if same_key else {**payload, "request_id": str(uuid4())}
                response = client.post(path, json=values)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, paths))
        assert sorted(status for status, _ in outcomes) == ([201, 409] if same_key else [201, 201])
        if same_key:
            assert next(body for status, body in outcomes if status == 409) == {
                "detail": {"code": "request_conflict"}
            }
        assert sum(len(officer.get(path).json()["items"]) for path in paths) == (
            1 if same_key else 2
        )
