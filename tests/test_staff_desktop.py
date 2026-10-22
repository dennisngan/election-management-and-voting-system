"""Individual staff access is managed through public Qt slots and real HTTPS/MySQL."""

import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, save_form, setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, texts_of, wait_for


@pytest.fixture
def ready_staff(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> Any:
    ready_setup(desktop, https_server, account, qt_app)
    staff = desktop.property("staff")
    assert staff is not None
    staff.open()
    wait_for(qt_app, lambda: setup_idle(staff))
    assert staff.property("state")["error"] == ""
    return staff


def create_officer(staff: Any, qt_app: QCoreApplication) -> tuple[dict, str]:
    password = "Desktop-Staff-Initial-42!"
    assert staff.loadAccount(0, False)
    staff.setField("username", "desktop_staff_" + uuid4().hex[:12])
    staff.setField("display_name", "職員測試帳戶")
    staff.setField("role", "polling_officer")
    staff.save(password, password)
    wait_for(qt_app, lambda: setup_idle(staff))
    assert staff.property("state")["error"] == ""
    return staff.property("state")["selected"], password


def test_desktop_creates_assigned_officer_and_edit_revokes_their_first_login_session(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    configuration = ready_setup(desktop, https_server, account, qt_app)
    election = save_form(configuration, qt_app, "election", {"name": "職員桌面權限測試"})
    constituency = save_form(
        configuration, qt_app, "constituency", {"name": "職員測試選區", "code": "STAFF"}
    )
    station = save_form(
        configuration, qt_app, "station", {"name": "職員獲派票站", "code": "ASSIGNED"}
    )
    staff = desktop.property("staff")
    assert staff is not None
    staff.open()
    wait_for(qt_app, lambda: setup_idle(staff))
    state = staff.property("state")
    assert state["error"] == ""
    assert any(row["username"] == account["username"] for row in state["accounts"])
    option = next(row for row in state["station_options"] if row["station"]["id"] == station["id"])
    assert option["election"]["id"] == election["id"]
    assert option["constituency"]["id"] == constituency["id"]
    assert option["station"]["name"] == station["name"]

    username = "desktop_staff_" + uuid4().hex[:12]
    temporary_password = "Desktop-Staff-Initial-42!"
    assert staff.loadAccount(0, False)
    staff.setField("username", username)
    staff.setField("display_name", "  陳美華職員  ")
    staff.setField("role", "polling_officer")
    staff.setStationAssigned(station["id"], True)
    assert staff.property("state")["dirty"] is True
    staff.save(temporary_password, temporary_password)
    wait_for(qt_app, lambda: setup_idle(staff))
    saved = staff.property("state")
    assert saved["error"] == ""
    assert saved["dirty"] is False
    created = saved["selected"]
    assert created["username"] == username
    assert created["display_name"] == "  陳美華職員  "
    assert created["role"] == "polling_officer"
    assert created["enabled"] is True
    assert created["must_change_password"] is True
    assert created["revision"] == 1
    assert created["station_ids"] == [station["id"]]

    officer = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        officer.signIn(https_server.url, username, temporary_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "password_change")
        assert state_of(officer)["account"]["username"] == username
        assert state_of(officer)["account"]["must_change_password"] is True

        assert staff.loadAccount(created["id"], False)
        wait_for(qt_app, lambda: setup_idle(staff))
        loaded = staff.property("state")
        assert loaded["selected"] == created
        assert loaded["form"] == {
            "username": username,
            "display_name": "  陳美華職員  ",
            "role": "polling_officer",
            "enabled": True,
            "station_ids": [station["id"]],
        }
        staff.setField("display_name", "陳美華點票職員")
        staff.setField("role", "counting_officer")
        staff.save("", "")
        wait_for(qt_app, lambda: setup_idle(staff))
        edited = staff.property("state")
        assert edited["error"] == ""
        assert edited["dirty"] is False
        assert edited["selected"]["id"] == created["id"]
        assert edited["selected"]["revision"] == 2
        assert edited["selected"]["display_name"] == "陳美華點票職員"
        assert edited["selected"]["role"] == "counting_officer"
        assert edited["selected"]["station_ids"] == [station["id"]]
        assert [row["action"] for row in edited["audit"]] == [
            "staff_created",
            "staff_updated",
        ]
        assert temporary_password not in json.dumps(edited)
        officer.refresh()
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "signed_out")
        assert state_of(officer)["account"] == {}
        assert state_of(officer)["error"] == "session_expired"
    finally:
        officer.shutdown()
        officer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_invalid_staff_creation_is_localized_without_submitting_or_losing_form_fields(
    desktop: DesktopController,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    ready_staff: Any,
    locale: str,
) -> None:
    staff = ready_staff
    desktop.setLocale(locale)
    assert staff.loadAccount(0, False)
    username = "desktop_validation_" + uuid4().hex[:12]
    staff.setField("username", username)
    staff.setField("display_name", "  保留職員資料  ")
    staff.setField("role", "supervisor")
    staff.setEnabled(False)
    erasures: list[bool] = []
    staff.erasePassword.connect(lambda: erasures.append(True))
    before = https_server.request_count("POST", "/api/accounts")
    password = "Desktop-Staff-Validation-42!"
    snippets = {
        "tc": {
            "staff_validation": "顯示名稱",
            "password_mismatch": "不相同",
            "min_password": "密碼",
        },
        "sc": {
            "staff_validation": "显示名称",
            "password_mismatch": "不相同",
            "min_password": "密码",
        },
        "en": {
            "staff_validation": "display names",
            "password_mismatch": "do not match",
            "min_password": "password",
        },
    }
    for field, malformed in (
        ("username", "  "),
        ("username", "u" * 65),
        ("display_name", "  "),
        ("display_name", "名" * 121),
    ):
        original = staff.property("state")["form"][field]
        staff.setField(field, malformed)
        form = staff.property("state")["form"]
        staff.save(password, password)
        state = staff.property("state")
        assert state["error"] == "staff_validation"
        assert state["form"] == form
        assert state["dirty"] is True
        assert state["busy"] is False
        assert snippets[locale][state["error"]] in texts_of(desktop)[state["error"]]
        assert password not in json.dumps(state)
        staff.setField(field, original)

    for candidate, confirmation, error in (
        (password, password + "-mismatch", "password_mismatch"),
        ("short", "short", "min_password"),
    ):
        form = staff.property("state")["form"]
        staff.save(candidate, confirmation)
        state = staff.property("state")
        assert state["error"] == error
        assert state["form"] == form
        assert state["dirty"] is True
        assert state["busy"] is False
        assert snippets[locale][error] in texts_of(desktop)[error]
        assert candidate not in json.dumps(state)
        assert confirmation not in json.dumps(state)
    assert len(erasures) == 6
    staff.refresh()
    wait_for(qt_app, lambda: setup_idle(staff))
    assert https_server.request_count("POST", "/api/accounts") == before


def test_refresh_preserves_dirty_staff_fields_and_load_requires_explicit_discard(
    desktop: DesktopController,
    qt_app: QCoreApplication,
    ready_staff: Any,
) -> None:
    staff = ready_staff
    own_id = state_of(desktop)["account"]["id"]
    assert staff.loadAccount(0, False)
    staff.setField("username", "unsaved_" + uuid4().hex[:12])
    staff.setField("display_name", "未儲存職員")
    staff.setField("role", "supervisor")
    staff.setEnabled(False)
    staff.refresh()
    assert staff.property("state")["refreshing"] is True
    staff.setField("display_name", "重新整理期間仍可輸入")
    form = staff.property("state")["form"]
    wait_for(qt_app, lambda: setup_idle(staff))
    state = staff.property("state")
    assert state["form"] == form
    assert state["selected"] == {}
    assert state["dirty"] is True
    assert staff.loadAccount(own_id, False) is False
    assert staff.property("state") == state
    assert staff.loadAccount(own_id, True) is True
    wait_for(qt_app, lambda: setup_idle(staff))
    loaded = staff.property("state")
    assert loaded["selected"]["id"] == own_id
    assert loaded["form"]["display_name"] == state_of(desktop)["account"]["display_name"]
    assert loaded["form"]["role"] == "administrator"
    assert loaded["form"]["enabled"] is True
    assert loaded["form"]["station_ids"] == []
    assert loaded["dirty"] is False


def test_password_reset_reloads_a_changed_revision_then_revokes_the_officer_session(
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    ready_staff: Any,
) -> None:
    staff = ready_staff
    created, initial_password = create_officer(staff, qt_app)
    personal_password = "Desktop-Staff-Personal-84!"
    reset_password = "Desktop-Staff-Reset-126!"
    officer = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        officer.signIn(https_server.url, created["username"], initial_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "password_change")
        officer.changePassword(initial_password, personal_password, personal_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "workspace")
        assert state_of(officer)["account"]["must_change_password"] is False
        before = staff.property("state")
        staff.resetPassword(reset_password, reset_password)
        wait_for(qt_app, lambda: setup_idle(staff))
        stale = staff.property("state")
        assert stale["error"] == "revision_conflict"
        assert stale["selected"] == before["selected"]
        assert stale["selected"]["revision"] == 1
        assert stale["form"] == before["form"]
        assert stale["dirty"] is False
        officer.refresh()
        wait_for(qt_app, lambda: state_of(officer)["connection"] == "connected")
        assert state_of(officer)["phase"] == "workspace"

        assert staff.loadAccount(created["id"], False)
        wait_for(qt_app, lambda: setup_idle(staff))
        assert staff.property("state")["selected"]["revision"] == 2
        assert staff.property("state")["selected"]["must_change_password"] is False
        staff.resetPassword(reset_password, reset_password)
        wait_for(qt_app, lambda: setup_idle(staff))
        reset = staff.property("state")
        assert reset["error"] == ""
        assert reset["notice"] == "password_reset_success"
        assert reset["selected"]["revision"] == 3
        assert reset["selected"]["must_change_password"] is True
        assert [row["action"] for row in reset["audit"]] == [
            "staff_created",
            "staff_password_reset",
        ]
        for secret in (initial_password, personal_password, reset_password):
            assert secret not in json.dumps(reset)
        officer.refresh()
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "signed_out")
        assert state_of(officer)["error"] == "session_expired"
        assert state_of(officer)["account"] == {}
        officer.signIn(https_server.url, created["username"], personal_password)
        wait_for(qt_app, lambda: state_of(officer)["error"] == "invalid_credentials")
        assert state_of(officer)["phase"] == "signed_out"
        officer.signIn(https_server.url, created["username"], reset_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "password_change")
        assert state_of(officer)["account"]["must_change_password"] is True
    finally:
        officer.shutdown()
        officer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_second_administrator_edit_conflict_preserves_the_local_staff_form(
    admin: TestClient,
    qt_app: QCoreApplication,
    ready_staff: Any,
) -> None:
    staff = ready_staff
    created, _ = create_officer(staff, qt_app)
    staff.setField("display_name", "本機未儲存職員名稱")
    staff.setField("role", "counting_officer")
    local_form = staff.property("state")["form"]
    updated = admin.put(
        f"/api/accounts/{created['id']}",
        json={
            "display_name": "另一管理員已儲存名稱",
            "role": "supervisor",
            "enabled": True,
            "station_ids": [],
            "revision": created["revision"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    staff.save("", "")
    wait_for(qt_app, lambda: setup_idle(staff))
    conflict = staff.property("state")
    assert conflict["error"] == "revision_conflict"
    assert conflict["selected"] == created
    assert conflict["form"] == local_form
    assert conflict["dirty"] is True
    staff.refresh()
    wait_for(qt_app, lambda: setup_idle(staff))
    refreshed = staff.property("state")
    assert refreshed["form"] == local_form
    assert refreshed["selected"] == created
    assert refreshed["dirty"] is True
    assert any(row == updated.json() for row in refreshed["accounts"])
    assert staff.loadAccount(created["id"], False) is False
    assert staff.loadAccount(created["id"], True) is True
    wait_for(qt_app, lambda: setup_idle(staff))
    loaded = staff.property("state")
    assert loaded["selected"] == updated.json()
    assert loaded["form"]["display_name"] == "另一管理員已儲存名稱"
    assert loaded["form"]["role"] == "supervisor"
    assert loaded["dirty"] is False


def test_editing_own_administrator_account_signs_out_and_clears_all_staff_state(
    desktop: DesktopController,
    qt_app: QCoreApplication,
    ready_staff: Any,
) -> None:
    staff = ready_staff
    own_id = state_of(desktop)["account"]["id"]
    assert staff.loadAccount(own_id, False)
    wait_for(qt_app, lambda: setup_idle(staff))
    staff.setField("display_name", "管理員已更新姓名")
    staff.save("", "")
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "signed_out")
    assert state_of(desktop)["error"] == "access_changed"
    assert state_of(desktop)["account"] == {}
    empty = {
        "accounts": [],
        "station_options": [],
        "selected": {},
        "form": {
            "username": "",
            "display_name": "",
            "role": "polling_officer",
            "enabled": True,
            "station_ids": [],
        },
        "audit": [],
        "dirty": False,
        "busy": False,
        "refreshing": False,
        "error": "",
        "notice": "",
        "editing": False,
    }
    assert staff.property("state") == empty
    staff.open()
    assert staff.loadAccount(own_id, False) is False
    assert staff.property("state") == empty
