"""Polling station and issuance counter journeys through the real MySQL-backed API."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.manage import bootstrap_account
from election.server.app import create_app
from tests.configuration_support import create_constituency, create_election


def test_admin_configures_four_stations_counters_and_a_persisted_counting_destination(
    admin: TestClient, database_url: str
) -> None:
    election = create_election(admin)
    north = create_constituency(admin, election["id"], "N")
    south = create_constituency(admin, election["id"], "S")
    bases = {
        row["id"]: f"/api/elections/{election['id']}/constituencies/{row['id']}/stations"
        for row in (north, south)
    }
    stations: list[dict] = []
    counters: dict[int, dict] = {}
    for constituency, code, name, mode in (
        (north, "N1", "  北區點票站  ", "local"),
        (north, "N2", "北區送箱票站", "send"),
        (south, "S1", "南區第一票站", "local"),
        (south, "S2", "南區第二票站", "local"),
    ):
        destination_id = stations[0]["id"] if mode == "send" else None
        created = admin.post(
            bases[constituency["id"]],
            json={
                "code": code,
                "name": name,
                "counting_mode": mode,
                "destination_station_id": destination_id,
                "request_id": str(uuid4()),
            },
        )
        assert created.status_code == 201
        station = created.json()
        assert station["name"] == name
        assert station["code"] == code
        assert station["election_id"] == election["id"]
        assert station["constituency_id"] == constituency["id"]
        assert station["counting_mode"] == mode
        assert station["destination_station_id"] == destination_id
        assert station["revision"] == 1
        assert station["created_at"] and station["updated_at"]
        stations.append(station)
        station_path = f"{bases[constituency['id']]}/{station['id']}"
        assert admin.get(station_path).json() == station
        counter_created = admin.post(
            station_path + "/counters",
            json={"name": name + " 發票櫃台", "code": "C1", "request_id": str(uuid4())},
        )
        assert counter_created.status_code == 201
        counter = counter_created.json()
        assert counter["station_id"] == station["id"]
        assert counter["constituency_id"] == constituency["id"]
        assert counter["election_id"] == election["id"]
        assert counter["code"] == "C1"
        assert counter["name"] == name + " 發票櫃台"
        assert counter["revision"] == 1
        assert counter["created_at"] and counter["updated_at"]
        counters[station["id"]] = counter
        counter_path = f"{station_path}/counters/{counter['id']}"
        assert admin.get(counter_path).json() == counter
        assert admin.get(station_path + "/counters").json()["items"] == [counter]
    for constituency in (north, south):
        listed = admin.get(bases[constituency["id"]])
        assert listed.status_code == 200
        assert {row["id"] for row in listed.json()["items"]} == {
            row["id"] for row in stations if row["constituency_id"] == constituency["id"]
        }
    sending = stations[1]
    sending_path = f"{bases[north['id']]}/{sending['id']}"
    edited = admin.put(
        sending_path,
        json={
            "name": "北區送箱票站（已修訂）",
            "code": "N2-EDIT",
            "counting_mode": "send",
            "destination_station_id": stations[0]["id"],
            "revision": 1,
        },
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    stations[1] = edited.json()
    counter = counters[sending["id"]]
    edited_counter = admin.put(
        f"{sending_path}/counters/{counter['id']}",
        json={"name": "北區送箱票站修訂櫃台", "code": "C1-EDIT", "revision": 1},
    )
    assert edited_counter.status_code == 200
    assert edited_counter.json()["revision"] == 2
    counters[sending["id"]] = edited_counter.json()
    with TestClient(create_app(database_url)) as restarted:
        restarted.headers.update(admin.headers)
        for station in stations:
            path = f"{bases[station['constituency_id']]}/{station['id']}"
            reopened = restarted.get(path)
            assert reopened.status_code == 200
            assert reopened.json() == station
            saved_counter = counters[station["id"]]
            assert restarted.get(path + "/counters").json()["items"] == [saved_counter]
            assert restarted.get(f"{path}/counters/{saved_counter['id']}").json() == saved_counter
        for constituency in (north, south):
            assert {
                row["id"] for row in restarted.get(bases[constituency["id"]]).json()["items"]
            } == {row["id"] for row in stations if row["constituency_id"] == constituency["id"]}


def create_station(
    admin: TestClient,
    base: str,
    code: str,
    *,
    mode: str = "local",
    destination_id: int | None = None,
) -> dict:
    response = admin.post(
        base,
        json={
            "name": "票站 " + code,
            "code": code,
            "counting_mode": mode,
            "destination_station_id": destination_id,
            "request_id": str(uuid4()),
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def station_arrangement(admin: TestClient) -> dict:
    election = create_election(admin)
    north = create_constituency(admin, election["id"], "N")
    south = create_constituency(admin, election["id"], "S")
    other_election = create_election(admin)
    other_constituency = create_constituency(admin, other_election["id"], "N")
    north_base = f"/api/elections/{election['id']}/constituencies/{north['id']}/stations"
    south_base = f"/api/elections/{election['id']}/constituencies/{south['id']}/stations"
    other_base = (
        f"/api/elections/{other_election['id']}/constituencies/{other_constituency['id']}/stations"
    )
    receiver = create_station(admin, north_base, "N1")
    alternate = create_station(admin, north_base, "N3")
    sender = create_station(admin, north_base, "N2", mode="send", destination_id=receiver["id"])
    south_receiver = create_station(admin, south_base, "S1")
    other_receiver = create_station(admin, other_base, "E1")
    return {
        "base": north_base,
        "receiver": receiver,
        "alternate": alternate,
        "sender": sender,
        "cross_constituency": south_receiver,
        "cross_election": other_receiver,
    }


@pytest.mark.parametrize(
    ("destination", "method"),
    [
        ("cross_constituency", "POST"),
        ("cross_constituency", "PUT"),
        ("cross_election", "POST"),
        ("cross_election", "PUT"),
        ("nonexistent", "POST"),
        ("nonexistent", "PUT"),
        ("sending_station", "POST"),
        ("sending_station", "PUT"),
        ("self", "PUT"),
    ],
)
def test_invalid_counting_destinations_preserve_the_saved_valid_route(
    admin: TestClient, station_arrangement: dict, destination: str, method: str
) -> None:
    base = station_arrangement["base"]
    sender = station_arrangement["sender"]
    sender_path = f"{base}/{sender['id']}"
    if destination == "nonexistent":
        destination_id = 2147483647
        assert admin.get(f"{base}/{destination_id}").status_code == 404
    elif destination == "self":
        destination_id = sender["id"]
    elif destination == "sending_station":
        forwarding = create_station(
            admin,
            base,
            "N4",
            mode="send",
            destination_id=station_arrangement["receiver"]["id"],
        )
        destination_id = forwarding["id"]
    else:
        destination_id = station_arrangement[destination]["id"]
    payload = {
        "name": "Invalid destination attempt",
        "code": "INVALID" if method == "POST" else sender["code"],
        "counting_mode": "send",
        "destination_station_id": destination_id,
    }
    if method == "POST":
        payload["request_id"] = str(uuid4())
        response = admin.post(base, json=payload)
    else:
        payload["revision"] = sender["revision"]
        response = admin.put(sender_path, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_counting_destination"}}
    assert admin.get(sender_path).json() == sender
    assert all(row["code"] != "INVALID" for row in admin.get(base).json()["items"])


def test_receiver_with_incoming_senders_cannot_be_redirected(
    admin: TestClient, station_arrangement: dict
) -> None:
    base = station_arrangement["base"]
    receiver = station_arrangement["receiver"]
    receiver_path = f"{base}/{receiver['id']}"
    response = admin.put(
        receiver_path,
        json={
            "name": receiver["name"],
            "code": receiver["code"],
            "counting_mode": "send",
            "destination_station_id": station_arrangement["alternate"]["id"],
            "revision": receiver["revision"],
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "receiver_in_use"}}
    assert admin.get(receiver_path).json() == receiver
    sender = station_arrangement["sender"]
    assert admin.get(f"{base}/{sender['id']}").json() == sender


def test_reassigning_incoming_senders_first_allows_the_old_receiver_to_send_elsewhere(
    admin: TestClient, station_arrangement: dict
) -> None:
    base = station_arrangement["base"]
    alternate = station_arrangement["alternate"]
    for row in (station_arrangement["sender"], station_arrangement["receiver"]):
        path = f"{base}/{row['id']}"
        response = admin.put(
            path,
            json={
                "name": row["name"],
                "code": row["code"],
                "counting_mode": "send",
                "destination_station_id": alternate["id"],
                "revision": row["revision"],
            },
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["revision"] == row["revision"] + 1
        assert saved["counting_mode"] == "send"
        assert saved["destination_station_id"] == alternate["id"]
        assert admin.get(path).json() == saved
    assert admin.get(f"{base}/{alternate['id']}").json() == alternate


def create_counter(admin: TestClient, station_path: str, code: str = "C1") -> dict:
    response = admin.post(
        station_path + "/counters",
        json={"name": "發票櫃台 " + code, "code": code, "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def station_records(admin: TestClient, station_arrangement: dict) -> dict:
    station = station_arrangement["alternate"]
    station_path = f"{station_arrangement['base']}/{station['id']}"
    counter = create_counter(admin, station_path)
    return {
        **station_arrangement,
        "station": station,
        "station_path": station_path,
        "counter": counter,
        "counter_path": f"{station_path}/counters/{counter['id']}",
    }


def station_calls(records: dict) -> list[tuple[str, str, dict | None]]:
    base, station_path = records["base"], records["station_path"]
    station_payload = {"name": "Forbidden", "code": "F", "counting_mode": "local"}
    counter_payload = {"name": "Forbidden", "code": "F"}
    return [
        ("GET", base, None),
        ("POST", base, {**station_payload, "request_id": str(uuid4())}),
        ("GET", station_path, None),
        ("PUT", station_path, {**station_payload, "revision": 1}),
        ("GET", station_path + "/counters", None),
        (
            "POST",
            station_path + "/counters",
            {**counter_payload, "request_id": str(uuid4())},
        ),
        ("GET", records["counter_path"], None),
        ("PUT", records["counter_path"], {**counter_payload, "revision": 1}),
    ]


@pytest.mark.parametrize(
    "access", ["anonymous", "temporary", "polling_officer", "counting_officer", "supervisor"]
)
def test_station_routes_reject_anonymous_temporary_and_nonadmin_access(
    admin: TestClient, database_url: str, station_records: dict, access: str
) -> None:
    with TestClient(create_app(database_url)) as restricted:
        if access != "anonymous":
            username = "station_role_" + uuid4().hex[:12]
            password = "Station-Role-Initial-42!"
            bootstrap_account(database_url, username, "票站權限測試", password)
            if access != "temporary":
                from sqlalchemy import select
                from sqlalchemy.orm import Session

                from election.server.db import make_engine
                from election.server.models import Account

                # Arrange roles until account administration is available in Ticket 04.
                engine = make_engine(database_url)
                try:
                    with Session(engine) as db:
                        account = db.scalar(select(Account).where(Account.username == username))
                        assert account is not None
                        account.role = access
                        db.commit()
                finally:
                    engine.dispose()
            login = restricted.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200
            restricted.headers["Authorization"] = "Bearer " + login.json()["token"]
            if access != "temporary":
                changed = restricted.post(
                    "/api/auth/password",
                    json={"current_password": password, "new_password": "Station-Role-Ready-84!"},
                )
                assert changed.status_code == 200
                restricted.headers["Authorization"] = "Bearer " + changed.json()["token"]
                assert restricted.get("/api/auth/me").json()["role"] == access
        expected = (
            (401, "session_expired")
            if access == "anonymous"
            else (
                403,
                "password_change_required" if access == "temporary" else "administrator_required",
            )
        )
        for method, path, payload in station_calls(station_records):
            response = restricted.request(method, path, json=payload)
            assert response.status_code == expected[0], (method, path)
            assert response.json() == {"detail": {"code": expected[1]}}
    for entity in ("station", "counter"):
        assert admin.get(station_records[entity + "_path"]).json() == station_records[entity]


@pytest.mark.parametrize(
    "invalid",
    [
        {"counting_mode": "remote"},
        {"counting_mode": "send", "destination_station_id": None},
        {"counting_mode": "local", "destination_station_id": 1},
        {"counting_mode": "send", "destination_station_id": True},
        {"counting_mode": "send", "destination_station_id": "1"},
        {"counting_mode": "send", "destination_station_id": 1.0},
        {"counting_mode": "send", "destination_station_id": 0},
        {"counting_mode": "send", "destination_station_id": -1},
    ],
)
def test_invalid_counting_mode_or_destination_shapes_leave_station_unchanged(
    admin: TestClient, station_records: dict, invalid: dict
) -> None:
    payload = {"name": "Invalid shape", "code": "SHAPE", **invalid}
    created = admin.post(station_records["base"], json={**payload, "request_id": str(uuid4())})
    edited = admin.put(station_records["station_path"], json={**payload, "revision": 1})
    for response in (created, edited):
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "validation_error"
    assert admin.get(station_records["station_path"]).json() == station_records["station"]
    assert all(row["code"] != "SHAPE" for row in admin.get(station_records["base"]).json()["items"])


def test_station_codes_are_unique_only_within_their_constituency(
    admin: TestClient, station_records: dict
) -> None:
    payload = {"name": "Duplicate", "code": station_records["receiver"]["code"]}
    duplicate = admin.post(station_records["base"], json={**payload, "request_id": str(uuid4())})
    edited = admin.put(station_records["station_path"], json={**payload, "revision": 1})
    for response in (duplicate, edited):
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "duplicate_configuration"}}
    for parent in ("cross_constituency", "cross_election"):
        row = station_records[parent]
        base = (
            f"/api/elections/{row['election_id']}/constituencies/{row['constituency_id']}/stations"
        )
        allowed = create_station(admin, base, payload["code"])
        assert allowed["constituency_id"] == row["constituency_id"]
        assert allowed["code"] == payload["code"]
    assert admin.get(station_records["station_path"]).json() == station_records["station"]


def test_counter_codes_are_unique_only_within_their_polling_station(
    admin: TestClient, station_records: dict
) -> None:
    station_path = station_records["station_path"]
    second = create_counter(admin, station_path, "C2")
    payload = {"name": "Duplicate", "code": station_records["counter"]["code"]}
    duplicate = admin.post(station_path + "/counters", json={**payload, "request_id": str(uuid4())})
    edited = admin.put(f"{station_path}/counters/{second['id']}", json={**payload, "revision": 1})
    for response in (duplicate, edited):
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "duplicate_configuration"}}
    for parent in ("receiver", "cross_constituency", "cross_election"):
        row = station_records[parent]
        other_path = (
            f"/api/elections/{row['election_id']}/constituencies/{row['constituency_id']}"
            f"/stations/{row['id']}"
        )
        allowed = create_counter(admin, other_path, payload["code"])
        assert allowed["station_id"] == row["id"]
        assert allowed["code"] == payload["code"]
    assert admin.get(station_path + "/counters").json()["items"] == [
        station_records["counter"],
        second,
    ]


def test_wrong_parent_station_and_counter_paths_cannot_read_or_modify_records(
    admin: TestClient, station_records: dict
) -> None:
    original_station = station_records["station"]
    wrong_station_paths = []
    for parent in ("cross_constituency", "cross_election"):
        row = station_records[parent]
        wrong_base = (
            f"/api/elections/{row['election_id']}/constituencies/{row['constituency_id']}/stations"
        )
        wrong_station_paths.append(f"{wrong_base}/{original_station['id']}")
    wrong_election = station_records["cross_election"]["election_id"]
    wrong_collection = (
        f"/api/elections/{wrong_election}/constituencies/{original_station['constituency_id']}"
        "/stations"
    )
    assert admin.get(wrong_collection).status_code == 404
    assert (
        admin.post(
            wrong_collection, json={"name": "Wrong", "code": "WRONG", "request_id": str(uuid4())}
        ).status_code
        == 404
    )
    wrong_station_paths.append(f"{wrong_collection}/{original_station['id']}")
    for station_path in wrong_station_paths:
        counter_path = f"{station_path}/counters/{station_records['counter']['id']}"
        for method, path, payload in [
            ("GET", station_path, None),
            ("PUT", station_path, {"name": "Wrong", "code": "WRONG", "revision": 1}),
            ("GET", station_path + "/counters", None),
            (
                "POST",
                station_path + "/counters",
                {"name": "Wrong", "code": "WRONG", "request_id": str(uuid4())},
            ),
            ("GET", counter_path, None),
            ("PUT", counter_path, {"name": "Wrong", "code": "WRONG", "revision": 1}),
        ]:
            response = admin.request(method, path, json=payload)
            assert response.status_code == 404, (method, path)
            assert response.json() == {"detail": {"code": "configuration_not_found"}}
    other_station_path = f"{station_records['base']}/{station_records['receiver']['id']}"
    wrong_counter_path = f"{other_station_path}/counters/{station_records['counter']['id']}"
    for response in (
        admin.get(wrong_counter_path),
        admin.put(wrong_counter_path, json={"name": "Wrong", "code": "WRONG", "revision": 1}),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "configuration_not_found"}}
    for entity in ("station", "counter"):
        assert admin.get(station_records[entity + "_path"]).json() == station_records[entity]
    assert admin.get(other_station_path + "/counters").json()["items"] == []


@pytest.mark.parametrize("entity", ["station", "counter"])
def test_stale_station_or_counter_edits_preserve_the_winning_revision(
    admin: TestClient, database_url: str, station_records: dict, entity: str
) -> None:
    path = station_records[entity + "_path"]
    with TestClient(create_app(database_url)) as another:
        another.headers.update(admin.headers)
        saved = another.get(path).json()
        payload = {"name": "Winning change", "code": "WIN", "revision": saved["revision"]}
        winning = admin.put(path, json=payload)
        assert winning.status_code == 200
        stale = another.put(path, json={**payload, "name": "Stale change"})
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"code": "revision_conflict"}}
        assert winning.json()["revision"] == saved["revision"] + 1
        assert another.get(path).json() == winning.json()


@pytest.mark.parametrize("entity", ["station", "counter"])
def test_concurrent_station_or_counter_edits_accept_one_writer(
    admin: TestClient, database_url: str, station_records: dict, entity: str
) -> None:
    path = station_records[entity + "_path"]
    start = Barrier(2)

    def submit(name: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.put(path, json={"name": name, "code": "EDIT", "revision": 1})
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ("First writer", "Second writer")))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    loser = next(body for status, body in outcomes if status == 409)
    assert loser == {"detail": {"code": "revision_conflict"}}
    assert winner["revision"] == 2
    assert admin.get(path).json() == winner


def create_path(records: dict, entity: str) -> str:
    return records["base"] if entity == "station" else records["station_path"] + "/counters"


@pytest.mark.parametrize("entity", ["station", "counter"])
def test_station_or_counter_create_replay_preserves_one_record_and_rejects_changed_payload(
    admin: TestClient, station_records: dict, entity: str
) -> None:
    path = create_path(station_records, entity)
    payload = {"name": "Replay 測試", "code": "REPLAY", "request_id": str(uuid4())}
    created = admin.post(path, json=payload)
    assert created.status_code == 201
    retried = admin.post(path, json=payload)
    assert retried.status_code == 200
    assert retried.json() == created.json()
    changed = admin.post(path, json={**payload, "name": "Changed retry"})
    assert changed.status_code == 409
    assert changed.json() == {"detail": {"code": "request_conflict"}}
    assert [row for row in admin.get(path).json()["items"] if row["code"] == "REPLAY"] == [
        created.json()
    ]


@pytest.mark.parametrize("entity", ["station", "counter"])
def test_station_or_counter_create_key_cannot_replay_in_a_different_parent(
    admin: TestClient, station_records: dict, entity: str
) -> None:
    source = create_path(station_records, entity)
    if entity == "station":
        parent = station_records["cross_constituency"]
        target = (
            f"/api/elections/{parent['election_id']}/constituencies/{parent['constituency_id']}"
            "/stations"
        )
    else:
        target = f"{station_records['base']}/{station_records['receiver']['id']}/counters"
    payload = {"name": "Scoped replay", "code": "SCOPE", "request_id": str(uuid4())}
    created = admin.post(source, json=payload)
    assert created.status_code == 201
    changed_parent = admin.post(target, json=payload)
    assert changed_parent.status_code == 409
    assert changed_parent.json() == {"detail": {"code": "request_conflict"}}
    assert all(row["code"] != "SCOPE" for row in admin.get(target).json()["items"])
    assert [row for row in admin.get(source).json()["items"] if row["code"] == "SCOPE"] == [
        created.json()
    ]


@pytest.mark.parametrize("entity", ["station", "counter"])
@pytest.mark.parametrize("changed_payload", [False, True])
def test_concurrent_station_or_counter_creates_replay_or_reject_a_changed_payload(
    admin: TestClient,
    database_url: str,
    station_records: dict,
    entity: str,
    changed_payload: bool,
) -> None:
    path = create_path(station_records, entity)
    payload = {"name": "Concurrent replay", "code": "RETRY", "request_id": str(uuid4())}
    start = Barrier(2)

    def submit(index: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            name = payload["name"] + (str(index) if changed_payload else "")
            start.wait(timeout=5)
            response = client.post(path, json={**payload, "name": name})
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (1, 2)))
    expected_statuses = [201, 409] if changed_payload else [200, 201]
    assert sorted(status for status, _ in outcomes) == expected_statuses
    winner = next(body for status, body in outcomes if status == 201)
    if changed_payload:
        assert next(body for status, body in outcomes if status == 409) == {
            "detail": {"code": "request_conflict"}
        }
    else:
        assert outcomes[0][1] == outcomes[1][1]
    assert [row for row in admin.get(path).json()["items"] if row["code"] == "RETRY"] == [winner]


def test_adding_a_sender_racing_with_receiver_redirection_preserves_compatible_routes(
    admin: TestClient, database_url: str, station_arrangement: dict
) -> None:
    base = station_arrangement["base"]
    unused_receiver = create_station(admin, base, "RACE-RECEIVE")
    alternate = station_arrangement["alternate"]
    start = Barrier(2)

    def submit(action: str) -> tuple[str, int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            if action == "sender":
                response = client.post(
                    base,
                    json={
                        "name": "Racing sender",
                        "code": "RACE-SEND",
                        "counting_mode": "send",
                        "destination_station_id": unused_receiver["id"],
                        "request_id": str(uuid4()),
                    },
                )
            else:
                response = client.put(
                    f"{base}/{unused_receiver['id']}",
                    json={
                        "name": unused_receiver["name"],
                        "code": unused_receiver["code"],
                        "counting_mode": "send",
                        "destination_station_id": alternate["id"],
                        "revision": 1,
                    },
                )
            return action, response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = {
            action: (status, body)
            for action, status, body in pool.map(submit, ("sender", "receiver"))
        }
    sender_status, sender_body = outcomes["sender"]
    receiver_status, receiver_body = outcomes["receiver"]
    assert (sender_status, receiver_status) in ((201, 409), (422, 200))
    saved_receiver = admin.get(f"{base}/{unused_receiver['id']}").json()
    rows = admin.get(base).json()["items"]
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        if row["counting_mode"] == "send":
            destination = by_id[row["destination_station_id"]]
            assert destination["id"] != row["id"]
            assert destination["constituency_id"] == row["constituency_id"]
            assert destination["election_id"] == row["election_id"]
            assert destination["counting_mode"] == "local"
            assert destination["destination_station_id"] is None
    if sender_status == 201:
        assert receiver_body == {"detail": {"code": "receiver_in_use"}}
        assert saved_receiver == unused_receiver
        assert admin.get(f"{base}/{sender_body['id']}").json() == sender_body
    else:
        assert sender_body == {"detail": {"code": "invalid_counting_destination"}}
        assert saved_receiver == receiver_body
        assert saved_receiver["counting_mode"] == "send"
        assert saved_receiver["destination_station_id"] == alternate["id"]
        assert all(row["code"] != "RACE-SEND" for row in rows)
