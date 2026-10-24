"""Immediate recovery retains the normal coverage either side of its mode events."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.fallback_support import confirm_fallback_activation, fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


def test_immediate_recovery_does_not_relabel_the_earlier_normal_interval(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        activation = confirm_fallback_activation(setup)
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T11:20:00+08:00", "cumulative_quantity": 110,
            "stock_snapshot_id": setup["snapshot"]["id"], "stock_snapshot_revision": 1,
            "source_context": "The external register is immediately available again at 110.",
            "reason": "No ordinary issues occurred before the connection was restored.",
        })
        assert created.status_code == 201
        target = path + f"/{created.json()['id']}"
        assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
        assert setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        ).status_code == 200
        saved = officer.put(setup["scope"]["path"] + "/2", json=turnout_draft(
            mode="recovery", fallback_recovery_id=created.json()["id"],
            fallback_recovery_revision=1, supplied_hourly=15, supplied_cumulative=115,
            event_at="2026-11-15T12:00:00+08:00",
            source_context="Normal register confirms 115 at noon after immediate recovery.",
        ))
        assert saved.status_code == 200
        assert saved.json()["source_basis"]["coverage"] == [
            {"mode": "normal", "start_at": "2026-11-15T03:00:00Z",
             "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
             "cumulative_end_quantity": 110, "hourly_quantity": 10},
            {"mode": "normal", "start_at": "2026-11-15T03:20:00Z",
             "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 110,
             "cumulative_end_quantity": 115, "hourly_quantity": 5},
        ]
        assert saved.json()["source_basis"]["reconciliation_difference"] == 0
        assert saved.json()["source_basis"]["selected_cumulative_quantity"] == 115
