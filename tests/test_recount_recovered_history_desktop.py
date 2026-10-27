"""Qt/TLS contract: old receipt settlement must not become current history."""

import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse, TransparentTlsProxy
from tests.test_local_recount_exports_history_api import complete_required_round
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class HistoricalRecountLossServer(LostSelectionResponse):
    drop_method: str = "POST"
    drop_status: int = 201
    arm_after_outcome_path: str = ""
    current_read_path: str = ""
    block_current_reads: bool = False
    current_reads_armed: threading.Event = field(default_factory=threading.Event)
    current_read_tagged: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def historical_recount_loss_server(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[HistoricalRecountLossServer]:
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
    endpoint = HistoricalRecountLossServer(
        f"https://localhost:{client_listener.getsockname()[1]}", ControlledClock()
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def tag_actual_response_loss(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Observe only public method/path/status; never inspect or replace response bodies.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        peer = request.client
        with endpoint.lock:
            if (request.method == "GET" and request.url.path == endpoint.arm_after_outcome_path
                    and response.status_code == 200):
                endpoint.arm_after_outcome_path = ""
                endpoint.block_current_reads = True
                endpoint.current_reads_armed.set()
            original_reply = (
                request.method == endpoint.drop_method and request.url.path == endpoint.drop_path
                and response.status_code == endpoint.drop_status
            )
            current_reply = (
                endpoint.block_current_reads and request.method == "GET"
                and request.url.path == endpoint.current_read_path and response.status_code == 200
            )
            if peer is not None and (original_reply or current_reply):
                endpoint.drop_peer = (peer.host, peer.port)
                if original_reply:
                    endpoint.drop_path = ""
                if current_reply:
                    endpoint.current_read_tagged.set()
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
    proxy = None
    server_thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        proxy = TransparentTlsProxy(client_listener, backend_port, endpoint)
        proxy.start()
        yield endpoint
    finally:
        endpoint.block_current_reads = False
        if proxy is not None:
            proxy.stop()
        server.should_exit = True
        wait_for(qt_app, lambda: not server_thread.is_alive())
        server_thread.join(timeout=0)
        backend_listener.close()
        client_listener.close()


def test_recovered_original_receipt_does_not_replace_a_later_current_instruction_on_read_loss(
    admin: TestClient,
    database_url: str,
    historical_recount_loss_server: HistoricalRecountLossServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "historical-recount-recovery"))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor = setup["clients"]["supervisor"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        setup["clock"].value += timedelta(minutes=10)
        endpoint = historical_recount_loss_server
        endpoint.clock.value = setup["clock"].value
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            child = editor.property("recounts")
            assert isinstance(child, QObject)
            wait_for_editor_idle(qt_app, child)
            child.setField("event_at", "2026-11-16 00:05:42.123456")
            child.setField("reason", "FIRST: preserve the original unknown instruction receipt.")
            endpoint.drop_path = recount_path
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            assert child.property("state")["uncertain_save"] is True
            first_state_response = supervisor.get(recount_path)
            assert first_state_response.status_code == 200, first_state_response.text
            assert len(first_state_response.json()["instructions"]) == 1
            first = first_state_response.json()["instructions"][0]
            request_id = first["request_id"]
            assert child.property("state")["pending_request_id"] == request_id
            outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            original_outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert original_outcome_response.status_code == 200, original_outcome_response.text
            original_outcome = original_outcome_response.json()
            original_wrapper = original_outcome["record"]
            assert original_wrapper["instruction"] == first
            assert original_wrapper["instruction"]["status"] == "pending"
            assert original_wrapper["round"]["revision"] == 1
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            original_command = next(row for row in recovery.property("state")["commands"]
                                    if row["request_id"] == request_id)
            assert original_command["status"] == "uncertain"

            # Other real public clients complete/select round2, then create later instruction2.
            completed = complete_required_round(
                setup, original_wrapper["round"], prior["selection"]["revision"]
            )
            setup["clock"].value += timedelta(minutes=10)
            endpoint.clock.value = setup["clock"].value
            second_response = supervisor.post(recount_path, json={
                "request_id": str(uuid4()), "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": completed["selection"]["revision"],
                "source_round_id": completed["id"], "source_round_revision": completed["revision"],
                "event_at": "2026-11-16T00:15:42.654321+08:00",
                "reason": "LATER: this current requirement must remain distinct from receipt1.",
                "password": READY_PASSWORD,
            })
            assert second_response.status_code == 201, second_response.text
            second = second_response.json()["instruction"]
            assert second["id"] != first["id"] and second["new_round_number"] == 3
            current_response = supervisor.get(recount_path)
            assert current_response.status_code == 200, current_response.text
            current = current_response.json()
            assert current["latest_instruction"]["id"] == second["id"]
            first_now = next(row for row in current["instructions"] if row["id"] == first["id"])
            assert first_now["status"] == "completed" and first_now["current_satisfied"] is None
            assert current["pending"] is True
            child.refresh()
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, editor)
            assert child.property("state")["uncertain_save"] is True
            assert child.property("state")["newer_basis"] is True
            displayed = editor.property("state")["selected"]

            endpoint.response_tagged.clear()
            endpoint.response_dropped.clear()
            endpoint.current_read_path = recount_path
            endpoint.arm_after_outcome_path = outcome_path
            try:
                recovery.checkOutcome(request_id)
                wait_for_editor_idle(qt_app, recovery)
                assert endpoint.current_reads_armed.is_set()
                # If a valid fix schedules no automatic read, explicitly exercise its current read.
                child.refresh()
                wait_for(qt_app, lambda: endpoint.current_read_tagged.is_set()
                         and endpoint.response_dropped.is_set())
                wait_for_editor_idle(qt_app, child)
                wait_for_editor_idle(qt_app, editor)
                checked = next(row for row in recovery.property("state")["commands"]
                               if row["request_id"] == request_id)
                assert checked["status"] == "committed"
                assert_public_business_fields(checked["receipt"]["record"], original_wrapper)
                stale = child.property("state")
                assert stale["uncertain_save"] is False and stale["dirty"] is False
                assert stale["pending_request_id"] == "" and stale["can_instruct"] is False
                latest = stale["latest_instruction"]
                # Intended RED at215a05f: cached pending instruction1 is relabeled latest/current.
                assert latest is None or latest["id"] != first["id"], latest
                assert stale["newer_basis"] is True
                if latest is not None:
                    # A previously authoritative current projection is also safe to retain.
                    assert latest["id"] == second["id"] and latest["status"] == "pending"
                    assert latest["current_satisfied"] is False and stale["pending"] is True
                assert editor.property("state")["selected"]["id"] == displayed["id"]
                assert editor.property("state")["selected_scope_id"] == scope_id
            finally:
                # Release real read delivery for cleanup and the explicit authoritative reload.
                with endpoint.lock:
                    endpoint.block_current_reads = False
                    endpoint.arm_after_outcome_path = ""
                    endpoint.drop_peer = None

            child.reload()
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, editor)
            loaded = child.property("state")
            assert loaded["latest_instruction"]["id"] == second["id"]
            assert loaded["latest_instruction"]["status"] == "pending"
            assert loaded["pending"] is True and loaded["can_instruct"] is False
            assert loaded["instructions"] == current["instructions"]
            assert loaded["error"] == "" and loaded["newer_basis"] is False
            assert editor.property("state")["selected"]["id"] == displayed["id"]
            assert editor.property("state")["selected_scope_id"] == scope_id
            immutable_response = supervisor.get(outcome_path + "?workflow=count")
            assert immutable_response.status_code == 200, immutable_response.text
            assert immutable_response.json() == original_outcome
            assert endpoint.request_count("POST", recount_path) == 1
