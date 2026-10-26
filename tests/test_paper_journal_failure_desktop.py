"""A committed response cannot unlock paper entry when its journal write fails."""

import asyncio
import json
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

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
from tests.test_allocation_paper_reentry_desktop import _register_paper
from tests.test_allocation_paper_reentry_desktop import (
    allocation_base_setup as allocation_base_setup,
)
from tests.test_client_recovery_contract_desktop import _draft_count
from tests.test_outage_reconciliation_edges_api import _create_outage_and_paper
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url
from tests.test_turnout_paper_reentry_desktop import _outage as turnout_outage
from tests.test_turnout_paper_reentry_desktop import _paper as turnout_paper
from tests.turnout_support import READY_PASSWORD as TURNOUT_READY_PASSWORD
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


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
    qt_app: QCoreApplication, *, password: str = READY_PASSWORD,
) -> Iterator[DesktopController]:
    client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(endpoint.url, username, password)
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


@contextmanager
def obstructed_journal_file(
    path: Path, endpoint: CompletedWriteServer,
) -> Iterator[Callable[[], None]]:
    original = path.read_bytes()
    saved = path.with_suffix(".saved")
    assert not saved.exists()
    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        if path.exists():
            path.rmdir()
        saved.rename(path)
        assert path.read_bytes() == original
        restored = True

    path.rename(saved)
    try:
        # A directory at the prepared journal's file path makes its actual
        # read/write fail on every platform, without replacing any product code.
        path.mkdir(mode=0o700)
        yield restore
    finally:
        endpoint.release.set()
        restore()


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
            with obstructed_journal_file(journal_path, endpoint) as restore_journal:
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
                assert state["error"] == "recovery_journal_outcome_unavailable"
                assert state["uncertain_save"] is True
                assert state["paper_binding_locked"] is True
                assert state["paper_record"]["id"] == paper["id"]
                assert editor.selectPaperRecord(0) is False
                workspace = client.property("workspace")
                assert workspace.property("unresolvedRequest") is True
                workspace.selectStation(0, True)
                assert workspace.property("state")["error"] == "workspace_uncertain_request"
                assert workspace.property("state")["selected"]["station"]["id"] == station_id

                restore_journal()
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


def test_committed_allocation_keeps_paper_locked_until_journal_outcome_can_be_checked(
    allocation_base_setup: dict,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    setup = allocation_base_setup
    endpoint = completed_write_server
    endpoint.clock.value = setup["clock"].value
    station_id = setup["station"]["id"]
    outage_path, paper = _register_paper(
        setup, action="create", target={"counter_id": setup["counter"]["id"]},
    )
    write_path = setup["base"] + "/allocations"
    with signed_in_client(endpoint, setup["account"]["username"], station_id, qt_app) as client:
        editor = client.property("allocations")
        editor.open()
        wait_for_editor_idle(qt_app, editor)
        editor.setField("counter_id", str(setup["counter"]["id"]))
        wait_for_editor_idle(qt_app, editor)
        editor.refreshPaperRecords()
        wait_for_editor_idle(qt_app, editor)
        assert [row["id"] for row in editor.property("state")["paper_records"]] == [paper["id"]]
        assert editor.selectPaperRecord(paper["id"]) is True
        for name, value in {
            "series": setup["series"], "serial_from": "000001", "serial_to": "000002",
        }.items():
            editor.setField(name, value)
        endpoint.hold_path = write_path
        editor.save()
        wait_for(qt_app, endpoint.entered.is_set)
        files = list(private_command_directory.glob("*.json"))
        assert len(files) == 1
        journal_path = files[0]
        original = json.loads(journal_path.read_text())
        assert original["status"] == "pending"
        assert original["payload"]["paper_record_id"] == paper["id"]
        with obstructed_journal_file(journal_path, endpoint) as restore_journal:
            endpoint.release.set()
            wait_for(qt_app, lambda: not editor.property("state")["busy"])
            entered = setup["polling"].get(outage_path)
            assert entered.status_code == 200, entered.text
            linked = entered.json()["record"]["paper_records"][0]
            assert linked["status"] == "entered"
            assert linked["reentry"]["request_id"] == original["request_id"]
            record = linked["reentry"]["record"]
            assert record["status"] == "recorded"
            assert record["quantity"] == 2
            history_path = write_path + f"/{record['id']}/history"
            committed = setup["polling"].get(history_path)
            assert committed.status_code == 200, committed.text
            assert len(committed.json()["items"]) == 1
            assert endpoint.request_count("POST", write_path) == 1

            state = editor.property("state")
            assert state["error"] == "recovery_journal_outcome_unavailable"
            assert state["paper_uncertain"] is True
            assert state["paper_record"]["id"] == paper["id"]
            assert editor.selectPaperRecord(0) is False
            editor.save()
            assert endpoint.request_count("POST", write_path) == 1
            workspace = client.property("workspace")
            assert workspace.property("unresolvedRequest") is True
            workspace.selectStation(0, True)
            assert workspace.property("state")["error"] == "workspace_uncertain_request"
            assert workspace.property("state")["selected"]["station"]["id"] == station_id

            restore_journal()
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
                         if row["request_id"] == command["request_id"])["status"] == "committed"
            ))
            wait_for_editor_idle(qt_app, editor)
            settled = editor.property("state")
            assert settled["paper_uncertain"] is False
            assert settled["paper_record"] == {}
            assert settled["selected"]["id"] == record["id"]
            assert workspace.property("unresolvedRequest") is False
            assert endpoint.request_count("POST", write_path) == 1
            after_check = setup["polling"].get(history_path)
            assert after_check.status_code == 200, after_check.text
            assert after_check.json() == committed.json()


def test_count_journal_failure_before_dispatch_leaves_pending_paper_correctable(
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
            original_forms = editor.property("state")["forms"]
            assert not private_command_directory.exists()
            private_command_directory.write_text("The journal path is unavailable.")
            try:
                editor.submitCount()
                wait_for(qt_app, lambda: not editor.property("state")["busy"])
                assert endpoint.request_count("POST", submit_path) == 0
                current = officer.get(round_path)
                assert current.status_code == 200, current.text
                assert current.json()["record"]["status"] == "draft"
                assert len(current.json()["history"]) == 2
                pending = officer.get(outage_path)
                assert pending.status_code == 200, pending.text
                assert pending.json()["record"]["paper_records"][0]["status"] == "pending"
                assert private_command_directory.is_file()
                state = editor.property("state")
                assert state["error"] == "recovery_journal_unavailable"
                assert state["uncertain_save"] is False
                assert state["paper_binding_locked"] is False
                assert state["paper_record"]["id"] == paper["id"]
                assert state["forms"] == original_forms
                assert client.property("workspace").property("unresolvedRequest") is False

                private_command_directory.unlink()
                private_command_directory.mkdir(mode=0o700)
                editor.submitCount()
                wait_for(qt_app, lambda: (
                    not editor.property("state")["busy"]
                    and editor.property("state")["selected"]["status"] == "submitted"
                ))
                assert endpoint.request_count("POST", submit_path) == 1
                assert editor.property("state")["paper_record"] == {}
            finally:
                if private_command_directory.is_file():
                    private_command_directory.unlink()
                    private_command_directory.mkdir(mode=0o700)


def test_allocation_journal_failure_before_dispatch_leaves_pending_paper_correctable(
    allocation_base_setup: dict,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    setup = allocation_base_setup
    endpoint = completed_write_server
    endpoint.clock.value = setup["clock"].value
    station_id = setup["station"]["id"]
    outage_path, paper = _register_paper(
        setup, action="create", target={"counter_id": setup["counter"]["id"]},
    )
    write_path = setup["base"] + "/allocations"
    with signed_in_client(endpoint, setup["account"]["username"], station_id, qt_app) as client:
        editor = client.property("allocations")
        editor.open()
        wait_for_editor_idle(qt_app, editor)
        editor.setField("counter_id", str(setup["counter"]["id"]))
        wait_for_editor_idle(qt_app, editor)
        editor.refreshPaperRecords()
        wait_for_editor_idle(qt_app, editor)
        assert editor.selectPaperRecord(paper["id"]) is True
        for name, value in {
            "series": setup["series"], "serial_from": "000001", "serial_to": "000002",
        }.items():
            editor.setField(name, value)
        original_forms = editor.property("state")["forms"]
        assert not private_command_directory.exists()
        private_command_directory.write_text("The journal path is unavailable.")
        try:
            editor.save()
            wait_for(qt_app, lambda: not editor.property("state")["busy"])
            assert endpoint.request_count("POST", write_path) == 0
            allocations = setup["polling"].get(write_path)
            assert allocations.status_code == 200, allocations.text
            assert allocations.json()["items"] == []
            pending = setup["polling"].get(outage_path)
            assert pending.status_code == 200, pending.text
            assert pending.json()["record"]["paper_records"][0]["status"] == "pending"
            assert private_command_directory.is_file()
            state = editor.property("state")
            assert state["error"] == "recovery_journal_unavailable"
            assert state["paper_uncertain"] is False
            assert state["paper_record"]["id"] == paper["id"]
            assert state["forms"] == original_forms
            assert client.property("workspace").property("unresolvedRequest") is False

            private_command_directory.unlink()
            private_command_directory.mkdir(mode=0o700)
            editor.save()
            wait_for(qt_app, lambda: (
                not editor.property("state")["busy"]
                and editor.property("state")["selected"].get("revision") == 1
            ))
            assert endpoint.request_count("POST", write_path) == 1
            assert editor.property("state")["paper_record"] == {}
        finally:
            if private_command_directory.is_file():
                private_command_directory.unlink()
                private_command_directory.mkdir(mode=0o700)


@pytest.fixture
def turnout_paper_setup(
    admin: TestClient, database_url: str, completed_write_server: CompletedWriteServer,
) -> Iterator[dict]:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    clock = TurnoutClock()
    completed_write_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = turnout_outage(
            officer, station_id, reference="Journal fault turnout " + uuid4().hex[:8],
        )
        paper = turnout_paper(
            officer, station_id, outage["id"], reference="JOURNAL-TURNOUT-" + uuid4().hex[:8],
            action="save", period_index=1, event_at="2026-11-15T09:30:00+08:00",
        )
        yield {
            "officer": officer, "account": account, "station_id": station_id,
            "write_path": scope["path"] + "/1", "paper": paper,
            "outage_path": (
                f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
            ),
        }


def open_turnout_paper(client: DesktopController, setup: dict, qt_app: QCoreApplication):
    editor = client.property("turnout")
    assert editor.open() is True
    wait_for_editor_idle(qt_app, editor)
    editor.refreshPaperRecords()
    wait_for(qt_app, lambda: (
        not editor.property("state")["paper_refreshing"]
        and any(row["id"] == setup["paper"]["id"]
                for row in editor.property("state")["paper_records"])
    ))
    assert editor.selectPaperRecord(setup["paper"]["id"]) is True
    for name, value in {
        "supplied_hourly": "0", "supplied_cumulative": "0",
        "event_time": "2026-11-15 09:30", "source_context": "Signed turnout paper.",
    }.items():
        editor.setField(name, value)
    return editor


def test_committed_turnout_keeps_paper_locked_until_journal_outcome_can_be_checked(
    turnout_paper_setup: dict,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    private_command_directory: Path,
) -> None:
    setup = turnout_paper_setup
    endpoint = completed_write_server
    write_path = setup["write_path"]
    paper_id = setup["paper"]["id"]
    with signed_in_client(
        endpoint, setup["account"]["username"], setup["station_id"], qt_app,
        password=TURNOUT_READY_PASSWORD,
    ) as client:
        editor = open_turnout_paper(client, setup, qt_app)
        endpoint.hold_path = write_path
        editor.save()
        wait_for(qt_app, endpoint.entered.is_set)
        files = list(private_command_directory.glob("*.json"))
        assert len(files) == 1
        journal_path = files[0]
        original = json.loads(journal_path.read_text())
        assert original["status"] == "pending"
        assert original["payload"]["paper_record_id"] == paper_id
        with obstructed_journal_file(journal_path, endpoint) as restore_journal:
            endpoint.release.set()
            wait_for(qt_app, lambda: not editor.property("state")["busy"])
            entered = setup["officer"].get(setup["outage_path"])
            assert entered.status_code == 200, entered.text
            linked = entered.json()["record"]["paper_records"][0]
            assert linked["status"] == "entered"
            assert linked["reentry"]["request_id"] == original["request_id"]
            assert linked["reentry"]["record"]["supplied_hourly"] == 0
            history_path = write_path + "/history"
            committed = setup["officer"].get(history_path)
            assert committed.status_code == 200, committed.text
            assert len(committed.json()["items"]) == 1
            assert endpoint.request_count("PUT", write_path) == 1

            state = editor.property("state")
            assert state["error"] == "recovery_journal_outcome_unavailable"
            assert state["uncertain_save"] is True
            assert state["paper_pending_request_id"] == original["request_id"]
            assert state["paper_record"]["id"] == paper_id
            assert editor.selectPaperRecord(0) is False
            assert editor.selectPeriod(2, True) is False
            workspace = client.property("workspace")
            assert workspace.property("unresolvedRequest") is True
            workspace.selectStation(0, True)
            assert workspace.property("state")["error"] == "workspace_uncertain_request"
            assert workspace.property("state")["selected"]["station"]["id"] == setup["station_id"]

            restore_journal()
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
                         if row["request_id"] == command["request_id"])["status"] == "committed"
            ))
            wait_for(qt_app, lambda: (
                not editor.property("state")["busy"]
                and not editor.property("state")["uncertain_save"]
                and editor.property("state")["selected"].get("status") == "draft"
            ))
            assert editor.property("state")["paper_record"] == {}
            assert editor.property("state")["paper_pending_request_id"] == ""
            assert workspace.property("unresolvedRequest") is False
            assert endpoint.request_count("PUT", write_path) == 1
            after_check = setup["officer"].get(history_path)
            assert after_check.status_code == 200, after_check.text
            assert after_check.json() == committed.json()
