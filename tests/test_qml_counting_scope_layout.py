"""Scope notes stay inside their border and preserve keyboard focus while polling."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_multiline_scope_fields_keep_text_and_focus_inside_the_visible_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        path = setup["paths"]["n1_counting_scopes"]
        box = setup["boxes"]["local_n1"]
        receiver = setup["clients"]["receiveronly"]
        saved = receiver.post(path, json={
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Multiline scope input", "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
            ],
        })
        assert saved.status_code == 201, saved.text
        submitted = receiver.post(f"{path}/{saved.json()['id']}/submit", json={
            "request_id": str(uuid4()), "expected_revision": 1,
        })
        assert submitted.status_code == 200, submitted.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "tc", "scope_id": saved.json()["id"],
            },
            """
            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            notes = '第一行：核對來源。\\nSecond line: preserve the receipt.\\n第三行：保留歷史。'
            enter('countingScopeNotes', notes)
            assert_multiline_inside_border('countingScopeNotes')
            field = control('countingScopeNotes')
            focus_changes = QSignalSpy(field.activeFocusChanged)
            editor.refresh()
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert field.property('activeFocus') is True
            assert focus_changes.count() == 0, 'Background polling interrupted note entry'
            assert field.property('text') == notes
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('countingScopeReason').property('activeFocus'))
            assert field.property('text') == notes, 'Tab inserted text instead of moving focus'
            enter('countingScopeReason', '重新核對。\\nPreserve the prior scope revision.')
            assert_multiline_inside_border('countingScopeReason')
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('countingScopeNotes').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('countingScopeReason').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('countingScopeSave').property('activeFocus'))
            """,
        )


def test_historical_view_can_start_an_independent_new_scope_without_changing_history(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        path = setup["paths"]["n1_counting_scopes"]
        box = setup["boxes"]["local_n1"]
        receiver = setup["clients"]["receiveronly"]
        command = {
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Preserved scope history", "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
            ],
        }
        saved = receiver.post(path, json=command)
        assert saved.status_code == 201, saved.text
        scope_path = f"{path}/{saved.json()['id']}"
        assert receiver.post(scope_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 1,
        }).status_code == 200
        amended = receiver.put(scope_path, json={
            **command, "request_id": str(uuid4()), "expected_revision": 1,
            "notes": "Current draft note", "amendment_reason": "Rechecked the paper reference",
        })
        assert amended.status_code == 200, amended.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en", "scope_id": saved.json()["id"],
            },
            """
            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            choose('countingScopeHistory', 1)
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert editor.property('state')['selected']['revision'] == 1
            assert editor.property('state')['historical'] is True
            assert control('countingScopeNotes').property('readOnly') is True
            assert control('countingScopeNew').property('enabled') is True
            click('countingScopeNew')
            assert editor.property('state')['selected'] == {}
            assert editor.property('state')['forms']['reference'] == ''
            assert editor.property('state')['historical'] is False
            """,
        )
        current = receiver.get(scope_path).json()
        assert current["record"]["revision"] == 2
        assert current["record"]["notes"] == "Current draft note"
        assert current["history"][1]["revision"] == 1
        assert current["history"][1]["status"] == "submitted"
        assert current["history"][1]["notes"] == ""
