"""Election completion changes reach public Qt lifecycle state through real HTTPS."""

import json
import os
import ssl
import stat
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.private_paths import private_directory, private_file
from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, wait_for, wait_for_editor_idle
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


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
