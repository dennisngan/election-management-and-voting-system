"""A committed response cannot unlock paper entry when its journal write fails."""

import asyncio
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, wait_for, wait_for_editor_idle
from tests.tally_support import tally_setup
from tests.test_client_recovery_contract_desktop import _draft_count
from tests.test_outage_reconciliation_edges_api import _create_outage_and_paper
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url


@dataclass
class CompletedWriteServer:
    url: str
    clock: ControlledClock
    hold_path: str = ""
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    requests: list[tuple[str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def request_count(self, method: str, path: str) -> int:
        with self.lock:
            return self.requests.count((method, path))


@pytest.fixture
def private_command_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "private-commands"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(directory))
    return directory


@pytest.fixture
def completed_write_server(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[CompletedWriteServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    endpoint = CompletedWriteServer(
        f"https://localhost:{listener.getsockname()[1]}", ControlledClock(),
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def hold_completed_write(request: Request, call_next) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        if (
            request.method in {"POST", "PUT"}
            and request.url.path == endpoint.hold_path
            and response.status_code in {200, 201}
        ):
            # The real authenticated handler has committed. Only delivery of
            # its unchanged response waits while the journal filesystem fails.
            endpoint.entered.set()
            await asyncio.to_thread(endpoint.release.wait)
        return response

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=listener.getsockname()[1],
        loop="asyncio", ws="none", ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
        ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"), access_log=False,
        log_level="warning", timeout_keep_alive=5, timeout_graceful_shutdown=1,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        endpoint.release.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()


@contextmanager
def signed_in_client(
    endpoint: CompletedWriteServer, username: str, station_id: int,
    qt_app: QCoreApplication,
) -> Iterator[DesktopController]:
    client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(endpoint.url, username, READY_PASSWORD)
        wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for_editor_idle(qt_app, workspace)
        workspace.selectStation(station_id)
        wait_for_editor_idle(qt_app, workspace)
        assert workspace.property("state")["selected"]["station"]["id"] == station_id
        yield client
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_committed_count_keeps_paper_locked_until_journal_outcome_can_be_checked(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    with tally_setup(admin, database_url) as setup:
        endpoint = completed_write_server
        endpoint.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        round_path = _draft_count(setup)
        round_id = int(round_path.rsplit("/", 1)[1])
        outage_path, paper = _create_outage_and_paper(setup, round_id)
        submit_path = round_path + "/submit"
        with signed_in_client(
            endpoint, setup["accounts"]["receiveronly"]["username"], station_id, qt_app,
        ) as client:
            editor = client.property("countingRounds")
            editor.open()
            wait_for_editor_idle(qt_app, editor)
            assert editor.selectScope(setup["scope"]["id"]) is True
            wait_for_editor_idle(qt_app, editor)
            assert editor.selectRound(round_id) is True
            wait_for(qt_app, lambda: (
                not editor.property("state")["busy"]
                and not editor.property("state")["paper_loading"]
                and any(row["id"] == paper["id"]
                        for row in editor.property("state")["paper_records"])
            ))
            assert editor.selectPaperRecord(paper["id"]) is True
            endpoint.hold_path = submit_path
            editor.submitCount()
            wait_for(qt_app, endpoint.entered.is_set)
            files = list(private_command_directory.glob("*.json"))
            assert len(files) == 1
            journal_path = files[0]
            original = json.loads(journal_path.read_text())
            assert original["status"] == "pending"
            assert original["payload"]["paper_record_id"] == paper["id"]
            try:
                journal_path.chmod(0o400)
                endpoint.release.set()
                wait_for(qt_app, lambda: not editor.property("state")["busy"])
                committed = officer.get(round_path)
                assert committed.status_code == 200, committed.text
                assert committed.json()["record"]["status"] == "submitted"
                entered = officer.get(outage_path)
                assert entered.status_code == 200, entered.text
                linked = entered.json()["record"]["paper_records"][0]
                assert linked["status"] == "entered"
                assert linked["reentry"]["request_id"] == original["request_id"]
                assert endpoint.request_count("POST", submit_path) == 1

                state = editor.property("state")
                assert state["error"] == "recovery_journal_unavailable"
                assert state["uncertain_save"] is True
                assert state["paper_binding_locked"] is True
                assert state["paper_record"]["id"] == paper["id"]
                assert editor.selectPaperRecord(0) is False
                workspace = client.property("workspace")
                assert workspace.property("unresolvedRequest") is True
                workspace.selectStation(0, True)
                assert workspace.property("state")["error"] == "workspace_uncertain_request"
                assert workspace.property("state")["selected"]["station"]["id"] == station_id

                journal_path.chmod(0o600)
                recovery = client.property("recovery")
                recovery.open()
                wait_for_editor_idle(qt_app, recovery)
                command = next(row for row in recovery.property("state")["commands"]
                               if row["request_id"] == original["request_id"])
                assert command["payload"] == original["payload"]
                assert command["status"] == "pending"
                recovery.checkOutcome(command["request_id"])
                wait_for(qt_app, lambda: (
                    not recovery.property("state")["busy"]
                    and next(row for row in recovery.property("state")["commands"]
                             if row["request_id"] == command["request_id"])["status"]
                    == "committed"
                ))
                wait_for(qt_app, lambda: (
                    not editor.property("state")["busy"]
                    and editor.property("state")["selected"]["status"] == "submitted"
                    and not editor.property("state")["uncertain_save"]
                ))
                assert editor.property("state")["paper_record"] == {}
                assert editor.property("state")["paper_binding_locked"] is False
                assert workspace.property("unresolvedRequest") is False
                assert endpoint.request_count("POST", submit_path) == 1
                after_check = officer.get(round_path)
                assert after_check.status_code == 200, after_check.text
                assert after_check.json() == committed.json()
            finally:
                endpoint.release.set()
                journal_path.chmod(0o600)
