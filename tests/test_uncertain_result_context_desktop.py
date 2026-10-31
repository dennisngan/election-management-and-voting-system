"""Unknown tie outcomes survive confirmed station changes until their receipt settles."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse
from tests.test_counting_workflow_retry_desktop import (
    lost_selection_response as lost_selection_response,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_result_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture(autouse=True)
def isolate_client_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "tie-context-journal"))


def test_unknown_tie_outcome_blocks_confirmed_constituency_change_until_original_receipt(
    admin: TestClient,
    database_url: str,
    lost_selection_response: LostSelectionResponse,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        # Public APIs prepare a complete, approved and selected ten-paper tie.
        save_result_round(setup, [5, 5], approve_and_select=True)
        endpoint = lost_selection_response
        endpoint.clock.value = setup["clock"].value
        source_id = setup["stations"]["N1"]["id"]
        target_id = setup["stations"]["S1"]["id"]
        constituency_id = setup["constituency_id"]
        target_constituency_id = setup["stations"]["S1"]["constituency_id"]
        assert constituency_id != target_constituency_id
        result_path = f"/api/workspace/constituencies/{constituency_id}/results"
        tie_path = result_path + "/tie-resolutions"
        target_path = f"/api/workspace/stations/{target_id}"
        reason = "Retain this reviewed decision after its committed TLS response is lost."
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(
                endpoint.url, setup["accounts"]["supervisor"]["username"], READY_PASSWORD
            )
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(source_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == source_id
            results = client.property("constituencyResults")
            assert results is not None
            results.open()
            wait_for_editor_idle(qt_app, results)
            initial = results.property("state")["result"]
            assert initial["complete"] is True
            assert len(initial["tie_candidate_ids"]) == 2
            assert initial["resolution_history"] == []
            candidate_id = initial["tie_candidate_ids"][0]
            results.setResolutionCandidate(candidate_id)
            results.setResolutionReason(reason)

            # The existing opaque TLS proxy drops only this successful response,
            # after the unchanged business route has committed its real decision.
            endpoint.drop_path = tie_path
            results.resolveTie(READY_PASSWORD)
            wait_for_editor_idle(qt_app, results)
            assert endpoint.response_tagged.is_set()
            assert endpoint.response_dropped.is_set()
            assert endpoint.request_count("POST", tie_path) == 1
            uncertain = results.property("state")
            assert uncertain["uncertain_save"] is True
            assert uncertain["dirty"] is True
            assert uncertain["selected_candidate_id"] == candidate_id
            assert uncertain["reason"] == reason
            committed_response = setup["clients"]["supervisor"].get(result_path)
            assert committed_response.status_code == 200, committed_response.text
            committed = committed_response.json()
            assert committed["resolved_candidate_id"] == candidate_id
            assert committed["tie_resolution"]["revision"] == 1
            assert len(committed["resolution_history"]) == 1

            # A background read observes a newer decision without settling the
            # unknown original command or replacing its reviewed local fields.
            results.refresh()
            wait_for_editor_idle(qt_app, results)
            assert results.property("state")["uncertain_save"] is True
            assert results.property("state")["selected_candidate_id"] == candidate_id
            assert results.property("state")["reason"] == reason
            assert workspace.property("selectionGuarded") is True
            target_reads = endpoint.request_count("GET", target_path)

            # This is the actual confirmed-discard Qt overload (returns None).
            # Expected RED at e6bbe40: selection changes to S and resets results.
            workspace.selectStation(target_id, True)
            wait_for_editor_idle(qt_app, workspace)
            blocked = workspace.property("state")
            assert blocked["selected"]["station"]["id"] == source_id
            assert blocked["selected"]["constituency"]["id"] == constituency_id
            assert blocked["error"] == "workspace_uncertain_request"
            assert endpoint.request_count("GET", target_path) == target_reads
            assert workspace.property("unresolvedRequest") is True
            retained = results.property("state")
            assert retained["constituency_id"] == constituency_id
            assert retained["uncertain_save"] is True
            assert retained["dirty"] is True
            assert retained["selected_candidate_id"] == candidate_id
            assert retained["reason"] == reason
            assert endpoint.request_count("POST", tie_path) == 1

            # There is no public checkOutcome on this controller. Explicitly
            # obtaining its cached original receipt uses the existing retry slot
            # and a fresh transient Supervisor password; it must create no r2.
            results.resolveTie(READY_PASSWORD)
            wait_for_editor_idle(qt_app, results)
            recovered = results.property("state")
            assert recovered["uncertain_save"] is False
            assert recovered["dirty"] is False
            assert recovered["result"]["resolved_candidate_id"] == candidate_id
            assert len(recovered["result"]["resolution_history"]) == 1
            # Public Qt copies add quantity-display fields within nested basis
            # records. Compare immutable decision fields without DTO equality.
            for key in (
                "id", "revision", "candidate_id", "actor_id", "accepted_at",
                "reason", "basis_digest",
            ):
                expected = committed["tie_resolution"][key]
                assert recovered["result"]["tie_resolution"][key] == expected
                assert recovered["result"]["resolution_history"][0][key] == expected
            assert READY_PASSWORD not in json.dumps(recovered, ensure_ascii=False)
            assert endpoint.request_count("POST", tie_path) == 2
            final_response = setup["clients"]["supervisor"].get(result_path)
            assert final_response.status_code == 200, final_response.text
            final = final_response.json()
            assert final["tie_resolution"] == committed["tie_resolution"]
            assert final["resolution_history"] == committed["resolution_history"]
            assert workspace.property("unresolvedRequest") is False

            workspace.selectStation(target_id)
            wait_for_editor_idle(qt_app, workspace)
            selected = workspace.property("state")["selected"]
            assert selected["station"]["id"] == target_id
            assert selected["constituency"]["id"] == target_constituency_id
            assert endpoint.request_count("GET", target_path) == target_reads + 1
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
