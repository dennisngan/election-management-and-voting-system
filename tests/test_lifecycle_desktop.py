"""Schedule editing uses real Qt HTTPS/MySQL in a dedicated lifecycle database."""

from collections.abc import Iterator
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QTimer

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.configuration_support import create_election
from tests.desktop_support import PERSONAL_PASSWORD, HttpsServer, wait_for
from tests.lifecycle_support import (
    complete_configuration,
    lifecycle_database_url,
    lifecycle_test_state,
    prepared_election,
    schedule_payload,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_desktop_saves_hong_kong_schedule_and_explicitly_activates_saved_election(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    database_url: str,
    qt_app: QCoreApplication,
) -> None:
    configuration = ready_setup(desktop, https_server, account, qt_app)
    with TestClient(create_app(database_url, now=https_server.clock)) as other:
        login = other.post(
            "/api/auth/login", json={"username": account["username"], "password": PERSONAL_PASSWORD}
        )
        assert login.status_code == 200
        other.headers["Authorization"] = "Bearer " + login.json()["token"]
        election = create_election(other)
        complete_configuration(other, election["id"])
    lifecycle = desktop.property("lifecycle")
    assert lifecycle is not None
    assert lifecycle.loadElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    state = lifecycle.property("state")
    assert state["selected"]["id"] == election["id"]
    assert state["schedule"] == {}
    assert state["forms"] == {
        "election_date": "",
        "planned_opening": "",
        "planned_closing": "",
        "reporting_interval_minutes": "60",
    }
    for field, value in {
        "election_date": "2026-11-15",
        "planned_opening": "2026-11-15 07:30",
        "planned_closing": "2026-11-15 22:30",
        "reporting_interval_minutes": "30",
    }.items():
        lifecycle.setField(field, value)
    lifecycle.save()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    saved = lifecycle.property("state")
    assert saved["error"] == ""
    assert saved["dirty"] is False
    assert saved["schedule"]["revision"] == 1
    assert saved["forms"]["planned_opening"] == "2026-11-15 07:30"
    assert saved["forms"]["planned_closing"] == "2026-11-15 22:30"
    assert configuration.property("state")["selected"]["election"] == {}
    lifecycle.activate()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    activated = lifecycle.property("state")
    assert activated["error"] == ""
    assert activated["selected"]["status"] == "active"
    assert activated["selected"]["revision"] == 2
    assert activated["active_election"]["id"] == election["id"]
    assert activated["active_election"]["schedule"] == activated["schedule"]
    assert lifecycle.loadElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["forms"] == saved["forms"]


@pytest.fixture
def lifecycle_setup(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[tuple[Any, TestClient]]:
    ready_setup(desktop, https_server, account, qt_app)
    with TestClient(create_app(database_url, now=https_server.clock)) as other:
        login = other.post(
            "/api/auth/login", json={"username": account["username"], "password": PERSONAL_PASSWORD}
        )
        assert login.status_code == 200
        other.headers["Authorization"] = "Bearer " + login.json()["token"]
        yield desktop.property("lifecycle"), other


def load_prepared(lifecycle: Any, other: TestClient, qt_app: QCoreApplication) -> tuple[dict, dict]:
    election, schedule = prepared_election(other)
    assert lifecycle.loadElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["selected"]["id"] == election["id"]
    return election, schedule


@pytest.mark.parametrize(
    "changes",
    [
        {"election_date": "2026-02-30"},
        {"election_date": "2026-1-15"},
        {"planned_opening": ""},
        {"planned_opening": "2026-11-16 07:30"},
        {"planned_opening": "2026-11-15T07:30+08:00"},
        {"planned_closing": "2026-11-15 07:30"},
        {"planned_closing": "2026-11-15 07:29"},
        {"reporting_interval_minutes": "0"},
        {"reporting_interval_minutes": "1441"},
        {"reporting_interval_minutes": "9" * 5000},
    ],
)
def test_invalid_schedule_input_is_preserved_without_a_network_save(
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    changes: dict[str, str],
) -> None:
    lifecycle, other = lifecycle_setup
    election, _ = load_prepared(lifecycle, other, qt_app)
    path = f"/api/elections/{election['id']}/schedule"
    before = https_server.request_count("PUT", path)
    for field, value in changes.items():
        lifecycle.setField(field, value)
    entered = lifecycle.property("state")["forms"]
    lifecycle.save()
    state = lifecycle.property("state")
    assert state["error"] == "schedule_validation"
    assert state["forms"] == entered
    assert state["dirty"] is True
    assert state["busy"] is False
    lifecycle.refresh()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert https_server.request_count("PUT", path) == before
    assert lifecycle.property("state")["forms"] == entered


def test_explicit_next_day_closing_is_saved_and_reopened_in_hong_kong_time(
    lifecycle_setup: tuple[Any, TestClient], qt_app: QCoreApplication
) -> None:
    lifecycle, other = lifecycle_setup
    election, _ = load_prepared(lifecycle, other, qt_app)
    lifecycle.setField("planned_closing", "2026-11-16 00:30")
    lifecycle.save()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    state = lifecycle.property("state")
    assert state["error"] == ""
    assert state["forms"]["planned_closing"] == "2026-11-16 00:30"
    assert datetime.fromisoformat(state["schedule"]["planned_closing_at"]) == datetime(
        2026, 11, 15, 16, 30, tzinfo=UTC
    )
    assert lifecycle.loadElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["forms"] == state["forms"]


def test_background_refresh_accepts_edits_and_dirty_selection_requires_explicit_discard(
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    lifecycle, other = lifecycle_setup
    election, _ = load_prepared(lifecycle, other, qt_app)
    destination, _ = prepared_election(other)
    https_server.hold_configuration_list = True
    lifecycle.refresh()
    wait_for(qt_app, https_server.configuration_list_entered.is_set)
    try:
        lifecycle.setField("reporting_interval_minutes", "30")
        assert lifecycle.property("state")["forms"]["reporting_interval_minutes"] == "30"
    finally:
        https_server.release_configuration_list.set()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    before = lifecycle.property("state")
    assert before["selected"]["id"] == election["id"]
    assert before["dirty"] is True
    assert lifecycle.loadElection(destination["id"], False) is False
    assert lifecycle.property("state") == before
    assert lifecycle.loadElection(destination["id"], True)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    after = lifecycle.property("state")
    assert after["selected"]["id"] == destination["id"]
    assert after["forms"]["reporting_interval_minutes"] == "60"
    assert after["dirty"] is False


def test_schedule_conflict_keeps_local_entries_until_explicit_reload(
    lifecycle_setup: tuple[Any, TestClient], qt_app: QCoreApplication
) -> None:
    lifecycle, other = lifecycle_setup
    election, schedule = load_prepared(lifecycle, other, qt_app)
    path = f"/api/elections/{election['id']}/schedule"
    changed = other.put(
        path, json=schedule_payload(revision=schedule["revision"], reporting_interval_minutes=15)
    )
    assert changed.status_code == 200
    lifecycle.setField("reporting_interval_minutes", "30")
    lifecycle.refresh()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["schedule"] == schedule
    lifecycle.save()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    rejected = lifecycle.property("state")
    assert rejected["error"] == "revision_conflict"
    assert rejected["forms"]["reporting_interval_minutes"] == "30"
    assert rejected["schedule"] == schedule
    assert lifecycle.loadElection(election["id"], False) is False
    assert lifecycle.loadElection(election["id"], True)
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["schedule"] == changed.json()
    assert lifecycle.property("state")["forms"]["reporting_interval_minutes"] == "15"


def test_activation_refuses_dirty_forms_and_active_selection_is_read_only(
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    lifecycle, other = lifecycle_setup
    election, _ = load_prepared(lifecycle, other, qt_app)
    path = f"/api/elections/{election['id']}/activate"
    requests = https_server.request_count("POST", path)
    lifecycle.setField("reporting_interval_minutes", "30")
    lifecycle.activate()
    assert lifecycle.property("state")["error"] == "unsaved_schedule"
    assert lifecycle.property("state")["forms"]["reporting_interval_minutes"] == "30"
    lifecycle.refresh()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert https_server.request_count("POST", path) == requests
    lifecycle.setField("reporting_interval_minutes", "60")
    assert lifecycle.property("state")["dirty"] is False
    lifecycle.activate()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    activated = lifecycle.property("state")
    assert activated["selected"]["status"] == "active"
    lifecycle.setField("reporting_interval_minutes", "30")
    assert lifecycle.property("state")["forms"] == activated["forms"]
    lifecycle.save()
    assert lifecycle.property("state")["error"] == "draft_required"
    assert lifecycle.property("state")["schedule"] == activated["schedule"]


def test_conflicting_active_election_is_visible_without_replacing_the_selected_draft(
    lifecycle_setup: tuple[Any, TestClient], qt_app: QCoreApplication
) -> None:
    lifecycle, other = lifecycle_setup
    selected, schedule = load_prepared(lifecycle, other, qt_app)
    different, planned = prepared_election(other)
    active = other.post(
        f"/api/elections/{different['id']}/activate",
        json={"election_revision": 1, "schedule_revision": planned["revision"]},
    )
    assert active.status_code == 200
    lifecycle.refresh()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    before = lifecycle.property("state")
    assert before["active_election"]["id"] == different["id"]
    assert before["selected"]["id"] == selected["id"]
    lifecycle.activate()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    after = lifecycle.property("state")
    assert after["error"] == "active_election_conflict"
    assert after["selected"] == before["selected"]
    assert after["schedule"] == schedule
    assert after["forms"] == before["forms"]


def test_logout_ignores_a_delayed_old_refresh_and_clears_schedule_inputs(
    desktop: DesktopController,
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    lifecycle, other = lifecycle_setup
    load_prepared(lifecycle, other, qt_app)
    https_server.hold_configuration_list = True
    lifecycle.refresh()
    wait_for(qt_app, https_server.configuration_list_entered.is_set)
    desktop.signOut()
    cleared = lifecycle.property("state")
    assert cleared["elections"] == []
    assert cleared["selected"] == {}
    assert cleared["schedule"] == {}
    assert cleared["active_election"] is None
    assert cleared["forms"]["election_date"] == ""
    https_server.release_configuration_list.set()
    settled = Event()
    QTimer.singleShot(300, settled.set)
    wait_for(qt_app, settled.is_set)
    assert lifecycle.property("state") == cleared
    assert lifecycle.loadElection(1, False) is False


def test_activation_updates_root_context_and_locks_configuration_without_erasing_unsaved_text(
    desktop: DesktopController,
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    lifecycle, other = lifecycle_setup
    election, _ = load_prepared(lifecycle, other, qt_app)
    configuration = desktop.property("configuration")
    assert configuration.load("election", election["id"], False)
    wait_for(qt_app, lambda: setup_idle(configuration))
    configuration.setField("election", "name", "啟用時仍保留的未儲存名稱")
    assert configuration.property("state")["dirty"]["election"] is True
    lifecycle.activate()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["selected"]["status"] == "active"
    desktop.refresh()
    wait_for(
        qt_app,
        lambda: (
            (desktop.property("state").get("active_election") or {}).get("id") == election["id"]
        ),
    )
    state = configuration.property("state")
    assert state["read_only"] is True
    assert state["election_status"] == "active"
    assert state["forms"]["election"]["name"] == "啟用時仍保留的未儲存名稱"
    assert state["dirty"]["election"] is True
    configuration.setField("election", "name", "啟用後不應接受的新文字")
    assert (
        configuration.property("state")["forms"]["election"]["name"] == "啟用時仍保留的未儲存名稱"
    )
    path = f"/api/elections/{election['id']}"
    requests_before = https_server.request_count("PUT", path)
    configuration.save("election")
    wait_for(qt_app, lambda: setup_idle(configuration))
    assert configuration.property("state")["error"] == "read_only_election"
    assert https_server.request_count("PUT", path) == requests_before
    assert other.get(path).json()["name"] == election["name"]
    assert (
        configuration.property("state")["forms"]["election"]["name"] == "啟用時仍保留的未儲存名稱"
    )


def test_external_admin_activation_freezes_schedule_edits_without_replacing_reviewed_values(
    desktop: DesktopController,
    lifecycle_setup: tuple[Any, TestClient],
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    lifecycle, other = lifecycle_setup
    election, schedule = load_prepared(lifecycle, other, qt_app)
    lifecycle.setField("reporting_interval_minutes", "30")
    reviewed = lifecycle.property("state")
    username = "schedule_other_admin_" + uuid4().hex[:12]
    temporary = "Schedule-Other-Admin-42!"
    created = other.post(
        "/api/accounts",
        json={
            "username": username,
            "display_name": "另一位時間表管理員",
            "role": "administrator",
            "enabled": True,
            "station_ids": [],
            "temporary_password": temporary,
        },
    )
    assert created.status_code == 201
    login = other.post("/api/auth/login", json={"username": username, "password": temporary})
    assert login.status_code == 200
    other.headers["Authorization"] = "Bearer " + login.json()["token"]
    ready = other.post(
        "/api/auth/password",
        json={"current_password": temporary, "new_password": "Schedule-Other-Admin-Ready-84!"},
    )
    assert ready.status_code == 200
    other.headers["Authorization"] = "Bearer " + ready.json()["token"]
    assert (
        other.get("/api/auth/me").json()["username"]
        != desktop.property("state")["account"]["username"]
    )
    activated = other.post(
        f"/api/elections/{election['id']}/activate",
        json={"election_revision": election["revision"], "schedule_revision": schedule["revision"]},
    )
    assert activated.status_code == 200
    lifecycle.refresh()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    current = lifecycle.property("state")
    assert current["active_election"] == activated.json()["election"]
    assert current.get("read_only", False) is True
    assert current["selected"] == reviewed["selected"]
    assert current["schedule"] == reviewed["schedule"]
    assert current["forms"] == reviewed["forms"]
    assert current["dirty"] is True
    lifecycle.setField("reporting_interval_minutes", "15")
    assert lifecycle.property("state")["forms"] == reviewed["forms"]
    path = f"/api/elections/{election['id']}/schedule"
    saves = https_server.request_count("PUT", path)
    lifecycle.save()
    wait_for(qt_app, lambda: setup_idle(lifecycle))
    assert lifecycle.property("state")["error"] == "draft_required"
    assert https_server.request_count("PUT", path) == saves
    assert lifecycle.property("state")["forms"] == reviewed["forms"]
    assert lifecycle.property("state")["schedule"] == schedule
