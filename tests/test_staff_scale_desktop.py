"""Staff directory refreshes must leave another desktop's authentication usable."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.desktop.controller import DesktopController
from election.server.configuration_models import Constituency, Election
from election.server.db import make_engine
from election.server.models import Account, AuditEvent, LoginSession
from election.server.security import hash_password
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation
from tests.configuration_desktop_support import ready_setup
from tests.desktop_support import (
    TLS_DIRECTORY,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_command,
    wait_for_editor_idle,
)

DIRECTORY_SIZE = 1500


@dataclass(frozen=True)
class LargeStaffDirectory:
    accounts: dict[int, dict[str, Any]]
    station_contexts: dict[int, dict[str, Any]]


@pytest.fixture
def large_election_test_staff_directory(
    database_url: str, admin: TestClient
) -> Iterator[LargeStaffDirectory]:
    """Arrange an exact synthetic subset only in the named disposable database."""
    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql"
    assert (
        parsed.database
        and parsed.database.endswith("_test")
        and not parsed.database.endswith("_lifecycle_test")
    ), (
        "Refusing large-directory seeds outside a dedicated ordinary test database"
    )
    engine = make_engine(database_url)
    account_ids: list[int] = []
    station_ids: list[int] = []
    constituency_ids: list[int] = []
    election_id: int | None = None
    prefix = "scale_fixture_" + uuid4().hex[:12]
    now = datetime.now(UTC).replace(tzinfo=None)
    password_hash = hash_password("Scale-Fixture-Unused-Password-42!")
    accounts: dict[int, dict[str, Any]] = {}
    station_contexts: dict[int, dict[str, Any]] = {}
    try:
        with Session(engine) as db:
            election = Election(
                name=prefix + " 大名冊測試選舉",
                status="draft",
                revision=1,
                request_id=str(uuid4()),
                creation_digest="0" * 64,
                created_at=now,
                updated_at=now,
            )
            db.add(election)
            db.flush()
            election_id = election.id
            constituencies = [
                Constituency(
                    election_id=election.id,
                    name=f"大名冊測試選區 {number}",
                    code=f"SCALE{number}",
                    seats=1,
                    choices_per_ballot=1,
                    revision=1,
                    request_id=str(uuid4()),
                    creation_digest="0" * 64,
                    created_at=now,
                    updated_at=now,
                )
                for number in (1, 2)
            ]
            db.add_all(constituencies)
            db.flush()
            constituency_ids = [row.id for row in constituencies]
            stations = [
                PollingStation(
                    constituency_id=constituencies[number % 2].id,
                    name=f"大名冊測試票站 {number}",
                    code=f"P{number:04d}",
                    counting_mode="local",
                    destination_station_id=None,
                    revision=1,
                    request_id=str(uuid4()),
                    creation_digest="0" * 64,
                    created_at=now,
                    updated_at=now,
                )
                for number in range(DIRECTORY_SIZE)
            ]
            roles = ("polling_officer", "counting_officer", "supervisor")
            staff = [
                Account(
                    username=f"{prefix}_{number:04d}",
                    display_name=f"大名冊測試職員 {number}",
                    role=roles[number % len(roles)],
                    password_hash=password_hash,
                    must_change_password=True,
                    enabled=number % 2 == 0,
                    revision=1,
                    created_at=now,
                )
                for number in range(DIRECTORY_SIZE)
            ]
            db.add_all(stations)
            db.add_all(staff)
            db.flush()
            station_ids = [row.id for row in stations]
            account_ids = [row.id for row in staff]
            db.add_all(
                [
                    StationAssignment(account_id=row.id, station_id=station.id, created_at=now)
                    for row, station in zip(staff, stations, strict=True)
                ]
            )
            for number, (row, station) in enumerate(zip(staff, stations, strict=True)):
                accounts[row.id] = {
                    "id": row.id,
                    "username": row.username,
                    "display_name": row.display_name,
                    "role": row.role,
                    "must_change_password": True,
                    "enabled": row.enabled,
                    "revision": 1,
                    "station_ids": [station.id],
                }
                constituency = constituencies[number % 2]
                station_contexts[station.id] = {
                    "election": {"id": election.id, "name": election.name, "status": "draft"},
                    "constituency": {
                        "id": constituency.id,
                        "name": constituency.name,
                        "code": constituency.code,
                    },
                    "station": {
                        "id": station.id,
                        "name": station.name,
                        "code": station.code,
                        "counting_mode": "local",
                        "destination_station_id": None,
                    },
                }
            db.commit()
        yield LargeStaffDirectory(accounts, station_contexts)
    finally:
        try:
            with Session(engine) as db:
                if account_ids:
                    db.execute(
                        delete(StationAssignment).where(
                            StationAssignment.account_id.in_(account_ids)
                        )
                    )
                    db.execute(delete(LoginSession).where(LoginSession.account_id.in_(account_ids)))
                    db.execute(delete(AuditEvent).where(AuditEvent.actor_id.in_(account_ids)))
                    db.execute(delete(Account).where(Account.id.in_(account_ids)))
                if station_ids:
                    db.execute(delete(PollingStation).where(PollingStation.id.in_(station_ids)))
                if constituency_ids:
                    db.execute(delete(Constituency).where(Constituency.id.in_(constituency_ids)))
                if election_id is not None:
                    db.execute(delete(Election).where(Election.id == election_id))
                db.commit()
            remaining_accounts = admin.get("/api/accounts")
            remaining_stations = admin.get("/api/accounts/station-options")
            assert remaining_accounts.status_code == remaining_stations.status_code == 200
            assert not set(account_ids).intersection(
                row["id"] for row in remaining_accounts.json()["items"]
            )
            assert not set(station_ids).intersection(
                row["station"]["id"] for row in remaining_stations.json()["items"]
            )
        finally:
            engine.dispose()


def test_officer_old_password_is_rejected_while_an_administrator_desktop_refreshes(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    large_election_test_staff_directory: LargeStaffDirectory,
) -> None:
    ready_setup(desktop, https_server, account, qt_app)
    staff = desktop.property("staff")
    staff.open()
    wait_for_editor_idle(qt_app, staff)
    assert staff.property("state")["error"] == ""
    directory = large_election_test_staff_directory
    state = staff.property("state")
    visible_accounts = {
        row["id"]: row for row in state["accounts"] if row["id"] in directory.accounts
    }
    assert len(visible_accounts) == DIRECTORY_SIZE
    assert visible_accounts == directory.accounts
    visible_stations = {
        row["station"]["id"]: row
        for row in state["station_options"]
        if row["station"]["id"] in directory.station_contexts
    }
    assert len(visible_stations) == DIRECTORY_SIZE
    own_account = next(
        row for row in state["accounts"] if row["id"] == state_of(desktop)["account"]["id"]
    )
    for station_id, expected in directory.station_contexts.items():
        context = visible_stations[station_id]
        assert {key: context[key] for key in expected} == expected
        assert context["account"] == own_account
        assert context["capabilities"] == {
            "prepare_polling": False,
            "prepare_counting": False,
            "approve": False,
        }
    username = "scale_officer_" + uuid4().hex[:12]
    initial_password = "Scale-Initial-Password-42!"
    personal_password = "Scale-Personal-Password-84!"
    reset_password = "Scale-Reset-Password-126!"
    assert staff.loadAccount(0, False)
    staff.setField("username", username)
    staff.setField("display_name", "規模測試職員")
    staff.save(initial_password, initial_password)
    # Credential setup observes command acknowledgements while dashboard refresh
    # remains enabled. The complete directory assertions above stay independent.
    wait_for_editor_command(qt_app, staff)
    assert staff.property("state")["error"] == ""
    created = staff.property("state")["selected"]
    assert created["username"] == username
    assert type(created["id"]) is int and created["id"] > 0

    officer = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        officer.signIn(https_server.url, username, initial_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "password_change")
        officer.changePassword(initial_password, personal_password, personal_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "workspace")
        assert staff.loadAccount(created["id"], False)
        wait_for_editor_command(qt_app, staff)
        loaded = staff.property("state")
        assert loaded["error"] == ""
        assert loaded["selected"]["id"] == created["id"]
        assert loaded["selected"]["must_change_password"] is False
        previous_revision = loaded["selected"]["revision"]
        staff.resetPassword(reset_password, reset_password)
        wait_for_editor_command(qt_app, staff)
        reset = staff.property("state")
        assert reset["error"] == ""
        assert reset["notice"] == "password_reset_success"
        assert reset["selected"]["id"] == created["id"]
        assert reset["selected"]["must_change_password"] is True
        assert reset["selected"]["revision"] == previous_revision + 1
        officer.refresh()
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "signed_out")
        assert state_of(officer)["error"] == "session_expired"
        officer.signIn(https_server.url, username, personal_password)
        wait_for(qt_app, lambda: state_of(officer)["error"] == "invalid_credentials")
        assert state_of(officer)["phase"] == "signed_out"
    finally:
        officer.shutdown()
        officer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
