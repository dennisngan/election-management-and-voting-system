"""Election completion changes reach public Qt lifecycle state through real HTTPS."""

import hashlib
import json
import os
import socket
import ssl
import stat
import threading
from collections.abc import Awaitable, Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtTest import QSignalSpy

from election.desktop.controller import DesktopController
from election.private_paths import private_directory, private_file
from election.server.app import create_app
from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    wait_for,
    wait_for_editor_idle,
)
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import (
    lifecycle_database_url,
    lifecycle_test_state,
    prepared_election,
)
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse
from tests.test_paper_journal_failure_desktop import CompletedWriteServer
from tests.test_paper_journal_failure_desktop import (
    completed_write_server as completed_write_server,
)
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
from tests.test_recount_checked_retry_desktop import ReconnectableRecountServer
from tests.test_recount_checked_retry_desktop import (
    reconnectable_recount_server as reconnectable_recount_server,
)
from tests.test_recount_instruction_restart_desktop import (
    lost_recount_response as lost_recount_response,
)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_completion_desktop_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_lifecycle_refresh_propagates_no_active_election_after_real_finalization(
    desktop: DesktopController,
    admin: TestClient,
    account: dict[str, str],
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        configuration = ready_setup(desktop, https_server, account, qt_app)
        lifecycle = desktop.property("lifecycle")
        assert lifecycle is not None
        election_id = setup["election"]["id"]
        wait_for(qt_app, lambda: (
            setup_idle(configuration) and setup_idle(lifecycle)
            and (lifecycle.property("state")["active_election"] or {}).get("id") == election_id
            and (desktop.property("state")["active_election"] or {}).get("id") == election_id
        ))
        assert desktop.property("state")["account"]["role"] == "administrator"
        assert desktop.property("workspace").property("state")["selected"] == {}
        context = ssl.create_default_context(cafile=str(TLS_DIRECTORY / "ca.pem"))
        with httpx.Client(base_url=https_server.url, verify=context) as supervisor:
            login = supervisor.post("/api/auth/login", json={
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
            })
            assert login.status_code == 200, login.text
            supervisor.headers["Authorization"] = "Bearer " + login.json()["token"]
            try:
                response = supervisor.get(setup["completion_path"])
                assert response.status_code == 200, response.text
                reviewed = response.json()
                assert reviewed["can_finalize"] is True
                finalized = supervisor.post(
                    f"/api/workspace/elections/{election_id}/finalizations", json={
                        "request_id": str(uuid4()),
                        "expected_election_revision": reviewed["election"]["revision"],
                        "basis_digest": reviewed["basis_digest"],
                        "password": BOX_READY_PASSWORD,
                    },
                )
                assert finalized.status_code == 201, finalized.text
                assert finalized.json()["election"]["status"] == "finalized"
                assert finalized.json()["active_election_id"] is None
                active = supervisor.get("/api/active-election")
                assert active.status_code == 200, active.text
                assert active.json()["election"] is None
                assert desktop.property("state")["active_election"]["id"] == election_id
                before = https_server.request_count("GET", "/api/active-election")
                lifecycle.refresh()
                wait_for(qt_app, lambda: setup_idle(lifecycle))
                observed_lifecycle = lifecycle.property("state")
                observed_root = desktop.property("state")
                after = https_server.request_count("GET", "/api/active-election")
            finally:
                logout = supervisor.delete("/api/auth/session")
                assert logout.status_code == 204, logout.text
        assert after == before + 1, "An independent active-election refresh overlapped this seam"
        assert observed_lifecycle["error"] == ""
        assert observed_lifecycle["active_election"] is None
        assert observed_root["active_election"] is None


def _assert_completion_credential_free(value: object) -> None:
    if isinstance(value, dict):
        assert not {
            "password", "current_password", "new_password", "temporary_password",
            "password_hash", "token", "token_hash", "session_token", "authorization",
            "secret", "secret_key", "access_token", "refresh_token",
        } & {str(key).lower() for key in value}
        for nested in value.values():
            _assert_completion_credential_free(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_completion_credential_free(nested)
    elif isinstance(value, str):
        assert BOX_READY_PASSWORD not in value


def test_supervisor_finalizes_without_station_and_keeps_true_election_recovery_command(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "election-finalization-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        actor = setup["accounts"]["supervisor"]
        election_id = setup["election"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert client.property("state")["account"]["role"] == "supervisor"
            assert client.property("state")["account"]["id"] == actor["id"]
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            assert completion is not None
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            before = completion.property("state")
            assert before["error"] == ""
            assert before["election_id"] == election_id
            reviewed = before["assessment"]
            assert reviewed["can_finalize"] is True
            assert https_server.request_count("POST", target) == 0
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            settled = completion.property("state")
            assert settled["error"] == ""
            assert settled["pending_request_id"] == ""
            assert settled["uncertain_save"] is False
            assert client.property("state")["active_election"] is None
            assert workspace.property("state")["selected"] == {}
            request_id = settled["receipt"]["request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
                "?workflow=election_completion"
            )
            outcome = setup["clients"]["supervisor"].get(outcome_path)
            assert outcome.status_code == 200, outcome.text
            canonical = outcome.json()
            assert canonical["request_id"] == request_id
            assert canonical["workflow"] == "election_completion"
            assert canonical["status"] == "committed"
            receipt = canonical["record"]
            assert receipt["election"]["id"] == election_id
            assert receipt["election"]["status"] == "finalized"
            assert receipt["active_election_id"] is None
            assert_public_business_fields(settled["receipt"], receipt)
            assert https_server.request_count("POST", target) == 1
            with https_server.lock:
                actual_statuses = [
                    row["status"] for row in https_server.request_timings
                    if row["method"] == "POST" and row["path"] == target
                ]
            assert actual_statuses == [201]
            recovery = client.property("recovery")
            assert recovery is not None
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            recovery_state = recovery.property("state")
            assert recovery_state["error"] == ""
            commands = recovery_state["commands"]
            assert len(commands) == 1
            command = commands[0]
            expected_payload = {
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"],
            }
            assert command["namespace"] == "election"
            assert type(command["election_id"]) is int and command["election_id"] == election_id
            assert election_id > 0 and "station_id" not in command
            assert command["request_id"] == request_id
            assert command["server_url"] == https_server.url
            assert command["actor_id"] == actor["id"]
            assert command["workflow"] == "election_completion"
            assert command["path"] == target and command["method"] == "POST"
            assert command["payload"] == expected_payload
            assert "station_id" not in command["payload"]
            assert command["confirmation_required"] is True
            assert command["status"] == "committed" and command["error"] == ""
            assert_public_business_fields(command["receipt"]["record"], receipt)
            _assert_completion_credential_free(settled)
            _assert_completion_credential_free(recovery_state)
            assert private_directory(journal_directory)
            files = list(journal_directory.rglob("*.json"))
            assert len(files) == 1
            journal_file = files[0]
            assert private_file(journal_file)
            if os.name == "posix":
                assert stat.S_IMODE(journal_directory.lstat().st_mode) == 0o700
                assert stat.S_IMODE(journal_file.lstat().st_mode) == 0o600
                assert journal_directory.lstat().st_uid == os.getuid()
                assert journal_file.lstat().st_uid == os.getuid()
            durable = json.loads(journal_file.read_text(encoding="utf-8"))
            for key in (
                "namespace", "election_id", "request_id", "server_url", "actor_id",
                "workflow", "path", "method", "payload", "status",
            ):
                assert durable[key] == command[key]
            assert "station_id" not in durable
            assert durable["receipt"]["record"] == receipt
            _assert_completion_credential_free(durable)
            durable_bytes = journal_file.read_bytes()
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            assert https_server.request_count("POST", target) == 1
            retained = recovery.property("state")["commands"]
            assert len(retained) == 1 and retained[0]["request_id"] == request_id
            assert retained[0]["status"] == "committed"
            assert_public_business_fields(retained[0]["receipt"]["record"], receipt)
            assert journal_file.read_bytes() == durable_bytes
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_lost_finalization_survives_refresh_restart_and_explicit_original_outcome_check(
    admin: TestClient,
    database_url: str,
    lost_recount_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "election-lost201-restart-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        endpoint = lost_recount_response
        endpoint.clock.value = setup["clock"].value
        actor = setup["accounts"]["supervisor"]
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        station_id = setup["stations"]["N1"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        first = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        first_destroyed = QSignalSpy(first.destroyed)
        try:
            first.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: first.property("state")["phase"] == "workspace")
            workspace = first.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (first.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = first.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert reviewed["can_finalize"] is True
            endpoint.drop_path = target
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            unknown = completion.property("state")
            assert unknown["uncertain_save"] is True
            assert unknown["receipt"] == {}
            request_id = unknown["pending_request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
            )
            query_path = outcome_path + "?workflow=election_completion"
            expected_identity = {
                "namespace": "election", "election_id": election_id,
                "request_id": request_id, "server_url": endpoint.url,
                "actor_id": actor["id"], "workflow": "election_completion",
                "path": target, "method": "POST", "confirmation_required": True,
                "payload": {
                    "request_id": request_id,
                    "expected_election_revision": reviewed["election"]["revision"],
                    "basis_digest": reviewed["basis_digest"],
                },
            }

            def assert_original_identity(row: dict) -> None:
                for key, value in expected_identity.items():
                    assert row[key] == value
                assert "station_id" not in row and "station_id" not in row["payload"]
                _assert_completion_credential_free(row)

            def assert_client_outcome_reads(expected: int) -> None:
                assert endpoint.request_count("POST", target) == 1
                assert endpoint.request_count("GET", outcome_path) == expected
                with endpoint.lock:
                    station_outcomes = [
                        path for method, path in endpoint.requests
                        if method == "GET" and path.startswith("/api/workspace/stations/")
                        and "/request-outcomes/" in path
                    ]
                assert station_outcomes == []

            # Independent public oracle; this is not a client-origin outcome request.
            persisted_response = supervisor.get(query_path)
            assert persisted_response.status_code == 200, persisted_response.text
            canonical = persisted_response.json()
            assert canonical["request_id"] == request_id
            assert canonical["workflow"] == "election_completion"
            assert canonical["status"] == "committed"
            receipt = canonical["record"]
            assert receipt["election"]["id"] == election_id
            assert receipt["election"]["status"] == "finalized"
            assert receipt["election"]["revision"] == reviewed["election"]["revision"] + 1
            assert receipt["active_election_id"] is None
            assert receipt["event"]["basis_digest"] == reviewed["basis_digest"]
            recovery = first.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            assert_original_identity(commands[0])
            assert commands[0]["status"] == "uncertain" and commands[0]["receipt"] is None
            assert private_directory(journal_directory)
            files = list(journal_directory.rglob("*.json"))
            assert len(files) == 1 and private_file(files[0])
            journal_file = files[0]
            unknown_bytes = journal_file.read_bytes()
            durable_unknown = json.loads(unknown_bytes)
            assert_original_identity(durable_unknown)
            assert durable_unknown["status"] == "uncertain"
            assert durable_unknown["receipt"] is None
            assert_client_outcome_reads(0)

            first.refresh()
            wait_for(qt_app, lambda: first.property("state")["active_election"] is None)
            wait_for_editor_idle(qt_app, workspace)
            wait_for_editor_idle(qt_app, completion)
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            refreshed = completion.property("state")
            assert refreshed["uncertain_save"] is True
            assert refreshed["pending_request_id"] == request_id
            assert refreshed["receipt"] == {}
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            retained = recovery.property("state")["commands"]
            assert len(retained) == 1
            assert_original_identity(retained[0])
            assert retained[0]["status"] == "uncertain" and retained[0]["receipt"] is None
            assert journal_file.read_bytes() == unknown_bytes
            assert_client_outcome_reads(0)
        finally:
            first.shutdown()
            first.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
        assert first_destroyed.count() == 1
        assert journal_file.read_bytes() == unknown_bytes
        assert_client_outcome_reads(0)

        fresh = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        fresh_destroyed = QSignalSpy(fresh.destroyed)
        try:
            fresh.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: fresh.property("state")["phase"] == "workspace")
            workspace = fresh.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            selected = workspace.property("state")["selected"]
            assert selected["station"]["id"] == station_id
            assert selected["election"]["id"] == election_id
            assert selected["election"]["status"] == "finalized"
            completion = fresh.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            restored = completion.property("state")
            assert restored["election_id"] == election_id
            assert restored["uncertain_save"] is True
            assert restored["pending_request_id"] == request_id
            assert restored["receipt"] == {}
            recovery = fresh.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            restored_commands = recovery.property("state")["commands"]
            assert len(restored_commands) == 1
            assert_original_identity(restored_commands[0])
            assert restored_commands[0]["status"] == "uncertain"
            assert restored_commands[0]["receipt"] is None
            assert journal_file.read_bytes() == unknown_bytes
            assert_client_outcome_reads(0)

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, completion)
            checked_commands = recovery.property("state")["commands"]
            assert len(checked_commands) == 1
            checked = checked_commands[0]
            assert_original_identity(checked)
            assert checked["status"] == "committed" and checked["error"] == ""
            assert recovery.property("state")["error"] == ""
            assert_public_business_fields(checked["receipt"]["record"], receipt)
            settled = completion.property("state")
            assert settled["uncertain_save"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert_public_business_fields(settled["receipt"], receipt)
            assert fresh.property("state")["active_election"] is None
            assert_client_outcome_reads(1)
            assert private_file(journal_file)
            durable_committed = json.loads(journal_file.read_text(encoding="utf-8"))
            assert_original_identity(durable_committed)
            assert durable_committed["status"] == "committed"
            assert durable_committed["receipt"]["record"] == receipt
            committed_bytes = journal_file.read_bytes()
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            assert_client_outcome_reads(1)
            assert journal_file.read_bytes() == committed_bytes
        finally:
            fresh.shutdown()
            fresh.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
        assert fresh_destroyed.count() == 1
        assert journal_file.read_bytes() == committed_bytes
        assert_client_outcome_reads(1)
        current = supervisor.get(setup["completion_path"])
        assert current.status_code == 200, current.text
        assert current.json()["election"] == receipt["election"]
        assert current.json()["active_election_id"] is None
        final_outcome = supervisor.get(query_path)
        assert final_outcome.status_code == 200, final_outcome.text
        assert final_outcome.json() == canonical


def test_late_original_finalization_ack_preserves_an_already_observed_active_election(
    admin: TestClient,
    database_url: str,
    completed_write_server: CompletedWriteServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "late-finalization-ack-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        # Prepare the competing draft before holding the real command's response.
        competing, planned = prepared_election(admin)
        election_id = setup["election"]["id"]
        assert competing["id"] != election_id
        station_id = setup["stations"]["N1"]["id"]
        actor = setup["accounts"]["supervisor"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        endpoint = completed_write_server
        endpoint.clock.value = setup["clock"].value
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            assert completion.property("state")["assessment"]["can_finalize"] is True
            assert endpoint.request_count("POST", target) == 0
            with endpoint.lock:
                endpoint.hold_path = target
            completion.finalize(BOX_READY_PASSWORD)
            try:
                wait_for(qt_app, endpoint.entered.is_set)
                pending = completion.property("state")
                request_id = pending["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert pending["busy"] is True and pending["uncertain_save"] is False
                assert endpoint.release.is_set() is False
                assert endpoint.request_count("POST", target) == 1
                outcome_path = (
                    f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
                    "?workflow=election_completion"
                )
                original_response = setup["clients"]["supervisor"].get(outcome_path)
                assert original_response.status_code == 200, original_response.text
                original = original_response.json()
                assert original["status"] == "committed"
                receipt = original["record"]
                assert receipt["election"]["id"] == election_id
                assert receipt["election"]["status"] == "finalized"
                assert receipt["active_election_id"] is None
                active_before = admin.get("/api/active-election")
                assert active_before.status_code == 200, active_before.text
                assert active_before.json()["election"] is None
                activated_response = admin.post(
                    f"/api/elections/{competing['id']}/activate", json={
                        "election_revision": competing["revision"],
                        "schedule_revision": planned["revision"],
                    },
                )
                assert activated_response.status_code == 200, activated_response.text
                active_election = activated_response.json()["election"]
                assert active_election["id"] == competing["id"]
                assert active_election["status"] == "active"
                # Complete an actual public refresh while the unchanged ACK waits.
                client.refresh()
                wait_for(qt_app, lambda: (
                    client.property("state")["active_election"] == active_election
                ))
                wait_for_editor_idle(qt_app, workspace)
                assert workspace.property("state")["selected"]["station"]["id"] == station_id
                still_pending = completion.property("state")
                assert still_pending["election_id"] == election_id
                assert still_pending["pending_request_id"] == request_id
                assert still_pending["busy"] is True and still_pending["uncertain_save"] is False
                assert endpoint.release.is_set() is False
            finally:
                endpoint.release.set()
            wait_for_editor_idle(qt_app, completion)
            settled = completion.property("state")
            assert settled["error"] == "" and settled["uncertain_save"] is False
            assert settled["pending_request_id"] == ""
            assert_public_business_fields(settled["receipt"], receipt)
            # Intended RED at c525: late ACK A clears this fresher observed B toNone.
            assert client.property("state")["active_election"] == active_election
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert endpoint.request_count("POST", target) == 1
            current = admin.get("/api/active-election")
            assert current.status_code == 200, current.text
            assert current.json() == activated_response.json()
            retained = setup["clients"]["supervisor"].get(outcome_path)
            assert retained.status_code == 200, retained.text
            assert retained.json() == original
            _assert_completion_credential_free(settled)
        finally:
            endpoint.release.set()
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


@dataclass
class IncompleteFinalizationReceiptBoundary(HttpsServer):
    alter_next_post_path: str = ""
    altered_response_count: int = 0
    omit_sources: bool = True
    evidence_directory: Path | None = None


def _write_incomplete_receipt_evidence(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())


@pytest.fixture
def incomplete_finalization_receipt_boundary(
    database_url: str, qt_app: QCoreApplication, tmp_path: Path,
) -> Iterator[IncompleteFinalizationReceiptBoundary]:
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare the existing local TLS fixture first"
    directory = tmp_path / "incomplete-finalization-wire"
    directory.mkdir(mode=0o700)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    endpoint = IncompleteFinalizationReceiptBoundary(
        f"https://localhost:{port}", ControlledClock(), evidence_directory=directory,
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def alter_only_actual_committed_finalization(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        with endpoint.lock:
            alter = (
                request.method == "POST" and request.url.path == endpoint.alter_next_post_path
                and response.status_code == 201
            )
            if alter:
                endpoint.alter_next_post_path = ""
            omit_sources = endpoint.omit_sources
        if not alter:
            return response
        # The actual route has committed; alter only its delivered protocol body.
        chunks = [chunk async for chunk in response.body_iterator]
        original_body = b"".join(
            chunk.encode() if isinstance(chunk, str) else chunk for chunk in chunks
        )
        payload = json.loads(original_body)
        assert payload["event"]["kind"] == "finalization"
        assert payload["event"]["outcome"]["sources"]
        assert payload["event"]["outcome"]["results"]
        if omit_sources:
            payload["event"]["outcome"]["sources"] = {}
        payload["event"]["outcome"]["results"] = [{"status": "finalized", "provisional": False}]
        headers = {
            name: value for name, value in response.headers.items()
            if name.lower() not in {"content-length", "content-type", "transfer-encoding"}
        }
        delivered = JSONResponse(
            payload, status_code=response.status_code, headers=headers,
            background=response.background,
        )
        # Capture both exact application bodies BEFORE delivering the faulty one.
        _write_incomplete_receipt_evidence(directory / "original-response201.json", original_body)
        _write_incomplete_receipt_evidence(directory / "delivered-response201.json", delivered.body)
        _write_incomplete_receipt_evidence(directory / "wire-fault-proof.json", json.dumps({
            "method": request.method, "path": request.url.path,
            "actual_handler_status": response.status_code,
            "delivered_status": delivered.status_code,
            "original_sha256": hashlib.sha256(original_body).hexdigest(),
            "delivered_sha256": hashlib.sha256(delivered.body).hexdigest(),
            "changed_fields": (["event.outcome.sources"] if omit_sources else [])
            + ["event.outcome.results"],
            "actual_handler_ran_first": True, "SQL_or_business_commit_replaced": False,
        }, indent=2).encode())
        with endpoint.lock:
            endpoint.altered_response_count += 1
        return delivered

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=port, loop="asyncio", ws="none",
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
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive(), "The owned finalization-receipt TLS server did not stop"


@pytest.mark.parametrize(
    "omit_sources", [True, False], ids=["missing_sources_and_results", "missing_results_only"],
)
def test_incomplete_finalization_receipt_stays_unknown_and_retains_actual_bad_body(
    admin: TestClient,
    database_url: str,
    incomplete_finalization_receipt_boundary: IncompleteFinalizationReceiptBoundary,
    omit_sources: bool,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "incomplete-finalization-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        endpoint = incomplete_finalization_receipt_boundary
        endpoint.clock.value = setup["clock"].value
        election_id = setup["election"]["id"]
        actor = setup["accounts"]["supervisor"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        directory = endpoint.evidence_directory
        assert isinstance(directory, Path)
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert reviewed["can_finalize"] is True
            finalized = QSignalSpy(completion.finalized)
            assert finalized.isValid()
            with endpoint.lock:
                endpoint.alter_next_post_path = target
                endpoint.omit_sources = omit_sources
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            unknown = deepcopy(completion.property("state"))
            assert endpoint.altered_response_count == 1
            assert endpoint.alter_next_post_path == ""
            original_bytes = (directory / "original-response201.json").read_bytes()
            delivered_bytes = (directory / "delivered-response201.json").read_bytes()
            original_receipt = json.loads(original_bytes)
            delivered_receipt = json.loads(delivered_bytes)
            expected_fault = deepcopy(original_receipt)
            if omit_sources:
                expected_fault["event"]["outcome"]["sources"] = {}
            expected_fault["event"]["outcome"]["results"] = [
                {"status": "finalized", "provisional": False},
            ]
            assert delivered_receipt == expected_fault
            assert len(original_receipt["event"]["outcome"]["results"]) == 2
            assert len(original_receipt["event"]["outcome"]["sources"]["polling_completion"]) == 4
            request_id = original_receipt["request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
                "?workflow=election_completion"
            )
            canonical_response = setup["clients"]["supervisor"].get(outcome_path)
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical == {
                "request_id": request_id, "workflow": "election_completion",
                "status": "committed", "record": original_receipt,
            }
            active = setup["clients"]["supervisor"].get("/api/active-election")
            assert active.status_code == 200, active.text
            assert active.json()["election"] is None
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            command = commands[0]
            files = list(journal_directory.glob("*.json"))
            assert len(files) == 1
            journal_file = files[0]
            durable_bytes = journal_file.read_bytes()
            durable = json.loads(durable_bytes)
            # Preserve the real first verdict even if this case is still RED.
            _write_incomplete_receipt_evidence(directory / "observed-verdict.json", json.dumps({
                "request_id": request_id, "actual_server_outcome": canonical["status"],
                "client_uncertain_save": unknown["uncertain_save"],
                "client_error": unknown["error"], "journal_status": durable["status"],
                "finalized_signal_count": finalized.count(),
                "post_count": endpoint.request_count("POST", target),
                "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
                "delivered_sha256": hashlib.sha256(delivered_bytes).hexdigest(),
            }, indent=2).encode())
            # Intended RED: c525 accepts the incomplete outcome as a terminal receipt.
            assert unknown["uncertain_save"] is True, {
                "error": unknown["error"], "journal_status": durable["status"],
                "finalized_signal_count": finalized.count(),
            }
            assert unknown["pending_request_id"] == request_id and unknown["receipt"] == {}
            assert unknown["error"] in {"request_failed", "invalid_response"}
            assert finalized.count() == 0
            assert command["namespace"] == "election" and command["election_id"] == election_id
            assert command["actor_id"] == actor["id"] and command["server_url"] == endpoint.url
            assert command["status"] == durable["status"] == "uncertain"
            assert command["error"] == durable["error"] == "invalid_response"
            expected_payload = {
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"],
            }
            assert command["payload"] == durable["payload"] == expected_payload
            assert "station_id" not in command and "station_id" not in durable
            assert_public_business_fields(command["receipt"]["record"], delivered_receipt)
            assert durable["receipt"]["record"] == delivered_receipt
            assert workspace.property("unresolvedRequest") is True
            _assert_completion_credential_free(durable)
            _assert_completion_credential_free(unknown)
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path.split("?", 1)[0]) == 0
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            assert completion.property("state")["uncertain_save"] is True
            assert completion.property("state")["pending_request_id"] == request_id
            assert completion.property("state")["receipt"] == {} and finalized.count() == 0
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path.split("?", 1)[0]) == 0
            assert journal_file.read_bytes() == durable_bytes
            assert (directory / "original-response201.json").read_bytes() == original_bytes
            assert (directory / "delivered-response201.json").read_bytes() == delivered_bytes
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_recovered_original_finalization_keeps_same_elections_reopened_current_assessment(
    admin: TestClient,
    database_url: str,
    lost_recount_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "recovered-finalization-reopened-current-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        endpoint = lost_recount_response
        endpoint.clock.value = setup["clock"].value
        actor = setup["accounts"]["supervisor"]
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        reopening_path = f"/api/workspace/elections/{election_id}/reopenings"
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert reviewed["can_finalize"] is True
            endpoint.drop_path = target
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            unknown = completion.property("state")
            assert unknown["uncertain_save"] is True and unknown["receipt"] == {}
            request_id = unknown["pending_request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
            )
            query_path = outcome_path + "?workflow=election_completion"
            original_response = supervisor.get(query_path)
            assert original_response.status_code == 200, original_response.text
            canonical = original_response.json()
            assert canonical["request_id"] == request_id
            assert canonical["workflow"] == "election_completion"
            assert canonical["status"] == "committed"
            receipt = canonical["record"]
            assert receipt["election"]["id"] == election_id
            assert receipt["election"]["status"] == "finalized"
            assert receipt["election"]["revision"] == reviewed["election"]["revision"] + 1
            assert receipt["active_election_id"] is None
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            original = commands[0]
            assert original["namespace"] == "election" and "station_id" not in original
            assert original["election_id"] == election_id and election_id > 0
            assert original["actor_id"] == actor["id"] and original["server_url"] == endpoint.url
            assert original["workflow"] == "election_completion"
            assert original["request_id"] == request_id
            assert original["method"] == "POST" and original["path"] == target
            assert original["status"] == "uncertain" and original["receipt"] is None
            assert original["payload"] == {
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"],
            }
            files = list(journal_directory.rglob("*.json"))
            assert len(files) == 1 and private_file(files[0])
            journal_file = files[0]
            unknown_bytes = journal_file.read_bytes()
            _assert_completion_credential_free(json.loads(unknown_bytes))
            reopened_response = supervisor.post(reopening_path, json={
                "request_id": str(uuid4()),
                "expected_election_revision": receipt["election"]["revision"],
                "previous_finalization_id": receipt["event"]["id"],
                "reason": "Continue authorized work without replacing the earlier final result.",
                "password": BOX_READY_PASSWORD,
            })
            assert reopened_response.status_code == 201, reopened_response.text
            reopened = reopened_response.json()
            assert reopened["election"]["id"] == election_id
            assert reopened["election"]["status"] == "active"
            assert reopened["election"]["revision"] == receipt["election"]["revision"] + 1
            assert reopened["active_election_id"] == election_id
            active_response = supervisor.get("/api/active-election")
            assert active_response.status_code == 200, active_response.text
            live_active = active_response.json()["election"]
            assert live_active["id"] == election_id and live_active["status"] == "active"
            assert live_active["revision"] == reopened["election"]["revision"]
            client.refresh()
            wait_for(qt_app, lambda: client.property("state")["active_election"] == live_active)
            wait_for_editor_idle(qt_app, workspace)
            wait_for_editor_idle(qt_app, completion)
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            current = completion.property("state")
            live_assessment = current["assessment"]
            assert current["uncertain_save"] is True
            assert current["pending_request_id"] == request_id and current["receipt"] == {}
            assert live_assessment["election"] == reopened["election"]
            assert live_assessment["active_election_id"] == election_id
            assert live_assessment["basis_digest"] != reviewed["basis_digest"]
            assert workspace.property("state")["selected"] == {}
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            retained = recovery.property("state")["commands"]
            assert len(retained) == 1
            identity_fields = (
                "namespace", "election_id", "request_id", "server_url", "actor_id",
                "workflow", "path", "method", "payload", "confirmation_required",
            )
            for key in identity_fields:
                assert retained[0][key] == original[key]
            assert retained[0]["status"] == "uncertain" and retained[0]["receipt"] is None
            assert journal_file.read_bytes() == unknown_bytes
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("POST", reopening_path) == 0
            assert endpoint.request_count("GET", outcome_path) == 0

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, completion)
            checked = recovery.property("state")["commands"]
            assert len(checked) == 1
            for key in identity_fields:
                assert checked[0][key] == original[key]
            assert checked[0]["status"] == "committed" and checked[0]["error"] == ""
            assert_public_business_fields(checked[0]["receipt"]["record"], receipt)
            settled = completion.property("state")
            assert settled["uncertain_save"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert_public_business_fields(settled["receipt"], receipt)
            assert client.property("state")["active_election"] == live_active
            root_election = client.property("state")["election"]
            assert {key: root_election[key] for key in reopened["election"]} == reopened["election"]
            assert {
                key: settled["election"][key] for key in reopened["election"]
            } == reopened["election"]
            assert workspace.property("state")["selected"] == {}
            # The old ACK must not replace the actual newer reopened assessment.
            assert settled["assessment"] == live_assessment
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("POST", reopening_path) == 0
            assert endpoint.request_count("GET", outcome_path) == 1
            with endpoint.lock:
                station_outcomes = [
                    path for method, path in endpoint.requests
                    if method == "GET" and path.startswith("/api/workspace/stations/")
                    and "/request-outcomes/" in path
                ]
            assert station_outcomes == []
            durable = json.loads(journal_file.read_text(encoding="utf-8"))
            for key in identity_fields:
                assert durable[key] == original[key]
            assert "station_id" not in durable
            assert durable["status"] == "committed"
            assert durable["receipt"]["record"] == receipt
            _assert_completion_credential_free(durable)
            _assert_completion_credential_free(settled)
            final_current = supervisor.get(setup["completion_path"])
            assert final_current.status_code == 200, final_current.text
            assert final_current.json()["election"] == reopened["election"]
            assert final_current.json()["active_election_id"] == election_id
            final_active = supervisor.get("/api/active-election")
            assert final_active.status_code == 200, final_active.text
            assert final_active.json() == active_response.json()
            final_original = supervisor.get(query_path)
            assert final_original.status_code == 200, final_original.text
            assert final_original.json() == canonical
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_unknown_finalization_keeps_original_election_context_when_another_election_activates(
    admin: TestClient,
    database_url: str,
    lost_recount_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "unknown-finalization-new-active-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        competing, planned = prepared_election(admin)
        election_id = setup["election"]["id"]
        assert competing["id"] != election_id
        actor = setup["accounts"]["supervisor"]
        settings_response = admin.get(f"/api/accounts/{actor['id']}")
        assert settings_response.status_code == 200, settings_response.text
        assert set(settings_response.json()["station_ids"]) == {
            row["id"] for row in setup["stations"].values()
        }
        endpoint = lost_recount_response
        endpoint.clock.value = setup["clock"].value
        target = f"/api/workspace/elections/{election_id}/finalizations"
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(endpoint.url, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert reviewed["can_finalize"] is True
            endpoint.drop_path = target
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            unknown = completion.property("state")
            assert unknown["uncertain_save"] is True and unknown["receipt"] == {}
            request_id = unknown["pending_request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
            )
            query_path = outcome_path + "?workflow=election_completion"
            original_response = setup["clients"]["supervisor"].get(query_path)
            assert original_response.status_code == 200, original_response.text
            original_outcome = original_response.json()
            assert original_outcome["request_id"] == request_id
            assert original_outcome["workflow"] == "election_completion"
            assert original_outcome["status"] == "committed"
            assert original_outcome["record"]["election"]["id"] == election_id
            assert original_outcome["record"]["election"]["status"] == "finalized"
            assert original_outcome["record"]["active_election_id"] is None
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            original = commands[0]
            assert original["namespace"] == "election" and "station_id" not in original
            assert original["election_id"] == election_id and election_id > 0
            assert original["actor_id"] == actor["id"] and original["server_url"] == endpoint.url
            assert original["workflow"] == "election_completion"
            assert original["request_id"] == request_id
            assert original["path"] == target and original["method"] == "POST"
            assert original["status"] == "uncertain" and original["receipt"] is None
            assert original["payload"] == {
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"],
            }
            files = list(journal_directory.rglob("*.json"))
            assert len(files) == 1 and private_file(files[0])
            journal_file = files[0]
            unknown_bytes = journal_file.read_bytes()
            _assert_completion_credential_free(json.loads(unknown_bytes))
            activated_response = admin.post(
                f"/api/elections/{competing['id']}/activate", json={
                    "election_revision": competing["revision"],
                    "schedule_revision": planned["revision"],
                },
            )
            assert activated_response.status_code == 200, activated_response.text
            active_b = activated_response.json()["election"]
            assert active_b["id"] == competing["id"] and active_b["status"] == "active"
            client.refresh()
            wait_for(qt_app, lambda: client.property("state")["active_election"] == active_b)
            wait_for_editor_idle(qt_app, workspace)
            wait_for_editor_idle(qt_app, completion)
            retained_state = completion.property("state")
            assert client.property("state")["active_election"] == active_b
            assert workspace.property("state")["selected"] == {}
            # Incoming B must not rebind the outstanding original election-A command.
            assert retained_state["election_id"] == election_id
            assert retained_state["pending_request_id"] == request_id
            assert retained_state["uncertain_save"] is True and retained_state["receipt"] == {}
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            refreshed = completion.property("state")
            assert refreshed["election_id"] == election_id
            assert refreshed["pending_request_id"] == request_id
            assert refreshed["uncertain_save"] is True and refreshed["receipt"] == {}
            assert refreshed["assessment"]["election"]["id"] == election_id
            assert refreshed["assessment"]["election"]["status"] == "finalized"
            assert refreshed["assessment"]["can_finalize"] is False
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            recovery_state = recovery.property("state")
            assert recovery_state["error"] == ""
            assert recovery_state["election_id"] == election_id
            retained = recovery_state["commands"]
            assert len(retained) == 1
            for key in (
                "namespace", "election_id", "request_id", "server_url", "actor_id",
                "workflow", "path", "method", "payload", "confirmation_required",
            ):
                assert retained[0][key] == original[key]
            assert "station_id" not in retained[0]
            assert retained[0]["status"] == "uncertain" and retained[0]["receipt"] is None
            assert journal_file.read_bytes() == unknown_bytes
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 0
            with endpoint.lock:
                business_writes = [
                    (method, path) for method, path in endpoint.requests
                    if method in {"POST", "PUT", "PATCH"} and not path.startswith("/api/auth/")
                ]
                outcome_reads = [
                    path for method, path in endpoint.requests
                    if method == "GET" and "/request-outcomes/" in path
                ]
            assert business_writes == [("POST", target)]
            assert outcome_reads == []
            assert client.property("state")["active_election"] == active_b
            assert workspace.property("state")["selected"] == {}
            _assert_completion_credential_free(refreshed)
            _assert_completion_credential_free(recovery_state)
            current_active = admin.get("/api/active-election")
            assert current_active.status_code == 200, current_active.text
            assert current_active.json() == activated_response.json()
            retained_outcome = setup["clients"]["supervisor"].get(query_path)
            assert retained_outcome.status_code == 200, retained_outcome.text
            assert retained_outcome.json() == original_outcome
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
        assert journal_file.read_bytes() == unknown_bytes
        assert json.loads(unknown_bytes)["status"] == "uncertain"
        assert endpoint.request_count("POST", target) == 1
        assert endpoint.request_count("GET", outcome_path) == 0


def test_large_finalized_quantities_round_trip_through_event_cache_and_public_qt(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quantity = 900719925474099312345
    quantity_text = "900719925474099312345"
    actual = 900719925474099312349
    actual_text = "900719925474099312349"
    difference = 900719925474099312339
    difference_text = "900719925474099312339"
    assert quantity > 2**64 and difference > 2**64
    journal_directory = tmp_path / "large-finalized-quantity-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(
        admin, database_url, n1_quantities=(quantity, 4), n1_selected=False,
    ) as setup:
        supervisor = setup["clients"]["supervisor"]
        n1 = setup["n1_round"]
        submitted = n1["submitted"]
        target = n1["round_path"]
        scope_id = setup["scope"]["id"]
        scope_revision = n1["options"]["scope"]["revision"]
        constituency_id = setup["constituency_id"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        assert submitted["status"] == "submitted" and submitted["revision"] == 3
        assert submitted["f1_complete"] is True and submitted["count_inputs_complete"] is True
        assert type(submitted["actual_counted_quantity"]) is int
        assert submitted["actual_counted_quantity"] == actual
        comparison = next(
            row for row in submitted["physical_comparisons"] if row["source"] == "stock"
        )
        assert comparison["expected_quantity"] == 10
        assert comparison["actual_quantity"] == actual
        assert comparison["difference_quantity"] == difference
        assert comparison["status"] == "pending"
        reason = "Signed synthetic tally confirms the exact large quantity; retain the stock gap."
        accepted_response = supervisor.post(target + "/physical-differences/stock/accept", json={
            "request_id": str(uuid4()), "expected_revision": 3,
            "scope_revision": scope_revision, "expected_decision_revision": 0,
            "reason": reason, "password": BOX_READY_PASSWORD,
        })
        assert accepted_response.status_code == 200, accepted_response.text
        accepted = accepted_response.json()
        accepted_stock = next(
            row for row in accepted["physical_comparisons"] if row["source"] == "stock"
        )
        assert accepted_stock["status"] == "accepted"
        assert accepted_stock["acceptance"]["difference_quantity"] == difference
        approved_response = supervisor.post(target + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": 3,
            "scope_revision": scope_revision, "password": BOX_READY_PASSWORD,
        })
        assert approved_response.status_code == 200, approved_response.text
        assert approved_response.json()["approval_valid"] is True
        selected_response = supervisor.post(target + "/select", json={
            "request_id": str(uuid4()), "expected_revision": 4,
            "scope_revision": scope_revision, "expected_selection_revision": 0,
            "password": BOX_READY_PASSWORD,
        })
        assert selected_response.status_code == 200, selected_response.text
        assert selected_response.json()["selected"] is True
        https_server.clock.value = setup["clock"].value
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, setup["accounts"]["supervisor"]["username"],
                          BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert reviewed["can_finalize"] is True and reviewed["blockers"] == []
            qt_before = next(
                row for row in reviewed["sources"]["constituencies"]
                if row["context"]["constituency"]["id"] == constituency_id
            )
            assert qt_before["candidate_totals"][0]["quantity"] == quantity_text
            assert qt_before["candidate_totals"][0]["quantity_display"] == quantity_text
            completion.finalize(BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, completion)
            state = completion.property("state")
            assert state["error"] == "" and state["uncertain_save"] is False
            qt_receipt = state["receipt"]
            request_id = qt_receipt["request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = base + f"/request-outcomes/{request_id}?workflow=election_completion"
            cached_response = supervisor.get(outcome_path)
            assert cached_response.status_code == 200, cached_response.text
            cached = cached_response.json()
            assert cached["status"] == "committed" and cached["request_id"] == request_id
            canonical = cached["record"]
            history_response = supervisor.get(base + "/completion/history")
            assert history_response.status_code == 200, history_response.text
            events = history_response.json()["events"]
            assert events == [canonical["event"]]
            # These are independent public reads of the MySQL cache and event rows.
            for outcome in (canonical["event"]["outcome"], events[0]["outcome"]):
                north = next(
                    row for row in outcome["results"]
                    if row["constituency"]["id"] == constituency_id
                )
                first_quantity = north["candidate_totals"][0]["quantity"]
                assert type(first_quantity) is int and first_quantity == quantity
                assert north["candidate_totals"][1]["quantity"] == 4
                chosen = next(
                    row["record"] for row in outcome["sources"]["selected_counts"]
                    if row["scope_id"] == scope_id
                )
                assert type(chosen["actual_counted_quantity"]) is int
                assert chosen["actual_counted_quantity"] == actual
                stock = next(
                    row for row in chosen["physical_comparisons"] if row["source"] == "stock"
                )
                assert type(stock["difference_quantity"]) is int
                assert stock["difference_quantity"] == difference and stock["status"] == "accepted"
                assert stock["acceptance"]["reason"] == reason
                assert stock["acceptance"]["actual_quantity"] == actual
                assert stock["acceptance"]["difference_quantity"] == difference
            qt_north = next(
                row for row in qt_receipt["event"]["outcome"]["results"]
                if row["constituency"]["id"] == constituency_id
            )
            assert qt_north["candidate_totals"][0]["quantity"] == quantity_text
            assert qt_north["candidate_totals"][0]["quantity_display"] == quantity_text
            qt_count = next(
                row["record"]
                for row in qt_receipt["event"]["outcome"]["sources"]["selected_counts"]
                if row["scope_id"] == scope_id
            )
            assert qt_count["actual_counted_quantity"] == actual_text
            assert qt_count["actual_counted_quantity_display"] == actual_text
            qt_stock = next(
                row for row in qt_count["physical_comparisons"] if row["source"] == "stock"
            )
            assert qt_stock["difference_quantity"] == difference_text
            assert qt_stock["difference_quantity_display"] == difference_text
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1 and commands[0]["status"] == "committed"
            recovered_north = next(
                row for row in commands[0]["receipt"]["record"]["event"]["outcome"]["results"]
                if row["constituency"]["id"] == constituency_id
            )
            assert recovered_north["candidate_totals"][0]["quantity_display"] == quantity_text
            files = list(journal_directory.glob("*.json"))
            assert len(files) == 1
            durable_bytes = files[0].read_bytes()
            durable = json.loads(durable_bytes)
            assert durable["receipt"]["record"] == canonical
            _assert_completion_credential_free(durable)
            assert https_server.request_count("POST", base + "/finalizations") == 1
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            assert files[0].read_bytes() == durable_bytes
            cached_again = supervisor.get(outcome_path)
            assert cached_again.status_code == 200 and cached_again.json() == cached
            assert https_server.request_count("POST", base + "/finalizations") == 1
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_predispatch_finalization_requires_checked_original_retry_with_fresh_own_password(
    admin: TestClient,
    database_url: str,
    reconnectable_recount_server: ReconnectableRecountServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "election-checked-original-retry-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        endpoint = reconnectable_recount_server
        endpoint.clock.value = setup["clock"].value
        origin = endpoint.url
        actor = setup["accounts"]["supervisor"]
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        server_before_response = supervisor.get(setup["completion_path"])
        assert server_before_response.status_code == 200, server_before_response.text
        server_before = server_before_response.json()
        assert server_before["can_finalize"] is True
        client = DesktopController(origin, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(origin, actor["username"], BOX_READY_PASSWORD)
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            wait_for(qt_app, lambda: (
                (client.property("state")["active_election"] or {}).get("id") == election_id
            ))
            assert workspace.property("state")["selected"] == {}
            completion = client.property("electionCompletion")
            completion.open()
            wait_for_editor_idle(qt_app, completion)
            reviewed = completion.property("state")["assessment"]
            assert_public_business_fields(reviewed, server_before)
            assert endpoint.request_count("POST", target) == 0
            endpoint.disconnect_proxy()
            try:
                completion.finalize(BOX_READY_PASSWORD)
                wait_for_editor_idle(qt_app, completion)
                unknown = completion.property("state")
                assert unknown["error"] == "disconnected"
                assert unknown["uncertain_save"] is True and unknown["receipt"] == {}
                request_id = unknown["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert endpoint.request_count("POST", target) == 0
            finally:
                endpoint.reconnect_proxy()
            assert endpoint.url == origin
            outcome_path = (
                f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
            )
            query_path = outcome_path + "?workflow=election_completion"
            expected_payload = {
                "request_id": request_id,
                "expected_election_revision": reviewed["election"]["revision"],
                "basis_digest": reviewed["basis_digest"],
            }
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1
            original = commands[0]
            assert original["namespace"] == "election" and "station_id" not in original
            assert original["election_id"] == election_id and election_id > 0
            assert original["request_id"] == request_id
            assert original["server_url"] == origin and original["actor_id"] == actor["id"]
            assert original["workflow"] == "election_completion"
            assert original["method"] == "POST" and original["path"] == target
            assert original["payload"] == expected_payload
            assert original["status"] == "uncertain" and original["error"] == "disconnected"
            assert original["confirmation_required"] is True and original["receipt"] is None
            identity_fields = (
                "namespace", "election_id", "request_id", "server_url", "actor_id",
                "workflow", "path", "method", "payload", "confirmation_required",
            )
            files = list(journal_directory.rglob("*.json"))
            assert len(files) == 1 and private_file(files[0])
            journal_file = files[0]
            unknown_bytes = journal_file.read_bytes()
            _assert_completion_credential_free(json.loads(unknown_bytes))
            absent_response = supervisor.get(query_path)
            assert absent_response.status_code == 200, absent_response.text
            not_found = {
                "request_id": request_id, "workflow": "election_completion", "status": "not_found",
            }
            assert absent_response.json() == not_found
            unchanged_response = supervisor.get(setup["completion_path"])
            assert unchanged_response.status_code == 200, unchanged_response.text
            assert unchanged_response.json() == server_before

            client.refresh()
            wait_for_editor_idle(qt_app, workspace)
            wait_for_editor_idle(qt_app, completion)
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            retained_state = completion.property("state")
            assert retained_state["uncertain_save"] is True
            assert retained_state["pending_request_id"] == request_id
            assert retained_state["receipt"] == {}
            assert journal_file.read_bytes() == unknown_bytes
            assert endpoint.request_count("POST", target) == 0
            assert endpoint.request_count("GET", outcome_path) == 0
            recovery.retry(request_id, BOX_READY_PASSWORD)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "recovery_retry_unavailable"
            assert completion.property("state")["pending_request_id"] == request_id
            assert endpoint.request_count("POST", target) == 0
            assert endpoint.request_count("GET", outcome_path) == 0
            assert journal_file.read_bytes() == unknown_bytes

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, completion)
            checked = recovery.property("state")["commands"]
            assert len(checked) == 1
            for key in identity_fields:
                assert checked[0][key] == original[key]
            assert checked[0]["status"] == "uncertain"
            assert checked[0]["error"] == "request_not_found" and checked[0]["receipt"] is None
            assert completion.property("state")["uncertain_save"] is True
            assert completion.property("state")["pending_request_id"] == request_id
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("POST", target) == 0
            checked_bytes = journal_file.read_bytes()
            durable_checked = json.loads(checked_bytes)
            assert durable_checked["status"] == "uncertain"
            assert durable_checked["error"] == "request_not_found"
            assert durable_checked["payload"] == expected_payload
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["error"] == "invalid_credentials"
            assert completion.property("state")["pending_request_id"] == request_id
            assert endpoint.request_count("POST", target) == 0
            assert journal_file.read_bytes() == checked_bytes

            delivered_statuses = []

            def observe_retry_status(reply: QNetworkReply) -> None:
                if reply.url().path() == target:
                    delivered_statuses.append(int(
                        reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
                    ))

            recovery.retry(request_id, BOX_READY_PASSWORD)
            # Consequential credentials get a new normal Qt manager synchronously.
            # Observe its public signal before processing events; never read body/headers.
            managers = client.findChildren(QNetworkAccessManager)
            assert managers
            for manager in managers:
                manager.finished.connect(observe_retry_status)
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, completion)
            assert delivered_statuses == [201]
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 1
            committed = recovery.property("state")["commands"]
            assert len(committed) == 1
            for key in identity_fields:
                assert committed[0][key] == original[key]
            assert committed[0]["status"] == "committed" and committed[0]["error"] == ""
            canonical_response = supervisor.get(query_path)
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical["request_id"] == request_id
            assert canonical["workflow"] == "election_completion"
            assert canonical["status"] == "committed"
            receipt = canonical["record"]
            assert receipt["request_id"] == request_id
            assert receipt["election"] == {
                **server_before["election"], "status": "finalized",
                "revision": server_before["election"]["revision"] + 1,
            }
            assert receipt["event"]["basis_digest"] == expected_payload["basis_digest"]
            assert receipt["event"]["outcome"]["sources"] == server_before["sources"]
            assert receipt["active_election_id"] is None
            settled = completion.property("state")
            assert settled["uncertain_save"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert_public_business_fields(settled["receipt"], receipt)
            assert_public_business_fields(committed[0]["receipt"]["record"], receipt)
            assert client.property("state")["active_election"] is None
            durable = json.loads(journal_file.read_text(encoding="utf-8"))
            for key in identity_fields:
                assert durable[key] == original[key]
            assert "station_id" not in durable
            assert durable["status"] == "committed"
            assert durable["receipt"]["record"] == receipt
            _assert_completion_credential_free(durable)
            _assert_completion_credential_free(settled)
            committed_bytes = journal_file.read_bytes()
            completion.refresh()
            wait_for_editor_idle(qt_app, completion)
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            assert endpoint.request_count("POST", target) == 1
            assert endpoint.request_count("GET", outcome_path) == 1
            assert journal_file.read_bytes() == committed_bytes
            with endpoint.lock:
                station_outcomes = [
                    path for method, path in endpoint.requests
                    if method == "GET" and path.startswith("/api/workspace/stations/")
                    and "/request-outcomes/" in path
                ]
                business_writes = [
                    (method, path) for method, path in endpoint.requests
                    if method in {"POST", "PUT", "PATCH"} and not path.startswith("/api/auth/")
                ]
            assert station_outcomes == []
            assert business_writes == [("POST", target)]
            final_current = supervisor.get(setup["completion_path"])
            assert final_current.status_code == 200, final_current.text
            assert final_current.json()["election"] == receipt["election"]
            assert final_current.json()["active_election_id"] is None
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
