"""A submitted, ready scope does not advertise a nonexistent scope approval step."""

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


def test_ready_scope_uses_its_own_submitted_state_in_every_language(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        path = setup["paths"]["n1_counting_scopes"]
        box = setup["boxes"]["local_n1"]
        receiver = setup["clients"]["receiveronly"]
        saved = receiver.post(path, json={
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Ready scope", "event_at": "2026-11-15T23:10:00+08:00",
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
        assert submitted.json()["count_ready"] is True
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
            frame()
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
            frame()
            assert editor.property('state')['selected']['count_ready'] is True
            for locale, row, history in (
                ('tc', 'Ready scope · 已提交 · 修訂版本 1', '已提交 · 修訂版本 1 · Ready scope'),
                ('sc', 'Ready scope · 已提交 · 修订版本 1', '已提交 · 修订版本 1 · Ready scope'),
                ('en', 'Ready scope · Submitted · Revision 1',
                    'Submitted · Revision 1 · Ready scope'),
            ):
                controller.setLocale(locale)
                frame()
                scope_button = control('countingScopeOption_' + str(setup['scope_id']))
                assert scope_button.property('text') == row
                assert control('countingScopeHistory').property('displayText') == history
            """,
        )
