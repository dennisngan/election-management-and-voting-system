"""Recovered external turnout replaces the fallback endpoint through renewed review."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_recovered_116_replaces_approved_fallback_115_and_preserves_both_revisions(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        prepared = approved_mixed_period(setup)
        activation, endpoint, original = (
            prepared["activation"], prepared["endpoint"], prepared["approved"]
        )
        turnout_path = setup["scope"]["path"]
        original_read = officer.get(turnout_path + "/2", params={"revision": 1})
        assert original_read.status_code == 200 and original_read.json() == original
        original_bytes = original_read.content
        created = officer.post(path, json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 116,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "source_context": "Recovered manual register confirms cumulative turnout 116 at noon.",
            "reason": "Reconcile the recovered register total with the stock-derived 115 endpoint.",
        })
        # First new-feature assertion: the activation-only command rejects recovery fields.
        # Reconciliation, invalidation and renewed-review assertions remain unreached in RED.
        assert created.status_code == 201
        recovery = created.json()
        assert type(recovery["id"]) is int and recovery["id"] > 0
        assert recovery["kind"] == "recovery"
        assert recovery["status"] == "draft" and recovery["revision"] == 1
        assert recovery["activation_id"] == activation["id"]
        assert recovery["activation_revision"] == 1
        assert recovery["event_at"] == "2026-11-15T04:00:00Z"
        assert recovery["cumulative_quantity"] == 116
        assert recovery["stock_snapshot_id"] == endpoint["id"]
        assert recovery["stock_snapshot_revision"] == 1
        assert recovery["reconciliation"]["stock_derived_cumulative_quantity"] == 115
        assert recovery["reconciliation"]["recovered_cumulative_quantity"] == 116
        assert type(recovery["reconciliation"]["difference"]) is int
        assert recovery["reconciliation"]["difference"] == 1
        pending = officer.get(path)
        assert pending.status_code == 200
        assert pending.json()["mode"] == "fallback"
        assert pending.json()["active_activation_id"] == activation["id"]
        target = path + f"/{recovery['id']}"
        submitted = officer.post(target + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
        pending = officer.get(path)
        assert pending.status_code == 200
        assert pending.json()["mode"] == "fallback"
        assert pending.json()["active_activation_id"] == activation["id"]
        confirmed = setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "approved"
        assert confirmed.json()["approved_by"] == setup["supervisor_account"]["id"]
        recovered = officer.get(path)
        assert recovered.status_code == 200
        assert recovered.json()["mode"] == "normal"
        assert recovered.json()["active_activation_id"] is None
        current = officer.get(turnout_path)
        assert current.status_code == 200
        old_period = current.json()["items"][1]
        assert old_period["record"] == original
        assert old_period["approval_valid"] is False and old_period["review_required"] is True
        assert current.json()["approved_prefix"]["periods"] == 1
        assert current.json()["approved_prefix"]["cumulative_end"] == 100
        retained = officer.get(turnout_path + "/2", params={"revision": 1})
        assert retained.status_code == 200 and retained.content == original_bytes

        amended = officer.post(turnout_path + "/2/amend", json=turnout_draft(
            expected_revision=1, mode="recovery", fallback_recovery_id=recovery["id"],
            fallback_recovery_revision=1, supplied_hourly=None, supplied_cumulative=None,
            event_at="2026-11-15T12:00:00+08:00",
            source_context=("Recovered manual register replaces the noon fallback endpoint "
                            "with 116."),
            amendment_reason="Review the recovered total instead of adding it to the old 115.",
        ))
        assert amended.status_code == 200
        draft = amended.json()
        assert draft["revision"] == 2 and draft["status"] == "draft"
        assert draft["provenance"] == "external_reconciled"
        expected_basis = {
            "recovery_id": recovery["id"], "recovery_revision": 1,
            "stock_derived_cumulative_quantity": 115,
            "recovered_cumulative_quantity": 116, "reconciliation_difference": 1,
            "coverage": [
                {
                    "mode": "normal", "start_at": "2026-11-15T03:00:00Z",
                    "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
                    "cumulative_end_quantity": 110, "hourly_quantity": 10,
                },
                {
                    "mode": "reconciled", "start_at": "2026-11-15T03:20:00Z",
                    "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 110,
                    "cumulative_end_quantity": 116, "hourly_quantity": 6,
                },
            ],
        }
        for key, value in expected_basis.items():
            assert draft["source_basis"][key] == value
        resubmitted = officer.post(turnout_path + "/2/submit", json=turnout_command(2))
        assert resubmitted.status_code == 200 and resubmitted.json()["status"] == "submitted"
        approved_response = setup["supervisor"].post(
            turnout_path + "/2/approve", json=turnout_command(2, password=READY_PASSWORD),
        )
        assert approved_response.status_code == 200
        approved = approved_response.json()
        assert approved["revision"] == 2 and approved["status"] == "approved"
        assert approved["provenance"] == "external_reconciled"
        assert approved["derived_cumulative_start"] == 100
        assert approved["derived_hourly"] == 16
        assert approved["derived_cumulative_end"] == 116
        assert approved["source_basis"] == draft["source_basis"]
        history = officer.get(turnout_path + "/2/history")
        assert history.status_code == 200 and history.json() == {"items": [original, approved]}
        current = officer.get(turnout_path)
        assert current.status_code == 200
        assert current.json()["approved_prefix"]["periods"] == 2
        assert current.json()["approved_prefix"]["cumulative_end"] == 116
        assert current.json()["items"][1]["record"] == approved
        unchanged = officer.get(setup["base"] + f"/stock-snapshots/{endpoint['id']}")
        assert unchanged.status_code == 200 and unchanged.json() == endpoint
