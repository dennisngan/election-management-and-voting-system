"""Public Qt polling retains local feedback, report identity and historical scope views."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.desktop_support import (
    TLS_DIRECTORY,
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


def prepare_n1_scope(receiver: TestClient, setup: dict, reference: str) -> dict:
    station_id = setup["stations"]["N1"]["id"]
    box = setup["boxes"]["local_n1"]
    return receiver.post(
        setup["paths"]["n1_counting_scopes"],
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "reference": reference,
            "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {
                    "station_id": station_id,
                    "revision": setup["accounting"]["N1"]["record"]["revision"],
                }
            ],
            "notes": "Source receipt and P(18) reviewed before counting.",
        },
    )


def test_material_refresh_keeps_invalid_time_and_validation_message(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        receiver = setup["clients"]["receiveronly"]
        saved = prepare_n1_scope(receiver, setup, "Polling preserves local validation")
        assert saved.status_code == 201, saved.text
        station_id = setup["stations"]["N1"]["id"]

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": saved.json()["id"],
            },
            """
            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not editor.property('state')['busy'])
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not editor.property('state')['busy'])
            enter('countingScopeEventAt', 'not a Hong Kong date')
            click('countingScopeSave')
            assert editor.property('state')['error'] == 'counting_scope_validation'
            assert editor.property('state')['dirty'] is True
            assert control('countingScopeEventAt').property('text') == 'not a Hong Kong date'
            assert control('countingScopeError').property('text') == (
                'Enter a valid reference and Hong Kong time, then review the selected boxes '
                'and source accounting.'
            )
            click('countingScopesRefresh')
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            state = editor.property('state')
            assert state['error'] == 'counting_scope_validation'
            assert state['dirty'] is True
            assert state['forms']['event_at'] == 'not a Hong Kong date'
            assert control('countingScopeError').property('visible') is True
            """,
        )


def test_material_refresh_keeps_historical_report_and_refreshes_frozen_source_validity(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        receiver = setup["clients"]["receiveronly"]
        box = setup["boxes"]["local_n1"]
        station_id = setup["stations"]["N1"]["id"]
        scope_path = setup["paths"]["n1_counting_scopes"]
        created = prepare_n1_scope(receiver, setup, "Polling preserves historical report")
        assert created.status_code == 201, created.text
        scope_id = created.json()["id"]
        submitted = receiver.post(
            f"{scope_path}/{scope_id}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )

        assert submitted.status_code == 200, submitted.text
        amended = receiver.put(
            f"{scope_path}/{scope_id}",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "reference": "Polling preserves historical report",
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [{"station_id": station_id, "revision": 1}],
                "notes": "Reasoned amendment retained as revision two.",
                "amendment_reason": "Corrected the submitted paper trail.",
            },
        )
        assert amended.status_code == 200, amended.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": scope_id,
                "scope_path": scope_path,
                "box_id": box["id"],
                "box_revision": box["revision"],
                "peer_username": setup["accounts"]["bothcounting"]["username"],
                "ca_file": str(TLS_DIRECTORY / "ca.pem"),
            },
            """
            import httpx
            import ssl
            from uuid import uuid4

            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not editor.property('state')['busy'])
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not editor.property('state')['busy'])
            choose('countingScopeHistory', 1)
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['selected']['revision'] == 1)
            assert editor.property('state')['historical'] is True
            frozen_receipt = editor.property('state')['selected']['box_basis'][0]['receipt_at']
            click('countingScopePreview')
            wait(lambda: not editor.property('state')['busy'])
            original_report = editor.property('state')['report_text']
            assert editor.property('state')['report']['scope_id'] == setup['scope_id']
            assert editor.property('state')['report']['revision'] == 1

            with httpx.Client(
                base_url=setup['server'],
                verify=ssl.create_default_context(cafile=setup['ca_file']),
            ) as peer:
                login = peer.post('/api/auth/login', json={
                    'username': setup['peer_username'], 'password': setup['password']})
                assert login.status_code == 200
                peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                correction = peer.put(
                    f"{setup['scope_path'].removesuffix('/counting-scopes')}/boxes/"
                    f"{setup['box_id']}/receipt",
                    json={
                        'request_id': str(uuid4()),
                        'expected_revision': setup['box_revision'],
                        'event_at': '2026-11-15T22:46:00+08:00',
                        'reason': 'Peer corrected the receipt time.',
                    },
                )
                assert correction.status_code == 200, correction.text

            click('countingScopesRefresh')
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            refreshed = editor.property('state')
            selected = refreshed['selected']
            assert selected['revision'] == 1
            assert refreshed['historical'] is True
            assert selected['source_current'] is False
            assert selected['box_basis'][0]['receipt_at'] == frozen_receipt
            assert refreshed['report']['scope_id'] == setup['scope_id']
            assert refreshed['report']['revision'] == 1
            assert refreshed['report_text'] == original_report
            assert control('countingScopeNotes').property('readOnly') is True
            assert control('countingScopeReportPreview').property('visible') is True
            """,
        )


def test_foreground_scope_save_supersedes_a_held_background_scope_read(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    desktop: Any,
    qt_app: Any,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        receiver = setup["clients"]["receiveronly"]
        created = prepare_n1_scope(receiver, setup, "Foreground save versus poll")
        assert created.status_code == 201, created.text
        station_id = setup["stations"]["N1"]["id"]
        scope_path = setup["paths"]["n1_counting_scopes"]

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

        https_server.release_staff_response.clear()
        https_server.staff_response_entered.clear()
        https_server.staff_response_finished.clear()
        https_server.hold_staff_response_path = scope_path
        editor.refresh()
        wait_for(qt_app, https_server.staff_response_entered.is_set)
        assert editor.property("state")["refreshing"] is True
        editor.setForm("notes", "Foreground save must beat the held poll response.")
        editor.save()
        assert editor.property("state")["busy"] is True

        https_server.release_staff_response.set()
        wait_for(qt_app, https_server.staff_response_finished.is_set)
        wait_for_editor_idle(qt_app, editor)
        qt_app.processEvents()
        current = editor.property("state")
        assert current["selected"]["revision"] == 2
        assert current["selected"]["notes"] == "Foreground save must beat the held poll response."
        assert current["forms"]["notes"] == "Foreground save must beat the held poll response."
        assert current["error"] == ""
