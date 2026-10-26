"""The recovery Material page loads against an authenticated empty journal."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import tally_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_recovery_material_page_imports_and_shows_empty_journal(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        state_directory = tmp_path / "client-journal"
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(state_directory))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
            },
            """
            from PySide6.QtQml import QQmlComponent
            from pathlib import Path
            from election.desktop.recovery_translations import RECOVERY_TRANSLATIONS

            recovery = controller.property('recovery')
            assert recovery is not None
            words = dict(controller.texts)
            words.update(RECOVERY_TRANSLATIONS['en'])
            component = QQmlComponent(engine)
            component.loadUrl(QUrl.fromLocalFile(
                str(Path('src/election/desktop/qml/RecoveryPage.qml').resolve())
            ))
            wait(lambda: component.status() != QQmlComponent.Status.Loading)
            assert component.status() == QQmlComponent.Status.Ready, component.errorString()
            page = component.createWithInitialProperties({
                'recovery': recovery,
                'words': words,
                'locale': 'en',
            })
            assert page is not None, component.errorString()
            page.setParentItem(window.contentItem())
            page.setWidth(window.width)
            page.setHeight(window.height)
            recovery.open()
            wait(lambda: not recovery.property('state')['busy'])
            assert recovery.property('state')['commands'] == []
            assert control('recoveryEmpty').property('visible') is True
            state_json = json.dumps(recovery.property('state'), ensure_ascii=False)
            assert setup['password'] not in state_json
            """,
        )
        assert not state_directory.exists()
