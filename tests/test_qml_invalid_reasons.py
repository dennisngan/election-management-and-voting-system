"""Invalid-ballot reason administration through the real Material workspace."""

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
