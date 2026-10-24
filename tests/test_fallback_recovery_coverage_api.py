"""An EPR recovery inside a reporting interval retains both source segments."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.fallback_support import confirm_fallback_activation, fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


def test_recovery_inside_period_uses_recovered_anchor_then_normal_endpoint(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        activation = confirm_fallback_activation(setup)
        observed = officer.post(setup["base"] + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T11:50:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        stock = observed.json()
        assert stock["ordinary_issued_quantity"] == 115
        created = officer.post(path, json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T11:50:00+08:00", "cumulative_quantity": 116,
            "stock_snapshot_id": stock["id"], "stock_snapshot_revision": 1,
            "source_context": "Recovered register total 116 at 11:50.",
            "reason": "The recovered register differs from the ordinary-stock endpoint by one.",
        })
        assert created.status_code == 201
        recovery = created.json()
        target = path + f"/{recovery['id']}"
        assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
        approved = setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert approved.status_code == 200
        draft = officer.put(setup["scope"]["path"] + "/2", json=turnout_draft(
            mode="recovery", fallback_recovery_id=recovery["id"], fallback_recovery_revision=1,
            supplied_hourly=20, supplied_cumulative=120,
            event_at="2026-11-15T12:00:00+08:00",
            source_context="Recovered external register advances from 116 at 11:50 to 120 at noon.",
        ))
        # First new behavior: recovery can occur between reporting boundaries.
        assert draft.status_code == 200
        saved = draft.json()
        assert saved["provenance"] == "external_reconciled"
        assert saved["source_basis"]["stock_derived_cumulative_quantity"] == 115
        assert saved["source_basis"]["recovered_cumulative_quantity"] == 116
        assert saved["source_basis"]["selected_cumulative_quantity"] == 120
        assert saved["source_basis"]["coverage"] == [
            {
                "mode": "normal", "start_at": "2026-11-15T03:00:00Z",
                "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
                "cumulative_end_quantity": 110, "hourly_quantity": 10,
            },
            {
                "mode": "reconciled", "start_at": "2026-11-15T03:20:00Z",
                "end_at": "2026-11-15T03:50:00Z", "cumulative_start_quantity": 110,
                "cumulative_end_quantity": 116, "hourly_quantity": 6,
            },
            {
                "mode": "normal", "start_at": "2026-11-15T03:50:00Z",
                "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 116,
                "cumulative_end_quantity": 120, "hourly_quantity": 4,
            },
        ]
        formal = setup["scope"]["path"] + "/2"
        assert officer.post(formal + "/submit", json=turnout_command(1)).status_code == 200
        result = setup["supervisor"].post(
            formal + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert result.status_code == 200
        assert result.json()["derived_hourly"] == 20
        assert result.json()["derived_cumulative_end"] == 120
        assert result.json()["source_basis"] == saved["source_basis"]
        current = officer.get(setup["scope"]["path"])
        assert current.status_code == 200
        assert current.json()["approved_prefix"]["cumulative_end"] == 120
        assert officer.get(setup["base"] + f"/stock-snapshots/{stock['id']}").json() == stock
