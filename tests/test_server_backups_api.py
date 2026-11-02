"""Administrator backup requests expose safe outcome metadata through public HTTP."""

import hashlib
import json
import stat
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.backup_support import mysql_test_container
from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def backup_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "server-backups"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setenv("ELECTION_BACKUP_DIRECTORY", str(directory))
    monkeypatch.setenv("ELECTION_MYSQL_CONTAINER", mysql_test_container())
    return directory


@pytest.fixture(autouse=True)
def configure_private_backup_runtime(backup_directory: Path) -> None:
    """Set private per-test backup configuration before authenticated app fixtures start."""


def _parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def test_admin_backup_returns_safe_real_artifact_metadata_and_replays_same_job(
    admin: TestClient,
    database_url: str,
    backup_directory: Path,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter = setup["counter"]
        rounds_path = setup["rounds_path"]
        options = counter.get(rounds_path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        saved = counter.post(rounds_path, json=f1)
        assert saved.status_code == 201, saved.text
        round_path = rounds_path + f"/{saved.json()['id']}"
        f2 = counter.put(round_path + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        submitted = counter.post(
            round_path + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": f2.json()["revision"],
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        supervisor = setup["clients"]["supervisor"]
        approved = supervisor.post(
            round_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        selected = supervisor.post(
            round_path + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": approved.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["selected"] is True

        request_id = str(uuid4())
        command = {"request_id": request_id}
        response = admin.post("/api/backups", json=command)
        assert response.status_code in (200, 201, 202), response.text
        job = response.json()
        assert set(job) == {
            "id", "request_id", "status", "requested_at", "completed_at", "cutoff_start",
            "cutoff_end", "sha256", "size_bytes", "error_code",
        }
        assert job["request_id"] == request_id
        deadline = time.monotonic() + 10
        while job["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            listed = admin.get("/api/backups")
            assert listed.status_code == 200, listed.text
            job = next(item for item in listed.json()["backups"] if item["id"] == job["id"])
        assert job["status"] == "succeeded"
        assert job["completed_at"] is not None and job["error_code"] is None
        assert _parse_time(job["cutoff_start"]) <= _parse_time(job["cutoff_end"])
        assert len(job["sha256"]) == 64 and all(ch in "0123456789abcdef" for ch in job["sha256"])
        assert job["size_bytes"] > 0
        assert str(backup_directory) not in json.dumps(job)
        assert "password" not in json.dumps(job).lower()
        assert "database_url" not in json.dumps(job).lower()
        assert "artifact_path" not in job and "path" not in job

        artifacts = [path for path in backup_directory.rglob("*") if path.is_file()]
        matched = [
            path for path in artifacts
            if hashlib.sha256(path.read_bytes()).hexdigest() == job["sha256"]
        ]
        assert len(matched) == 1
        artifact = matched[0]
        assert artifact.stat().st_size == job["size_bytes"]
        assert stat.S_IMODE(backup_directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600

        replay = admin.post("/api/backups", json=command)
        assert replay.status_code < 300, replay.text
        assert replay.json() == job
        listing = admin.get("/api/backups")
        assert listing.status_code == 200, listing.text
        assert [item["id"] for item in listing.json()["backups"]].count(job["id"]) == 1
        assert sum(
            1 for path in backup_directory.rglob("*")
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == job["sha256"]
        ) == 1

        non_admin = counter.post("/api/backups", json={"request_id": str(uuid4())})
        assert non_admin.status_code == 403, non_admin.text
        current = admin.get("/api/auth/me")
        assert current.status_code == 200, current.text
        audit = admin.get(f"/api/accounts/{current.json()['id']}/audit")
        assert audit.status_code == 200, audit.text
        events = [
            event for event in audit.json()["items"]
            if event["details"].get("request_id") == request_id
        ]
        assert {event["action"] for event in events} >= {
            "backup_requested", "backup_completed"
        }
        assert all(
            READY_PASSWORD not in json.dumps(event)
            for event in events
        )
