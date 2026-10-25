"""Constituency-result controls use authenticated public state in the Material client."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
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


def test_authenticated_workspace_exposes_constituency_results_controller(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        api_result = setup["clients"]["supervisor"].get(
            f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        )
        assert api_result.status_code == 200, api_result.text
        assert api_result.json()["complete"] is True
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
            },
            "results = controller.property('constituencyResults')\n"
            "assert results is not None, 'Missing constituency-results controller'",
        )


def test_material_result_view_marks_missing_contribution_as_partial(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with result_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
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
            results = controller.property('constituencyResults')
            assert results is not None
            results.open()
            wait(lambda: not results.property('state')['busy'])
            state = results.property('state')
            record = state['result']
            assert record['complete'] is False
            assert record['provisional'] is True
            assert any(row['code'] == 'selected_count_missing' for row in record['pending'])
            assert any(row['quantity'] is None for row in record['candidate_totals'])
            assert all(row['quantity'] is None for row in record['candidate_totals'])
            """,
        )


def test_material_zero_tie_shows_received_scope_without_source_double_count(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
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
            results = controller.property('constituencyResults')
            assert results is not None
            results.open()
            wait(lambda: not results.property('state')['busy'])
            record = results.property('state')['result']
            assert record['complete'] is True
            assert record['provisional'] is True
            assert [row['quantity'] for row in record['candidate_totals']] == [0, 0]
            assert record['tie_candidate_ids'] == [
                row['candidate_id'] for row in record['candidate_totals']
            ]
            assert len(record['contributions']) == 2
            transferred = [
                box['id']
                for contribution in record['contributions']
                for box in contribution['frozen_source_context']['box_basis']
                if box['origin_station_id'] != box['destination_station_id']
            ]
            all_box_ids = {
                box['id']
                for contribution in record['contributions']
                for box in contribution['frozen_source_context']['box_basis']
            }
            assert setup['transferred_box_id'] in all_box_ids
            assert len(transferred) == 2
            """,
        )


def test_material_supervisor_resolves_explicit_tie_and_exports_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        csv_path = tmp_path / "constituency-result.csv"
        pdf_path = tmp_path / "constituency-result.pdf"
        reason = (
            "Supervisor reviewed the signed tie record and chose the explicitly selected candidate."
        )
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "reason": reason,
                "csv_path": str(csv_path),
                "pdf_path": str(pdf_path),
            },
            """
            results = controller.property('constituencyResults')
            assert results is not None
            results.open()
            wait(lambda: not results.property('state')['busy'])
            initial = results.property('state')['result']
            assert len(initial['tie_candidate_ids']) == 2
            candidate_id = initial['tie_candidate_ids'][1]
            results.setResolutionCandidate(candidate_id)
            results.setResolutionReason(setup['reason'])
            assert results.property('state')['dirty'] is True
            assert setup['password'] not in json.dumps(
                results.property('state'), ensure_ascii=False
            )
            results.resolveTie(setup['password'])
            wait(lambda: not results.property('state')['busy'])
            after = results.property('state')
            assert after['result']['resolved_candidate_id'] == candidate_id
            assert after['result']['resolution_history'][0]['reason'] == setup['reason']
            assert after['result']['resolution_history'][0]['valid'] is True
            assert setup['password'] not in json.dumps(after, ensure_ascii=False)
            results.reload()
            wait(lambda: not results.property('state')['busy'])
            assert results.property('state')['result']['resolved_candidate_id'] == candidate_id
            results.preview('en')
            wait(lambda: not results.property('state')['busy']
                and bool(results.property('state')['report']))
            assert setup['reason'] in results.property('state')['report_text']
            results.exportReport('en', 'csv', setup['csv_path'])
            wait(lambda: not results.property('state')['busy'])
            assert setup['password'] not in json.dumps(
                results.property('state'), ensure_ascii=False
            )
            results.exportReport('en', 'pdf', setup['pdf_path'])
            wait(lambda: not results.property('state')['busy'])
            """,
        )
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        assert reason in csv_text
        pdf_text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
        assert reason in pdf_text
        assert READY_PASSWORD not in csv_text and READY_PASSWORD not in pdf_text
