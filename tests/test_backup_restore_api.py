"""Ticket 26 public restore acceptance seam; restore execution is owned by root."""

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
from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)

TARGET_SCHEMA = "election_t19_comparisons_test"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


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
    """Configure the source API to keep its dump and manifest in private tmp storage."""


@pytest.fixture
def restore_database_url(database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    source_url = make_url(os.environ["ELECTION_DATABASE_URL"])
    configured = (
        os.environ.get("ELECTION_RESTORE_DATABASE_URL")
        or os.environ.get("ELECTION_TEST_DATABASE_URL")
        or dotenv_values(".env").get("ELECTION_TEST_DATABASE_URL")
    )
    if not configured:
        configured = source_url.set(database=TARGET_SCHEMA).render_as_string(hide_password=False)
    target_url = make_url(str(configured))
    assert source_url.database == "election_t19_comparisons_lifecycle_test"
    assert target_url.database == TARGET_SCHEMA
    assert target_url.database != source_url.database
    assert database_url == os.environ["ELECTION_DATABASE_URL"]
    monkeypatch.setenv("ELECTION_DATABASE_URL", str(configured))
    alembic_command.upgrade(Config("alembic.ini"), "head")
    monkeypatch.setenv("ELECTION_DATABASE_URL", database_url)
    monkeypatch.setenv("ELECTION_RESTORE_DATABASE_URL", str(configured))
    return str(configured)


def _public_elections_hash(client: TestClient) -> tuple[str, list[dict]]:
    response = client.get("/api/elections")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    encoded = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), items


def test_backup_manifest_restores_public_count_state_and_known_request_once(
    admin: TestClient,
    database_url: str,
    backup_directory: Path,
    restore_database_url: str,
) -> None:
    source_url = os.environ["ELECTION_DATABASE_URL"]
    source_parsed = make_url(source_url)
    restore_parsed = make_url(restore_database_url)
    assert source_parsed.database == "election_t19_comparisons_lifecycle_test"
    assert restore_parsed.database == TARGET_SCHEMA
    assert source_parsed.database != restore_parsed.database

    target_sentinel_name = "restore-target-sentinel-" + uuid4().hex
    target_admin_name = "restore-target-admin-" + uuid4().hex[:12]
    target_admin_password = "Target-Initial-Only-42!"
    bootstrap_account(
        restore_database_url,
        target_admin_name,
        "Disposable restore target administrator",
        target_admin_password,
    )

    with TestClient(
        create_app(restore_database_url), base_url="https://testserver"
    ) as target_admin:
        login = target_admin.post(
            "/api/auth/login",
            json={"username": target_admin_name, "password": target_admin_password},
        )
        assert login.status_code == 200, login.text
        target_admin.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = target_admin.post(
            "/api/auth/password",
            json={
                "current_password": target_admin_password,
                "new_password": "Target-Ready-Only-84!",
            },
        )
        assert changed.status_code == 200, changed.text
        target_admin.headers["Authorization"] = "Bearer " + changed.json()["token"]
        sentinel = target_admin.post(
            "/api/elections",
            json={"request_id": str(uuid4()), "name": target_sentinel_name},
        )
        assert sentinel.status_code == 201, sentinel.text
        target_before_hash, target_before_items = _public_elections_hash(target_admin)
        assert any(row["id"] == sentinel.json()["id"] for row in target_before_items)

        with tally_setup(admin, database_url) as setup:
            counter, rounds_path = setup["counter"], setup["rounds_path"]
            options = counter.get(rounds_path).json()
            f1_request_id = str(uuid4())
            f1_command = complete_f1_command(
                options,
                actual_counted_quantity=5,
                request_id=f1_request_id,
            )
            f1_command["candidate_votes"][0]["quantity"] = 5
            f1_saved = counter.post(rounds_path, json=f1_command)
            assert f1_saved.status_code == 201, f1_saved.text
            round_target = rounds_path + f"/{f1_saved.json()['id']}"
            f2 = counter.put(round_target + "/f2", json=complete_f2_command(options))
            assert f2.status_code == 200, f2.text
            submitted = counter.post(
                round_target + "/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": f2.json()["revision"],
                    "scope_revision": options["scope"]["revision"],
                },
            )
            assert submitted.status_code == 200, submitted.text
            approved = setup["clients"]["supervisor"].post(
                round_target + "/approve",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": submitted.json()["revision"],
                    "scope_revision": options["scope"]["revision"],
                    "password": READY_PASSWORD,
                },
            )
            assert approved.status_code == 200, approved.text
            selected = setup["clients"]["supervisor"].post(
                round_target + "/select",
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

            restore_admin_password = "Restore-Source-Admin-42!"
            source_reader = admin.post(
                "/api/accounts",
                json={
                    "username": "restore-source-admin-" + uuid4().hex[:12],
                    "display_name": "Restore verification administrator",
                    "role": "administrator",
                    "enabled": True,
                    "station_ids": [],
                    "temporary_password": restore_admin_password,
                },
            )
            assert source_reader.status_code == 201, source_reader.text
            source_reader_account = source_reader.json()

            backup_request = {"request_id": str(uuid4())}
            requested = admin.post("/api/backups", json=backup_request)
            assert requested.status_code in (200, 201, 202), requested.text
            job = requested.json()
            deadline = time.monotonic() + 10
            while job["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
                listed = admin.get("/api/backups")
                assert listed.status_code == 200, listed.text
                job = next(row for row in listed.json()["backups"] if row["id"] == job["id"])
            assert job["status"] == "succeeded", job
            assert job["completed_at"] is not None and job["error_code"] is None
            assert job["sha256"] and len(job["sha256"]) == 64
            manifest_path = backup_directory / f"{job['id']}.manifest.json"
            artifact_path = backup_directory / f"{job['id']}.sql"
            assert manifest_path.is_file() and artifact_path.is_file()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            assert manifest["backup_id"] == job["id"]
            assert manifest["sha256"] == job["sha256"] == artifact_hash
            assert manifest["size_bytes"] == job["size_bytes"] == artifact_path.stat().st_size
            assert stat.S_IMODE(backup_directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600

            scope = setup["scope"]
            scope_path = f"{setup['paths']['n1_counting_scopes']}/{scope['id']}"
            successor = setup["clients"]["bothcounting"].put(
                scope_path,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "reference": scope["reference"],
                    "event_at": scope["event_at"],
                    "box_revisions": [
                        {"box_id": row["id"], "revision": row["revision"]}
                        for row in scope["box_basis"]
                    ],
                    "accounting_revisions": [
                        {"station_id": row["station_id"], "revision": row["revision"]}
                        for row in scope["accounting_basis"]
                    ],
                    "notes": "Source scope changed after the captured backup cutoff.",
                    "amendment_reason": "Record a post-backup successor for restore comparison.",
                },
            )
            assert successor.status_code == 200, successor.text
            assert successor.json()["revision"] == 2
            after_cutoff = setup["clients"]["bothcounting"].post(
                scope_path + "/submit",
                json={"request_id": str(uuid4()), "expected_revision": 2},
            )
            assert after_cutoff.status_code == 200, after_cutoff.text
            assert after_cutoff.json()["count_ready"] is True

            manifest_path_text = str(manifest_path)
            artifact_path_text = str(artifact_path)
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
                manifest_path_text,
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
            completed = subprocess.run(
                command,
                cwd=Path(__file__).resolve().parents[1],
                env=child_env,
                capture_output=True,
                text=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            for secret in (
                source_url,
                restore_database_url,
                source_parsed.password or "",
                restore_parsed.password or "",
                restore_admin_password,
                target_admin_password,
            ):
                if secret:
                    assert secret not in output
            if completed.returncode != 0:
                target_after_hash, target_after_items = _public_elections_hash(target_admin)
                assert target_after_hash == target_before_hash
                assert any(row["id"] == sentinel.json()["id"] for row in target_after_items)
                assert "No module named" in completed.stderr
                assert "election.server.backup_restore" in completed.stderr
            assert completed.returncode == 0, (
                f"restore CLI exit={completed.returncode}; manifest={manifest_path_text}; "
                f"artifact={artifact_path_text}; source_sha256={job['sha256']}; "
                f"target_before_sha256={target_before_hash}; "
                f"target_after_sha256={target_after_hash if completed.returncode else 'pending'}"
            )

            result = json.loads(completed.stdout)
            assert result == {
                "status": "succeeded",
                "source_schema": source_parsed.database,
                "target_schema": TARGET_SCHEMA,
                "backup_id": job["id"],
                "sha256": job["sha256"],
            }

            expired_session = target_admin.get("/api/auth/me")
            assert expired_session.status_code == 401, expired_session.text

            with TestClient(
                create_app(restore_database_url), base_url="https://testserver"
            ) as restored_admin:
                admin_login = restored_admin.post(
                    "/api/auth/login",
                    json={
                        "username": source_reader_account["username"],
                        "password": restore_admin_password,
                    },
                )
                assert admin_login.status_code == 200, admin_login.text
                changed = restored_admin.post(
                    "/api/auth/password",
                    json={
                        "current_password": restore_admin_password,
                        "new_password": "Restore-Source-Ready-84!",
                    },
                )
                assert changed.status_code == 200, changed.text
                restored_admin.headers["Authorization"] = "Bearer " + changed.json()["token"]
                sentinel_list = restored_admin.get("/api/elections")
                assert sentinel_list.status_code == 200, sentinel_list.text
                assert all(
                    row["id"] != sentinel.json()["id"] for row in sentinel_list.json()["items"]
                )
                assignment = restored_admin.get(
                    f"/api/accounts/{setup['accounts']['receiveronly']['id']}"
                )
                assert assignment.status_code == 200, assignment.text
                assert setup["stations"]["N1"]["id"] in assignment.json()["station_ids"]
                audit = restored_admin.get(
                    f"/api/accounts/{setup['accounts']['receiveronly']['id']}/audit"
                )
                assert audit.status_code == 200, audit.text
                assert {row["action"] for row in audit.json()["items"]} >= {
                    "f1_draft_saved",
                    "count_round_submitted",
                    "count_round_approved",
                    "count_round_selected",
                }

                with TestClient(
                    create_app(restore_database_url), base_url="https://testserver"
                ) as restored_counter:
                    counter_login = restored_counter.post(
                        "/api/auth/login",
                        json={
                            "username": setup["accounts"]["receiveronly"]["username"],
                            "password": READY_PASSWORD,
                        },
                    )
                    assert counter_login.status_code == 200, counter_login.text
                    restored_counter.headers["Authorization"] = (
                        "Bearer " + counter_login.json()["token"]
                    )
                    station_id = setup["stations"]["N1"]["id"]
                    stock = restored_counter.get(f"/api/workspace/stations/{station_id}/stock")
                    assert stock.status_code == 200, stock.text
                    assert any(
                        row["id"] == setup["accounting"]["N1"]["receipt"]["id"]
                        for row in stock.json()["items"]
                    )
                    boxes = restored_counter.get(
                        f"/api/workspace/stations/{station_id}/boxes"
                    )
                    assert boxes.status_code == 200, boxes.text
                    box_ids = {row["id"] for row in boxes.json()["items"]}
                    assert setup["boxes"]["local_n1"]["id"] in box_ids
                    assert setup["boxes"]["transferred_n2"]["id"] in box_ids
                    accounting = restored_counter.get(
                        f"/api/workspace/stations/{station_id}/accounting"
                    )
                    assert accounting.status_code == 200, accounting.text
                    assert accounting.json()["record"]["revision"] == 1
                    assert accounting.json()["record"]["approval_valid"] is True
                    report_path = (
                        f"{setup['paths']['n1_counting_scopes']}/{setup['scope']['id']}"
                        "/revisions/1/statement"
                    )
                    report = restored_counter.get(report_path, params={"locale": "en"})
                    assert report.status_code == 200, report.text
                    assert report.json()["record"]["count_ready"] is True
                    assert (
                        report.json()["record"]["accounting_basis"]
                        == setup["scope"]["accounting_basis"]
                    )

                    replay = restored_counter.post(rounds_path, json=f1_command)
                    assert replay.status_code == 200, replay.text
                    assert replay.json() == f1_saved.json()
                    rounds = restored_counter.get(rounds_path)
                    assert rounds.status_code == 200, rounds.text
                    assert len(rounds.json()["rounds"]) == 1
                    assert rounds.json()["rounds"][0]["id"] == f1_saved.json()["id"]
                    current_round = restored_counter.get(round_target)
                    assert current_round.status_code == 200, current_round.text
                    assert [
                        row["revision"] for row in current_round.json()["history"]
                    ] == [4, 3, 2, 1]
