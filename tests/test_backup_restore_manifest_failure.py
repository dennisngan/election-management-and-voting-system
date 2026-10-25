"""A final restore-manifest write failure must not misreport recovered data."""

import hashlib
import json
import os
import stat
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from election.manage import bootstrap_account
from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state

TARGET_SCHEMA = "election_t19_comparisons_test"
RESTORE_START_READINESS_SECONDS = 30


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_source_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def restore_database_url(database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    source_url = make_url(os.environ["ELECTION_DATABASE_URL"])
    target = (
        os.environ.get("ELECTION_RESTORE_DATABASE_URL")
        or os.environ.get("ELECTION_TEST_DATABASE_URL")
        or dotenv_values(".env").get("ELECTION_TEST_DATABASE_URL")
    )
    if not target:
        target = source_url.set(database=TARGET_SCHEMA).render_as_string(hide_password=False)
    target_url = make_url(str(target))
    assert source_url.database == "election_t19_comparisons_lifecycle_test"
    assert target_url.database == TARGET_SCHEMA
    assert target_url.database != source_url.database
    assert database_url == os.environ["ELECTION_DATABASE_URL"]
    monkeypatch.setenv("ELECTION_DATABASE_URL", str(target))
    alembic_command.upgrade(Config("alembic.ini"), "head")
    monkeypatch.setenv("ELECTION_DATABASE_URL", database_url)
    monkeypatch.setenv("ELECTION_RESTORE_DATABASE_URL", str(target))
    return str(target)


@pytest.fixture
def backup_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "server-backups"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setenv("ELECTION_BACKUP_DIRECTORY", str(directory))
    monkeypatch.setenv("ELECTION_MYSQL_CONTAINER", "election-system-mysql")
    return directory


@pytest.fixture(autouse=True)
def configure_private_backup_runtime(backup_directory: Path) -> None:
    """Keep source dump/manifest files private and outside the repository."""


def _elections_hash(client: TestClient) -> tuple[str, list[dict]]:
    response = client.get("/api/elections")
    assert response.status_code == 200, response.text
    elections = response.json()["items"]
    encoded = json.dumps(elections, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), elections


def test_restore_survives_final_manifest_failure_after_target_import(
    admin: TestClient,
    database_url: str,
    restore_database_url: str,
    backup_directory: Path,
) -> None:
    source_url = os.environ["ELECTION_DATABASE_URL"]
    source_parsed = make_url(source_url)
    target_parsed = make_url(restore_database_url)
    source_schema = source_parsed.database
    assert source_schema == "election_t19_comparisons_lifecycle_test"
    assert target_parsed.database == TARGET_SCHEMA and target_parsed.database != source_schema

    source_election_name = "backup-source-" + uuid4().hex
    source_election = admin.post(
        "/api/elections",
        json={"request_id": str(uuid4()), "name": source_election_name},
    )
    assert source_election.status_code == 201, source_election.text
    source_admin_password = "Restore-Source-Initial-42!"
    source_admin = admin.post(
        "/api/accounts",
        json={
            "username": "restore-source-" + uuid4().hex[:12],
            "display_name": "Recoverable source administrator",
            "role": "administrator",
            "enabled": True,
            "station_ids": [],
            "temporary_password": source_admin_password,
        },
    )
    assert source_admin.status_code == 201, source_admin.text
    source_account = source_admin.json()
    source_ready_password = "Restore-Source-Ready-84!"
    with TestClient(create_app(database_url), base_url="https://testserver") as source_auth:
        login = source_auth.post(
            "/api/auth/login",
            json={"username": source_account["username"], "password": source_admin_password},
        )
        assert login.status_code == 200, login.text
        source_auth.headers["Authorization"] = "Bearer " + login.json()["token"]
        password_change = source_auth.post(
            "/api/auth/password",
            json={
                "current_password": source_admin_password,
                "new_password": source_ready_password,
            },
        )
        assert password_change.status_code == 200, password_change.text
        copied_session_token = password_change.json()["token"]

    target_admin_name = "restore-target-" + uuid4().hex[:12]
    target_admin_password = "Restore-Target-Initial-42!"
    bootstrap_account(
        restore_database_url,
        target_admin_name,
        "Disposable target administrator",
        target_admin_password,
    )
    target_sentinel_name = "restore-target-sentinel-" + uuid4().hex
    with TestClient(
        create_app(restore_database_url), base_url="https://testserver"
    ) as target_admin:
        target_login = target_admin.post(
            "/api/auth/login",
            json={"username": target_admin_name, "password": target_admin_password},
        )
        assert target_login.status_code == 200, target_login.text
        target_admin.headers["Authorization"] = "Bearer " + target_login.json()["token"]
        target_password_change = target_admin.post(
            "/api/auth/password",
            json={
                "current_password": target_admin_password,
                "new_password": "Restore-Target-Ready-84!",
            },
        )
        assert target_password_change.status_code == 200, target_password_change.text
        target_admin.headers["Authorization"] = "Bearer " + target_password_change.json()["token"]
        sentinel = target_admin.post(
            "/api/elections",
            json={"request_id": str(uuid4()), "name": target_sentinel_name},
        )
        assert sentinel.status_code == 201, sentinel.text
        target_before_sha, target_before_elections = _elections_hash(target_admin)
        assert len(target_before_sha) == 64
        assert any(row["id"] == sentinel.json()["id"] for row in target_before_elections)

        backup_response = admin.post("/api/backups", json={"request_id": str(uuid4())})
        assert backup_response.status_code in (200, 201, 202), backup_response.text
        backup = backup_response.json()
        deadline = time.monotonic() + 10
        while backup["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            listed = admin.get("/api/backups")
            assert listed.status_code == 200, listed.text
            backup = next(row for row in listed.json()["backups"] if row["id"] == backup["id"])
        assert backup["status"] == "succeeded", backup
        manifest_path = backup_directory / f"{backup['id']}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "complete"
        assert manifest["sha256"] == backup["sha256"]

        runtime_dir = backup_directory / "restore-jobs"
        command = [
            "uv",
            "run",
            "--locked",
            "--all-groups",
            "--no-sync",
            "python",
            "-m",
            "election.server.backup_restore",
            "--manifest",
            str(manifest_path),
            "--target-schema",
            TARGET_SCHEMA,
            "--mysql-container",
            "election-system-mysql",
        ]
        child_env = os.environ.copy()
        child_env["ELECTION_DATABASE_URL"] = source_url
        child_env["ELECTION_RESTORE_DATABASE_URL"] = restore_database_url
        child_env["ELECTION_MYSQL_CONTAINER"] = "election-system-mysql"
        source_path = str(Path(__file__).resolve().parents[1] / "src")
        child_env["PYTHONPATH"] = os.pathsep.join(
            part for part in (source_path, child_env.get("PYTHONPATH", "")) if part
        )
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started_path: Path | None = None
        prior_path: Path | None = None
        restricted = False
        try:
            deadline = time.monotonic() + RESTORE_START_READINESS_SECONDS
            while time.monotonic() < deadline and process.poll() is None:
                candidates = (
                    list(runtime_dir.glob("*.started.json")) if runtime_dir.exists() else []
                )
                if candidates:
                    started_path = candidates[0]
                    started = json.loads(started_path.read_text(encoding="utf-8"))
                    prior_path = runtime_dir / started["prior_target_artifact"]
                    assert prior_path.is_file(), f"prior target archive missing: {prior_path}"
                    prior_hash = hashlib.sha256(prior_path.read_bytes()).hexdigest()
                    assert prior_hash == started["prior_target_sha256"]
                    assert stat.S_IMODE(prior_path.stat().st_mode) == 0o600
                    assert stat.S_IMODE(runtime_dir.stat().st_mode) == 0o700
                    runtime_dir.chmod(0o500)
                    restricted = True
                    break
                time.sleep(0.01)
            if started_path is None:
                if process.poll() is None:
                    process.terminate()
                stdout, stderr = process.communicate()
                pytest.fail(
                    "restore start record was not observed before the bounded readiness cap; "
                    f"exit={process.returncode}, manifest={manifest_path}"
                )
            stdout, stderr = process.communicate()
        finally:
            if process.poll() is None:
                process.communicate()
            if restricted and runtime_dir.exists():
                runtime_dir.chmod(0o700)

        combined_output = stdout + stderr
        for secret in (
            source_url,
            restore_database_url,
            source_parsed.password,
            target_parsed.password,
            source_admin_password,
            source_ready_password,
            target_admin_password,
            "Restore-Target-Ready-84!",
        ):
            if secret:
                assert secret not in combined_output
        assert process.returncode == 0, (
            f"Restore CLI exit={process.returncode}; stdout={stdout}; stderr={stderr}"
        )
        result = json.loads(stdout)
        assert result == {
            "status": "succeeded",
            "source_schema": source_schema,
            "target_schema": TARGET_SCHEMA,
            "backup_id": backup["id"],
            "sha256": backup["sha256"],
        }
        assert "restore_result_manifest_unavailable" in stderr

        expired_target_session = target_admin.get("/api/auth/me")
        assert expired_target_session.status_code == 401, expired_target_session.text
        with TestClient(
            create_app(restore_database_url), base_url="https://testserver"
        ) as stale_session:
            stale_session.headers["Authorization"] = "Bearer " + copied_session_token
            expired_source_session = stale_session.get("/api/auth/me")
            assert expired_source_session.status_code == 401, expired_source_session.text

        with TestClient(
            create_app(restore_database_url), base_url="https://testserver"
        ) as fresh_admin:
            fresh_login = fresh_admin.post(
                "/api/auth/login",
                json={
                    "username": source_account["username"],
                    "password": source_ready_password,
                },
            )
            assert fresh_login.status_code == 200, fresh_login.text
            fresh_admin.headers["Authorization"] = "Bearer " + fresh_login.json()["token"]
            elections = fresh_admin.get("/api/elections")
            assert elections.status_code == 200, elections.text
            election_names = {row["name"] for row in elections.json()["items"]}
            assert source_election_name in election_names
            assert target_sentinel_name not in election_names
