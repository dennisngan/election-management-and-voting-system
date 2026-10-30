"""The actual Material allocation controls save through real TLS and MySQL."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import READY_PASSWORD, ready_client, staff_account
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_uses_visible_controls_to_allocate_ordinary_stock(
    allocation_setup: dict, https_server: HttpsServer, locale: str
) -> None:
    setup = allocation_setup
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
            "locale": locale,
        },
        """
        click('allocationNavigation')
        editor = controller.property('allocations')
        wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
        frame()
        choose('allocationCounter', 0)
        enter('allocationSeries', '普通系列 A')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000003')
        enter('allocationEventAt', '2026-11-08 08:05')
        assert control('allocationQuantity').property('text') == '3'
        assert control('allocationQuantity').property('readOnly') is True
        click('allocationSave')
        wait(lambda: not any(editor.property('state')[key] for key in ('busy', 'refreshing')))
        assert editor.property('state')['error'] == ''
        assert editor.property('state')['selected']['revision'] == 1
        assert editor.property('state')['availability'][0]['available_display'] == '5'
        assert control('allocationSerialFrom').property('text') == '000001'
        """,
    )
    current = setup["officer"].get(setup["base"] + "/allocations").json()
    assert len(current["items"]) == 1
    assert current["items"][0]["quantity"] == 3


def test_historical_counter_field_displays_the_frozen_name_after_counter_rename(
    allocation_setup: dict, admin: TestClient, https_server: HttpsServer
) -> None:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    created = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    renamed = admin.put(
        setup["counter_base"] + f"/{setup['counter']['id']}",
        json={"code": "C1", "name": "後來更名櫃台", "revision": 1},
    )
    assert renamed.status_code == 200
    amended = setup["officer"].put(
        path + f"/{created.json()['id']}",
        json=allocation_payload(setup["counter"]["id"], revision=1, reason="核對交收文件"),
    )
    assert amended.status_code == 200
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
        },
        """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        choose('allocationPicker', 0)
        wait(idle)
        assert control('allocationCounter').property('displayText') == 'C1 · 後來更名櫃台'
        click('allocationHistoryRevision1')
        wait(idle)
        assert control('allocationCounter').property('enabled') is False
        assert control('allocationCounter').property('displayText') == 'C1 · 發票櫃台一'
        """,
    )
    current = setup["officer"].get(setup["base"] + "/allocations").json()
    assert len(current["items"]) == 1
    assert current["items"][0]["revision"] == 2
    assert current["items"][0]["counter"]["name"] == "後來更名櫃台"


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_visible_amendment_history_and_report_scope_controls_keep_reviewed_revision(
    allocation_setup: dict, https_server: HttpsServer, locale: str
) -> None:
    setup = allocation_setup
    response = setup["officer"].post(
        setup["base"] + "/allocations", json=allocation_payload(setup["counter"]["id"])
    )

    assert response.status_code == 201
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
            "locale": locale,
        },
        """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        choose('allocationPicker', 0)
        wait(idle)
        enter('allocationSerialTo', '000004')
        enter('allocationReason', '紙本派發單更正至四張')
        frame()
        reason = control('allocationReason')
        background = reason.property('background')
        cursor = reason.property('cursorRectangle')
        inside = reason.mapToItem(background, QPointF(cursor.x(), cursor.y()))
        assert inside.y() >= 8, 'The reason text crosses its visible top border'
        assert inside.y() + cursor.height() <= background.height() - 8
        QTest.keyClick(window, Qt.Key.Key_Tab)
        wait(lambda: control('allocationSave').property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Backtab)
        wait(lambda: control('allocationReason').property('activeFocus'))
        cursor = reason.property('cursorRectangle')
        inside = reason.mapToItem(background, QPointF(cursor.x(), cursor.y()))
        assert inside.y() >= 8, 'Reverse focus moves the reason outside its border'
        click('allocationSave')
        wait(idle)
        assert editor.property('state')['error'] == ''
        assert editor.property('state')['selected']['revision'] == 2
        click('allocationHistoryRevision1')
        wait(idle)
        assert editor.property('state')['historical'] is True
        assert control('allocationSerialTo').property('text') == '000003'
        assert control('allocationSerialTo').property('readOnly') is True
        assert control('allocationCounter').property('enabled') is False
        assert control('allocationSave').property('visible') is False
        choose('allocationReportScope', 1)
        click('allocationPreview')
        wait(idle)
        assert editor.property('state')['report']['revision'] == 1
        assert editor.property('state')['report']['availability'] is None
        assert editor.property('state')['report']['locale'] == setup['locale']
        assert '000003' in control('allocationReportPreview').property('text')
        assert control('allocationReportPreview').property('readOnly') is True
        choose('allocationReportScope', 0)
        click('allocationPreview')
        wait(idle)
        assert editor.property('state')['report']['report_scope'] == 'station_current'
        assert editor.property('state')['report']['items'][0]['revision'] == 2
        assert editor.property('state')['selected']['revision'] == 1
        click('allocationReload')
        wait(idle)
        assert editor.property('state')['selected']['revision'] == 2
        assert control('allocationSerialTo').property('readOnly') is False
        """,
    )


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_read_only_roles_see_working_review_controls_without_editing_or_save_actions(
    allocation_setup: dict,
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    role: str,
) -> None:
    setup = allocation_setup
    created = setup["officer"].post(
        setup["base"] + "/allocations", json=allocation_payload(setup["counter"]["id"])
    )
    assert created.status_code == 201
    account = staff_account(admin, [setup["station"]["id"]], role)
    with ready_client(database_url, account):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": setup["station"]["id"],
            },
            """
            click('allocationNavigation')
            editor = controller.property('allocations')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            frame()
            assert control('allocationNew').property('visible') is False
            choose('allocationPicker', 0)
            wait(idle)
            assert control('allocationCounter').property('enabled') is False
            assert control('allocationSerialTo').property('readOnly') is True
            assert control('allocationReason').property('readOnly') is True
            assert control('allocationSave').property('visible') is False
            item = focus('allocationSerialTo')
            QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(window, Qt.Key.Key_9)
            assert item.property('text') == '000003'
            choose('allocationReportScope', 1)
            click('allocationPreview')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['report']['revision'] == 1
            assert control('allocationReportPreview').property('text').startswith(
                'P(14) 發票櫃台選票派發紀錄')
            assert control('allocationExportPdf').property('enabled') is True
            assert control('allocationExportCsv').property('enabled') is True
            """,
        )
