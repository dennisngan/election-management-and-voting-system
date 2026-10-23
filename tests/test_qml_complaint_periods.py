"""Actual P19 Material actions use the approved real API and MySQL seams."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from election.desktop.translations import TRANSLATIONS
from tests.complaint_period_support import READY_PASSWORD, complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    complaint_payload,
    complaint_staff,
    station_categories,
)
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_prepares_zero_submits_amends_and_reads_old_p19_through_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    station_id = scope["station"]["id"]
    https_server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        api,
        account,
    ):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
                "navigation_label": TRANSLATIONS[locale]["complaint_period_title"],
            },
            """
            assert (control('complaintPeriodsNavigation').property('text')
                    == setup['navigation_label'])
            click('complaintPeriodsNavigation')
            periods = controller.property('complaintPeriods')
            wait(lambda: not periods.property('state')['busy'])
            frame()
            assert periods.property('state')['current']['status'] == 'missing'
            click('complaintPeriodPrepare')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            assert control('complaintPeriodReceivedTotal').property('value') == '0'
            assert periods.property('state')['selected']['members'] == []
            frame()
            click('complaintPeriodSubmit')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['selected']['status'] == 'submitted'
            frame()
            enter('complaintPeriodReason', '核對本時段案件後重新準備')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('complaintPeriodAmend').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('complaintPeriodReason').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('complaintPeriodAmend').property('activeFocus'))
            click('complaintPeriodAmend')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            assert periods.property('state')['selected']['revision'] == 2
            wait(lambda: len(periods.property('state')['history']) == 2)
            frame()
            click('complaintPeriodHistoryRevision1')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['historical'] is True
            assert periods.property('state')['selected']['status'] == 'submitted'
            assert control('complaintPeriodAmend').property('enabled') is False
            assert control('complaintPeriodReason').property('readOnly') is True
            frame()
            click('complaintPeriodReload')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['selected']['revision'] == 2
            assert periods.property('state')['historical'] is False
            """,
        )
        response = api.get(scope["path"] + "/1")
        assert response.status_code == 200
        row = response.json()
        assert row["revision"] == 2 and row["status"] == "draft"
        assert row["total_received"] == row["total_completed"] == row["total_in_progress"] == 0
        assert row["amendment_reason"] == "核對本時段案件後重新準備"


def test_supervisor_p19_control_reconfirms_and_erases_existing_password(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    station_id, path = scope["station"]["id"], scope["path"]
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [station_id]) as (api, _),
        complaint_staff(admin, database_url, clock, "supervisor", [station_id]) as (sv, account),
    ):
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            """
            click('complaintPeriodsNavigation')
            periods = controller.property('complaintPeriods')
            wait(lambda: not periods.property('state')['busy'])
            frame()
            assert control('complaintPeriodPrepare').property('visible') is False
            enter('complaintPeriodPassword', 'wrong-existing-password')
            click('complaintPeriodApprove')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == 'invalid_credentials'
            assert control('complaintPeriodPassword').property('text') == ''
            frame()
            enter('complaintPeriodPassword', setup['password'])
            click('complaintPeriodApprove')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            assert periods.property('state')['selected']['approval_valid'] is True
            assert periods.property('state')['summary']['approved_current_display'] == '1'
            assert control('complaintPeriodPassword').property('text') == ''
            assert control('complaintPeriodApprove').property('enabled') is False
            """,
        )
        assert sv.get(path + "/1").json()["approval_valid"] is True


def test_counting_officer_reads_frozen_zero_and_live_stale_basis_then_previews_both_report_scopes(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    station_id, path = scope["station"]["id"], scope["path"]
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [station_id]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [station_id]) as (sv, _),
        complaint_staff(admin, database_url, clock, "counting_officer", [station_id]) as (
            reader,
            account,
        ),
    ):
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        approved = sv.post(path + "/1/approve", json=period_command(1, password=READY_PASSWORD))
        assert approved.status_code == 200
        category = station_categories(po, station_id)[0]
        late = po.post(
            scope["case_path"], json=complaint_payload(category, reason="紙本投訴恢復後補錄")
        )
        assert late.status_code == 201
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            """
            click('complaintPeriodsNavigation')
            periods = controller.property('complaintPeriods')
            wait(lambda: not periods.property('state')['busy'])
            frame()
            assert control('complaintPeriodReceivedTotal').property('value') == '0'
            assert periods.property('state')['selected']['status'] == 'approved'
            assert periods.property('state')['selected']['members'] == []
            assert periods.property('state')['current']['review_required'] is True
            assert periods.property('state')['current']['approval_valid'] is False
            assert control('complaintPeriodPrepare').property('visible') is False
            assert control('complaintPeriodApprove').property('visible') is False
            assert control('complaintPeriodReason').property('readOnly') is True
            assert control('complaintPeriodReportScope').property('currentIndex') == 0
            click('complaintPeriodPreview')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            report = periods.property('state')['report']
            assert report['report_scope'] == 'period_revision'
            assert report['items'][0]['total_received'] == 0
            assert report['items'][0]['approved_by'] is not None
            assert report['summary'] is None
            assert control('complaintPeriodReportPreview').property('readOnly') is True
            choose('complaintPeriodReportScope', 1)
            click('complaintPeriodPreview')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            report = periods.property('state')['report']
            assert report['report_scope'] == 'station_current'
            assert report['summary'] == {'required': 3, 'missing': 2, 'approved_current': 0}
            assert periods.property('state')['selected']['total_received'] == 0
            assert periods.property('state')['historical'] is False
            """,
        )
        assert reader.get(path + "/1").json()["total_received"] == 0


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_p19_preview_and_multiline_amendment_fit_borders_and_preserve_read_only_text(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    station_id, path = scope["station"]["id"], scope["path"]
    https_server.clock.value = clock.value
    reason = "時段修訂第一行：核對紙本案件。\n時段修訂第二行：確認本時段明確零宗。"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        api,
        account,
    ):
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
                "reason": reason,
            },
            """
            click('complaintPeriodsNavigation')
            periods = controller.property('complaintPeriods')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['selected']['status'] == 'submitted'
            frame()
            click('complaintPeriodPreview')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            assert periods.property('state')['report']['locale'] == setup['locale']
            preview = control('complaintPeriodReportPreview')
            assert preview.property('readOnly') is True
            assert_multiline_inside_border('complaintPeriodReportPreview')
            original_preview = preview.property('text')
            QTest.keyClick(window, Qt.Key.Key_9)
            assert preview.property('text') == original_preview
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: not preview.property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: preview.property('activeFocus'))
            assert_multiline_inside_border('complaintPeriodReportPreview')

            enter('complaintPeriodReason', setup['reason'])
            assert_multiline_inside_border('complaintPeriodReason')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('complaintPeriodAmend').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('complaintPeriodReason').property('activeFocus'))
            assert_multiline_inside_border('complaintPeriodReason')
            assert control('complaintPeriodReason').property('text') == setup['reason']
            click('complaintPeriodAmend')
            wait(lambda: not periods.property('state')['busy'])
            saved = periods.property('state')
            assert saved['error'] == '' and saved['selected']['revision'] == 2
            assert saved['selected']['amendment_reason'] == setup['reason']
            assert saved['selected']['total_received'] == 0
            assert saved['selected']['members'] == []
            frame()
            click('complaintPeriodPreview')
            wait(lambda: not periods.property('state')['busy'])
            assert periods.property('state')['error'] == ''
            assert periods.property('state')['report']['revision'] == 2
            assert_multiline_inside_border('complaintPeriodReportPreview')
            saved_preview = preview.property('text')
            assert all(line in saved_preview for line in setup['reason'].splitlines())
            QTest.keyClick(window, Qt.Key.Key_9)
            assert preview.property('text') == saved_preview
            """,
        )
        current = api.get(path + "/1")
        assert current.status_code == 200
        row = current.json()
        assert row["revision"] == 2 and row["status"] == "draft"
        assert row["amendment_reason"] == reason
        assert row["total_received"] == row["total_completed"] == row["total_in_progress"] == 0
        assert row["members"] == []
        history = api.get(path + "/1/history")
        assert history.status_code == 200
        rows = history.json()["items"]
        assert [entry["revision"] for entry in rows] == [1, 2]
        assert rows[0]["status"] == "submitted" and rows[0]["amendment_reason"] == ""
        assert rows[1]["amendment_reason"] == reason
