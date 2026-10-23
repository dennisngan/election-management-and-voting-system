"""Administrator category controls run the actual Material window over HTTPS."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.complaint_support import category_edit
from tests.configuration_desktop_support import ready_setup
from tests.configuration_support import create_election
from tests.desktop_support import PERSONAL_PASSWORD, HttpsServer
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
    ("locale", "election_caption", "disabled_label"),
    [
        ("tc", "所選選舉", "已停用"),
        ("sc", "所选选举", "已停用"),
        ("en", "Selected election", "Disabled"),
    ],
)
def test_admin_creates_category_through_translated_material_controls(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    locale: str,
    election_caption: str,
    disabled_label: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    categories = admin.get(path)
    assert categories.status_code == 200
    disabled_category = categories.json()["items"][0]
    disabled = admin.put(
        f"{path}/{disabled_category['id']}",
        json=category_edit(disabled_category, enabled=False),
    )
    assert disabled.status_code == 200
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "locale": locale,
            "election_caption": election_caption,
            "disabled_option": (
                disabled_category["code"]
                + " · "
                + disabled_category["label_" + locale]
                + " · "
                + disabled_label
            ),
        },
        """
        click('complaintCategoriesNavigation')
        catalog = controller.property('complaintCategories')
        def category_failure():
            state = catalog.property('state')
            selected = state['selected']
            return {
                **{
                    key: state[key] for key in (
                        'error', 'notice', 'election_id', 'dirty', 'busy', 'refreshing'
                    )
                },
                'selected': {
                    key: selected.get(key) for key in ('id', 'revision', 'is_other', 'enabled')
                },
                'form': {
                    key: state['form'].get(key) for key in (
                        'code', 'label_tc', 'label_sc', 'label_en',
                        'description_required', 'enabled'
                    )
                },
            }
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        elections = catalog.property('state')['elections']
        index = next(index for index, row in enumerate(elections)
            if row['id'] == setup['election_id'])
        choose('complaintCategoryElection', index)
        wait(lambda: not catalog.property('state')['busy'])
        assert catalog.property('state')['election_id'] == setup['election_id']
        frame()
        election_picker = control('complaintCategoryElection')
        captions = [item.property('text') for item in election_picker.parentItem().childItems()
            if item.property('visible')]
        assert setup['election_caption'] in captions, captions
        from PySide6.QtGui import QAccessible
        accessible = QAccessible.queryAccessibleInterface(election_picker)
        assert accessible is not None
        assert accessible.text(QAccessible.Text.Name) == setup['election_caption']
        picker = focus('complaintCategoryPicker')
        QTest.keyClick(window, Qt.Key.Key_Space)
        wait(lambda: QQmlProperty(picker, 'popup.visible').read())
        frame()
        popup = QQmlProperty(picker, 'popup.contentItem').read()
        pending, option_texts = list(popup.childItems()), []
        while pending:
            item = pending.pop()
            option_texts.append(item.property('text'))
            pending.extend(item.childItems())
        assert setup['disabled_option'] in option_texts, option_texts
        QTest.keyClick(window, Qt.Key.Key_Escape)
        wait(lambda: not QQmlProperty(picker, 'popup.visible').read())
        frame()
        click('complaintCategoryNew')
        assert catalog.property('state')['editing'] is True, catalog.property('state')['error']
        frame()
        enter('complaintCategoryCode', 'QML-0001')
        enter('complaintCategoryTc', '界面分類繁體')
        enter('complaintCategorySc', '界面分类简体')
        enter('complaintCategoryEn', 'Material category')
        click('complaintCategoryDescriptionRequired')
        click('complaintCategorySave')
        wait(lambda: not catalog.property('state')['busy'])
        assert catalog.property('state')['error'] == '', category_failure()
        assert catalog.property('state')['selected']['revision'] == 1
        assert catalog.property('state')['selected']['description_required'] is True
        assert catalog.property('state')['selected']['verified_source'] is False
        assert control('complaintCategoryCode').property('readOnly') is True
        """,
    )
    response = admin.get(f"/api/elections/{election['id']}/complaint-categories")
    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["code"] == "QML-0001")
    assert (row["label_tc"], row["label_sc"], row["label_en"]) == (
        "界面分類繁體",
        "界面分类简体",
        "Material category",
    )
