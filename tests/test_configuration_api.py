"""Draft configuration journeys through the authenticated API and real MySQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.manage import bootstrap_account
from election.server.app import create_app
from tests.configuration_support import create_constituency, create_election


def test_admin_creates_reopens_and_edits_a_persisted_draft(
    admin: TestClient, database_url: str
) -> None:
    created = admin.post(
        "/api/elections", json={"name": "  測試 Election 2026  ", "request_id": str(uuid4())}
    )
    assert created.status_code == 201
    election = created.json()
    assert election["name"] == "  測試 Election 2026  "
    assert election["status"] == "draft"
    assert election["revision"] == 1
    path = f"/api/elections/{election['id']}"
    edited = admin.put(path, json={"name": "秋季選舉", "revision": 1})
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    with TestClient(create_app(database_url)) as another_client:
        another_client.headers.update(admin.headers)
        assert another_client.get(path).json()["name"] == "秋季選舉"
        assert any(
            row["id"] == election["id"]
            for row in another_client.get("/api/elections").json()["items"]
        )


def test_constituencies_keep_candidates_and_ballot_numbers_independent(admin: TestClient) -> None:
    election = create_election(admin)
    base = f"/api/elections/{election['id']}/constituencies"
    north = admin.post(base, json={"code": "N", "name": "北區", "request_id": str(uuid4())})
    south = admin.post(base, json={"code": "S", "name": "南區", "request_id": str(uuid4())})
    assert north.status_code == south.status_code == 201
    assert north.json()["seats"] == north.json()["choices_per_ballot"] == 1
    paths = [f"{base}/{row.json()['id']}/candidates" for row in (north, south)]
    first = admin.post(
        paths[0], json={"name": "  陳 Example  ", "ballot_number": 1, "request_id": str(uuid4())}
    )
    second = admin.post(
        paths[1], json={"name": "  陳 Example  ", "ballot_number": 1, "request_id": str(uuid4())}
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["name"] == "  陳 Example  "
    assert admin.get(paths[0]).json()["items"] == [first.json()]
    assert admin.get(paths[1]).json()["items"] == [second.json()]
    changed = admin.put(
        f"{paths[0]}/{first.json()['id']}",
        json={"name": "陳已更正", "ballot_number": 2, "revision": 1},
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    assert admin.get(paths[1]).json()["items"][0]["ballot_number"] == 1
    renamed = admin.put(
        f"{base}/{north.json()['id']}", json={"name": "新北區", "code": "NN", "revision": 1}
    )
    assert renamed.status_code == 200
    assert admin.get(f"{base}/{north.json()['id']}").json()["name"] == "新北區"


def create_candidate(admin: TestClient, base: str, ballot_number: int = 1) -> dict:
    response = admin.post(
        base,
        json={"name": "候選人", "ballot_number": ballot_number, "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def configuration(admin: TestClient) -> dict:
    election = create_election(admin)
    constituency = create_constituency(admin, election["id"])
    election_path = f"/api/elections/{election['id']}"
    constituency_path = f"{election_path}/constituencies/{constituency['id']}"
    candidate = create_candidate(admin, constituency_path + "/candidates")
    return {
        "election": election,
        "constituency": constituency,
        "candidate": candidate,
        "election_path": election_path,
        "constituency_path": constituency_path,
        "candidate_path": f"{constituency_path}/candidates/{candidate['id']}",
    }


def configuration_calls(configuration: dict) -> list[tuple[str, str, dict | None]]:
    election_path = configuration["election_path"]
    constituency_path = configuration["constituency_path"]
    candidate_path = configuration["candidate_path"]
    return [
        ("GET", "/api/elections", None),
        ("POST", "/api/elections", {"name": "Forbidden", "request_id": str(uuid4())}),
        ("GET", election_path, None),
        ("PUT", election_path, {"name": "Forbidden", "revision": 1}),
        ("GET", election_path + "/constituencies", None),
        (
            "POST",
            election_path + "/constituencies",
            {"name": "Forbidden", "code": "F", "request_id": str(uuid4())},
        ),
        ("GET", constituency_path, None),
        ("PUT", constituency_path, {"name": "Forbidden", "code": "F", "revision": 1}),
        ("GET", constituency_path + "/candidates", None),
        (
            "POST",
            constituency_path + "/candidates",
            {"name": "Forbidden", "ballot_number": 2, "request_id": str(uuid4())},
        ),
        ("GET", candidate_path, None),
        ("PUT", candidate_path, {"name": "Forbidden", "ballot_number": 2, "revision": 1}),
    ]


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_nonadmin_roles_cannot_read_or_modify_any_configuration_route(
    admin: TestClient, database_url: str, configuration: dict, role: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from election.server.db import make_engine
    from election.server.models import Account

    username = "role_config_" + uuid4().hex[:12]
    password = "Role-Configuration-Initial-42!"
    bootstrap_account(database_url, username, "非管理員測試", password)
    # Arrange a role directly until account administration is delivered in Ticket 04.
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            account = db.scalar(select(Account).where(Account.username == username))
            assert account is not None
            account.role = role
            db.commit()
    finally:
        engine.dispose()
    with TestClient(create_app(database_url)) as restricted:
        login = restricted.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert login.status_code == 200
        restricted.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = restricted.post(
            "/api/auth/password",
            json={"current_password": password, "new_password": "Role-Configuration-Ready-84!"},
        )
        assert changed.status_code == 200
        restricted.headers["Authorization"] = "Bearer " + changed.json()["token"]
        assert restricted.get("/api/auth/me").json()["role"] == role
        for method, path, payload in configuration_calls(configuration):
            denied = restricted.request(method, path, json=payload)
            assert denied.status_code == 403, (method, path)
            assert denied.json() == {"detail": {"code": "administrator_required"}}
    assert admin.get(configuration["election_path"]).json() == configuration["election"]
    assert admin.get(configuration["constituency_path"]).json() == configuration["constituency"]
    assert admin.get(configuration["candidate_path"]).json() == configuration["candidate"]


@pytest.mark.parametrize("temporary_password", [False, True])
def test_anonymous_and_temporary_password_sessions_cannot_access_configuration(
    database_url: str, configuration: dict, temporary_password: bool
) -> None:
    with TestClient(create_app(database_url)) as restricted:
        if temporary_password:
            username = "temporary_config_" + uuid4().hex[:12]
            password = "Temporary-Configuration-42!"
            bootstrap_account(database_url, username, "臨時密碼測試", password)
            login = restricted.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200
            restricted.headers["Authorization"] = "Bearer " + login.json()["token"]
        expected_status = 403 if temporary_password else 401
        expected_code = "password_change_required" if temporary_password else "session_expired"
        for method, path, payload in configuration_calls(configuration):
            denied = restricted.request(method, path, json=payload)
            assert denied.status_code == expected_status, (method, path)
            assert denied.json() == {"detail": {"code": expected_code}}


@pytest.mark.parametrize("field", ["seats", "choices_per_ballot"])
def test_constituencies_reject_other_counting_modes_on_create_and_edit(
    admin: TestClient, configuration: dict, field: str
) -> None:
    collection = configuration["election_path"] + "/constituencies"
    for invalid in (0, 2, True, "1", 1.0):
        payload = {"name": "Invalid mode", "code": "X", field: invalid}
        created = admin.post(collection, json={**payload, "request_id": str(uuid4())})
        edited = admin.put(configuration["constituency_path"], json={**payload, "revision": 1})
        for response in (created, edited):
            assert response.status_code == 422, (field, invalid)
            assert response.json() == {"detail": {"code": "validation_error", "fields": [field]}}
    assert admin.get(collection).json()["items"] == [configuration["constituency"]]


def test_duplicate_constituency_code_is_rejected_only_within_its_election(
    admin: TestClient, configuration: dict
) -> None:
    collection = configuration["election_path"] + "/constituencies"
    duplicate = admin.post(
        collection, json={"name": "Duplicate", "code": "N", "request_id": str(uuid4())}
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": {"code": "duplicate_configuration"}}
    another_election = create_election(admin)
    same_code_elsewhere = create_constituency(admin, another_election["id"], "N")
    assert same_code_elsewhere["id"] != configuration["constituency"]["id"]
    south = create_constituency(admin, configuration["election"]["id"], "S")
    renamed = admin.put(
        f"{collection}/{south['id']}", json={"name": "Conflicting edit", "code": "N", "revision": 1}
    )
    assert renamed.status_code == 409
    assert admin.get(f"{collection}/{south['id']}").json() == south
    assert admin.get(configuration["constituency_path"]).json() == configuration["constituency"]


def test_duplicate_ballot_number_rejects_create_and_edit_without_changing_candidates(
    admin: TestClient, configuration: dict
) -> None:
    collection = configuration["constituency_path"] + "/candidates"
    duplicate = admin.post(
        collection, json={"name": "Duplicate", "ballot_number": 1, "request_id": str(uuid4())}
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": {"code": "duplicate_configuration"}}
    second = create_candidate(admin, collection, 2)
    conflicting_edit = admin.put(
        f"{collection}/{second['id']}",
        json={"name": "Conflicting edit", "ballot_number": 1, "revision": 1},
    )
    assert conflicting_edit.status_code == 409
    assert admin.get(f"{collection}/{second['id']}").json() == second
    assert admin.get(collection).json()["items"] == [configuration["candidate"], second]


def test_wrong_parent_paths_cannot_read_create_or_edit_unrelated_records(
    admin: TestClient, configuration: dict
) -> None:
    another_election = create_election(admin)
    wrong_election = f"/api/elections/{another_election['id']}"
    wrong_constituency = create_constituency(admin, configuration["election"]["id"], "S")
    wrong_constituency_path = (
        f"{configuration['election_path']}/constituencies/{wrong_constituency['id']}"
    )
    wrong_election_constituency = (
        f"{wrong_election}/constituencies/{configuration['constituency']['id']}"
    )
    candidate_id = configuration["candidate"]["id"]
    invalid_paths = [
        (wrong_election_constituency, {"name": "Wrong", "code": "W", "revision": 1}),
        (
            f"{wrong_election_constituency}/candidates/{candidate_id}",
            {"name": "Wrong", "ballot_number": 2, "revision": 1},
        ),
        (
            f"{wrong_constituency_path}/candidates/{candidate_id}",
            {"name": "Wrong", "ballot_number": 2, "revision": 1},
        ),
    ]
    for path, payload in invalid_paths:
        for response in (admin.get(path), admin.put(path, json=payload)):
            assert response.status_code == 404
            assert response.json() == {"detail": {"code": "configuration_not_found"}}
    wrong_collection = wrong_election_constituency + "/candidates"
    assert admin.get(wrong_collection).status_code == 404
    assert (
        admin.post(
            wrong_collection,
            json={"name": "Wrong", "ballot_number": 2, "request_id": str(uuid4())},
        ).status_code
        == 404
    )
    assert admin.get(configuration["candidate_path"]).json() == configuration["candidate"]
    assert admin.get(wrong_constituency_path + "/candidates").json()["items"] == []


@pytest.mark.parametrize("entity", ["election", "constituency", "candidate"])
def test_stale_edits_from_another_client_preserve_the_winning_revision(
    admin: TestClient, database_url: str, configuration: dict, entity: str
) -> None:
    path = configuration[entity + "_path"]
    with TestClient(create_app(database_url)) as another_client:
        another_client.headers.update(admin.headers)
        saved = another_client.get(path).json()
        payload = {"name": "Winning change", "revision": saved["revision"]}
        if entity == "constituency":
            payload["code"] = "WIN"
        if entity == "candidate":
            payload["ballot_number"] = 2
        winning = admin.put(path, json=payload)
        assert winning.status_code == 200
        stale = another_client.put(path, json={**payload, "name": "Stale change"})
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"code": "revision_conflict"}}
        assert winning.json()["revision"] == saved["revision"] + 1
        assert another_client.get(path).json() == winning.json()


@pytest.mark.parametrize("entity", ["election", "constituency", "candidate"])
def test_create_retries_reuse_the_record_and_reject_a_changed_payload(
    admin: TestClient, configuration: dict, entity: str
) -> None:
    path = "/api/elections"
    request_id = str(uuid4())
    payload = {"name": "Replay 測試 " + request_id, "request_id": request_id}
    if entity == "constituency":
        path = configuration["election_path"] + "/constituencies"
        payload["code"] = "REPLAY"
    elif entity == "candidate":
        path = configuration["constituency_path"] + "/candidates"
        payload["ballot_number"] = 2
    created = admin.post(path, json=payload)
    assert created.status_code == 201
    retried = admin.post(path, json=payload)
    assert retried.status_code == 200
    assert retried.json() == created.json()
    changed = admin.post(path, json={**payload, "name": "Changed retry"})
    assert changed.status_code == 409
    assert changed.json() == {"detail": {"code": "request_conflict"}}
    assert [
        row for row in admin.get(path).json()["items"] if row["id"] == created.json()["id"]
    ] == [created.json()]
    assert sum(row["name"] == payload["name"] for row in admin.get(path).json()["items"]) == 1


def test_scoped_create_retry_key_cannot_be_reused_for_an_unrelated_parent(
    admin: TestClient, configuration: dict
) -> None:
    second_election = create_election(admin)
    constituency_payload = {"name": "Scope", "code": "R", "request_id": str(uuid4())}
    source_collection = configuration["election_path"] + "/constituencies"
    assert admin.post(source_collection, json=constituency_payload).status_code == 201
    target_collection = f"/api/elections/{second_election['id']}/constituencies"
    changed_parent = admin.post(target_collection, json=constituency_payload)
    assert changed_parent.status_code == 409
    assert changed_parent.json() == {"detail": {"code": "request_conflict"}}
    assert admin.get(target_collection).json()["items"] == []
    other_constituency = create_constituency(admin, configuration["election"]["id"], "S")
    candidate_payload = {"name": "Scope", "ballot_number": 2, "request_id": str(uuid4())}
    candidate_source = configuration["constituency_path"] + "/candidates"
    assert admin.post(candidate_source, json=candidate_payload).status_code == 201
    candidate_target = (
        f"{configuration['election_path']}/constituencies/{other_constituency['id']}/candidates"
    )
    changed_parent = admin.post(candidate_target, json=candidate_payload)
    assert changed_parent.status_code == 409
    assert changed_parent.json() == {"detail": {"code": "request_conflict"}}
    assert admin.get(candidate_target).json()["items"] == []


def test_full_configuration_survives_server_recreation(
    admin: TestClient, database_url: str, configuration: dict
) -> None:
    with TestClient(create_app(database_url)) as restarted:
        restarted.headers.update(admin.headers)
        for entity in ("election", "constituency", "candidate"):
            response = restarted.get(configuration[entity + "_path"])
            assert response.status_code == 200
            assert response.json() == configuration[entity]
        assert restarted.get(configuration["election_path"] + "/constituencies").json()[
            "items"
        ] == [configuration["constituency"]]
        assert restarted.get(configuration["constituency_path"] + "/candidates").json()[
            "items"
        ] == [configuration["candidate"]]


@pytest.mark.parametrize("entity", ["election", "constituency", "candidate"])
def test_overlapping_edits_accept_only_one_writer_for_the_same_revision(
    admin: TestClient, database_url: str, configuration: dict, entity: str
) -> None:
    start = Barrier(2)
    path = configuration[entity + "_path"]

    def submit(name: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            payload = {"name": name, "revision": 1}
            if entity == "constituency":
                payload["code"] = name
            if entity == "candidate":
                payload["ballot_number"] = 1
            start.wait(timeout=5)
            response = client.put(path, json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ("First writer", "Second writer")))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    assert winner["revision"] == 2
    assert admin.get(path).json() == winner


@pytest.mark.parametrize("entity", ["election", "constituency", "candidate"])
def test_concurrent_create_retries_return_the_same_resource_without_duplicates(
    admin: TestClient, database_url: str, configuration: dict, entity: str
) -> None:
    start = Barrier(2)
    request_id = str(uuid4())
    path = "/api/elections"
    payload = {"name": "Concurrent retry " + request_id, "request_id": request_id}
    if entity == "constituency":
        path = configuration["election_path"] + "/constituencies"
        payload["code"] = "RETRY"
    elif entity == "candidate":
        path = configuration["constituency_path"] + "/candidates"
        payload["ballot_number"] = 2

    def submit(_: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.post(path, json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (1, 2)))
    assert sorted(status for status, _ in outcomes) == [200, 201]
    assert outcomes[0][1] == outcomes[1][1]
    assert [row for row in admin.get(path).json()["items"] if row["name"] == payload["name"]] == [
        outcomes[0][1]
    ]
