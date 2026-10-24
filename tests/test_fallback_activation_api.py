"""Supervisor confirmation activates a frozen ordinary-stock fallback baseline."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.fallback_support import fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import READY_PASSWORD, turnout_command


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_confirms_frozen_fallback_activation_without_changing_normal_turnout(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        snapshot = setup["snapshot"]
        created = officer.post(path, json=setup["command"])
        # First new-feature assertion: the missing fallback route is the intended RED.
        # Confirmation, mode, frozen-source and history assertions remain unreached in RED.
        assert created.status_code == 201
        saved = created.json()
        assert type(saved["id"]) is int and saved["id"] > 0
        assert saved["kind"] == "activation"
        assert saved["station_id"] == snapshot["station_id"]
        assert saved["revision"] == 1 and saved["status"] == "draft"
        assert saved["actor_id"] == setup["account"]["id"]
        assert saved["event_at"] == "2026-11-15T03:20:00Z"
        assert saved["entered_at"] == "2026-11-15T04:00:00Z"
        assert saved["cumulative_quantity"] == 110
        assert saved["source_context"] == setup["command"]["source_context"]
        assert saved["stock_snapshot_id"] == snapshot["id"]
        assert saved["stock_snapshot_revision"] == 1
        assert saved["stock_snapshot"] == snapshot
        collection = officer.get(path)
        assert collection.status_code == 200
        assert collection.json()["items"] == [saved]
        assert collection.json()["mode"] == "normal"
        assert collection.json()["active_activation_id"] is None
        normal = officer.get(setup["scope"]["path"])
        assert normal.status_code == 200 and normal.json() == setup["turnout"]

        target = path + f"/{saved['id']}"
        submitted = officer.post(target + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200
        submitted_record = submitted.json()
        assert submitted_record["revision"] == 1 and submitted_record["status"] == "submitted"
        assert submitted_record["stock_snapshot"] == snapshot
        pending = officer.get(path)
        assert pending.status_code == 200
        assert pending.json()["items"] == [submitted_record]
        assert pending.json()["mode"] == "normal"
        assert pending.json()["active_activation_id"] is None

        confirmed = setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        approved = confirmed.json()
        assert approved["revision"] == 1 and approved["status"] == "approved"
        assert approved["approved_by"] == setup["supervisor_account"]["id"]
        assert approved["stock_snapshot"] == snapshot
        active = officer.get(path)
        assert active.status_code == 200
        assert active.json()["items"] == [approved]
        assert active.json()["mode"] == "fallback"
        assert active.json()["active_activation_id"] == saved["id"]
        reopened = officer.get(target)
        assert reopened.status_code == 200 and reopened.json() == approved
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json() == {"items": [approved]}
        normal = officer.get(setup["scope"]["path"])
        assert normal.status_code == 200 and normal.json() == setup["turnout"]
