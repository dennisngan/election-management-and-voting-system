"""Counting-scope preparation through the actual Material client and MySQL API."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.desktop_support import (
    HttpsServer,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_received_box_scope_saves_and_submits_with_source_accounting_provenance(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["stations"]["N1"]["id"]
        path = setup["paths"]["n1_counting_scopes"]
        boxes = setup["boxes"]
        n1_id = setup["stations"]["N1"]["id"]
        n2_id = setup["stations"]["N2"]["id"]
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "pdf_path": str(tmp_path / "counting-scope.pdf"),
                "csv_path": str(tmp_path / "counting-scope.csv"),
            },
            f"""
            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not editor.property('state')['busy'])
            state = editor.property('state')
            assert state['context']['station']['id'] == {station_id}
            assert len(state['source_accounting']) == 2
            click('countingScopeBox_{boxes["local_n1"]["id"]}')
            click('countingScopeBox_{boxes["transferred_n2"]["id"]}')
            choose('countingScopeAccounting_{n1_id}', 1)
            choose('countingScopeAccounting_{n2_id}', 1)
            enter('countingScopeReference', 'N1 received mixed-origin set')
            enter('countingScopeEventAt', '2026-11-15 23:10')
            enter('countingScopeNotes', 'Both received boxes checked against the handover record.')
            click('countingScopeSave')
            wait(lambda: not editor.property('state')['busy'])
            draft = editor.property('state')['selected']
            assert draft['status'] == 'draft'
            assert draft['source_current'] is True
            assert draft['blockers'] == []
            assert draft['estimated_box_from_stock_quantity'] is None
            assert control('countingScopeStockEstimate').property('text') == '—'
            assert control('countingScopeCoverageWarning_{n2_id}').property('visible') is True
            click('countingScopeSubmit')
            wait(lambda: not editor.property('state')['busy'])
            submitted = editor.property('state')['selected']
            assert submitted['status'] == 'submitted'
            assert submitted['count_ready'] is True
            assert control('countingScopeSubmit').property('visible') is False
            enter('countingScopeNotes', 'Amended source check after submission.')
            editor.loadRevision(1)
            assert editor.property('state')['error'] == 'unsaved_changes'
            assert editor.property('state')['forms']['notes'] == (
                'Amended source check after submission.'
            )
            assert editor.property('state')['selected']['revision'] == submitted['revision']
            click('countingScopeSave')
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['error'] == 'scope_reason_required'
            assert control('countingScopeError').property('text') == (
                'A reason is required to amend a submitted counting scope.'
            )
            enter('countingScopeReason', 'The handover reference was rechecked.')
            click('countingScopeSave')
            wait(lambda: not editor.property('state')['busy'])
            amended = editor.property('state')['selected']
            assert amended['status'] == 'draft'
            assert amended['revision'] == 2
            assert amended['amendment_reason'] == 'The handover reference was rechecked.'
            click('countingScopeOption_' + str(amended['id']))
            wait(lambda: not editor.property('state')['busy'])
            assert len(editor.property('state')['history']) == 2
            choose('countingScopeHistory', 1)
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['selected']['revision'] == 1)
            historical = editor.property('state')['selected']
            assert historical['status'] == 'submitted'
            assert editor.property('state')['historical'] is True
            assert control('countingScopeNotes').property('text') == (
                'Both received boxes checked against the handover record.'
            )
            frozen_box = control('countingScopeFrozenBox_{boxes["local_n1"]["id"]}')
            assert 'Revision {boxes["local_n1"]["revision"]}' in frozen_box.property('text')
            accounting_basis = control('countingScopeP18Basis_{n1_id}')
            assert 'Revision 1' in accounting_basis.property('text')
            assert control('countingScopeNotes').property('readOnly') is True
            assert control('countingScopeSave').property('enabled') is False
            click('countingScopePreview')
            wait(lambda: not editor.property('state')['busy'])
            report = editor.property('state')['report']
            assert report['locale'] == 'en'
            assert report['scope_id'] == historical['id']
            assert report['revision'] == 1
            assert control('countingScopeReportPreview').property('visible') is True
            editor.download('pdf', setup['pdf_path'], 'en')
            wait(lambda: not editor.property('state')['busy'])
            assert Path(setup['pdf_path']).read_bytes().startswith(b'%PDF-')
            editor.download('csv', setup['csv_path'], 'en')
            wait(lambda: not editor.property('state')['busy'])
            assert Path(setup['csv_path']).read_bytes().startswith(bytes.fromhex('efbbbf'))
            editor.newScope()
            editor.setBoxSelected({boxes["local_n1"]["id"]}, True)
            editor.chooseAccounting({n1_id}, {setup["accounting"]["N1"]["record"]["revision"]})
            editor.setForm('reference', 'Duplicate membership probe')
            editor.setForm('event_at', '2026-11-15 23:20')
            editor.save()
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['error'] == 'box_already_in_scope'
            assert control('countingScopeError').property('text') == (
                'The selected box already belongs to another counting scope.'
            )
            """,
        )
        response = setup["clients"]["receiveronly"].get(path)
        assert response.status_code == 200, response.text
        current = response.json()
        assert len(current["scopes"]) == 1
        scope = current["scopes"][0]
        assert scope["status"] == "draft"
        assert scope["revision"] == 2
        assert {box["id"] for box in scope["box_basis"]} == {
            boxes["local_n1"]["id"],
            boxes["transferred_n2"]["id"],
        }
        assert {source["station_id"] for source in scope["accounting_basis"]} == {n1_id, n2_id}
        assert all(
            not row["all_source_boxes_in_scope"]
            for row in scope["coverage"]
            if row["station"]["id"] == n2_id
        )
        historical = setup["clients"]["receiveronly"].get(f"{path}/{scope['id']}/revisions/1")
        assert historical.status_code == 200, historical.text
        assert historical.json()["status"] == "submitted"
        assert historical.json()["is_current"] is False


def test_dirty_scope_keeps_local_input_and_refuses_stale_save_until_reload(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    desktop: Any,
    qt_app: QCoreApplication,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["stations"]["N1"]["id"]
        source = setup["accounting"]["N1"]["record"]
        box = setup["boxes"]["local_n1"]
        receiver = setup["clients"]["receiveronly"]
        path = setup["paths"]["n1_counting_scopes"]
        created = receiver.post(
            path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Stale edit scope",
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [
                    {"station_id": station_id, "revision": source["revision"]}
                ],
                "notes": "Initial saved notes.",
            },
        )
        assert created.status_code == 201, created.text

        desktop.signIn(
            https_server.url,
            setup["accounts"]["receiveronly"]["username"],
            READY_PASSWORD,
        )
        wait_for(qt_app, lambda: desktop.property("state")["phase"] == "workspace")
        workspace = desktop.property("workspace")
        workspace.open()
        wait_for(qt_app, lambda: not workspace.property("state")["busy"])
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: not workspace.property("state")["busy"])
        editor = desktop.property("countingScopes")
        editor.open()
        wait_for_editor_idle(qt_app, editor)
        editor.selectScope(created.json()["id"])
        wait_for_editor_idle(qt_app, editor)
        assert editor.property("state")["selected"]["revision"] == 1

        editor.setForm("notes", "Local notes must survive a refresh.")
        changed = receiver.put(
            f"{path}/{created.json()['id']}",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "reference": "Stale edit scope",
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [
                    {"station_id": station_id, "revision": source["revision"]}
                ],
                "notes": "A peer saved a newer revision.",
            },
        )
        assert changed.status_code == 200, changed.text
        save_count = https_server.request_count("PUT", f"{path}/{created.json()['id']}")
        editor.refresh()
        wait_for_editor_idle(qt_app, editor)
        stale = editor.property("state")
        assert stale["dirty"] is True
        assert stale["newer_revision"] is True
        assert stale["forms"]["notes"] == "Local notes must survive a refresh."
        assert stale["selected"]["revision"] == 2

        editor.save()
        assert editor.property("state")["error"] == "revision_conflict"
        assert https_server.request_count("PUT", f"{path}/{created.json()['id']}") == save_count

        editor.discardAndReload()
        wait_for_editor_idle(qt_app, editor)
        current = editor.property("state")
        assert current["dirty"] is False
        assert current["newer_revision"] is False
        assert current["forms"]["notes"] == "A peer saved a newer revision."
