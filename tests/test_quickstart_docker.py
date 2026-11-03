"""Opt-in single-file Compose deployment and initial-account workflow."""

import json
import os
import socket
import ssl
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from tests.test_docker_deployment import wait_for_public_health

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("ELECTION_RUN_DOCKER_TESTS") != "1",
    reason="Opt in to an owned one-file deployment with ELECTION_RUN_DOCKER_TESTS=1",
)


@pytest.fixture
def quick_stack():
    project = "election-quick-" + uuid4().hex[:10]
    folder = ROOT / ".runtime" / project
    folder.mkdir(parents=True, mode=0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = folder / "config.yml"
    text = (ROOT / "config.example.yml").read_text()
    text = text.replace("context: .", "context: " + json.dumps(str(ROOT)))
    text = text.replace("./data/mysql", str(folder / "mysql"))
    text = text.replace("&server_port 8443", "&server_port " + str(port))
    text = text.replace("username: admin", "username: ' admin '")
    text = text.replace("CHANGE_ME_TO_A_UNIQUE_TEMPORARY_PASSWORD", "Initial-Admin-Password-84!")
    text = text.replace(
        "# No settings below this line need editing.",
        """
    - username: observer
      display_name: Observer
      role: supervisor
      password: Initial-Observer-Password-84$$!

# No settings below this line need editing.""",
    )
    config.write_text(text)
    config.chmod(0o600)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ELECTION_")
    }

    def compose(*arguments, check=True):
        result = subprocess.run(
            ["docker", "compose", "--project-name", project, "-f", str(config), *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    try:
        yield compose, config, folder, port
    finally:
        logs = compose("logs", "--no-color", check=False)
        path = folder / "services.private.log"
        path.write_text(logs.stdout + logs.stderr)
        path.chmod(0o600)
        compose("down", "--remove-orphans", check=False)


def test_one_command_seeds_accounts_and_preserves_them_and_data_on_restart(quick_stack):
    compose, config, folder, port = quick_stack
    compose("up", "-d", "--build", "--wait", "--wait-timeout", "180")
    compose("cp", "api:/run/election/tls/ca.pem", str(folder / "ca.pem"))
    tls = ssl.create_default_context(cafile=str(folder / "ca.pem"))
    with httpx.Client(base_url=f"https://localhost:{port}", verify=tls, timeout=20) as client:
        wait_for_public_health(client)
        login = client.post(
            "/api/auth/login",
            json={
                "username": "admin",
                "password": "Initial-Admin-Password-84!",
            },
        )
        assert login.status_code == 200, login.text
        assert login.json()["account"]["must_change_password"] is True
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = client.post(
            "/api/auth/password",
            json={
                "current_password": "Initial-Admin-Password-84!",
                "new_password": "Personal-Admin-Password-84!",
            },
        )
        assert changed.status_code == 200
        client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        accounts = client.get("/api/accounts").json()["items"]
        assert {(row["username"], row["role"]) for row in accounts} == {
            ("admin", "administrator"),
            ("observer", "supervisor"),
        }
        observer = client.post(
            "/api/auth/login",
            json={
                "username": "observer",
                "password": "Initial-Observer-Password-84$!",
            },
        )
        assert observer.status_code == 200
        assert observer.json()["account"]["must_change_password"] is True
        saved = client.post(
            "/api/elections",
            json={
                "name": "One config persistent election",
                "request_id": str(uuid4()),
            },
        )
        assert saved.status_code == 201, saved.text
        election_id = saved.json()["id"]
        privacy = compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "from pathlib import Path; assert not Path('/config.yml').exists(); "
            "assert not Path('/run/election/tls/ca-key.pem').exists(); "
            "assert not Path('/run/election/mysql-root-password').exists(); print('isolated')",
        )
        assert privacy.stdout.strip() == "isolated"
        document = yaml.safe_load(config.read_text())
        document["x-election"]["accounts"][0]["password"] = "Replacement-Config-Password-84!"
        document["x-election"]["accounts"][0]["role"] = "polling_officer"
        document["x-election"]["accounts"].append(
            {
                "username": "later",
                "display_name": "Later",
                "role": "administrator",
                "password": "Later-Startup-Password-84!",
            }
        )
        config.write_text(yaml.safe_dump(document, sort_keys=False))
        compose("down")
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "180")
        wait_for_public_health(client)
        assert client.get("/api/auth/me").status_code == 200
        assert any(row["id"] == election_id for row in client.get("/api/elections").json()["items"])
        accounts = client.get("/api/accounts").json()["items"]
        assert {(row["username"], row["role"]) for row in accounts} == {
            ("admin", "administrator"),
            ("observer", "supervisor"),
        }
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "Replacement-Config-Password-84!",
                },
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "Personal-Admin-Password-84!",
                },
            ).status_code
            == 200
        )
        compose("run", "--rm", "--no-deps", "-T", "admin", "reserve")
        competing = compose("run", "--rm", "--no-deps", "-T", "admin", "reserve", check=False)
        assert competing.returncode != 0 and "maintenance_already_pending" in competing.stderr
        compose("stop", "api")
        image_id = compose("images", "--quiet", "api").stdout.strip()
        backed_up = compose(
            "run", "--rm", "--no-deps", "-T", "admin", "backup", "--image-id", image_id
        )
        backup_id = json.loads(backed_up.stdout)["backup_id"]
        receipt = compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "admin",
            "-c",
            "import json,sys; from pathlib import Path; "
            "path=Path('/var/lib/election/backups')/(sys.argv[1]+'.maintenance.json'); "
            "value=json.loads(path.read_text()); "
            "assert value['image_id']==sys.argv[2]; print('identity_retained')",
            backup_id,
            image_id,
        )
        assert receipt.stdout.strip() == "identity_retained"
        compose("run", "--rm", "--no-deps", "-T", "admin", "migrate")
        compose("run", "--rm", "--no-deps", "-T", "admin", "finish")
        compose("up", "-d", "--wait", "--wait-timeout", "180")
        wait_for_public_health(client)
        assert any(row["id"] == election_id for row in client.get("/api/elections").json()["items"])
