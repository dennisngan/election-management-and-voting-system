"""Two staff clients use public Qt controls over real TLS and MySQL."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import READY_PASSWORD, draft_payload, polling_scope, ready_polling_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_two_desktops_prepare_review_and_amend_an_opening_without_losing_dirty_input(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    clients = []
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        try:
            for _, account in (officer_info, supervisor_info):
                client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
                clients.append(client)
                client.signIn(https_server.url, account["username"], READY_PASSWORD)
                wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
                workspace = client.property("workspace")
                wait_for(qt_app, lambda: setup_idle(workspace))
                workspace.selectStation(station_id)
                wait_for(qt_app, lambda: setup_idle(workspace))
            officer, supervisor = clients
            editor = officer.property("polling")
            reviewer = supervisor.property("polling")
            assert editor is not None and reviewer is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["items"] == []
            editor.setField("event_at", "2025-11-15 07:35")
            editor.setField("reason", "檢查設備延誤")
            workspace = officer.property("workspace")
            workspace.refresh()
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["forms"]["reason"] == "檢查設備延誤"
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["forms"]["reason"] == "檢查設備延誤"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["record"]["revision"] == 1
            assert editor.property("state")["items"] == [editor.property("state")["record"]]
            editor.submit()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["record"]["status"] == "submitted"
            reviewer.open()
            wait_for(qt_app, lambda: setup_idle(reviewer))
            reviewer.approve("wrong-existing-password")
            wait_for(qt_app, lambda: setup_idle(reviewer))
            assert reviewer.property("state")["error"] == "invalid_credentials"
            reviewer.approve(READY_PASSWORD)
            wait_for(qt_app, lambda: setup_idle(reviewer))
            assert reviewer.property("state")["record"]["status"] == "approved"
            assert READY_PASSWORD not in str(reviewer.property("state"))
            editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_at", "2025-11-15 07:36")
            editor.setField("amendment_reason", "核對紙本後修正")
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            current = editor.property("state")
            assert current["error"] == ""
            assert current["record"]["status"] == "draft"
            assert current["record"]["revision"] == 2
            assert current["history"][0]["status"] == "approved"
            assert current["history"][0]["revision"] == 1
            assert current["history"][1]["amendment_reason"] == "核對紙本後修正"
            for locale in ("tc", "sc", "en"):
                officer.setLocale(locale)
                assert "polling_events" in officer.property("texts")
                assert editor.property("state")["forms"]["event_at"] == "2025-11-15 07:36"
            officer.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["history"] == []
        finally:
            for client in clients:
                client.shutdown()
                client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_polling_editor_guards_station_kind_reload_and_stale_revision_changes(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = polling_scope(admin)
    first, second = [station["id"] for station in scope.stations]
    with ready_polling_staff(admin, database_url, "polling_officer", [first, second]) as info:
        api, account = info
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(first)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("polling")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_at", "bad time")
            editor.save()
            assert editor.property("state")["error"] == "polling_validation"
            assert editor.property("state")["forms"]["event_at"] == "bad time"
            assert not editor.setKind("admission_closure", False)
            assert editor.property("state")["kind"] == "opening"
            assert not editor.reload(False)
            workspace.selectStation(second)
            assert workspace.property("state")["error"] == "unsaved_station_changes"
            assert state_of(client)["station"]["id"] == first
            assert editor.property("state")["forms"]["event_at"] == "bad time"
            workspace.selectStation(second, True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert state_of(client)["station"]["id"] == second
            assert editor.property("state")["forms"]["event_at"] == ""
            workspace.selectStation(first)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.setKind("queue_clear_estimate", True)
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_at", "2025-11-15 22:30")
            editor.setField("estimated_clear_at", "2025-11-15 22:50")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["record"]["revision"] == 1
            path = scope.path + "/queue_clear_estimate"
            newer = api.put(
                path,
                json=draft_payload(
                    1,
                    event_at="2025-11-15T22:30:00+08:00",
                    estimated_clear_at="2025-11-15T23:00:00+08:00",
                    reason="第二部電腦修正預計時間",
                ),
            )
            assert newer.status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["newer_revision"] is True
            assert editor.property("state")["record"]["revision"] == 1
            assert editor.property("state")["forms"]["estimated_clear_at"] == "2025-11-15 22:50"
            editor.setField("reason", "保留尚未儲存的輸入")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "revision_conflict"
            assert editor.property("state")["forms"]["reason"] == "保留尚未儲存的輸入"
            assert not editor.reload(False)
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["record"]["revision"] == 2
            assert editor.property("state")["forms"]["estimated_clear_at"] == "2025-11-15 23:00"
            assert editor.property("state")["forms"]["reason"] == "第二部電腦修正預計時間"
            assert editor.property("state")["newer_revision"] is False
            assert editor.formatTime("2025-11-15T15:00:00Z") == "2025-11-15 23:00 HKT"
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
