"""An opened results page keeps its recount child bound to the selected constituency."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent, QObject

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _assert_automatic_recount_read(
    qt_app: QCoreApplication, child: QObject, endpoint: HttpsServer,
    path: str, expected: dict, previous_reads: int, station_id: int, actor_id: int,
) -> None:
    def loaded_current_context() -> bool:
        state = child.property("state")
        return bool(
            endpoint.request_count("GET", path) > previous_reads
            and not state["busy"] and not state["refreshing"]
            and state["basis_digest"] == expected["basis_digest"]
            and state["scope_sources"] == expected["scope_sources"]
            and state["instructions"] == expected["instructions"]
            and state["constituency_id"] == expected["context"]["constituency"]["id"]
        )

    # Reuse the existing five-second public-state wait. A valid background refresh
    # may add reads, so only require a positive change rather than an exact count.
    wait_for(qt_app, loaded_current_context)
    state = child.property("state")
    assert state["station_id"] == station_id and state["account_id"] == actor_id
    assert state["role"] == "supervisor"
    assert state["context"]["election"]["id"] == expected["context"]["election"]["id"]
    assert state["context"]["constituency"]["id"] == expected["context"]["constituency"]["id"]
    assert state["can_instruct"] is expected["can_instruct"]
    assert state["forms"] == {"event_at": "", "reason": ""}
    assert state["dirty"] is False and state["uncertain_save"] is False
    assert state["pending_request_id"] == "" and state["error"] == ""


@pytest.mark.parametrize("opening_context", ["before_selection", "switch_constituency"])
def test_open_results_automatically_loads_recounts_after_workspace_context_changes(
    opening_context: str,
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-recount-context-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        account = setup["accounts"]["supervisor"]
        north_station_id, south_station_id = (
            setup["stations"]["N1"]["id"], setup["stations"]["S1"]["id"],
        )
        north_id, south_id = (
            setup["constituency_id"], setup["stations"]["S1"]["constituency_id"],
        )
        assert north_id != south_id
        north_path = f"/api/workspace/constituencies/{north_id}/recounts"
        south_path = f"/api/workspace/constituencies/{south_id}/recounts"
        north_response, south_response = supervisor.get(north_path), supervisor.get(south_path)
        assert north_response.status_code == south_response.status_code == 200
        north, south = north_response.json(), south_response.json()
        assert north["can_instruct"] is True and len(north["scope_sources"]) == 2
        assert north["instructions"] == []
        assert south["can_instruct"] is False and south["scope_sources"] == []
        assert south["instructions"] == []
        assert north["basis_digest"] != south["basis_digest"]
        https_server.clock.value = setup["clock"].value
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"] == {}
            results = client.property("constituencyResults")
            child = results.property("recounts")
            assert isinstance(child, QObject)

            if opening_context == "before_selection":
                results.open()
                wait_for_editor_idle(qt_app, results)
                assert child.property("state")["constituency_id"] == 0
                before = https_server.request_count("GET", north_path)
                workspace.selectStation(north_station_id)
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == north_station_id
                _assert_automatic_recount_read(
                    qt_app, child, https_server, north_path, north, before,
                    north_station_id, account["id"],
                )
            else:
                workspace.selectStation(north_station_id)
                wait_for_editor_idle(qt_app, workspace)
                before = https_server.request_count("GET", north_path)
                results.open()
                _assert_automatic_recount_read(
                    qt_app, child, https_server, north_path, north, before,
                    north_station_id, account["id"],
                )
                wait_for_editor_idle(qt_app, results)
                before = https_server.request_count("GET", south_path)
                # Keep the page opened: selecting a station is the sole context
                # action. Do not reopen/reload either results or its child.
                workspace.selectStation(south_station_id)
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == south_station_id
                _assert_automatic_recount_read(
                    qt_app, child, https_server, south_path, south, before,
                    south_station_id, account["id"],
                )
                wait_for_editor_idle(qt_app, results)
                before = https_server.request_count("GET", north_path)
                workspace.selectStation(north_station_id)
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == north_station_id
                _assert_automatic_recount_read(
                    qt_app, child, https_server, north_path, north, before,
                    north_station_id, account["id"],
                )
            wait_for_editor_idle(qt_app, results)
            assert results.property("state")["dirty"] is False
            assert results.property("state")["uncertain_save"] is False
            assert client.property("recovery").property("state")["commands"] == []
            assert list(journal_directory.glob("*.json")) == []
            assert https_server.request_count("POST", north_path) == 0
            assert https_server.request_count("POST", south_path) == 0
            preserved_north = supervisor.get(north_path)
            preserved_south = supervisor.get(south_path)
            assert preserved_north.status_code == preserved_south.status_code == 200
            assert preserved_north.json() == north and preserved_south.json() == south
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
