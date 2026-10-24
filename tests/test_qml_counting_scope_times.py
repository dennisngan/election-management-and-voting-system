"""Precise original scope times survive a note correction in the actual Material client."""

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


def test_material_note_amendment_preserves_original_seconds_and_explicit_time_changes(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        path = setup["paths"]["n1_counting_scopes"]
        box = setup["boxes"]["local_n1"]
        receiver = setup["clients"]["receiveronly"]
        saved = receiver.post(path, json={
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Precise scope preparation",
            "event_at": "2026-11-15T23:10:17.123456+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
            ],
        })
        assert saved.status_code == 201, saved.text
        assert saved.json()["event_at"] == "2026-11-15T15:10:17.123456Z"
        scope_path = f"{path}/{saved.json()['id']}"
        assert receiver.post(scope_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 1,
        }).status_code == 200
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
            frame()
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            frame()
            assert control('countingScopeEventAt').property('text') == (
                '2026-11-15 23:10:17.123456'
            )
            enter('countingScopeNotes', 'Only the paper reference note changes.')
            enter('countingScopeReason',
                'Verified the original event time against the paper record.')
            click('countingScopeSave')
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert editor.property('state')['selected']['revision'] == 2
            assert editor.property('state')['selected']['event_at'] == '2026-11-15T15:10:17.123456Z'
            enter('countingScopeEventAt', '2026-11-15 23:11:18.654321')
            click('countingScopeSave')
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            assert editor.property('state')['selected']['revision'] == 3
            assert editor.property('state')['selected']['event_at'] == '2026-11-15T15:11:18.654321Z'
            assert control('countingScopeEventAt').property('text') == (
                '2026-11-15 23:11:18.654321'
            )
            """,
        )
        history = receiver.get(scope_path).json()["history"]
        assert [row["revision"] for row in history] == [3, 2, 1]
        assert history[2]["event_at"] == history[1]["event_at"] == "2026-11-15T15:10:17.123456Z"
        assert history[0]["event_at"] == "2026-11-15T15:11:18.654321Z"
