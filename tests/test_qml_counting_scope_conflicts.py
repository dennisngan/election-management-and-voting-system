"""A peer's real submission yields a translated, recoverable Material conflict."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.desktop_support import TLS_DIRECTORY, HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_material_localizes_a_peer_submission_conflict_and_reloads_its_actual_state(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        receiver = setup["clients"]["receiveronly"]
        path = setup["paths"]["n1_counting_scopes"]
        box = setup["boxes"]["local_n1"]
        saved = receiver.post(path, json={
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Peer submission conflict", "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
            ],
        })
        assert saved.status_code == 201, saved.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "scope_id": saved.json()["id"],
                "path": path,
                "ca_file": str(TLS_DIRECTORY / "ca.pem"),
            },
            """
            import httpx
            import ssl
            from uuid import uuid4

            click('countingScopesNavigation')
            editor = controller.countingScopes
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            frame()
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            frame()
            assert editor.property('state')['selected']['status'] == 'draft'
            # A second authenticated client submits the unchanged content revision.
            # The Material client still holds its original draft until it reloads.
            with httpx.Client(base_url=setup['server'],
                    verify=ssl.create_default_context(cafile=setup['ca_file'])) as peer:
                login = peer.post('/api/auth/login', json={
                    'username': setup['username'], 'password': setup['password']})
                assert login.status_code == 200
                peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                submitted = peer.post(setup['path'] + '/' + str(setup['scope_id']) + '/submit',
                    json={'request_id': str(uuid4()), 'expected_revision': 1})
                assert submitted.status_code == 200
            assert editor.property('state')['selected']['status'] == 'draft'
            click('countingScopeSubmit')
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['error'] == 'scope_state_conflict', (
                editor.property('state')['error'], editor.property('state')['dirty'],
                editor.property('state')['selected']['status'])
            for locale, expected in (
                ('en', 'Another staff member changed this scope’s submission state. '
                       'Reload it before continuing.'),
                ('tc', '另一位職員已變更此點票範圍的提交狀態；請重新載入後再繼續。'),
                ('sc', '另一位职员已更改此点票范围的提交状态；请重新加载后再继续。'),
            ):
                controller.setLocale(locale)
                frame()
                assert control('countingScopeError').property('text') == expected
            editor.discardAndReload()
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert editor.property('state')['selected']['status'] == 'submitted'
            assert editor.property('state')['selected']['revision'] == 1
            assert editor.property('state')['error'] == ''
            """,
        )
