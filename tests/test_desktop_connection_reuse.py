"""Credential commands survive idle sockets while concurrent public reads continue."""

import time
from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup
from tests.desktop_support import HttpsServer, sign_in, state_of, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url
from tests.test_staff_desktop import create_officer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_bad_login_after_idle_preserves_concurrent_health_and_sends_one_credential_command(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    ready_setup(desktop, https_server, account, qt_app)
    desktop.signOut()
    wait_for(qt_app, lambda: https_server.request_count("DELETE", "/api/auth/session") == 1)
    # Drain the local logout response before deliberately withholding Qt events.
    # This models a busy/resuming client across the server's five-second idle close.
    QTest.qWait(100)
    before_login = https_server.request_count("POST", "/api/auth/login")
    before_health = https_server.request_count("GET", "/api/health")
    time.sleep(5.3)
    desktop.refresh()
    desktop.signIn(https_server.url, account["username"], "Incorrect-Idle-Password!")
    wait_for(qt_app, lambda: not state_of(desktop)["busy"])
    assert state_of(desktop)["error"] == "invalid_credentials"
    wait_for(qt_app, lambda: https_server.request_count("GET", "/api/health") > before_health)
    QTest.qWait(100)
    assert state_of(desktop)["connection"] == "connected"
    assert state_of(desktop)["phase"] == "signed_out"
    assert https_server.request_count("POST", "/api/auth/login") == before_login + 1


def test_password_reset_preserves_a_concurrent_held_profile_and_sends_one_reset(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    ready_setup(desktop, https_server, account, qt_app)
    staff = desktop.property("staff")
    staff.open()
    wait_for_editor_idle(qt_app, staff)
    created, _ = create_officer(staff, qt_app)
    https_server.hold_profile = True
    desktop.refresh()
    wait_for(qt_app, https_server.profile_entered.is_set)
    path = f"/api/accounts/{created['id']}/password-reset"
    before = https_server.request_count("POST", path)
    previous_revision = staff.property("state")["selected"]["revision"]
    password = "Transport-Reset-Test-126!"
    staff.resetPassword(password, password)
    wait_for(qt_app, lambda: not staff.property("state")["busy"])
    reset = staff.property("state")
    assert reset["error"] == ""
    assert reset["notice"] == "password_reset_success"
    assert reset["selected"]["id"] == created["id"]
    assert reset["selected"]["must_change_password"] is True
    assert reset["selected"]["revision"] == previous_revision + 1
    assert https_server.request_count("POST", path) == before + 1
    assert not https_server.profile_finished.is_set()
    assert state_of(desktop)["error"] == ""
    https_server.release_profile.set()
    wait_for(qt_app, https_server.profile_finished.is_set)
    QTest.qWait(100)
    assert state_of(desktop)["phase"] == "workspace"
    assert state_of(desktop)["error"] == ""
    assert state_of(desktop)["connection"] == "connected"


def test_held_profile_waits_for_explicit_release_while_qt_processes_events(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    https_server.hold_profile = True
    sign_in(desktop, https_server, account, qt_app)
    wait_for(qt_app, https_server.profile_entered.is_set)
    # Sign-in's real authenticated refresh stays held beyond the former fixture
    # timeout. Process Qt events and yield to the Python server thread throughout,
    # staying below the unchanged eight-second transport limit.
    held_until = time.monotonic() + 5.3
    while time.monotonic() < held_until:
        QTest.qWait(10)
        time.sleep(0.01)
    assert not https_server.release_profile.is_set()
    assert not https_server.profile_finished.is_set()
    https_server.release_profile.set()
    wait_for(qt_app, https_server.profile_finished.is_set)
    assert https_server.delayed_profile_status == 200
    QTest.qWait(100)
    assert state_of(desktop)["phase"] == "password_change"
    assert state_of(desktop)["error"] == ""
    assert state_of(desktop)["connection"] == "connected"
