"""Fallback request identity includes every accepted nonempty source reason."""

from fastapi.testclient import TestClient

from tests.fallback_support import fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election


def test_changed_activation_reason_cannot_replay_an_existing_request_identity(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        command = {**setup["command"], "reason": "Supervisor observed the register outage."}
        saved = setup["officer"].post(setup["path"], json=command)
        assert saved.status_code == 201
        assert saved.json()["reason"] == "Supervisor observed the register outage."
        changed = setup["officer"].post(setup["path"], json={
            **command, "reason": "Different explanation supplied with the same request identity.",
        })
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "request_conflict"
        replay = setup["officer"].post(setup["path"], json=command)
        assert replay.status_code == 201 and replay.json() == saved.json()
        retained = setup["officer"].get(setup["path"] + f"/{saved.json()['id']}/history")
        assert retained.status_code == 200 and retained.json() == {"items": [saved.json()]}
