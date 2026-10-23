"""Actual complaint case controls exercise HTTPS/MySQL; Computer proof is separate."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from election.desktop.translations import TRANSLATIONS
from tests.complaint_period_support import complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    category_edit,
    complaint_payload,
    complaint_staff,
    complaint_stations,
    station_categories,
)
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml

READY_PASSWORD = "Complaint-Ready-Test-84!"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_creates_completes_and_reviews_case_history_through_visible_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station["id"],
                "locale": locale,
                "status_label": TRANSLATIONS[locale]["complaint_in_progress"],
            },
            """
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            assert control('complaintReference').property('visible')
            assert not control('complaintReference').property('readOnly')
            assert control('complaintWorkStatus').property('currentText') == setup['status_label']
            enter('complaintReference', 'UI0001')
            enter('complaintReceivedTime', '2026-11-15 08:15')
            choose('complaintCategory', 0)
            enter('complaintDescription', '入口安排 <保留原文> & source')
            choose('complaintWorkStatus', 0)
            assert not control('complaintCompletedTime').property('visible')
            enter('complaintReason', '新案件可填補錄原因')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('complaintCreate').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('complaintReason').property('activeFocus'))
            click('complaintCreate')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['revision'] == 1
            assert (control('complaintDescription').property('text')
                == '入口安排 <保留原文> & source')
            frame()
            choose('complaintWorkStatus', 1)
            assert control('complaintCompletedTime').property('visible')
            enter('complaintCompletedTime', '2026-11-15 09:15')
            click('complaintEdit')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['revision'] == 2
            assert cases.property('state')['selected']['work_status'] == 'completed'
            frame()
            click('complaintHistoryRevision1')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['historical']
            assert cases.property('state')['selected']['revision'] == 1
            assert control('complaintReference').property('readOnly')
            assert not control('complaintEdit').property('enabled')
            assert not control('complaintAmend').property('enabled')
            frame()
            click('complaintReload')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['selected']['revision'] == 2
            assert not control('complaintReference').property('readOnly')
            """,
        )
        response = api.get(path)
        assert response.status_code == 200
        (case,) = response.json()["items"]
        assert case["case_reference"] == "UI0001" and case["revision"] == 2
        assert case["work_status"] == "completed"
        assert case["completed_at"] == "2026-11-15T01:15:00Z"


def test_receipt_correction_into_submitted_period_has_a_reasoned_gui_recovery_path(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    sid, path, periods = scope["station"]["id"], scope["case_path"], scope["path"]
    https_server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        created = api.post(
            path,
            json=complaint_payload(
                station_categories(api, sid)[0], received_at="2026-11-15T06:30:00+08:00"
            ),
        )
        assert created.status_code == 201
        original = created.json()
        assert original["requires_amendment"] is False
        assert api.put(periods + "/1", json=period_command()).status_code == 200
        assert api.post(periods + "/1/submit", json=period_command(1)).status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": sid,
                "locale": "en",
            },
            """
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            choose('complaintPicker', 0)
            wait(lambda: not cases.property('state')['busy'])
            assert not cases.property('state')['requires_amendment']
            enter('complaintReceivedTime', '2026-11-15 08:15')
            click('complaintEdit')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == 'complaint_amendment_required'
            assert cases.property('state')['forms']['received_time'] == '2026-11-15 08:15'
            assert control('complaintAmend').property('visible')
            enter('complaintReason', '紙本顯示接收時間應屬已提交時段，保留修正原因')
            click('complaintAmend')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['revision'] == 2
            assert cases.property('state')['selected']['requires_amendment']
            """,
        )
        history = api.get(f"{path}/{original['id']}/history").json()["items"]
        assert len(history) == 2
        assert history[0]["received_at"] == "2026-11-14T22:30:00Z"
        assert history[1]["received_at"] == "2026-11-15T00:15:00Z"
        assert history[1]["amendment_reason"] == "紙本顯示接收時間應屬已提交時段，保留修正原因"
        report = api.get(periods + "/1").json()
        assert report["total_received"] == 0 and report["members"] == []
        assert report["basis_current"] is False


def test_protected_case_uses_reasoned_amendment_and_late_new_case_keeps_reason_accessible(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    sid, path, periods = scope["station"]["id"], scope["case_path"], scope["path"]
    https_server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        original = api.post(path, json=complaint_payload(station_categories(api, sid)[0])).json()
        assert api.put(periods + "/1", json=period_command()).status_code == 200
        assert api.post(periods + "/1/submit", json=period_command(1)).status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": sid,
                "locale": "en",
            },
            """
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            choose('complaintPicker', 0)
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['requires_amendment']
            assert not control('complaintEdit').property('enabled')
            assert control('complaintAmend').property('visible')
            enter('complaintDescription', '已提交統計的案件更正')
            click('complaintAmend')
            assert cases.property('state')['error'] == 'complaint_amendment_reason_required'
            assert cases.property('state')['forms']['description'] == '已提交統計的案件更正'
            enter('complaintReason', '按紙本修訂原因')
            click('complaintAmend')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['revision'] == 2
            assert cases.property('state')['selected']['amendment_reason'] == '按紙本修訂原因'
            frame()
            click('complaintNew')
            wait(lambda: not cases.property('state')['selected'])
            enter('complaintReference', 'LATEUI0001')
            enter('complaintReceivedTime', '2026-11-15 08:20')
            choose('complaintCategory', 0)
            enter('complaintDescription', '新增遲錄案件')
            assert control('complaintReason').property('visible')
            click('complaintCreate')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == 'complaint_late_reason_required'
            assert cases.property('state')['forms']['case_reference'] == 'LATEUI0001'
            enter('complaintReason', '補錄至已提交時段的理由')
            click('complaintCreate')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['requires_amendment']
            assert not cases.property('state')['selected']['ever_submitted']
            """,
        )
        assert len(api.get(f"{path}/{original['id']}/history").json()["items"]) == 2
        late = next(
            row for row in api.get(path).json()["items"] if row["case_reference"] == "LATEUI0001"
        )
        assert late["amendment_reason"] == "補錄至已提交時段的理由"


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_counting_officer_and_supervisor_read_case_controls_without_write_actions(
    admin: TestClient, database_url: str, https_server: HttpsServer, role: str
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    sid = station["id"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{sid}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (officer, _):
        original = officer.post(
            path, json=complaint_payload(station_categories(officer, sid)[0])
        ).json()
    with complaint_staff(admin, database_url, clock, role, [sid]) as (api, account):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": sid,
                "locale": "sc",
            },
            """
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            choose('complaintPicker', 0)
            wait(lambda: not cases.property('state')['busy'])
            assert control('complaintReference').property('visible')
            assert control('complaintReference').property('readOnly')
            assert control('complaintDescription').property('readOnly')
            assert not control('complaintCategory').property('enabled')
            assert not control('complaintWorkStatus').property('enabled')
            for name in ('complaintCreate', 'complaintEdit', 'complaintAmend', 'complaintNew'):
                assert not control(name).property('visible')
            assert control('complaintReload').property('enabled')
            frame()
            click('complaintHistoryRevision1')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['selected']['revision'] == 1
            assert not cases.property('state')['dirty']
            """,
        )
        assert api.get(path).json()["items"] == [original]


def test_dirty_new_revision_and_reload_actions_require_real_cancel_or_discard_confirmation(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    sid = station["id"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{sid}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        category = station_categories(api, sid)[0]
        original = api.post(path, json=complaint_payload(category)).json()
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": sid,
                "locale": "tc",
                "original_description": original["description"],
            },
            """
            from PySide6.QtCore import QObject
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            choose('complaintPicker', 0)
            wait(lambda: not cases.property('state')['busy'])
            enter('complaintDescription', '尚未儲存的內容')
            click('complaintNew')
            dialog = window.findChild(QObject, 'complaintDiscardDialog')
            assert dialog is not None
            wait(lambda: dialog.property('visible'))
            click('complaintKeepEditing')
            wait(lambda: not dialog.property('visible'))
            assert cases.property('state')['forms']['description'] == '尚未儲存的內容'
            assert cases.property('state')['selected']['revision'] == 1
            click('complaintReload')
            wait(lambda: dialog.property('visible'))
            click('complaintDiscardChanges')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not cases.property('state')['busy'] and
                cases.property('state')['forms']['description'] == setup['original_description'])
            assert not cases.property('state')['dirty']
            enter('complaintReason', '未儲存的歷史切換測試')
            click('complaintHistoryRevision1')
            wait(lambda: dialog.property('visible'))
            click('complaintKeepEditing')
            wait(lambda: not dialog.property('visible'))
            assert cases.property('state')['forms']['reason'] == '未儲存的歷史切換測試'
            click('complaintNew')
            wait(lambda: dialog.property('visible'))
            click('complaintDiscardChanges')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not cases.property('state')['selected'])
            assert cases.property('state')['forms']['description'] == ''
            assert not cases.property('state')['dirty']
            """,
        )
        assert api.get(path).json()["items"] == [original]


def test_disabled_category_keeps_frozen_label_and_provenance_and_outside_period_warning(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = complaint_stations(admin), ComplaintClock()
    sid = scope["N1"]["id"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{sid}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        category = station_categories(api, sid)[0]
        original = api.post(
            path, json=complaint_payload(category, received_at="2026-11-15T07:29:00+08:00")
        ).json()
        changed = admin.put(
            f"/api/elections/{scope['election']['id']}/complaint-categories/{category['id']}",
            json=category_edit(category, label_tc="後來的名稱", enabled=False),
        )
        assert changed.status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": sid,
                "locale": "tc",
                "original_label": original["category_label_tc"],
                "category_id": category["id"],
            },
            """
            click('complaintsNavigation')
            cases = controller.property('complaints')
            wait(lambda: not cases.property('state')['busy'])
            frame()
            choose('complaintPicker', 0)
            wait(lambda: not cases.property('state')['busy'])
            assert setup['original_label'] in control('complaintCategory').property('displayText')
            assert '後來的名稱' not in control('complaintCategory').property('displayText')
            assert control('complaintFrozenCategory').property('visible')
            source = control('complaintCategorySource').property('value')
            assert 'Polling arrangements' in source and '61' in source
            assert control('complaintOutsideCoverage').property('visible')
            choose('complaintCategory', 0)
            enter('complaintDescription', '保留原分類及時段外實際時間')
            click('complaintEdit')
            wait(lambda: not cases.property('state')['busy'])
            assert cases.property('state')['error'] == ''
            assert cases.property('state')['selected']['category_revision'] == 1
            assert cases.property('state')['selected']['period_index'] is None
            frame()
            click('complaintNew')
            wait(lambda: not cases.property('state')['selected'])
            assert control('complaintCategory').property('count') == 4
            choose('complaintCategory', 0)
            assert int(cases.property('state')['forms']['category_id']) != setup['category_id']
            """,
        )
        saved = api.get(path).json()["items"][0]
        assert saved["category_label_tc"] == original["category_label_tc"]
        assert saved["received_at"] == original["received_at"] and saved["period_index"] is None
