"""Actual Material P(18) controls operate the real HTTPS/MySQL workflow."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.desktop.translations import TRANSLATIONS
from tests.desktop_support import HttpsServer
from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.qml_workspace_support import run_workspace_qml
from tests.special_paper_support import special_paper_setup
from tests.test_accounting_desktop import database_url as database_url
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer
from tests.turnout_support import READY_PASSWORD, turnout_staff


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_counter_uses_visible_sources_and_saves_exact_accounting_in_each_language(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": station_id,
                    "locale": locale,
                    "navigation_label": TRANSLATIONS[locale]["accounting_title"],
                    "pdf_label": TRANSLATIONS[locale]["stock_export_pdf"],
                    "csv_label": TRANSLATIONS[locale]["stock_export_csv"],
                },
                """
                assert control('accountingNavigation').property('text') == setup['navigation_label']
                click('accountingNavigation')
                editor = controller.property('accounting')
                wait(lambda: not editor.property('state')['busy'])
                frame()
                assert control('accountingSave').property('enabled') is False
                choose('accountingSpecialSource', 0)
                choose('accountingTurnoutSource', 1)
                enter('accountingNotes', '核對原始紙本；保留未觀察的實際張數。')
                assert_multiline_inside_border('accountingNotes')
                QTest.keyClick(window, Qt.Key.Key_Tab)
                wait(lambda: control('accountingSave').property('activeFocus'))
                click('accountingSave')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['error'] == ''
                assert editor.property('state')['selected']['revision'] == 1
                frame()
                assert control('accountingExportPdf').property('text') == setup['pdf_label']
                assert control('accountingExportCsv').property('text') == setup['csv_label']
                assert control('accounting_observed_counted_quantityValue').property('text') == '—'
                stock = control('accounting_estimated_box_from_stock_quantityValue')
                turnout = control('accounting_estimated_box_from_turnout_quantityValue')
                assert stock.property('text') == '2'
                assert turnout.property('text') == '—'
                click('accountingSubmit')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['error'] == ''
                assert editor.property('state')['selected']['status'] == 'submitted'
                frame()
                assert control('accountingReason').property('visible') is True
                assert control('accountingSave').property('enabled') is False
                enter('accountingNotes', '更正備註並保留原版。')
                enter('accountingReason', '重新核對紙本備註。')
                click('accountingSave')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['error'] == ''
                assert editor.property('state')['selected']['revision'] == 2
                choose('accountingHistory', 1)
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['historical'] is True
                assert editor.property('state')['selected']['revision'] == 1
                assert control('accountingNotes').property('readOnly') is True
                assert control('accountingSave').property('enabled') is False
                click('accountingReload')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['selected']['revision'] == 2
                assert control('accountingNotes').property('text') == '更正備註並保留原版。'
                """,
            )
            response = counter.get(setup["base"] + "/accounting")
            assert response.status_code == 200
            current = response.json()
            assert current["record"]["revision"] == 2
            assert current["record"]["notes"] == "更正備註並保留原版。"
            assert current["record"]["summary"]["observed_counted_quantity"] is None
            assert len(current["history"]) == 2


def test_supervisor_approves_exact_revision_and_password_is_erased_after_attempts(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        path = setup["base"] + "/accounting"
        https_server.clock.value = setup["clock"].value
        with (
            turnout_staff(
                admin, database_url, setup["clock"], [station_id], "counting_officer"
            ) as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id], "supervisor") as (
                supervisor,
                account,
            ),
        ):
            saved = counter.put(
                path,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "special_paper_id": special.json()["id"],
                    "special_paper_revision": 1,
                    "notes": "A source-station accounting revision for review.",
                },
            )
            assert saved.status_code == 200
            submitted = counter.post(
                path + "/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                },
            )
            assert submitted.status_code == 200
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": station_id,
                    "locale": "en",
                },
                """
                click('accountingNavigation')
                editor = controller.property('accounting')
                wait(lambda: not editor.property('state')['busy'])
                frame()
                assert control('accountingSave').property('visible') is False
                assert control('accountingNotes').property('readOnly') is True
                enter('accountingApprovalPassword', 'wrong-existing-password')
                click('accountingApprove')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['error'] == 'invalid_credentials'
                assert control('accountingApprovalPassword').property('text') == ''
                frame()
                enter('accountingApprovalPassword', setup['password'])
                click('accountingApprove')
                wait(lambda: not editor.property('state')['busy'])
                assert editor.property('state')['error'] == ''
                assert editor.property('state')['selected']['status'] == 'approved'
                assert editor.property('state')['selected']['approval_valid'] is True
                assert control('accountingApprovalPassword').property('text') == ''
                assert control('accountingApprove').property('enabled') is False
                """,
            )
            assert supervisor.get(path).json()["record"]["status"] == "approved"


def test_accounting_shows_approved_fallback_provenance_as_labeled_sources(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        approved_mixed_period(setup)
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            options = counter.get(setup["base"] + "/accounting")
            assert options.status_code == 200
            special = options.json()["special_options"][0]
            saved = counter.put(
                setup["base"] + "/accounting",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "special_paper_id": special["id"],
                    "special_paper_revision": 1,
                    "turnout_period_index": 2,
                    "turnout_revision": 1,
                },
            )
            assert saved.status_code == 200
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": station_id,
                    "locale": "en",
                },
                """
                click('accountingNavigation')
                editor = controller.property('accounting')
                wait(lambda: not editor.property('state')['busy'])
                frame()
                provenance = control('accountingTurnoutProvenanceValue')
                assert provenance.property('text') == 'Normal and fallback intervals'
                assert control('accountingStockTurnoutValue').property('text') == '115'
                assert control('accountingOrdinaryDeltaValue').property('text') == '5'
                estimate = control('accounting_estimated_box_from_turnout_quantityValue')
                assert estimate.property('text') == '115'
                coverage = control('accountingCoverage0Value')
                assert coverage.property('text') == '100 → 110 · Covered turnout 10'
                """,
            )
