"""Opt-in public deployment journey using NEW Docker resources, real HTTPS and MySQL."""

import json
import os
import socket
import ssl
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

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
        yield compose, directory, port
    finally:
        logs = compose("logs", "--no-color", "api", check=False)
        log_path = directory / "validation-api.log"
        log_path.write_text(logs.stdout + logs.stderr)
        log_path.chmod(0o600)
        compose("down", "--remove-orphans", check=False)


def test_fresh_bootstrap_persistence_restore_and_guarded_maintenance(docker_deployment):
    compose, directory, port = docker_deployment
    refused = compose("run", "--rm", "--no-deps", "-T", "api", check=False)
    assert refused.returncode != 0
    assert "database_schema_incompatible" in refused.stderr
    password = "Docker-Initial-Password-84!"
    ready_password = "Docker-Personal-Password-84!"
    compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "admin",
        "initialize",
        input=password + "\n" + password + "\n",
    )
    compose("up", "--detach", "--wait", "--wait-timeout", "90", "api")
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
        compose("run", "--rm", "--no-deps", "-T", "admin", "backup")
        compose("run", "--rm", "--no-deps", "-T", "admin", "migrate")
        compose("run", "--rm", "--no-deps", "-T", "admin", "finish")
        compose("up", "--detach", "--wait", "--wait-timeout", "90", "api")
        wait_for_public_health(client)
        assert any(row["id"] == election_id for row in client.get("/api/elections").json()["items"])
