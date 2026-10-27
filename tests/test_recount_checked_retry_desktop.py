"""Real pre-dispatch disconnect and explicit original recount retry contract."""

import json
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from election.server.app import create_app
from tests.box_support import INITIAL_PASSWORD, READY_PASSWORD
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


@dataclass
class ReconnectableRecountServer(LostSelectionResponse):
    backend_port: int = 0
    client_port: int = 0
    proxy: TransparentTlsProxy | None = None

    def disconnect_proxy(self) -> None:
        assert self.proxy is not None
        self.proxy.stop()  # Closes the listener and existing opaque TLS connections.
        self.proxy = None

    def reconnect_proxy(self) -> None:
        assert self.proxy is None
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.client_port))
            listener.listen()
        except BaseException:
            listener.close()
            raise
        self.proxy = TransparentTlsProxy(listener, self.backend_port, self)
        self.proxy.start()


@pytest.fixture
def reconnectable_recount_server(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[ReconnectableRecountServer]:
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
    client_port = client_listener.getsockname()[1]
    endpoint = ReconnectableRecountServer(
        f"https://localhost:{client_port}", ControlledClock(),
        backend_port=backend_port, client_port=client_port,
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def observe_real_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # The only fault is a disconnected listener; never inspect bodies or fabricate replies.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        return await call_next(request)

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
    server_thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        endpoint.proxy = TransparentTlsProxy(client_listener, backend_port, endpoint)
        endpoint.proxy.start()
        yield endpoint
    finally:
        if endpoint.proxy is not None:
            endpoint.proxy.stop()
        server.should_exit = True
        wait_for(qt_app, lambda: not server_thread.is_alive())
        server_thread.join(timeout=0)
        backend_listener.close()
        client_listener.close()
        assert not server_thread.is_alive(), "The owned retry HTTPS server did not stop"


def test_checked_not_found_retries_original_recount_with_fresh_password_and_settles_child(
    admin: TestClient,
    database_url: str,
    reconnectable_recount_server: ReconnectableRecountServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "checked-recount-retry"))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor, counter = setup["clients"]["supervisor"], setup["clients"]["receiveronly"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        actor_id = setup["accounts"]["supervisor"]["id"]
        assert actor_id != setup["accounts"]["receiveronly"]["id"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        before_source = counter.get(source_path)
        assert before_source.status_code == 200, before_source.text
        old_history_ids = [row["revision_id"] for row in before_source.json()["history"]]
        setup["clock"].value += timedelta(minutes=10)
        endpoint = reconnectable_recount_server
        endpoint.clock.value = setup["clock"].value
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        reason = "An explicitly checked request keeps its original body and identifier."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, editor):
            child = editor.property("recounts")
            assert isinstance(child, QObject)
            wait_for_editor_idle(qt_app, child)
            child.setField("event_at", "2026-11-16 00:05:42.123456")
            child.setField("reason", reason)
            endpoint.disconnect_proxy()
            try:
                child.instruct(READY_PASSWORD)
                wait_for_editor_idle(qt_app, child)
                assert child.property("state")["uncertain_save"] is True
                request_id = child.property("state")["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert endpoint.request_count("POST", recount_path) == 0
            finally:
                # Restore exactly the same HTTPS origin before any outcome check/retry/cleanup.
                endpoint.reconnect_proxy()

            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = [row for row in recovery.property("state")["commands"]
                        if row["request_id"] == request_id and row["path"] == recount_path]
            assert len(commands) == 1
            original = commands[0]
            assert original["status"] == "uncertain" and original["confirmation_required"] is True
            assert original["actor_id"] == actor_id and original["station_id"] == station_id
            assert original["server_url"] == endpoint.url and original["method"] == "POST"
            assert original["workflow"] == "count"
            assert original["payload"] == {
                "request_id": request_id, "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": prior["selection"]["revision"],
                "source_round_id": prior["id"], "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": reason,
            }
            outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            absent_response = supervisor.get(outcome_path + "?workflow=count")
            assert absent_response.status_code == 200, absent_response.text
            absent = {"request_id": request_id, "workflow": "count", "status": "not_found"}
            assert absent_response.json() == absent
            empty_state = supervisor.get(recount_path)
            assert empty_state.status_code == 200, empty_state.text
            assert empty_state.json()["instructions"] == []
            empty_rounds = counter.get(setup["rounds_path"])
            assert empty_rounds.status_code == 200, empty_rounds.text
            assert [row["id"] for row in empty_rounds.json()["rounds"]] == [prior["id"]]
            assert endpoint.request_count("POST", recount_path) == 0
            assert endpoint.request_count("GET", outcome_path) == 0

            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "recovery_retry_unavailable"
            assert endpoint.request_count("POST", recount_path) == 0
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            checked_absent = next(row for row in recovery.property("state")["commands"]
                                  if row["request_id"] == request_id)
            assert checked_absent["status"] == "uncertain"
            assert checked_absent["error"] == "request_not_found"
            assert checked_absent["payload"] == original["payload"]
            assert endpoint.request_count("GET", outcome_path) == 1
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "invalid_credentials"
            assert endpoint.request_count("POST", recount_path) == 0

            # The fixture's already-replaced initial password is not the current own password.
            recovery.retry(request_id, INITIAL_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            rejected_password = next(row for row in recovery.property("state")["commands"]
                                     if row["request_id"] == request_id)
            assert recovery.property("state")["error"] == "invalid_credentials"
            assert rejected_password["status"] == "uncertain"
            assert rejected_password["error"] == "invalid_credentials"
            assert rejected_password["payload"] == original["payload"]
            assert endpoint.request_count("POST", recount_path) == 1
            still_absent = supervisor.get(outcome_path + "?workflow=count")
            assert still_absent.status_code == 200, still_absent.text
            assert still_absent.json() == absent
            still_empty = supervisor.get(recount_path)
            assert still_empty.status_code == 200, still_empty.text
            assert still_empty.json()["instructions"] == []

            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "recovery_retry_unavailable"
            assert endpoint.request_count("POST", recount_path) == 1
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            rechecked = next(row for row in recovery.property("state")["commands"]
                             if row["request_id"] == request_id)
            assert rechecked["status"] == "uncertain" and rechecked["error"] == "request_not_found"
            assert rechecked["payload"] == original["payload"]
            assert endpoint.request_count("GET", outcome_path) == 2
            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            committed = next(row for row in recovery.property("state")["commands"]
                             if row["request_id"] == request_id)
            assert committed["status"] == "committed" and committed["error"] == ""
            assert committed["payload"] == original["payload"]
            assert endpoint.request_count("POST", recount_path) == 2
            assert endpoint.request_count("GET", outcome_path) == 2

            final_state = supervisor.get(recount_path)
            assert final_state.status_code == 200, final_state.text
            instructions = final_state.json()["instructions"]
            assert len(instructions) == 1 and instructions[0]["request_id"] == request_id
            instruction = instructions[0]
            assert instruction["actor_id"] == actor_id and instruction["reason"] == reason
            new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
            new_response = counter.get(new_path)
            assert new_response.status_code == 200, new_response.text
            assert len(new_response.json()["history"]) == 1
            blank = new_response.json()["record"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert all(blank[key] is None for key in ("event_at", "entered_at", "actor_id"))
            outcome_response = supervisor.get(outcome_path + "?workflow=count")
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            assert outcome["status"] == "committed" and outcome["request_id"] == request_id
            assert outcome["record"] == {"instruction": instruction, "round": blank}
            assert_public_business_fields(committed["receipt"]["record"], outcome["record"])
            other_actor = counter.get(outcome_path + "?workflow=count")
            assert other_actor.status_code == 200, other_actor.text
            assert other_actor.json() == absent
            for secret in (INITIAL_PASSWORD, READY_PASSWORD):
                assert secret not in json.dumps(recovery.property("state"))
            repeated_outcome = supervisor.get(outcome_path + "?workflow=count")
            assert repeated_outcome.status_code == 200, repeated_outcome.text
            assert repeated_outcome.json() == outcome
            preserved_response = counter.get(source_path)
            assert preserved_response.status_code == 200, preserved_response.text
            preserved = preserved_response.json()
            assert [row["revision_id"] for row in preserved["history"]] == old_history_ids
            for key in ("candidate_votes", "invalid_papers", "scope_basis", "f2", "event_at",
                        "entered_at", "actor_id", "approved_at", "approved_by"):
                assert preserved["record"][key] == prior[key]

            # Likely first uncovered RED at6d051522: Recovery's known commit never settles child.
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, editor)
            settled = child.property("state")
            assert settled["uncertain_save"] is False
            assert settled["dirty"] is False and settled["pending_request_id"] == ""
            assert settled["error"] == ""
            assert settled["forms"] == {"event_at": "", "reason": ""}
            assert editor.property("state")["selected"]["id"] == prior["id"]
            assert editor.property("state")["dirty"] is False
            assert any(row["id"] == instruction["new_round_id"]
                       for row in editor.property("state")["rounds"])
            assert endpoint.request_count("POST", recount_path) == 2
