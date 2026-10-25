"""Constituency-result Material workflow over authenticated public state."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.test_constituency_tie_api import _save_tie_round, complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_result_page_exposes_complete_zero_tie_and_secure_resolution(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = setup["clients"]["supervisor"].get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is True
        assert [row["quantity"] for row in before.json()["candidate_totals"]] == [0, 0]
        assert len(before.json()["tie_candidate_ids"]) == 2

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "reason": "Supervisor records the explicitly chosen tied candidate.",
            },
            """
            results = controller.property('constituencyResults')
            assert results is not None
            click('constituencyResultsNavigation')
            wait(lambda: not results.property('state')['busy'])
            state = results.property('state')
            record = state['result']
            assert record['complete'] is True
            assert record['provisional'] is True
            assert [row['quantity'] for row in record['candidate_totals']] == [0, 0]
            assert record['tie_candidate_ids'] == [
                row['candidate_id'] for row in record['candidate_totals']
            ]
            assert state['selected_candidate_id'] == 0

            choose('constituencyResultTieCandidate', 1)
            candidate_id = record['tie_candidate_ids'][1]
            assert results.property('state')['selected_candidate_id'] == candidate_id
            enter('constituencyResultTieReason', setup['reason'])
            click('constituencyResultDiscard')
            click_confirmation(
                control('constituencyResultDiscardDialog'),
                controller.texts['constituency_result_discard_accept'],
            )
            wait(lambda: results.property('state')['dirty'] is False)
            discarded = results.property('state')
            assert discarded['selected_candidate_id'] == 0
            assert discarded['reason'] == ''

            choose('constituencyResultTieCandidate', 1)
            enter('constituencyResultTieReason', setup['reason'])
            click('constituencyResultResolveTie')
            enter('constituencyResultsPassword', setup['password'])
            click_confirmation(
                control('constituencyResultsPasswordDialog'),
                controller.texts['constituency_result_password_confirm'],
            )
            wait(lambda: not results.property('state')['busy'])
            resolved = results.property('state')
            assert resolved['result']['resolved_candidate_id'] == candidate_id
            assert resolved['result']['resolution_history'][0]['reason'] == setup['reason']
            assert resolved['result']['resolution_history'][0]['valid'] is True
            assert setup['password'] not in json.dumps(resolved, ensure_ascii=False)
            assert control('constituencyResultsPassword').property('text') == ''
            """,
        )
        after = setup["clients"]["supervisor"].get(result_path)
        assert after.status_code == 200, after.text
        assert after.json()["resolved_candidate_id"] == before.json()["tie_candidate_ids"][1]
        assert len(after.json()["resolution_history"]) == 1
