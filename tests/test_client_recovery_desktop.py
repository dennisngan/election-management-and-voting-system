"""Client-journal recovery after a committed count request loses its TLS reply."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, wait_for, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import (
    database_url as database_url,
)
from tests.test_counting_rounds_desktop import (
    f1_editor,
)
from tests.test_counting_rounds_desktop import (
    private_active_pointer as private_active_pointer,
)
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_workflow_retry_desktop import (
    LostSelectionResponse,
)
from tests.test_counting_workflow_retry_desktop import (
    lost_selection_response as lost_selection_response,
)


def test_committed_count_receipt_is_recovered_after_desktop_restart(
    admin: TestClient,
    database_url: str,
    lost_selection_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_directory = tmp_path / "client-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(state_directory))
    with tally_setup(admin, database_url) as setup:
        endpoint = lost_selection_response
        endpoint.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        round_target = path + f"/{created.json()['id']}"
        f2 = counter.put(round_target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        station_id = setup["stations"]["N1"]["id"]
        endpoint.drop_path = round_target + "/submit"

        with f1_editor(
            endpoint,
            qt_app,
            setup["accounts"]["receiveronly"],
            station_id,
            setup["scope"]["id"],
        ) as (_, editor):
            before = editor.property("state")
            assert before["selected"]["status"] == "draft"
            assert before["selected"]["count_inputs_complete"] is True
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            assert endpoint.response_tagged.is_set()
            assert endpoint.response_dropped.is_set()
            assert editor.property("state")["uncertain_save"] is True
            assert endpoint.request_count("POST", round_target + "/submit") == 1

        recovered_client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            recovered_client.signIn(
                endpoint.url, setup["accounts"]["receiveronly"]["username"], READY_PASSWORD
            )
            wait_for(qt_app, lambda: recovered_client.property("state")["phase"] == "workspace")
            workspace = recovered_client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == station_id

            recovery = recovered_client.property("recovery")
            assert recovery is not None, "Fresh desktop session has no recovery controller"
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            state = recovery.property("state")
            assert state["station_id"] == station_id
            assert len(state["commands"]) == 1
            command = state["commands"][0]
            request_id = command["request_id"]
            assert command["status"] in ("pending", "uncertain")
            assert READY_PASSWORD not in json.dumps(state, ensure_ascii=False)
            assert "password" not in json.dumps(command, ensure_ascii=False).lower()
            assert "authorization" not in json.dumps(command, ensure_ascii=False).lower()
            assert endpoint.request_count("POST", round_target + "/submit") == 1

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            committed = recovery.property("state")["commands"][0]
            assert committed["status"] == "committed"
            public_outcome = counter.get(
                f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}?workflow=count"
            )
            assert public_outcome.status_code == 200, public_outcome.text
            assert public_outcome.json()["status"] == "committed"
            assert committed["receipt"]["record"] == public_outcome.json()["record"]
            assert endpoint.request_count("POST", round_target + "/submit") == 1

            count_history = counter.get(round_target)
            assert count_history.status_code == 200, count_history.text
            assert [row["revision"] for row in count_history.json()["history"]] == [3, 2, 1]

            assert state_directory.stat().st_mode & 0o777 == 0o700
            journal_files = list(state_directory.iterdir())
            assert journal_files
            for journal_file in journal_files:
                assert journal_file.stat().st_mode & 0o777 == 0o600
                content = journal_file.read_text(encoding="utf-8")
                assert READY_PASSWORD not in content
                assert "password" not in content.lower()
                assert "authorization" not in content.lower()
        finally:
            recovered_client.shutdown()
            recovered_client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
