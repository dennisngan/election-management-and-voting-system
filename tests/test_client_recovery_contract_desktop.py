"""Recovery requires an outcome check and validates the saved public receipt."""

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, wait_for, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)


@dataclass
class RecoveryFaultServer:
    url: str
    clock: ControlledClock
    requests: list[tuple[str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    fail_before_path: str = ""
    fail_after_path: str = ""
    corrupt_outcome_path: str = ""
    malformed_success_path: str = ""

    def request_count(self, method: str, path: str) -> int:
        with self.lock:
            return self.requests.count((method, path))


@pytest.fixture
def recovery_fault_server(
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[RecoveryFaultServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    endpoint = RecoveryFaultServer(
        url=f"https://localhost:{port}",
        clock=ControlledClock(),
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def inject_public_response_faults(
        request: Request,
        call_next,
    ) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
            fail_before = (
                request.method in ("POST", "PUT", "PATCH")
                and path == endpoint.fail_before_path
            )
        if fail_before:
            return JSONResponse({"detail": {"code": "request_failed"}}, status_code=503)

        response = await call_next(request)
        with endpoint.lock:
            fail_after = (
                request.method in ("POST", "PUT", "PATCH")
                and path == endpoint.fail_after_path
            )
            corrupt_outcome = request.method == "GET" and path == endpoint.corrupt_outcome_path
            malformed_success = (
                request.method in ("POST", "PUT", "PATCH")
                and path == endpoint.malformed_success_path
            )
        if fail_after and response.status_code == 200:
            return JSONResponse({"detail": {"code": "request_failed"}}, status_code=503)
        if malformed_success and response.status_code == 200:
            return JSONResponse({"status": "submitted"}, status_code=200)
        if corrupt_outcome and response.status_code == 200:
            chunks = [chunk async for chunk in response.body_iterator]
            body = b"".join(chunk.encode() if isinstance(chunk, str) else chunk for chunk in chunks)
            payload = json.loads(body)
            payload["record"]["id"] += 1000000
            preserved_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower() not in {"content-length", "content-type", "transfer-encoding"}
            }
            return JSONResponse(
                payload,
                status_code=response.status_code,
                headers=preserved_headers,
                background=response.background,
            )
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            loop="asyncio",
            ws="none",
            ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
            ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
            log_level="warning",
            access_log=False,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()


def _draft_count(setup: dict) -> str:
    counter, rounds_path = setup["counter"], setup["rounds_path"]
    options = counter.get(rounds_path).json()
    f1 = complete_f1_command(options, actual_counted_quantity=5)
    f1["candidate_votes"][0]["quantity"] = 5
    created = counter.post(rounds_path, json=f1)
    assert created.status_code == 201, created.text
    target = rounds_path + f"/{created.json()['id']}"
    f2 = counter.put(target + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    return target


def _fresh_recovery_client(
    server: RecoveryFaultServer,
    setup: dict,
    station_id: int,
    qt_app: QCoreApplication,
    account_key: str = "receiveronly",
) -> tuple[DesktopController, object]:
    account = setup["accounts"][account_key]
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    client.signIn(server.url, account["username"], READY_PASSWORD)
    wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
    workspace = client.property("workspace")
    wait_for_editor_idle(qt_app, workspace)
    workspace.selectStation(station_id)
    wait_for_editor_idle(qt_app, workspace)
    recovery = client.property("recovery")
    recovery.open()
    wait_for_editor_idle(qt_app, recovery)
    return client, recovery


def test_retry_waits_for_an_explicit_not_found_outcome(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
    with tally_setup(admin, database_url) as setup:
        server = recovery_fault_server
        server.clock.value = setup["clock"].value
        target = _draft_count(setup)
        station_id = setup["stations"]["N1"]["id"]
        server.fail_before_path = target + "/submit"
        with f1_editor(
            server,
            qt_app,
            setup["accounts"]["receiveronly"],
            station_id,
            setup["scope"]["id"],
        ) as (_, editor):
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["uncertain_save"] is True
        assert server.request_count("POST", target + "/submit") == 1

        client, recovery = _fresh_recovery_client(server, setup, station_id, qt_app)
        try:
            command = recovery.property("state")["commands"][0]
            assert command["status"] in ("pending", "uncertain")
            recovery.retry(command["request_id"], "")
            wait_for_editor_idle(qt_app, recovery)
            assert server.request_count("POST", target + "/submit") == 1, (
                "recovery retried before checking whether the original request committed"
            )

            recovery.checkOutcome(command["request_id"])
            wait_for_editor_idle(qt_app, recovery)
            checked = recovery.property("state")["commands"][0]
            assert checked["status"] == "uncertain"
            assert checked["error"] == "request_not_found"
            server.fail_before_path = ""
            recovery.retry(command["request_id"], "")
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["status"] == "committed"
            assert server.request_count("POST", target + "/submit") == 2
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_mismatched_outcome_receipt_stays_uncertain(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
    with tally_setup(admin, database_url) as setup:
        server = recovery_fault_server
        server.clock.value = setup["clock"].value
        target = _draft_count(setup)
        station_id = setup["stations"]["N1"]["id"]
        server.fail_after_path = target + "/submit"
        with f1_editor(
            server,
            qt_app,
            setup["accounts"]["receiveronly"],
            station_id,
            setup["scope"]["id"],
        ) as (_, editor):
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["uncertain_save"] is True
        assert server.request_count("POST", target + "/submit") == 1

        client, recovery = _fresh_recovery_client(server, setup, station_id, qt_app)
        try:
            request_id = recovery.property("state")["commands"][0]["request_id"]
            outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
            server.corrupt_outcome_path = outcome_path
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            command = recovery.property("state")["commands"][0]
            assert command["status"] == "uncertain"
            assert command.get("receipt") is None

            server.corrupt_outcome_path = ""
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["status"] == "committed"
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_noncanonical_retry_reply_stays_uncertain_after_not_found(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
    with tally_setup(admin, database_url) as setup:
        server = recovery_fault_server
        server.clock.value = setup["clock"].value
        target = _draft_count(setup)
        station_id = setup["stations"]["N1"]["id"]
        server.fail_before_path = target + "/submit"
        with f1_editor(
            server,
            qt_app,
            setup["accounts"]["receiveronly"],
            station_id,
            setup["scope"]["id"],
        ) as (_, editor):
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["uncertain_save"] is True
        assert server.request_count("POST", target + "/submit") == 1

        client, recovery = _fresh_recovery_client(server, setup, station_id, qt_app)
        try:
            request_id = recovery.property("state")["commands"][0]["request_id"]
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["error"] == "request_not_found"

            server.fail_before_path = ""
            server.malformed_success_path = target + "/submit"
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            command = recovery.property("state")["commands"][0]
            assert command["status"] == "uncertain"

            server.malformed_success_path = ""
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["status"] == "committed"
            assert server.request_count("POST", target + "/submit") == 2
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_invalid_fresh_password_preserves_original_supervisor_command(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
    with tally_setup(admin, database_url) as setup:
        server = recovery_fault_server
        server.clock.value = setup["clock"].value
        counter, rounds_path = setup["counter"], setup["rounds_path"]
        options = counter.get(rounds_path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = counter.post(rounds_path, json=f1)
        assert created.status_code == 201, created.text
        target = rounds_path + f"/{created.json()['id']}"
        f2 = counter.put(target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": f2.json()["revision"],
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        supervisor = setup["clients"]["supervisor"]
        approved = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text

        station_id = setup["stations"]["N1"]["id"]
        server.fail_before_path = target + "/select"
        with f1_editor(
            server,
            qt_app,
            setup["accounts"]["supervisor"],
            station_id,
            setup["scope"]["id"],
        ) as (_, editor):
            editor.selectApproved(READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["uncertain_save"] is True
        assert server.request_count("POST", target + "/select") == 1

        server.fail_before_path = ""
        client, recovery = _fresh_recovery_client(
            server, setup, station_id, qt_app, account_key="supervisor"
        )
        try:
            initial = recovery.property("state")["commands"][0]
            request_id = initial["request_id"]
            assert initial["confirmation_required"] is True
            assert "password" not in initial["payload"]
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["error"] == "request_not_found"

            recovery.retry(request_id, "Wrong-Recovery-Password-42!")
            wait_for_editor_idle(qt_app, recovery)
            denied = recovery.property("state")["commands"][0]
            assert denied["request_id"] == request_id
            assert denied["status"] == "uncertain"
            assert denied["error"] == "invalid_credentials"
            assert server.request_count("POST", target + "/select") == 2
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))
            assert "Wrong-Recovery-Password-42!" not in json.dumps(recovery.property("state"))

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            after_denial = recovery.property("state")["commands"][0]
            assert after_denial["request_id"] == request_id
            assert after_denial["status"] == "uncertain"
            assert after_denial["error"] == "request_not_found"
            assert server.request_count("POST", target + "/select") == 2

            recovery.retry(request_id, READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            committed = recovery.property("state")["commands"][0]
            assert committed["request_id"] == request_id
            assert committed["status"] == "committed"
            assert server.request_count("POST", target + "/select") == 3
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
