"""Public backup failure outcomes retain prior successful artifacts."""

import hashlib
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def configure_backup_runtime(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    directory = tmp_path / "private-backups"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setenv("ELECTION_BACKUP_DIRECTORY", str(directory))
    monkeypatch.setenv("ELECTION_MYSQL_CONTAINER", "election-system-mysql")
    monkeypatch.setenv("ELECTION_MYSQLDUMP_BINARY", "mysqldump")
    with lifecycle_test_state(database_url):
        yield


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_state(directory: Path) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, _hash(path))
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def test_unavailable_dump_client_preserves_success_and_failed_replay(
    admin: TestClient, database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backup_directory = Path(os.environ["ELECTION_BACKUP_DIRECTORY"])
    success_request = str(uuid4())
    success_response = admin.post("/api/backups", json={"request_id": success_request})
    assert success_response.status_code < 300, success_response.text
    success = success_response.json()
    assert success["status"] == "succeeded"
    assert success["error_code"] is None
    assert success["size_bytes"] > 0
    assert len(success["sha256"]) == 64
    assert stat.S_IMODE(backup_directory.stat().st_mode) == 0o700
    before = _artifact_state(backup_directory)
    assert len(before) == 2
    assert any(
        size == success["size_bytes"] and digest == success["sha256"]
        for size, digest in before.values()
    )

    missing_binary = tmp_path / "missing-client" / "mysqldump"
    monkeypatch.delenv("ELECTION_MYSQL_CONTAINER", raising=False)
    monkeypatch.setenv("ELECTION_MYSQLDUMP_BINARY", str(missing_binary))
    failed_request = str(uuid4())
    with TestClient(create_app(database_url), base_url="https://testserver") as unavailable:
        unavailable.headers["Authorization"] = admin.headers["Authorization"]
        response = unavailable.post("/api/backups", json={"request_id": failed_request})
        assert response.status_code < 300, response.text
        failed = response.json()
        assert failed["status"] == "failed"
        assert failed["error_code"] == "backup_client_unavailable"
        assert failed["sha256"] is None and failed["size_bytes"] is None
        assert failed["completed_at"] is not None
        replay = unavailable.post("/api/backups", json={"request_id": failed_request})
        assert replay.status_code < 300, replay.text
        assert replay.json() == failed
        listing = unavailable.get("/api/backups")
        assert listing.status_code == 200, listing.text
        rows = listing.json()["backups"]
        assert sum(row["id"] == success["id"] for row in rows) == 1
        assert sum(row["id"] == failed["id"] for row in rows) == 1
        assert next(row for row in rows if row["id"] == success["id"]) == success
        assert next(row for row in rows if row["id"] == failed["id"]) == failed
        public_json = json.dumps({"failed": failed, "listing": listing.json()})
        assert str(backup_directory) not in public_json
        assert str(missing_binary) not in public_json
        assert "database_url" not in public_json.lower()
        assert "password" not in public_json.lower()
        assert database_url not in public_json, (
            "public backup data exposed the configured database URL"
        )
        password = make_url(database_url).password
        assert not password or password not in public_json, (
            "public backup data exposed a database password"
        )
        current = unavailable.get("/api/auth/me")
        assert current.status_code == 200, current.text
        audit = unavailable.get(f"/api/accounts/{current.json()['id']}/audit")
        assert audit.status_code == 200, audit.text
        events = [
            event
            for event in audit.json()["items"]
            if event["details"].get("request_id") in {success_request, failed_request}
        ]
        success_events = [
            event for event in events if event["details"].get("request_id") == success_request
        ]
        failed_events = [
            event for event in events if event["details"].get("request_id") == failed_request
        ]
        assert [event["action"] for event in success_events].count("backup_requested") == 1
        assert [event["action"] for event in success_events].count("backup_completed") == 1
        assert [event["action"] for event in failed_events].count("backup_requested") == 1
        assert [event["action"] for event in failed_events].count("backup_failed") == 1
        assert all(str(missing_binary) not in json.dumps(event) for event in events)

    assert _artifact_state(backup_directory) == before
