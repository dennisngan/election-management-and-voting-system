"""Accounting and counting-scope discard choices follow the selected app language."""

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


@pytest.mark.parametrize("page", ["accounting", "countingScopes"])
def test_localized_discard_keeps_unsaved_input_on_cancel_and_restores_only_on_confirmation(
    admin: TestClient, database_url: str, https_server: HttpsServer, page: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        receiver = setup["clients"]["receiveronly"]
        station_id = setup["stations"]["N1"]["id"]
        if page == "countingScopes":
            path = setup["paths"]["n1_counting_scopes"]
            box = setup["boxes"]["local_n1"]
            saved = receiver.post(path, json={
                "request_id": str(uuid4()), "expected_revision": 0,
                "reference": "Localized discard", "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [{"station_id": station_id, "revision": 1}],
                "notes": "Saved scope note",
            })
            assert saved.status_code == 201, saved.text
            scope_id, original_notes = saved.json()["id"], "Saved scope note"
            target = f"{path}/{scope_id}"
            notes, reload = "countingScopeNotes", "countingScopeReload"
        else:
            scope_id, original_notes = 0, ""
            target = setup["paths"]["n1_accounting"]
            notes, reload = "accountingNotes", "accountingReload"
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD, "station_id": station_id,
                "locale": "tc", "page": page, "scope_id": scope_id,
                "notes": notes, "reload": reload, "original_notes": original_notes,
            },
            """
            from PySide6.QtCore import QObject
            click(setup['page'] + 'Navigation')
            editor = controller.property(setup['page'])
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            frame()
            if setup['scope_id']:
                click('countingScopeOption_' + str(setup['scope_id']))
                wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
                frame()
            enter(setup['notes'], 'Unsaved local note; cancel must retain it.')
            for locale, keep, discard in (
                ('tc', '繼續編輯', '捨棄變更'),
                ('sc', '继续编辑', '舍弃更改'),
                ('en', 'Keep editing', 'Discard changes'),
            ):
                controller.setLocale(locale)
                frame()
                click(setup['reload'])
                dialogs = [obj for obj in window.findChildren(QObject)
                    if obj.inherits('QQuickDialog') and obj.property('visible')]
                assert len(dialogs) == 1
                dialog = dialogs[0]
                wait(lambda: dialog.property('opened'))
                frame()
                pending, captions = list(dialog.property('footer').childItems()), []
                while pending:
                    item = pending.pop()
                    if item.inherits('QQuickAbstractButton') and item.property('visible'):
                        captions.append(item.property('text'))
                    pending.extend(item.childItems())
                assert set(captions) == {keep, discard}, (locale, captions)
                try:
                    click_confirmation(dialog, keep)
                except AssertionError as error:
                    focused = window.property('activeFocusItem')
                    raise AssertionError((locale, dialog.objectName(),
                        dialog.property('opened'), dialog.property('visible'),
                        dialog.property('activeFocus'), dialog.property('focus'),
                        focused.objectName() if focused else None)) from error
                assert editor.property('state')['dirty'] is True
                assert control(setup['notes']).property('text') == (
                    'Unsaved local note; cancel must retain it.'
                )
            click(setup['reload'])
            dialogs = [obj for obj in window.findChildren(QObject)
                if obj.inherits('QQuickDialog') and obj.property('visible')]
            assert len(dialogs) == 1
            click_confirmation(dialogs[0], 'Discard changes')
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert editor.property('state')['dirty'] is False
            assert control(setup['notes']).property('text') == setup['original_notes']
            assert editor.property('state')['selected']['revision'] == 1
            """,
        )
        latest = receiver.get(target).json()["record"]
        assert latest["revision"] == 1
        assert latest["notes"] == original_notes
