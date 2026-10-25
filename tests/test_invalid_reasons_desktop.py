"""Invalid-reason catalogue edits through the authenticated Material client."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup
from tests.configuration_support import create_election
from tests.desktop_support import PERSONAL_PASSWORD, TLS_DIRECTORY, HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize(
    ("locale", "navigation_caption", "revision_caption"),
    [
        ("tc", "無效選票原因", "原因版本"),
        ("sc", "无效选票原因", "原因版本"),
        ("en", "Invalid ballot reasons", "Reason revision"),
    ],
)
def test_admin_edits_display_labels_creates_project_reason_and_reads_history(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    locale: str,
    navigation_caption: str,
    revision_caption: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    seeded = admin.get(path)
    assert seeded.status_code == 200, seeded.text
    original = seeded.json()["items"][0]
    other = next(row for row in seeded.json()["items"] if row["is_other"])
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": original["id"],
            "other_id": other["id"],
            "source_english": original["source_english"],
            "original_label_en": original["label_en"],
            "locale": locale,
            "navigation_caption": navigation_caption,
            "revision_caption": revision_caption,
            "project_code": "project-f1-display-note",
        },
        """
        click('invalidReasonsNavigation')
        catalog = controller.property('invalidReasons')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        assert control('invalidReasonsNavigation').property('text') == (
            setup['navigation_caption']
        )
        elections = catalog.property('state')['elections']
        election_index = next(index for index, row in enumerate(elections)
            if row['id'] == setup['election_id'])
        choose('invalidReasonElection', election_index)
        wait(lambda: not catalog.property('state')['busy'])
        reasons = catalog.property('state')['items']
        selected_index = next(index for index, row in enumerate(reasons)
            if row['id'] == setup['reason_id'])
        choose('invalidReasonPicker', selected_index)
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        frame()
        assert catalog.property('state')['selected']['source_english'] == (
            setup['source_english']
        )
        for language, caption in (
            ('tc', '無效選票原因'),
            ('sc', '无效选票原因'),
            ('en', 'Invalid ballot reasons'),
        ):
            controller.setLocale(language)
            frame()
            assert control('invalidReasonsTitle').property('text') == caption
        controller.setLocale(setup['locale'])
        frame()

        enter('invalidReasonLabelTc', '本地顯示繁體')
        enter('invalidReasonLabelSc', '本地显示简体')
        enter('invalidReasonLabelEn', 'Local display English')
        click('invalidReasonSave')
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        changed = catalog.property('state')['selected']
        assert changed['revision'] == 2
        assert changed['source_english'] == setup['source_english']
        assert changed['verified_source'] is True
        assert changed['translation_provenance'] == 'project_translation'
        assert setup['source_english'] in control('invalidReasonSourceEnglish').property('text')
        assert control('invalidReasonHistory').property('visible') is True
        choose('invalidReasonHistory', 1)
        wait(lambda: catalog.property('state')['selected']['revision'] == 1)
        assert catalog.property('state')['historical'] is True
        assert control('invalidReasonLabelEn').property('readOnly') is True
        assert control('invalidReasonSave').property('enabled') is False
        assert catalog.property('state')['selected']['label_en'] == (
            setup['original_label_en']
        )

        other_index = next(index for index, row in enumerate(
            catalog.property('state')['items']) if row['id'] == setup['other_id'])
        choose('invalidReasonPicker', other_index)
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert control('invalidReasonEnabled').property('enabled') is False
        assert control('invalidReasonExplanationRequired').property('enabled') is False
        assert control('invalidReasonEnabled').property('checked') is True
        assert control('invalidReasonExplanationRequired').property('checked') is True

        click('invalidReasonNew')
        enter('invalidReasonCode', setup['project_code'])
        enter('invalidReasonLabelTc', '項目自訂繁體')
        enter('invalidReasonLabelSc', '项目自定义简体')
        enter('invalidReasonLabelEn', 'Project-specific note')
        click('invalidReasonExplanationRequired')
        click('invalidReasonSave')
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        project = catalog.property('state')['selected']
        assert project['code'] == setup['project_code']
        assert project['stage'] == 'f1'
        assert project['verified_source'] is False
        assert project['source_english'] == ''
        assert project['source_letter'] is None
        assert project['reference_page'] is None
        assert project['reference_printed_page'] is None
        assert project['explanation_required'] is True
        assert project['translation_provenance'] == 'project_translation'
        """,
    )
    current = admin.get(path + f"/{original['id']}")
    assert current.status_code == 200, current.text
    record, history = current.json()["record"], current.json()["history"]
    assert record["revision"] == 2
    assert record["source_english"] == original["source_english"]
    assert record["label_en"] == "Local display English"
    assert history[1]["label_en"] == original["label_en"]
    project_catalog = admin.get(path)
    assert project_catalog.status_code == 200, project_catalog.text
    project = next(
        row for row in project_catalog.json()["items"] if row["code"] == "project-f1-display-note"
    )
    assert project["source_english"] == "" and project["verified_source"] is False


def test_discard_confirmation_preserves_dirty_input_and_peer_revision_warning(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": original["id"],
            "locale": "tc",
            "ca_file": str(TLS_DIRECTORY / "ca.pem"),
            "catalog_path": path,
            "initial_label": original["label_tc"],
        },
        """
        import httpx
        import ssl
        from PySide6.QtCore import QObject
        from uuid import uuid4

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
        enter('invalidReasonLabelTc', '本地未儲存內容')
        assert catalog.property('state')['dirty'] is True

        with httpx.Client(
            base_url=setup['server'],
            verify=ssl.create_default_context(cafile=setup['ca_file']),
        ) as peer:
            login = peer.post('/api/auth/login', json={
                'username': setup['username'], 'password': setup['password']})
            assert login.status_code == 200
            peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
            updated = peer.put(
                setup['catalog_path'] + '/' + str(setup['reason_id']),
                json={
                    'request_id': str(uuid4()),
                    'expected_revision': 1,
                    'label_tc': '同事更新的繁體文字',
                    'label_sc': '同事更新的简体文字',
                    'label_en': 'Peer updated English',
                    'enabled': True,
                    'explanation_required': False,
                },
            )
            assert updated.status_code == 200, updated.text

        click('invalidReasonsRefresh')
        wait(lambda: not catalog.property('state')['refreshing'])
        assert catalog.property('state')['dirty'] is True
        assert catalog.property('state')['newer_revision'] is True
        assert control('invalidReasonLabelTc').property('text') == '本地未儲存內容'
        assert control('invalidReasonSave').property('enabled') is False
        assert control('invalidReasonNewerWarning').property('visible') is True

        click('invalidReasonReload')
        dialogs = [obj for obj in window.findChildren(QObject)
            if obj.inherits('QQuickDialog') and obj.property('visible')]
        assert len(dialogs) == 1
        dialog = dialogs[0]
        wait(lambda: dialog.property('opened'))
        frame()
        click_confirmation(dialog, '繼續編輯')
        assert catalog.property('state')['dirty'] is True
        assert control('invalidReasonLabelTc').property('text') == '本地未儲存內容'

        click('invalidReasonReload')
        dialogs = [obj for obj in window.findChildren(QObject)
            if obj.inherits('QQuickDialog') and obj.property('visible')]
        assert len(dialogs) == 1
        click_confirmation(dialogs[0], '捨棄變更')
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        assert catalog.property('state')['dirty'] is False
        assert catalog.property('state')['selected']['revision'] == 2
        assert control('invalidReasonLabelTc').property('text') == '同事更新的繁體文字'
        """,
    )
    latest = admin.get(path + f"/{original['id']}").json()["record"]
    assert latest["revision"] == 2
    assert latest["label_tc"] == "同事更新的繁體文字"


def test_refresh_keeps_intentionally_selected_history_and_allows_return_to_head(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    revision_two = admin.put(
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
    assert revision_two.status_code == 200, revision_two.text
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": original["id"],
            "locale": "en",
        },
        """
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
        assert catalog.property('state')['selected']['revision'] == 2
        choose('invalidReasonHistory', 1)
        wait(lambda: catalog.property('state')['selected']['revision'] == 1)
        assert catalog.property('state')['historical'] is True
        assert catalog.property('state')['newer_revision'] is False

        catalog.refresh()
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        state = catalog.property('state')
        assert state['selected']['revision'] == 1
        assert state['historical'] is True
        assert state['newer_revision'] is False
        assert [row['revision'] for row in state['history']] == [2, 1]
        assert control('invalidReasonNewerWarning').property('visible') is False

        choose('invalidReasonHistory', 0)
        wait(lambda: catalog.property('state')['selected']['revision'] == 2)
        current = catalog.property('state')
        assert current['historical'] is False
        assert current['newer_revision'] is False
        assert control('invalidReasonLabelEn').property('readOnly') is False
        """,
    )


def test_historical_refresh_adds_peer_revision_without_making_intermediate_revision_current(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    revision_two = admin.put(
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
    assert revision_two.status_code == 200, revision_two.text
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "reason_id": original["id"],
            "locale": "en",
            "ca_file": str(TLS_DIRECTORY / "ca.pem"),
            "catalog_path": path,
        },
        """
        import httpx
        import ssl
        from uuid import uuid4

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
        assert [row['revision'] for row in catalog.property('state')['history']] == [2, 1]
        choose('invalidReasonHistory', 1)
        wait(lambda: catalog.property('state')['selected']['revision'] == 1)
        assert catalog.property('state')['historical'] is True

        with httpx.Client(
            base_url=setup['server'],
            verify=ssl.create_default_context(cafile=setup['ca_file']),
        ) as peer:
            login = peer.post('/api/auth/login', json={
                'username': setup['username'], 'password': setup['password']})
            assert login.status_code == 200
            peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
            revision_three = peer.put(
                setup['catalog_path'] + '/' + str(setup['reason_id']),
                json={
                    'request_id': str(uuid4()),
                    'expected_revision': 2,
                    'label_tc': '第三版本繁體顯示',
                    'label_sc': '第三版本简体显示',
                    'label_en': 'Third revision display',
                    'enabled': True,
                    'explanation_required': False,
                },
            )
            assert revision_three.status_code == 200, revision_three.text

        catalog.refresh()
        wait(lambda: not any(catalog.property('state')[key]
            for key in ('busy', 'refreshing')))
        refreshed = catalog.property('state')
        assert refreshed['selected']['revision'] == 1
        assert refreshed['historical'] is True
        assert refreshed['newer_revision'] is False
        assert [row['revision'] for row in refreshed['history']] == [3, 2, 1]

        choose('invalidReasonHistory', 1)
        wait(lambda: catalog.property('state')['selected']['revision'] == 2)
        intermediate = catalog.property('state')
        assert intermediate['historical'] is True
        assert intermediate['newer_revision'] is False
        assert control('invalidReasonLabelEn').property('readOnly') is True
        assert control('invalidReasonSave').property('enabled') is False

        choose('invalidReasonHistory', 0)
        wait(lambda: catalog.property('state')['selected']['revision'] == 3)
        current = catalog.property('state')
        assert current['historical'] is False
        assert current['newer_revision'] is False
        assert control('invalidReasonLabelEn').property('readOnly') is False
        enter('invalidReasonLabelEn', 'Editable current head')
        assert control('invalidReasonSave').property('enabled') is True
        """,
    )
