"""A Supervisor reads actionable election completion through the actual Material UI."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import (
    READY_PASSWORD,
    draft_payload,
    polling_scope,
    ready_polling_staff,
)
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_opens_completion_and_sees_missing_actual_polling_in_material(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with ready_polling_staff(
        admin, database_url, "supervisor", station_ids
    ) as (_, account):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_ids[0],
                "locale": "en",
                "election_id": scope.election["id"],
                "required_station_ids": station_ids,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            assert completion is not None
            wait(lambda: not completion.property('state')['busy']
                and not completion.property('state')['refreshing'])
            state = completion.property('state')
            assert state['election_id'] == setup['election_id']
            assert state['error'] == ''
            assert state['assessment']['can_finalize'] is False
            assert control('electionCompletionStatus').property('text') == (
                'Election cannot be finalized yet')
            for station_id in setup['required_station_ids']:
                notice = control('electionCompletionBlocker_' + str(station_id))
                assert notice.property('visible')
                assert 'Polling completion is missing' in notice.property('text')
                assert str(station_id) in notice.property('text')
            """,
        )


@pytest.mark.parametrize(
    ("locale", "approval_message", "station_caption"),
    [
        ("en", "Polling completion requires current approval", "Polling station"),
        ("tc", "投票服務完成記錄需要有效批准", "投票站"),
        ("sc", "投票服务完成记录需要有效批准", "投票站"),
    ],
)
def test_supervisor_sees_draft_polling_completion_requires_approval_in_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    approval_message: str,
    station_caption: str,
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with (
        ready_polling_staff(
            admin, database_url, "polling_officer", station_ids
        ) as (officer, _),
        ready_polling_staff(
            admin, database_url, "supervisor", station_ids
        ) as (_, account),
    ):
        saved = officer.put(
            scope.path + "/service_completion",
            json=draft_payload(event_at="2025-11-15T23:25:00+08:00"),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "draft"
        assert saved.json()["revision"] == 1
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_ids[0],
                "locale": locale,
                "election_id": scope.election["id"],
                "constituency_id": scope.constituency["id"],
                "approval_message": approval_message,
                "station_caption": station_caption,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            assert completion is not None
            wait(lambda: not completion.property('state')['busy']
                and not completion.property('state')['refreshing'])
            state = completion.property('state')
            assert state['election_id'] == setup['election_id']
            assert state['error'] == ''
            assessment = state['assessment']
            assert assessment['can_finalize'] is False
            assert {
                'code': 'polling_completion_approval_required',
                'station_id': setup['station_id'],
                'constituency_id': setup['constituency_id'],
                'revision': 1,
                'status': 'draft',
            } in assessment['blockers']
            frame()
            notice = control('electionCompletionBlocker_' + str(setup['station_id']))
            assert notice.property('visible')
            assert notice.width() > 0 and notice.height() > 0
            assert _pointer_geometry(notice) is not None, (
                'The approval blocker must be inside the actual Material viewport')
            assert notice.property('text') == (
                setup['approval_message'] + ' · ' + setup['station_caption']
                + ' #' + str(setup['station_id']))
            """,
        )
