"""Dirty-basis and uncertain-retry edges for constituency tie decisions."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.test_constituency_tie_api import _save_tie_round, complete_tie_setup
from tests.test_counting_workflow_retry_desktop import (
    LostSelectionResponse,
)
from tests.test_counting_workflow_retry_desktop import (
    lost_selection_response as lost_selection_response,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_dirty_tie_review_tracks_same_digest_decision_and_discards_explicitly(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "result_path": result_path,
                "reason": "Local Supervisor review before the peer decision.",
                "peer_reason": "Second Supervisor confirms the same tied candidate.",
            },
            """
            import ssl
            import urllib.request
            import uuid
            from pathlib import Path

            results = controller.property('constituencyResults')
            assert results is not None
            prior_refresh = controller.property('state')['last_refresh']
            controller.refresh()
            wait(lambda: controller.property('state')['last_refresh'] != prior_refresh)
            assert results.property('state')['result'] == {}

            results.open()
            wait(lambda: not results.property('state')['busy'])
            reviewed = results.property('state')['result']
            candidate_id = reviewed['tie_candidate_ids'][0]
            results.setResolutionCandidate(candidate_id)
            assert results.property('state')['dirty'] is True
            results.setResolutionCandidate(candidate_id)
            assert results.property('state')['dirty'] is True
            results.setResolutionReason(setup['reason'])
            assert results.property('state')['dirty'] is True

            def post_json(path, payload, token=None):
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                request = urllib.request.Request(
                    setup['server'] + path,
                    data=json.dumps(payload).encode(),
                    headers=headers,
                    method='POST',
                )
                context = ssl.create_default_context(
                    cafile=str(Path('.runtime/tls/ca.pem').resolve())
                )
                with urllib.request.urlopen(request, context=context) as response:
                    return json.loads(response.read())

            session = post_json('/api/auth/login', {
                'username': setup['username'], 'password': setup['password']
            })
            peer = post_json(setup['result_path'] + '/tie-resolutions', {
                'request_id': str(uuid.uuid4()),
                'expected_resolution_revision': 0,
                'basis_digest': reviewed['basis_digest'],
                'candidate_id': candidate_id,
                'reason': setup['peer_reason'],
                'password': setup['password'],
            }, session['token'])
            assert peer['resolved_candidate_id'] == candidate_id
            assert peer['basis_digest'] == reviewed['basis_digest']

            results.refresh()
            wait(lambda: not results.property('state')['refreshing'])
            newer = results.property('state')
            assert newer['newer_basis'] is True
            assert newer['dirty'] is True
            assert newer['selected_candidate_id'] == candidate_id
            assert newer['reason'] == setup['reason']

            results.discardAndReload()
            wait(lambda: not results.property('state')['busy'])
            reloaded = results.property('state')
            assert reloaded['dirty'] is False
            assert reloaded['newer_basis'] is False
            assert reloaded['selected_candidate_id'] == 0
            assert reloaded['reason'] == ''
            assert reloaded['result']['tie_resolution']['revision'] == 1
            """,
        )
        assert https_server.request_count("GET", result_path) == 2


def test_dropped_tie_response_retries_original_receipt_with_fresh_password(
    admin: TestClient,
    database_url: str,
    lost_selection_response: LostSelectionResponse,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        endpoint = lost_selection_response
        endpoint.clock.value = setup["clock"].value
        endpoint.drop_path = (
            f"/api/workspace/constituencies/{setup['constituency_id']}/results/tie-resolutions"
        )
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        run_workspace_qml(
            {
                "server": endpoint.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "reason": "Supervisor decision committed before TLS response loss.",
                "wrong_password": "Wrong-Password-42!",
            },
            """
            import json

            results = controller.property('constituencyResults')
            assert results is not None
            results.open()
            wait(lambda: not results.property('state')['busy'])
            initial = results.property('state')['result']
            candidate_id = initial['tie_candidate_ids'][1]
            results.setResolutionCandidate(candidate_id)
            results.setResolutionReason(setup['reason'])
            results.resolveTie(setup['password'])
            wait(lambda: not results.property('state')['busy'])
            assert results.property('state')['uncertain_save'] is True

            results.refresh()
            wait(lambda: not results.property('state')['refreshing'])
            uncertain = results.property('state')
            assert uncertain['newer_basis'] is True
            assert uncertain['uncertain_save'] is True
            assert uncertain['selected_candidate_id'] == candidate_id
            assert uncertain['reason'] == setup['reason']

            results.resolveTie(setup['wrong_password'])
            wait(lambda: not results.property('state')['busy'])
            denied = results.property('state')
            assert denied['error'] == 'invalid_credentials'
            assert denied['uncertain_save'] is True
            assert denied['selected_candidate_id'] == candidate_id
            assert denied['reason'] == setup['reason']

            results.setResolutionCandidate(initial['tie_candidate_ids'][0])
            results.setResolutionReason('Changed command must not replace the pending receipt.')
            assert results.property('state')['selected_candidate_id'] == candidate_id
            assert results.property('state')['reason'] == setup['reason']
            results.discardAndReload()
            assert results.property('state')['uncertain_save'] is True
            assert results.property('state')['dirty'] is True

            results.resolveTie(setup['password'])
            wait(lambda: not results.property('state')['busy'])
            recovered = results.property('state')
            assert recovered['uncertain_save'] is False
            assert recovered['dirty'] is False
            assert recovered['newer_basis'] is False
            assert recovered['result']['resolved_candidate_id'] == candidate_id
            assert len(recovered['result']['resolution_history']) == 1
            assert setup['password'] not in json.dumps(recovered, ensure_ascii=False)
            """,
        )
        assert endpoint.response_tagged.is_set()
        assert endpoint.response_dropped.is_set()
        assert endpoint.request_count("POST", f"{result_path}/tie-resolutions") == 3
        result = setup["clients"]["supervisor"].get(result_path)
        assert result.status_code == 200, result.text
        assert len(result.json()["resolution_history"]) == 1
