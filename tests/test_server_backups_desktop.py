"""Administrator backup metadata and uncertain-save recovery through public Qt."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from sqlalchemy.engine import make_url

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state

pytest_plugins = ("tests.test_counting_workflow_retry_desktop",)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def configure_private_backup_runtime(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    directory = tmp_path / "private-server-backups"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setenv("ELECTION_BACKUP_DIRECTORY", str(directory))
    monkeypatch.setenv("ELECTION_MYSQL_CONTAINER", "election-system-mysql")
    monkeypatch.setenv("ELECTION_MYSQLDUMP_BINARY", "mysqldump")
    with lifecycle_test_state(database_url):
        yield directory


def _admin_credentials(admin: TestClient) -> dict[str, str]:
    response = admin.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return {"username": response.json()["username"], "password": "Configuration-Ready-84!"}


def _controller_job(controller: object, request_id: str) -> dict:
    state = controller.state  # type: ignore[attr-defined]
    return next(
        (job for job in state["jobs"] if job.get("request_id") == request_id),
        {},
    )


def test_admin_backup_exposes_safe_metadata_and_blocks_polling_officer(
    admin: TestClient,
    database_url: str,
    https_server,
    desktop: DesktopController,
    qt_app: QCoreApplication,
    configure_private_backup_runtime: Path,
) -> None:
    account = _admin_credentials(admin)
    desktop.signIn(https_server.url, account["username"], account["password"])
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    wait_for_editor_idle(qt_app, desktop.property("serverBackups"))
    backups = desktop.property("serverBackups")
    assert backups.open() is True
    wait_for_editor_idle(qt_app, backups)

    backups.requestBackup()
    request_id = backups.state["pending_request_id"]
    assert request_id
    wait_for(
        qt_app,
        lambda: _controller_job(backups, request_id).get("status") in ("succeeded", "failed"),
    )
    job = _controller_job(backups, request_id)
    assert job["status"] == "succeeded"
    assert job["size_bytes"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", job["sha256"])
    serialized = json.dumps(backups.state["jobs"])
    assert "password" not in serialized.lower()
    assert "database_url" not in serialized.lower()
    assert str(configure_private_backup_runtime) not in serialized
    assert database_url not in serialized, "backup metadata exposed the configured database URL"
    password = make_url(database_url).password
    assert not password or password not in serialized, "backup metadata exposed a database password"
    assert "path" not in job and "artifact_path" not in job

    account_response = admin.post(
        "/api/accounts",
        json={
            "username": "backup_reader_" + uuid4().hex[:12],
            "display_name": "Backup permission check",
            "role": "polling_officer",
            "temporary_password": "Backup-Initial-42!",
            "station_ids": [],
        },
    )
    assert account_response.status_code == 201, account_response.text
    reader = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        reader.signIn(https_server.url, account_response.json()["username"], "Backup-Initial-42!")
        wait_for(qt_app, lambda: state_of(reader)["phase"] == "password_change")
        reader.changePassword("Backup-Initial-42!", READY_PASSWORD, READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(reader)["phase"] == "workspace")
        reader_backups = reader.property("serverBackups")
        start = len(https_server.requests)
        assert reader_backups.open() is False
        assert reader_backups.state["error"] == "administrator_required"
        with https_server.lock:
            requests = https_server.requests[start:]
        assert ("POST", "/api/backups") not in requests
        assert ("GET", "/api/backups") not in requests
    finally:
        reader.shutdown()
        reader.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_committed_backup_with_lost_tls_response_recovers_by_explicit_read(
    admin: TestClient,
    database_url: str,
    lost_selection_response,
    qt_app: QCoreApplication,
    configure_private_backup_runtime: Path,
) -> None:
    endpoint = lost_selection_response
    account = _admin_credentials(admin)
    desktop = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        desktop.signIn(endpoint.url, account["username"], account["password"])
        wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
        backups = desktop.property("serverBackups")
        backups.open()
        wait_for_editor_idle(qt_app, backups)
        start_gets = endpoint.request_count("GET", "/api/backups")
        endpoint.drop_path = "/api/backups"
        backups.requestBackup()
        wait_for(qt_app, lambda: backups.state["uncertain_save"])
        request_id = backups.state["pending_request_id"]
        assert request_id
        assert backups.state["error"] == "disconnected"
        assert endpoint.request_count("POST", "/api/backups") == 1
        wait_for(
            qt_app,
            lambda: endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set(),
        )
        committed = next(
            row
            for row in admin.get("/api/backups").json()["backups"]
            if row["request_id"] == request_id
        )
        assert committed["status"] == "succeeded"

        backups.checkPendingOutcome()
        wait_for(
            qt_app,
            lambda: (
                _controller_job(backups, request_id).get("status") == "succeeded"
                and not backups.state["uncertain_save"]
            ),
        )
        assert endpoint.request_count("POST", "/api/backups") == 1
        assert endpoint.request_count("GET", "/api/backups") > start_gets
        assert backups.state["pending_request_id"] in (None, "")
        assert _controller_job(backups, request_id) == committed
    finally:
        desktop.shutdown()
        desktop.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
