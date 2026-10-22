"""Desktop setup actions run through real Qt networking, TLS and MySQL."""

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.desktop_support import (
    PERSONAL_PASSWORD,
    TLS_DIRECTORY,
    HttpsServer,
    sign_in,
    state_of,
    wait_for,
)


def test_desktop_creates_and_reopens_a_draft_without_losing_unsaved_text(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(account["password"], PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    setup = desktop.property("configuration")
    assert setup is not None
    setup.open()
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert setup.load("election", 0, False)
    setup.setField("election", "name", "  保留原名 Election  ")
    setup.save("election")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    state = cast(dict[str, Any], setup.property("state"))
    election_id = state["selected"]["election"]["id"]
    assert state["selected"]["election"]["name"] == "  保留原名 Election  "
    setup.setField("election", "name", "尚未儲存的改動")
    setup.refresh()
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert setup.property("state")["forms"]["election"]["name"] == "尚未儲存的改動"
    assert setup.load("election", election_id, False) is False
    assert setup.property("state")["forms"]["election"]["name"] == "尚未儲存的改動"
    assert setup.load("election", election_id, True)
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert setup.property("state")["forms"]["election"]["name"] == "  保留原名 Election  "


def test_desktop_maintains_two_candidate_lists_and_localized_validation(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(account["password"], PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    setup = desktop.property("configuration")
    setup.load("election", 0, False)
    setup.setField("election", "name", "兩區桌面測試")
    setup.save("election")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    for code, name in (("N", "北區"), ("S", "南區")):
        assert setup.load("constituency", 0, False)
        setup.setField("constituency", "code", code)
        setup.setField("constituency", "name", name)
        setup.save("constituency")
        wait_for(qt_app, lambda: not setup.property("state")["busy"])
        assert setup.load("candidate", 0, False)
        setup.setField("candidate", "name", "  候選人 Example  ")
        for locale in ("tc", "sc", "en"):
            desktop.setLocale(locale)
            setup.setField("candidate", "ballot_number", "0")
            setup.save("candidate")
            assert setup.property("state")["error"] == "configuration_validation"
            assert setup.property("state")["forms"]["candidate"]["name"] == "  候選人 Example  "
        setup.setField("candidate", "ballot_number", "1")
        setup.save("candidate")
        wait_for(qt_app, lambda: not setup.property("state")["busy"])
        assert len(setup.property("state")["candidates"]) == 1
        assert setup.property("state")["candidates"][0]["ballot_number"] == 1
    north = next(row for row in setup.property("state")["constituencies"] if row["code"] == "N")
    assert setup.load("constituency", north["id"], False)
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert len(setup.property("state")["candidates"]) == 1
    assert setup.property("state")["candidates"][0]["constituency_id"] == north["id"]
    desktop.signOut()
    assert setup.property("state")["elections"] == []
    assert setup.load("election", 0, False) is False


def test_another_client_refresh_preserves_form_and_a_stale_save_is_rejected(
    desktop: DesktopController,
    https_server: HttpsServer,
    database_url: str,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(account["password"], PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    setup = desktop.property("configuration")
    setup.load("election", 0, False)
    setup.setField("election", "name", "原來名稱")
    setup.save("election")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    selected = setup.property("state")["selected"]["election"]
    setup.setField("election", "name", "我的未儲存名稱")
    with TestClient(create_app(database_url, now=https_server.clock)) as other:
        login = other.post(
            "/api/auth/login", json={"username": account["username"], "password": PERSONAL_PASSWORD}
        )
        other.headers["Authorization"] = "Bearer " + login.json()["token"]
        path = f"/api/elections/{selected['id']}"
        assert other.put(path, json={"name": "另一客戶端已儲存", "revision": 1}).status_code == 200
        setup.refresh()
        wait_for(qt_app, lambda: not setup.property("state")["busy"])
        assert setup.property("state")["forms"]["election"]["name"] == "我的未儲存名稱"
        assert any(
            row["name"] == "另一客戶端已儲存"
            for row in setup.property("state")["elections"]
            if row["id"] == selected["id"]
        )
        setup.save("election")
        wait_for(qt_app, lambda: setup.property("state")["error"] == "revision_conflict")
        assert setup.property("state")["forms"]["election"]["name"] == "我的未儲存名稱"
        assert other.get(path).json()["name"] == "另一客戶端已儲存"


def ready_setup(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> Any:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(account["password"], PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    setup = desktop.property("configuration")
    assert setup is not None
    return setup


def save_form(setup: Any, qt_app: QCoreApplication, kind: str, values: dict[str, str]) -> dict:
    assert setup.load(kind, 0, False)
    for field, value in values.items():
        setup.setField(kind, field, value)
    setup.save(kind)
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert setup.property("state")["error"] == ""
    return setup.property("state")["selected"][kind]


def saved_hierarchy(setup: Any, qt_app: QCoreApplication) -> dict[str, dict]:
    return {
        "election": save_form(setup, qt_app, "election", {"name": "桌面父記錄測試"}),
        "constituency": save_form(setup, qt_app, "constituency", {"code": "N", "name": "北區"}),
        "candidate": save_form(
            setup, qt_app, "candidate", {"name": "原有候選人", "ballot_number": "1"}
        ),
    }


def test_saving_election_and_constituency_preserves_dirty_descendant_forms(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    rows = saved_hierarchy(setup, qt_app)
    setup.setField("candidate", "name", "尚未儲存候選人")
    setup.setField("constituency", "name", "尚未儲存選區")
    setup.setField("election", "name", "已更改選舉")
    setup.save("election")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    after_election = setup.property("state")
    assert after_election["selected"]["election"]["name"] == "已更改選舉"
    assert after_election["selected"]["constituency"] == rows["constituency"]
    assert after_election["forms"]["constituency"]["name"] == "尚未儲存選區"
    assert after_election["dirty"]["constituency"] is True
    assert after_election["selected"]["candidate"] == rows["candidate"]
    assert after_election["forms"]["candidate"]["name"] == "尚未儲存候選人"
    assert after_election["dirty"]["candidate"] is True
    setup.save("constituency")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    after_constituency = setup.property("state")
    assert after_constituency["selected"]["constituency"]["name"] == "尚未儲存選區"
    assert after_constituency["selected"]["candidate"] == rows["candidate"]
    assert after_constituency["forms"]["candidate"]["name"] == "尚未儲存候選人"
    assert after_constituency["dirty"]["candidate"] is True
    assert after_constituency["editing"]["candidate"] is True


def test_saving_parent_preserves_a_new_unsaved_child_form(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    save_form(setup, qt_app, "election", {"name": "新選區父記錄"})
    assert setup.load("constituency", 0, False)
    setup.setField("constituency", "code", "NEW")
    setup.setField("constituency", "name", "尚未儲存新選區")
    setup.setField("election", "name", "父記錄已儲存")
    setup.save("election")
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    state = setup.property("state")
    assert state["forms"]["constituency"] == {"code": "NEW", "name": "尚未儲存新選區"}
    assert state["selected"]["constituency"] == {}
    assert state["editing"]["constituency"] is True
    assert state["dirty"]["constituency"] is True


@pytest.mark.parametrize("parent", ["election", "constituency"])
def test_switching_parent_requires_discard_and_then_loads_saved_context(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    parent: str,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    rows = saved_hierarchy(setup, qt_app)
    if parent == "election":
        destination = save_form(setup, qt_app, "election", {"name": "另一選舉"})
        assert setup.load("election", rows["election"]["id"], False)
        wait_for(qt_app, lambda: not setup.property("state")["busy"])
    else:
        destination = save_form(setup, qt_app, "constituency", {"code": "S", "name": "南區"})
    assert setup.load("constituency", rows["constituency"]["id"], False)
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert setup.load("candidate", rows["candidate"]["id"], False)
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    setup.setField("candidate", "name", "不可自動丟失的文字")
    before = setup.property("state")
    assert setup.load(parent, destination["id"], False) is False
    assert setup.property("state") == before
    assert setup.load(parent, destination["id"], True) is True
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    after = setup.property("state")
    assert after["selected"][parent] == destination
    assert after["forms"][parent]["name"] == destination["name"]
    assert after["selected"]["candidate"] == {}
    assert after["forms"]["candidate"]["name"] == ""
    assert after["dirty"]["candidate"] is False
    assert after["editing"]["candidate"] is False
    assert after["candidates"] == []
    if parent == "election":
        assert after["selected"]["constituency"] == {}
        assert after["constituencies"] == []


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_malformed_ballot_numbers_are_localized_without_submitting_or_crashing(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    locale: str,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    rows = saved_hierarchy(setup, qt_app)
    desktop.setLocale(locale)
    candidate_path = (
        f"/api/elections/{rows['election']['id']}/constituencies/"
        f"{rows['constituency']['id']}/candidates/{rows['candidate']['id']}"
    )
    before = https_server.request_count("PUT", candidate_path)
    expected = {
        "tc": "候選人編號須為正整數",
        "sc": "候选人编号须为正整数",
        "en": "candidate numbers a positive integer",
    }
    for malformed in ("", "-1", "1.5", "1e3", "one", "１２", "2147483648", "9" * 5000):
        setup.setField("candidate", "ballot_number", malformed)
        setup.save("candidate")
        state = setup.property("state")
        assert state["error"] == "configuration_validation"
        assert state["busy"] is False
        assert state["forms"]["candidate"]["ballot_number"] == malformed
        assert state["forms"]["candidate"]["name"] == "原有候選人"
        assert expected[locale] in desktop.property("texts")[state["error"]]
    setup.refresh()
    wait_for(qt_app, lambda: not setup.property("state")["busy"])
    assert https_server.request_count("PUT", candidate_path) == before


def test_second_desktop_sees_new_saved_draft_without_overwriting_its_unsaved_form(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    second = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        second.signIn(https_server.url, account["username"], PERSONAL_PASSWORD)
        wait_for(qt_app, lambda: state_of(second)["phase"] == "workspace")
        other_setup = second.property("configuration")
        other_setup.open()
        wait_for(qt_app, lambda: not other_setup.property("state")["busy"])
        original_ids = {row["id"] for row in other_setup.property("state")["elections"]}
        assert other_setup.load("election", 0, False)
        other_setup.setField("election", "name", "另一桌面的未儲存選舉")
        created = save_form(setup, qt_app, "election", {"name": "其他桌面剛儲存的新選舉"})
        assert created["id"] not in original_ids
        other_setup.refresh()
        wait_for(qt_app, lambda: not other_setup.property("state")["busy"])
        state = other_setup.property("state")
        assert any(row == created for row in state["elections"])
        assert state["forms"]["election"]["name"] == "另一桌面的未儲存選舉"
        assert state["selected"]["election"] == {}
        assert state["dirty"]["election"] is True
    finally:
        second.shutdown()
        second.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
