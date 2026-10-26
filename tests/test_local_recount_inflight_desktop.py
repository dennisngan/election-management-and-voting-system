"""Retain the original recount identity while its real TLS response remains in flight."""

import asyncio
import json
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
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
    HttpsServer,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class RecountResponseGate(HttpsServer):
    hold_path: str = ""
    instruction_committed: threading.Event = field(default_factory=threading.Event)
    release_response: threading.Event = field(default_factory=threading.Event)
    response_released: threading.Event = field(default_factory=threading.Event)
    gate_timed_out: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def recount_response_gate(
    database_url: str, qt_app: QCoreApplication
) -> Iterator[RecountResponseGate]:
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare local TLS with election.manage tls-dev"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = RecountResponseGate(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def hold_only_committed_recount_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Observe method/path only, never credentials, headers or request bodies.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        if (
            request.method == "POST" and request.url.path == endpoint.hold_path
            and response.status_code == 201
        ):
            endpoint.hold_path = ""
            # The real route has committed before returning this untouched reply.
            endpoint.instruction_committed.set()
            released = await asyncio.to_thread(endpoint.release_response.wait, 5)
            if not released:
                endpoint.gate_timed_out.set()
            endpoint.response_released.set()
        return response

    server = uvicorn.Server(uvicorn.Config(
        application,
        host="127.0.0.1", port=port, loop="asyncio", ws="none", lifespan="on",
        ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
        ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
        log_level="warning", access_log=False,
        timeout_keep_alive=5, timeout_graceful_shutdown=1,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        endpoint.release_response.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive(), "The owned recount HTTPS fixture did not stop"


def test_confirmed_station_discard_cannot_reset_a_committed_recount_with_reply_in_flight(
    admin: TestClient,
    database_url: str,
    recount_response_gate: RecountResponseGate,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        station_id = setup["stations"]["N1"]["id"]
        target_id = setup["stations"]["S1"]["id"]
        scope_id = setup["scope"]["id"]
        supervisor_id = setup["accounts"]["supervisor"]["id"]
        assert setup["stations"]["N1"]["constituency_id"] != (
            setup["stations"]["S1"]["constituency_id"]
        )
        setup["clock"].value += timedelta(minutes=10)
        endpoint = recount_response_gate
        endpoint.clock.value = setup["clock"].value
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        target_path = f"/api/workspace/stations/{target_id}"
        event_time = "2026-11-16 00:05:42.123456"
        reason = "Retain this source while its recorded recount instruction reply is in flight."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            recounts = editor.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            assert recounts.property("state")["can_instruct"] is True
            assert editor.property("state")["selected"]["id"] == prior["id"]
            recounts.setField("event_at", event_time)
            recounts.setField("reason", reason)
            assert recounts.property("state")["dirty"] is True
            assert editor.property("state")["dirty"] is False
            endpoint.hold_path = recount_path
            recounts.instruct(READY_PASSWORD)
            try:
                wait_for(qt_app, endpoint.instruction_committed.is_set)
                # Public readback proves the actual commit, independent of ACK.
                committed_response = setup["clients"]["supervisor"].get(recount_path)
                assert committed_response.status_code == 200, committed_response.text
                committed = committed_response.json()
                assert len(committed["instructions"]) == 1
                instruction = committed["instructions"][0]
                pending = recounts.property("state")
                request_id = pending["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert request_id == instruction["request_id"]
                assert instruction["actor_id"] == supervisor_id
                assert instruction["scope_id"] == scope_id
                assert instruction["source_round_id"] == prior["id"]
                assert instruction["source_round_revision"] == prior["revision"]
                assert instruction["reason"] == reason
                assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
                assert pending["busy"] is True and pending["uncertain_save"] is False
                assert pending["actor_id"] == supervisor_id
                assert pending["role"] == "supervisor"
                assert pending["scope_id"] == scope_id
                assert pending["forms"] == {"event_at": event_time, "reason": reason}
                assert endpoint.response_released.is_set() is False
                assert endpoint.gate_timed_out.is_set() is False
                assert endpoint.request_count("POST", recount_path) == 1
                workspace = client.property("workspace")
                target_reads = endpoint.request_count("GET", target_path)

                # Actual public confirmed-discard overload; its return is None.
                workspace.selectStation(target_id, True)
                wait_for_editor_idle(qt_app, workspace)
                guarded = workspace.property("state")
                # Expected first RED at687919fa: station becomes S and child resets.
                assert guarded["selected"]["station"]["id"] == station_id
                assert guarded["error"]
                assert endpoint.request_count("GET", target_path) == target_reads
                retained = recounts.property("state")
                assert retained["busy"] is True and retained["uncertain_save"] is False
                assert retained["scope_id"] == scope_id
                assert retained["scope"] == pending["scope"]
                assert retained["selection"] == pending["selection"]
                assert retained["actor_id"] == supervisor_id
                assert retained["context"]["account"]["id"] == supervisor_id
                assert retained["role"] == "supervisor"
                assert retained["pending_request_id"] == request_id
                assert retained["forms"] == pending["forms"]
                assert editor.property("state")["selected"]["id"] == prior["id"]
                assert endpoint.response_released.is_set() is False
                assert endpoint.gate_timed_out.is_set() is False
            finally:
                # Release the original real response even when the RED assertion fails.
                endpoint.release_response.set()

            wait_for(qt_app, endpoint.response_released.is_set)
            wait_for_editor_idle(qt_app, recounts)
            wait_for_editor_idle(qt_app, editor)
            settled = recounts.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["error"] == "" and settled["pending_request_id"] == ""
            assert settled["latest_instruction"]["request_id"] == request_id
            assert settled["latest_instruction"]["id"] == instruction["id"]
            assert READY_PASSWORD not in json.dumps(settled)
            assert endpoint.gate_timed_out.is_set() is False
            assert editor.property("state")["selected"]["id"] == prior["id"]
            assert editor.property("state")["selected"]["revision"] == prior["revision"]
            assert editor.property("state")["dirty"] is False
            assert any(row["id"] == instruction["new_round_id"]
                       for row in editor.property("state")["rounds"])
            final_response = setup["clients"]["supervisor"].get(recount_path)
            assert final_response.status_code == 200, final_response.text
            assert final_response.json()["instructions"] == committed["instructions"]
            assert endpoint.request_count("POST", recount_path) == 1

            workspace.selectStation(target_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == target_id
            assert endpoint.request_count("GET", target_path) == target_reads + 1
