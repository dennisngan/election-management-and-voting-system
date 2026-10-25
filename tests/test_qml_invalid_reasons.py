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


def test_admin_manages_the_f2_catalogue_through_material_in_all_locales(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    f1_before = admin.get(path).json()["items"]
    f2_before = admin.get(path, params={"stage": "f2"}).json()["items"]
    verified = next(row for row in f2_before if row["verified_source"])
    source_english = verified["source_english"]
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "verified_id": verified["id"],
            "source_english": source_english,
            "locale": "en",
        },
        """
        from PySide6.QtCore import QObject

        click('invalidReasonsNavigation')
        catalog = controller.property('invalidReasons')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        choose('invalidReasonElection', next(index for index, row in enumerate(
            catalog.property('state')['elections']) if row['id'] == setup['election_id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['stage'] == 'f1'
        assert len(catalog.property('state')['items']) == 8
        choose('invalidReasonStage', 1)
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['stage'] == 'f2'
        assert len(catalog.property('state')['items']) == 5
        assert all(row['stage'] == 'f2' for row in catalog.property('state')['items'])
        for language, caption in (
            ('tc', 'F2 無效選票判定'),
            ('sc', 'F2 无效选票判定'),
            ('en', 'F2 invalid-paper determination'),
        ):
            controller.setLocale(language)
            frame()
            assert control('invalidReasonStage').property('displayText') == caption, (
                language, control('invalidReasonStage').property('displayText'),
                control('invalidReasonStage').property('model'),
            )

        controller.setLocale('en')
        frame()
        other = next(row for row in catalog.property('state')['items'] if row['is_other'])
        choose('invalidReasonPicker', next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == other['id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert control('invalidReasonEnabled').property('enabled') is False
        assert control('invalidReasonExplanationRequired').property('enabled') is False
        assert catalog.property('state')['selected']['stage'] == 'f2'
        assert catalog.property('state')['selected']['enabled'] is True
        assert catalog.property('state')['selected']['explanation_required'] is True

        click('invalidReasonNew')
        enter('invalidReasonCode', 'project-f2-ui-reason')
        enter('invalidReasonLabelTc', '項目自訂判定原因')
        enter('invalidReasonLabelSc', '项目自定义判定原因')
        enter('invalidReasonLabelEn', 'Project F2 determination reason')
        click('invalidReasonSave')
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        project = catalog.property('state')['selected']
        assert project['stage'] == 'f2' and project['verified_source'] is False
        assert project['source_english'] == '' and project['source_letter'] is None
        assert project['reference_page'] is None and project['reference_printed_page'] is None

        choose('invalidReasonPicker', next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == setup['verified_id']))
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['selected']['source_english'] == setup['source_english']
        enter('invalidReasonLabelEn', 'Local F2 display label')
        click('invalidReasonSave')
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        changed = catalog.property('state')['selected']
        assert changed['stage'] == 'f2' and changed['revision'] == 2
        assert changed['source_english'] == setup['source_english']
        assert changed['verified_source'] is True

        enter('invalidReasonLabelTc', '尚未儲存的 F2 文字')
        assert catalog.property('state')['dirty'] is True
        choose('invalidReasonStage', 0)
        dialog = window.findChild(QObject, 'invalidReasonDiscardDialog')
        assert dialog is not None and dialog.property('visible') is True
        assert catalog.property('state')['stage'] == 'f2'
        assert control('invalidReasonLabelTc').property('text') == '尚未儲存的 F2 文字'
        click_confirmation(dialog, controller.texts['keep_editing'])
        assert catalog.property('state')['dirty'] is True
        assert catalog.property('state')['stage'] == 'f2'

        choose('invalidReasonStage', 0)
        click_confirmation(dialog, controller.texts['discard_changes'])
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['stage'] == 'f1'
        assert catalog.property('state')['dirty'] is False
        assert catalog.property('state')['selected'] == {}
        """,
    )
    f1_after = admin.get(path).json()["items"]
    assert f1_after == f1_before
    f2_after = admin.get(path, params={"stage": "f2"}).json()["items"]
    project = next(row for row in f2_after if row["code"] == "project-f2-ui-reason")
    changed = next(row for row in f2_after if row["id"] == verified["id"])
    assert project["stage"] == "f2" and project["source_english"] == ""
    assert changed["label_en"] == "Local F2 display label"
    assert changed["source_english"] == source_english and changed["revision"] == 2


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
