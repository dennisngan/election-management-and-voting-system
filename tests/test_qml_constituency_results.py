"""Constituency-result Material workflow over authenticated public state."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import result_setup
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
                "transferred_box_id": setup["boxes"]["transferred_n2"]["id"],
                "reason": "Supervisor records the explicitly chosen tied candidate.",
            },
            """
            from PySide6.QtCore import QObject
            results = controller.property('constituencyResults')
            assert results is not None
            click('constituencyResultsNavigation')
            wait(lambda: not results.property('state')['busy'])
            state = results.property('state')
            record = state['result']
            assert record['complete'] is True
            assert record['provisional'] is True
            assert control('constituencyResultsCompleteValue').property('text') == (
                controller.texts['constituency_results_yes']
            )
            assert control('constituencyResultsProvisionalValue').property('text') == (
                controller.texts['constituency_results_yes']
            )
            assert [row['quantity'] for row in record['candidate_totals']] == [0, 0]
            assert record['tie_candidate_ids'] == [
                row['candidate_id'] for row in record['candidate_totals']
            ]
            assert state['selected_candidate_id'] == 0
            page = control('constituencyResultsPage')
            for locale in ('en', 'tc', 'sc'):
                controller.setLocale(locale)
                expected_captions = {
                    controller.texts['selected_election'],
                    controller.texts['constituency_name'],
                }
                def result_captions():
                    return {item.property('text') for item in page.findChildren(QObject)
                            if isinstance(item.property('text'), str)}
                wait(lambda: expected_captions <= result_captions())
                expected_votes_caption = {
                    'en': 'Candidate valid votes', 'tc': '候選人有效票', 'sc': '候选人有效票'
                }[locale]
                wait(lambda: sum(item.property('text') == expected_votes_caption
                                 for item in page.findChildren(QObject))
                     == len(record['contributions']))
            controller.setLocale('en')
            received_box = control(
                'constituencyResultBox_' + str(setup['transferred_box_id'])
            )
            assert controller.texts['box_received_status'] in received_box.property('text')

            choose('constituencyResultTieCandidate', 1)
            candidate_id = record['tie_candidate_ids'][1]
            assert results.property('state')['selected_candidate_id'] == candidate_id
            enter('constituencyResultTieReason', setup['reason'])
            click('constituencyResultDiscard')
            click_confirmation(
                window.findChild(QObject, 'constituencyResultDiscardDialog'),
                controller.texts['constituency_results_confirm_discard'],
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
                window.findChild(QObject, 'constituencyResultsPasswordDialog'),
                controller.texts['constituency_results_confirm'],
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


def test_supervisor_result_page_keeps_missing_contributions_null_and_unresolvable(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with result_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = setup["clients"]["supervisor"].get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is False
        assert any(row["quantity"] is None for row in before.json()["candidate_totals"])

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "transferred_box_id": setup["boxes"]["transferred_n2"]["id"],
            },
            """
            from PySide6.QtCore import QObject
            results = controller.property('constituencyResults')
            assert results is not None
            click('constituencyResultsNavigation')
            wait(lambda: not results.property('state')['busy'])
            state = results.property('state')
            record = state['result']
            assert record['complete'] is False
            assert record['provisional'] is True
            assert control('constituencyResultsCompleteValue').property('text') == (
                controller.texts['constituency_results_no']
            )
            assert control('constituencyResultsProvisionalValue').property('text') == (
                controller.texts['constituency_results_yes']
            )
            assert any(row['code'] == 'selected_count_missing' for row in record['pending'])
            assert all(row['quantity'] is None for row in record['candidate_totals'])
            for row in record['candidate_totals']:
                displayed = control(
                    'constituencyResultCandidateVotes_' + str(row['candidate_id'])
                ).property('text')
                assert displayed == '—'
            assert control('constituencyResultsTiePanel').property('visible') is False
            """,
        )
