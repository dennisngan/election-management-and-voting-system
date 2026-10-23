"""Administrator category controls run the actual Material window over HTTPS."""

from collections.abc import Iterator

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
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_admin_creates_category_through_translated_material_controls(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    locale: str,
) -> None:
    election = create_election(admin)
    ready_setup(desktop, https_server, account, qt_app)
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": PERSONAL_PASSWORD,
            "station_id": 0,
            "election_id": election["id"],
            "locale": locale,
        },
        """
        click('complaintCategoriesNavigation')
        catalog = controller.property('complaintCategories')
        wait(lambda: not catalog.property('state')['refreshing'])
        frame()
        elections = catalog.property('state')['elections']
        index = next(index for index, row in enumerate(elections)
            if row['id'] == setup['election_id'])
        choose('complaintCategoryElection', index)
        wait(lambda: not catalog.property('state')['busy'])
        assert catalog.property('state')['election_id'] == setup['election_id']
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
        assert catalog.property('state')['error'] == ''
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
