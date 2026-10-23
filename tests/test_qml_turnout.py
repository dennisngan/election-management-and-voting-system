"""Actual turnout controls drive real HTTPS workflows; Computer proof is separate."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from election.desktop.translations import TRANSLATIONS
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    submit_period,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_uses_visible_turnout_controls_to_save_and_submit_explicit_zero(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
                "navigation_label": TRANSLATIONS[locale]["turnout_title"],
            },
            """
            assert control('turnoutNavigation').property('text') == setup['navigation_label']
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy'])
            frame()
            assert turnout.property('state')['selected_period'] == 1
            assert control('turnoutHourly').property('readOnly') is False
            assert control('turnoutSubmit').property('enabled') is False
            enter('turnoutHourly', '0')
            enter('turnoutEventTime', '2026-11-15 09:30')
            enter('turnoutSource', '紙本明確零人，開站確認仍待處理')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('turnoutSave').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('turnoutSource').property('activeFocus'))
            click('turnoutSave')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['revision'] == 1
            assert control('turnoutHourly').property('text') == '0'
            assert control('turnoutCumulative').property('text') == ''
            frame()
            assert control('turnoutSubmit').property('enabled') is True
            click('turnoutSubmit')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['status'] == 'submitted'
            assert control('turnoutAmend').property('visible') is True
            assert control('turnoutSave').property('visible') is False
            assert control('turnoutApprovalPassword').property('visible') is False
            frame()
            choose('turnoutReportScope', 0)
            click('turnoutPreview')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['report']['report_scope'] == 'period_revision'
            assert turnout.property('state')['report']['revision'] == 1
            assert turnout.property('state')['report']['locale'] == setup['locale']
            assert '紙本明確零人' in control('turnoutReportPreview').property('text')
            frame()
            choose('turnoutReportScope', 1)
            click('turnoutPreview')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['report']['report_scope'] == 'station_current'
            assert turnout.property('state')['report']['period_count'] == 3
            """,
        )
        response = api.get(f"{path}/1")
        assert response.status_code == 200
        selected = response.json()
        assert selected["supplied_hourly"] == 0
        assert selected["supplied_cumulative"] is None
        assert selected["source_context"] == "紙本明確零人，開站確認仍待處理"
        assert selected["status"] == "submitted"


def test_supervisor_uses_approval_controls_and_password_is_erased_after_each_attempt(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (
            supervisor,
            account,
        ),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=0,
            event_at="2026-11-15T09:30:00+08:00",
            source_context="首個時段明確零人",
        )
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            """
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy'])
            frame()
            assert control('turnoutHourly').property('readOnly') is True
            assert control('turnoutSave').property('visible') is False
            enter('turnoutApprovalPassword', 'wrong-existing-password')
            click('turnoutApprove')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == 'invalid_credentials'
            assert control('turnoutApprovalPassword').property('text') == ''
            assert control('turnoutApprove').property('enabled') is False
            frame()
            enter('turnoutApprovalPassword', setup['password'])
            click('turnoutApprove')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['status'] == 'approved'
            assert turnout.property('state')['approved_prefix']['cumulative_end_display'] == '0'
            assert control('turnoutApprovalPassword').property('text') == ''
            assert control('turnoutApprovalPassword').property('enabled') is False
            """,
        )
        assert supervisor.get(path).json()["approved_prefix"]["cumulative_end"] == 0


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer"])
def test_history_control_opens_exact_read_only_revision_and_reload_returns_to_current(
    admin: TestClient, database_url: str, https_server: HttpsServer, role: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], role) as (_, account),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=10,
            event_at="2026-11-15T09:30:00+08:00",
            source_context="原外部報表",
        )
        amended = officer.post(
            f"{path}/1/amend",
            json=turnout_draft(
                1,
                supplied_hourly=12,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="重新核對外部報表",
                amendment_reason="核對後更正為十二人",
            ),
        )
        assert amended.status_code == 200
        submitted = officer.post(f"{path}/1/submit", json=turnout_command(2))
        assert submitted.status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "sc",
                "role": role,
            },
            """
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy']
                and len(turnout.property('state')['history']) == 2)
            frame()
            assert control('turnoutHourly').property('text') == '12'
            click('turnoutHistoryRevision1')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['revision'] == 1
            assert turnout.property('state')['historical'] is True
            assert control('turnoutHourly').property('text') == '10'
            assert control('turnoutHourly').property('readOnly') is True
            assert control('turnoutSource').property('readOnly') is True
            assert control('turnoutAmend').property('enabled') is False
            frame()
            click('turnoutReload')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['revision'] == 2
            assert turnout.property('state')['historical'] is False
            assert control('turnoutHourly').property('text') == '12'
            assert (control('turnoutHourly').property('readOnly')
                == (setup['role'] != 'polling_officer'))
            """,
        )


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_multiline_source_reason_and_readonly_preview_stay_inside_material_borders(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        submit_period(
            api,
            path,
            1,
            supplied_hourly=0,
            event_at="2026-11-15T09:30:00+08:00",
            source_context="原始外部報表",
        )
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
            },
            """
            def inside_border(name):
                field = control(name)
                field.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
                wait(lambda: field.property('activeFocus'))
                background = field.property('background')
                for position in (0, len(field.property('text'))):
                    field.setProperty('cursorPosition', position)
                    frame()
                    cursor = field.property('cursorRectangle')
                    inside = field.mapToItem(background, QPointF(cursor.x(), cursor.y()))
                    assert inside.y() >= 8, name + ' crosses its visible top border'
                    assert inside.y() + cursor.height() <= background.height() - 8
                    assert inside.x() >= 8, name + ' crosses its visible left border'
                    assert inside.x() + cursor.width() <= background.width() - 8

            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy']
                and turnout.property('state')['selected'].get('status') == 'submitted')
            frame()
            enter('turnoutSource', '來源第一行\\n來源第二行')
            inside_border('turnoutSource')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('turnoutAmendmentReason').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('turnoutSource').property('activeFocus'))
            inside_border('turnoutSource')
            enter('turnoutAmendmentReason', '修訂原因第一行\\n修訂原因第二行')
            inside_border('turnoutAmendmentReason')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('turnoutAmend').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('turnoutAmendmentReason').property('activeFocus'))
            inside_border('turnoutAmendmentReason')
            assert control('turnoutAmendmentReason').property('text') == (
                '修訂原因第一行\\n修訂原因第二行')
            click('turnoutAmend')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['revision'] == 2
            frame()
            click('turnoutPreview')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['report']['revision'] == 2
            preview = control('turnoutReportPreview')
            assert preview.property('readOnly') is True
            inside_border('turnoutReportPreview')
            saved_preview = preview.property('text')
            QTest.keyClick(window, Qt.Key.Key_9)
            assert preview.property('text') == saved_preview
            """,
        )
        current = api.get(f"{path}/1")
        assert current.status_code == 200
        assert current.json()["revision"] == 2
        assert current.json()["source_context"] == "來源第一行\n來源第二行"
        assert current.json()["amendment_reason"] == "修訂原因第一行\n修訂原因第二行"
