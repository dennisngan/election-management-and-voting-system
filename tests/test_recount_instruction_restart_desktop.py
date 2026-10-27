"""Qt/TLS lost-recount and fresh-controller context recovery contract."""

import json
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse, TransparentTlsProxy
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def lost_recount_response(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[LostSelectionResponse]:
    """Use the existing opaque proxy, tagging only a real committed recount201 reply."""
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare local TLS with election.manage tls-dev"
    backend_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    backend_listener.bind(("127.0.0.1", 0))
    backend_listener.listen()
    backend_port = backend_listener.getsockname()[1]
    client_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_listener.bind(("127.0.0.1", 0))
    client_listener.listen()
    endpoint = LostSelectionResponse(
        f"https://localhost:{client_listener.getsockname()[1]}", ControlledClock()
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def tag_only_committed_recount(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Method/path metadata only; the proxy forwards encrypted bytes opaquely.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        peer = request.client
        if (request.method == "POST" and request.url.path == endpoint.drop_path
                and response.status_code == 201 and peer is not None):
            with endpoint.lock:
                endpoint.drop_peer = (peer.host, peer.port)
                endpoint.drop_path = ""
            endpoint.response_tagged.set()
        return response

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=backend_port, loop="asyncio", ws="none",
        ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
        ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
        log_level="warning", access_log=False,
        timeout_keep_alive=5, timeout_graceful_shutdown=1,
    ))
    server_thread = threading.Thread(
        target=server.run, kwargs={"sockets": [backend_listener]}, daemon=True
    )
    proxy = TransparentTlsProxy(client_listener, backend_port, endpoint)
    server_thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        proxy.start()
        yield endpoint
    finally:
        proxy.stop()
        server.should_exit = True
        wait_for(qt_app, lambda: not server_thread.is_alive())
        server_thread.join(timeout=0)
        backend_listener.close()
        client_listener.close()
        assert not server_thread.is_alive(), "The owned recount HTTPS server did not stop"


def test_restarted_client_cannot_discard_context_before_checking_original_recount_outcome(
    admin: TestClient,
    database_url: str,
    lost_recount_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "recount-restart-journal"))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor, counter = setup["clients"]["supervisor"], setup["clients"]["receiveronly"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        target_id = setup["stations"]["S1"]["id"]
        actor_id = setup["accounts"]["supervisor"]["id"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        source_response = counter.get(source_path)
        assert source_response.status_code == 200, source_response.text
        old_history_ids = [row["revision_id"] for row in source_response.json()["history"]]
        setup["clock"].value += timedelta(minutes=10)
        endpoint = lost_recount_response
        endpoint.clock.value = setup["clock"].value
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        target_path = f"/api/workspace/stations/{target_id}"
        reason = "Keep the original recount identity until its lost reply is explicitly checked."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (first_client, first_editor):
            first_child = first_editor.property("recounts")
            assert isinstance(first_child, QObject)
            wait_for_editor_idle(qt_app, first_child)
            first_child.setField("event_at", "2026-11-16 00:05:42.123456")
            first_child.setField("reason", reason)
            endpoint.drop_path = recount_path
            first_child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, first_child)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            assert first_child.property("state")["uncertain_save"] is True
            state_response = supervisor.get(recount_path)
            assert state_response.status_code == 200, state_response.text
            assert len(state_response.json()["instructions"]) == 1
            instruction = state_response.json()["instructions"][0]
            request_id = instruction["request_id"]
            assert str(UUID(request_id)) == request_id
            assert first_child.property("state")["pending_request_id"] == request_id
            assert instruction["actor_id"] == actor_id and instruction["scope_id"] == scope_id
            assert instruction["source_round_id"] == prior["id"]
            new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
            new_response = counter.get(new_path)
            assert new_response.status_code == 200, new_response.text
            new_view = new_response.json()
            assert len(new_view["history"]) == 1 and new_view["record"]["revision"] == 1
            expected_wrapper = {"instruction": instruction, "round": new_view["record"]}
            first_recovery = first_client.property("recovery")
            first_recovery.open()
            wait_for_editor_idle(qt_app, first_recovery)
            original_commands = [row for row in first_recovery.property("state")["commands"]
                                 if row["request_id"] == request_id and row["path"] == recount_path]
            assert len(original_commands) == 1
            original = original_commands[0]
            assert original["status"] == "uncertain"
            assert original["confirmation_required"] is True
            assert original["actor_id"] == actor_id and original["station_id"] == station_id
            assert original["server_url"] == endpoint.url and original["workflow"] == "count"
            assert original["method"] == "POST"
            assert original["payload"] == {
                "request_id": request_id, "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": prior["selection"]["revision"],
                "source_round_id": prior["id"], "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": reason,
            }
            assert "password" not in json.dumps(original["payload"]).lower()
            assert READY_PASSWORD not in json.dumps(original)
            assert endpoint.request_count("POST", recount_path) == 1
        # f1_editor has actually shut down/deleted the first authenticated controller.

        outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (fresh_client, fresh_editor):
            fresh_child = fresh_editor.property("recounts")
            assert isinstance(fresh_child, QObject)
            wait_for_editor_idle(qt_app, fresh_child)
            recovery = fresh_client.property("recovery")
            # Loading a station must restore its durable guard before Recovery is opened.
            assert fresh_client.property("workspace").property("unresolvedRequest") is True
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            restored_commands = [row for row in recovery.property("state")["commands"]
                                 if row["request_id"] == request_id and row["path"] == recount_path]
            assert len(restored_commands) == 1
            restored = restored_commands[0]
            for field in ("request_id", "server_url", "actor_id", "station_id", "workflow",
                          "path", "method", "payload", "confirmation_required",
                          "receipt", "status"):
                assert restored[field] == original[field]
            assert restored["status"] == "uncertain"
            assert endpoint.request_count("POST", recount_path) == 1
            assert endpoint.request_count("GET", outcome_path) == 0
            displayed_round = fresh_editor.property("state")["selected"]
            workspace = fresh_client.property("workspace")
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert fresh_child.property("state")["scope_id"] == scope_id
            target_reads = endpoint.request_count("GET", target_path)

            # A durable unresolved instruction also protects the current tally selection.
            assert fresh_editor.selectRound(instruction["new_round_id"]) is False
            assert fresh_editor.property("state")["selected"]["id"] == displayed_round["id"]
            workspace.selectStation(target_id, True)
            wait_for_editor_idle(qt_app, workspace)
            # Expected first RED at1d318c4: durable unresolved command does not guard this switch.
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert workspace.property("state")["error"]
            assert endpoint.request_count("GET", target_path) == target_reads
            assert fresh_child.property("state")["scope_id"] == scope_id
            assert fresh_child.property("state")["actor_id"] == actor_id
            assert fresh_editor.property("state")["selected"]["id"] == displayed_round["id"]
            assert any(row["request_id"] == request_id and row["status"] == "uncertain"
                       for row in recovery.property("state")["commands"])

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, fresh_child)
            wait_for_editor_idle(qt_app, fresh_editor)
            checked = next(row for row in recovery.property("state")["commands"]
                           if row["request_id"] == request_id)
            assert checked["status"] == "committed" and checked["error"] == ""
            assert recovery.property("state")["error"] == ""
            outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            assert outcome["request_id"] == request_id and outcome["status"] == "committed"
            assert outcome["workflow"] == "count"
            assert outcome["record"] == expected_wrapper
            assert_public_business_fields(checked["receipt"]["record"], expected_wrapper)
            assert fresh_editor.property("state")["selected"]["id"] == displayed_round["id"]
            assert fresh_editor.property("state")["selected"]["revision"] == (
                displayed_round["revision"]
            )
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("POST", recount_path) == 1
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))

            workspace.selectStation(target_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == target_id
            assert endpoint.request_count("GET", target_path) == target_reads + 1

        final_state = supervisor.get(recount_path)
        assert final_state.status_code == 200, final_state.text
        assert final_state.json()["instructions"] == state_response.json()["instructions"]
        final_new = counter.get(new_path)
        assert final_new.status_code == 200, final_new.text
        assert final_new.json() == new_view
        preserved_response = counter.get(source_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == old_history_ids
        for field in ("candidate_votes", "invalid_papers", "scope_basis", "f2", "event_at",
                      "entered_at", "actor_id", "approved_at", "approved_by"):
            assert preserved["record"][field] == prior[field]
        assert endpoint.request_count("POST", recount_path) == 1
