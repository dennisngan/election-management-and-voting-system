"""Opt-in public deployment journey using NEW Docker resources, real HTTPS and MySQL."""

import json
import os
import socket
import ssl
import subprocess
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.desktop_support import state_of, wait_for
from tests.stock_support import (
    INITIAL_PASSWORD,
    READY_PASSWORD,
    staff_account,
    stock_payload,
    stock_stations,
)

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("ELECTION_RUN_DOCKER_TESTS") != "1",
    reason="Opt in to new isolated Docker resources with ELECTION_RUN_DOCKER_TESTS=1",
)


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_for_public_health(client):
    for _ in range(100):
        try:
            if client.get("/api/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    pytest.fail("Public HTTPS endpoint did not become ready")


@pytest.fixture
def docker_deployment():
    project = "election-acceptance-" + uuid4().hex[:10]
    directory = ROOT / ".runtime" / project
    directory.mkdir(mode=0o700, parents=True)
    port = free_port()
    environment = {
        **os.environ,
        "ELECTION_DEPLOY_PROJECT": project,
        "ELECTION_DEPLOY_ROOT": str(directory),
        "ELECTION_DEPLOY_PORT": str(port),
        "ELECTION_DEPLOY_BIND": "127.0.0.1",
    }

    def compose(*arguments, input=None, check=True):
        result = subprocess.run(
            ["docker", "compose", "--env-file", "/dev/null", *arguments],
            cwd=ROOT,
            env=environment,
            input=input,
            capture_output=True,
            text=True,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def operate(script, *arguments, input=None):
        result = subprocess.run(
            ["sh", str(ROOT / "deploy" / script), *arguments],
            cwd=ROOT,
            env=environment,
            input=input,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    try:
        compose("build", "api")
        compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "prepare",
            "--root",
            "/data",
            "--host-root",
            str(directory),
            "--host",
            "127.0.0.1",
            "--project",
            project,
            "--port",
            str(port),
        )
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        yield compose, operate, directory, port
    finally:
        logs = compose("logs", "--no-color", "api", check=False)
        log_path = directory / "validation-api.log"
        log_path.write_text(logs.stdout + logs.stderr)
        log_path.chmod(0o600)
        compose("down", "--remove-orphans", check=False)


def test_fresh_bootstrap_persistence_restore_and_guarded_maintenance(docker_deployment, qt_app):
    compose, operate, directory, port = docker_deployment
    refused = compose("run", "--rm", "--no-deps", "-T", "api", check=False)
    assert refused.returncode != 0
    assert "database_schema_incompatible" in refused.stderr
    password = "Docker-Initial-Password-84!"
    ready_password = "Docker-Personal-Password-84!"
    operate("setup.sh", "--host", "127.0.0.1", input=password + "\n" + password + "\n")
    context = ssl.create_default_context(cafile=str(directory / "tls/ca.pem"))
    with httpx.Client(base_url=f"https://127.0.0.1:{port}", verify=context, timeout=30) as client:
        wait_for_public_health(client)
        assert client.get("/api/health").status_code == 200
        signed_in = client.post("/api/auth/login", json={"username": "admin", "password": password})
        assert signed_in.status_code == 200
        client.headers["Authorization"] = "Bearer " + signed_in.json()["token"]
        changed = client.post(
            "/api/auth/password",
            json={
                "current_password": password,
                "new_password": ready_password,
            },
        )
        assert changed.status_code == 200
        token = changed.json()["token"]
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/api/elections").json()["items"] == []
        name = "Docker persistent election"
        saved = client.post("/api/elections", json={"name": name, "request_id": str(uuid4())})
        assert saved.status_code == 201, saved.text
        election_id = saved.json()["id"]
        station = stock_stations(client)[0]
        account = staff_account(client, [station["id"]])
        with httpx.Client(base_url=client.base_url, verify=context, timeout=30) as officer:
            login = officer.post(
                "/api/auth/login",
                json={
                    "username": account["username"],
                    "password": INITIAL_PASSWORD,
                },
            )
            assert login.status_code == 200
            officer.headers["Authorization"] = "Bearer " + login.json()["token"]
            changed_officer = officer.post(
                "/api/auth/password",
                json={
                    "current_password": INITIAL_PASSWORD,
                    "new_password": READY_PASSWORD,
                },
            )
            assert changed_officer.status_code == 200
            officer.headers["Authorization"] = "Bearer " + changed_officer.json()["token"]
            path = f"/api/workspace/stations/{station['id']}/stock"
            receipt = officer.post(path, json=stock_payload())
            assert receipt.status_code == 201, receipt.text
            report = path + f"/{receipt.json()['id']}"
            pdf = officer.get(report + "/statement.pdf?revision=1&locale=tc")
            assert pdf.status_code == 200, pdf.text
            text = "".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
            assert "普通系列 A" in text
            csv = officer.get(report + "/statement.csv?revision=1&locale=tc")
            assert csv.status_code == 200
            assert "普通系列 A" in csv.text and "000001" in csv.text
        desktop = DesktopController(str(client.base_url), str(directory / "tls/ca.pem"))
        try:
            desktop.signIn(str(client.base_url), account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace", timeout=15)
            assert state_of(desktop)["account"]["id"] == account["id"]
        finally:
            desktop.shutdown()
            desktop.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
        compose("build", "api")
        compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "90", "api")
        wait_for_public_health(client)
        assert any(
            row["id"] == election_id and row["name"] == name
            for row in client.get("/api/elections").json()["items"]
        )
        snapshot = client.post("/api/backups", json={"request_id": str(uuid4())})
        assert snapshot.status_code < 300, snapshot.text
        job = snapshot.json()
        assert job["status"] == "succeeded", job
        compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "admin",
            "prepare-test",
            "--schema",
            "election_verification_test",
            "--restore",
        )
        restored = compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "admin",
            "restore",
            "--manifest",
            f"/var/lib/election/backups/{job['id']}.manifest.json",
            "--target-schema",
            "election_verification_test",
        )
        assert json.loads(restored.stdout)["status"] == "succeeded"
        restored_port = free_port()
        readback = compose(
            "run",
            "--rm",
            "--detach",
            "--no-deps",
            "--publish",
            f"127.0.0.1:{restored_port}:8443",
            "--volume",
            f"{directory}/config/restore-server.env:/run/election/server.env:ro",
            "api",
        )
        try:
            with httpx.Client(
                base_url=f"https://127.0.0.1:{restored_port}", verify=context, timeout=10
            ) as recovered:
                wait_for_public_health(recovered)
                recovered.headers["Authorization"] = "Bearer " + token
                assert recovered.get("/api/elections").status_code == 401
                login = recovered.post(
                    "/api/auth/login",
                    json={
                        "username": "admin",
                        "password": ready_password,
                    },
                )
                assert login.status_code == 200
                recovered.headers["Authorization"] = "Bearer " + login.json()["token"]
                assert any(
                    row["id"] == election_id
                    for row in recovered.get("/api/elections").json()["items"]
                )
        finally:
            subprocess.run(["docker", "stop", readback.stdout.strip()], capture_output=True)
        no_backup = compose("run", "--rm", "--no-deps", "-T", "admin", "migrate", check=False)
        assert "pre_migration_backup_required" in no_backup.stderr
        compose("stop", "api")
        backup_directory = directory / "backups"
        backup_directory.chmod(0o755)
        unsafe_storage = compose("run", "--rm", "--no-deps", "-T", "admin", "backup", check=False)
        assert "backup_directory_not_private" in unsafe_storage.stderr
        backup_directory.chmod(0o700)
        failure = compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--env",
            "ELECTION_MYSQLDUMP_BINARY=/unavailable/mysqldump",
            "admin",
            "backup",
            check=False,
        )
        assert failure.returncode != 0
        blocked = compose("run", "--rm", "--no-deps", "-T", "api", check=False)
        assert "deployment_maintenance_pending" in blocked.stderr
        backed_up = compose("run", "--rm", "--no-deps", "-T", "admin", "backup")
        backup_id = json.loads(backed_up.stdout)["backup_id"]
        manifest_path = backup_directory / (backup_id + ".manifest.json")
        original_manifest = manifest_path.read_text()
        manifest = json.loads(original_manifest)
        manifest["application_source_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        invalid_provenance = compose(
            "run", "--rm", "--no-deps", "-T", "admin", "migrate", check=False
        )
        assert "pre_migration_backup_mismatch" in invalid_provenance.stderr
        manifest_path.write_text(original_manifest)
        compose("run", "--rm", "--no-deps", "-T", "admin", "migrate")
        compose("run", "--rm", "--no-deps", "-T", "admin", "finish")
        operate("maintenance.sh", "upgrade")
        wait_for_public_health(client)
        assert any(row["id"] == election_id for row in client.get("/api/elections").json()["items"])
