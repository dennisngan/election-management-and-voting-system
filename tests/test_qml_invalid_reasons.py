"""Invalid-ballot reason administration through the real Material workspace."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup
from tests.configuration_support import create_election
from tests.desktop_support import PERSONAL_PASSWORD, HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_invalid_reason_navigation_opens_the_actual_material_page(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    catalog_path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    seeded = admin.get(catalog_path)
    assert seeded.status_code == 200, seeded.text
    selected = seeded.json()["items"][0]
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": selected["id"],
            "locale": "en",
        },
        """
        click('invalidReasonsNavigation')
        catalog = controller.property('invalidReasons')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        elections = catalog.property('state')['elections']
        index = next(index for index, row in enumerate(elections)
            if row['id'] == setup['election_id'])
        choose('invalidReasonElection', index)
        wait(lambda: not catalog.property('state')['busy'])
        reasons = catalog.property('state')['items']
        reason_index = next(index for index, row in enumerate(reasons)
            if row['id'] == setup['reason_id'])
        choose('invalidReasonPicker', reason_index)
        wait(lambda: not catalog.property('state')['busy'])
        assert catalog.property('state')['selected']['id'] == setup['reason_id']
        """,
    )


def test_catalog_refresh_does_not_close_open_election_reason_or_history_picker(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    first = create_election(admin)
    second = create_election(admin)
    path = f"/api/elections/{first['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    revised = admin.put(
        path + f"/{original['id']}",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "label_tc": "第二版本繁體顯示",
            "label_sc": "第二版本简体显示",
            "label_en": "Second revision display",
            "enabled": True,
            "explanation_required": False,
        },
    )


    assert revised.status_code == 200, revised.text
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "first_election_id": first["id"],
            "second_election_id": second["id"],
            "reason_id": original["id"],
            "locale": "en",
        },
        """
        from PySide6.QtQml import QQmlProperty

        click('invalidReasonsNavigation')
        catalog = controller.property('invalidReasons')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        choose('invalidReasonElection', next(index for index, row in enumerate(
            catalog.property('state')['elections']) if row['id'] == setup['first_election_id']))
        wait(lambda: not catalog.property('state')['busy'])
        choose('invalidReasonPicker', next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == setup['reason_id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['selected']['revision'] == 2

        def refresh_with_popup(name, selection_index=None):
            picker = focus(name)
            visible = QQmlProperty(picker, 'popup.visible')
            assert visible.isValid(), name
            QTest.keyClick(window, Qt.Key.Key_Space)
            wait(lambda: visible.read())
            selected_index = picker.property('currentIndex')
            assert selected_index >= 0, (
                name, picker.property('currentIndex'),
                control('invalidReasonsPage').property('historyRows'),
                catalog.property('state')['selected'], catalog.property('state')['history']
            )
            catalog.refresh()
            wait(lambda: not any(catalog.property('state')[key]
                for key in ('busy', 'refreshing')))
            assert visible.read(), name + ' popup closed during refresh'
            assert picker.property('currentIndex') == selected_index
            if selection_index is None:
                QTest.keyClick(window, Qt.Key.Key_Down)
            else:
                QTest.keyClick(window, Qt.Key.Key_Home)
                for _ in range(selection_index):
                    QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            wait(lambda: not visible.read())

        refresh_with_popup('invalidReasonPicker')
        assert catalog.property('state')['selected']['id'] != setup['reason_id']
        choose('invalidReasonPicker', next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == setup['reason_id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['selected']['revision'] == 2

        refresh_with_popup('invalidReasonHistory')
        assert catalog.property('state')['selected']['revision'] == 1
        assert catalog.property('state')['historical'] is True

        second_election_index = next(index for index, row in enumerate(
            catalog.property('state')['elections'])
            if row['id'] == setup['second_election_id'])
        refresh_with_popup('invalidReasonElection', second_election_index)
        assert catalog.property('state')['election_id'] == setup['second_election_id']
        """,
    )


def test_reason_picker_stays_open_through_the_real_five_second_desktop_poll(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    reasons = admin.get(
        f"/api/elections/{election['id']}/invalid-ballot-reasons"
    ).json()["items"]
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": reasons[0]["id"],
            "locale": "en",
        },
        """
        from PySide6.QtQml import QQmlProperty

        click('invalidReasonsNavigation')
        catalog = controller.property('invalidReasons')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        choose('invalidReasonElection', next(index for index, row in enumerate(
            catalog.property('state')['elections']) if row['id'] == setup['election_id']))
        wait(lambda: not catalog.property('state')['busy'])
        choose('invalidReasonPicker', next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == setup['reason_id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))

        picker = focus('invalidReasonPicker')
        visible = QQmlProperty(picker, 'popup.visible')
        assert visible.isValid()
        selected_index = picker.property('currentIndex')
        selected_id = catalog.property('state')['selected']['id']
        previous_refresh = controller.property('state')['last_refresh']
        click('invalidReasonPicker')
        wait(lambda: visible.read())
        wait(lambda: controller.property('state')['last_refresh'] != previous_refresh, timeout=10)
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert visible.read(), 'The 5-second desktop poll closed the reason picker'
        assert picker.property('currentIndex') == selected_index
        assert catalog.property('state')['selected']['id'] == selected_id
        QTest.keyClick(window, Qt.Key.Key_Down)
        QTest.keyClick(window, Qt.Key.Key_Return)
        wait(lambda: not visible.read())
        assert catalog.property('state')['selected']['id'] != selected_id
        """,
        timeout=35,
    )
