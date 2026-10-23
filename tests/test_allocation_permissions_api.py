"""Allocation scope and write guards are exercised through the real MySQL API."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.server.configuration_models import Election
from election.server.db import make_engine
from tests.lifecycle_support import lifecycle_database_url
from tests.stock_support import ready_client, staff_account
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture
def allocation_versions(allocation_setup: dict) -> dict:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    create_command = allocation_payload(setup["counter"]["id"])
    created = officer.post(path, json=create_command)
    assert created.status_code == 201
    original = created.json()
    target = path + f"/{original['id']}"
    correction = allocation_payload(
        setup["counter"]["id"],
        revision=1,
        serial_from="000002",
        serial_to="000004",
        reason="核對櫃台交收文件，更正派票範圍",
    )
    amended = officer.put(target, json=correction)
    assert amended.status_code == 200
    return {
        **setup,
        "path": path,
        "target": target,
        "original": original,
        "current": amended.json(),
        "create_command": create_command,
        "correction": correction,
    }


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_readers_reopen_current_and_immutable_allocation_history(
    allocation_versions: dict, admin: TestClient, database_url: str, role: str
) -> None:
    setup = allocation_versions
    account = staff_account(admin, [setup["station"]["id"]], role)
    with ready_client(database_url, account) as reader:
        listed = reader.get(setup["path"])
        assert listed.status_code == 200
        view = listed.json()
        assert view["scope"]["station"]["id"] == setup["station"]["id"]
        assert view["items"] == [setup["current"]]
        assert view["availability"][0]["available_quantity"] == 5
        current = reader.get(setup["target"])
        assert current.status_code == 200 and current.json() == setup["current"]
        original = reader.get(setup["target"] + "?revision=1")
        assert original.status_code == 200 and original.json() == setup["original"]
        history = reader.get(setup["target"] + "/history")
        assert history.status_code == 200
        assert history.json()["items"] == [setup["original"], setup["current"]]


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_readers_cannot_write_or_replay_successful_allocation_commands(
    allocation_versions: dict, admin: TestClient, database_url: str, role: str
) -> None:
    setup = allocation_versions
    account = staff_account(admin, [setup["station"]["id"]], role)
    with ready_client(database_url, account) as reader:
        for method, path, command in (
            ("POST", setup["path"], setup["create_command"]),
            ("PUT", setup["target"], setup["correction"]),
        ):
            for payload in (command, {**command, "request_id": str(uuid4())}):
                denied = reader.request(method, path, json=payload)
                assert denied.status_code == 403
                assert denied.json() == {"detail": {"code": "operational_role_required"}}
    history = setup["officer"].get(setup["target"] + "/history")
    assert history.status_code == 200
    assert history.json()["items"] == [setup["original"], setup["current"]]


def test_administrator_cannot_read_write_or_replay_operational_allocations(
    allocation_versions: dict, admin: TestClient
) -> None:
    setup = allocation_versions
    for method, path, payload in (
        ("GET", setup["path"], None),
        ("GET", setup["target"], None),
        ("GET", setup["target"] + "?revision=1", None),
        ("GET", setup["target"] + "/history", None),
        ("POST", setup["path"], setup["create_command"]),
        ("PUT", setup["target"], setup["correction"]),
    ):
        denied = admin.request(method, path, json=payload)
        assert denied.status_code == 403
        assert denied.json() == {"detail": {"code": "operational_role_required"}}
    assert setup["officer"].get(setup["target"]).json() == setup["current"]


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_other_station_assignments_do_not_reveal_allocations_or_bypass_replay_guards(
    allocation_versions: dict, admin: TestClient, database_url: str, role: str
) -> None:
    setup = allocation_versions
    account = staff_account(admin, [setup["stations"][1]["id"]], role)
    with ready_client(database_url, account) as outsider:
        for path in (
            setup["path"],
            setup["target"],
            setup["target"] + "?revision=1",
            setup["target"] + "/history",
            setup["path"] + "/9223372036854775807",
            setup["path"] + "/9223372036854775807/history",
        ):
            denied = outsider.get(path)
            assert denied.status_code == 403
            assert denied.json() == {"detail": {"code": "station_access_denied"}}
        for method, path, payload in (
            ("POST", setup["path"], setup["create_command"]),
            ("PUT", setup["target"], setup["correction"]),
        ):
            denied = outsider.request(method, path, json=payload)
            assert denied.status_code == 403
            expected = (
                "station_access_denied"
                if role == "polling_officer"
                else "operational_role_required"
            )
            assert denied.json() == {"detail": {"code": expected}}
    history = setup["officer"].get(setup["target"] + "/history")
    assert history.status_code == 200
    assert history.json()["items"] == [setup["original"], setup["current"]]


def test_finalized_allocations_remain_readable_but_reject_new_and_replayed_writes(
    allocation_versions: dict, database_url: str
) -> None:
    setup = allocation_versions
    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.database and parsed.database.endswith("_lifecycle_test")
    engine = make_engine(database_url)
    original_status = None
    try:
        # Arrange only this synthetic election state, as in received-stock guards.
        # This verifies the write guard, not the future Ticket 24 finalization workflow.
        with Session(engine) as db:
            election = db.get(Election, setup["station"]["election_id"])
            assert election is not None
            original_status = election.status
            election.status = "finalized"
            db.commit()
        officer = setup["officer"]
        listed = officer.get(setup["path"])
        assert listed.status_code == 200
        assert listed.json()["scope"]["election"]["status"] == "finalized"
        assert listed.json()["items"] == [setup["current"]]
        assert officer.get(setup["target"]).json() == setup["current"]
        assert officer.get(setup["target"] + "?revision=1").json() == setup["original"]
        for method, path, command in (
            ("POST", setup["path"], setup["create_command"]),
            ("PUT", setup["target"], setup["correction"]),
        ):
            for payload in (command, {**command, "request_id": str(uuid4())}):
                denied = officer.request(method, path, json=payload)
                assert denied.status_code == 409
                assert denied.json() == {"detail": {"code": "election_read_only"}}
        history = officer.get(setup["target"] + "/history")
        assert history.status_code == 200
        assert history.json()["items"] == [setup["original"], setup["current"]]
    finally:
        try:
            with Session(engine) as db:
                election = db.get(Election, setup["station"]["election_id"])
                if election is not None and original_status is not None:
                    election.status = original_status
                db.commit()
        finally:
            engine.dispose()
