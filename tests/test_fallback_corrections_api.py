"""Reasoned source corrections preserve approved history and renew period review."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


def test_corrected_activation_baseline_retains_history_and_renews_dependent_turnout(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        officer, activation = setup["officer"], prepared["activation"]
        path = setup["path"] + f"/{activation['id']}"
        corrected = officer.post(path + "/amend", json={
            **setup["command"], "request_id": str(uuid4()), "expected_revision": 1,
            "cumulative_quantity": 111,
            "source_context": "Corrected confirmed external baseline is 111 at 11:20.",
            "reason": "Supervisor register transcription correction: 110 should be 111.",
        })
        assert corrected.status_code == 201
        draft = corrected.json()
        assert draft["id"] == activation["id"] and draft["revision"] == 2
        assert draft["status"] == "draft" and draft["cumulative_quantity"] == 111
        assert draft["stock_snapshot"] == activation["stock_snapshot"]
        old_source = officer.get(path, params={"revision": 1})
        assert old_source.status_code == 200 and old_source.json() == activation
        turnout = setup["scope"]["path"]
        pending = officer.get(turnout)
        assert pending.status_code == 200
        assert pending.json()["items"][1]["record"] == prepared["approved"]
        assert pending.json()["items"][1]["review_required"] is True
        assert pending.json()["approved_prefix"]["cumulative_end"] == 100
        assert officer.post(path + "/submit", json=turnout_command(2)).status_code == 200
        confirmed = setup["supervisor"].post(
            path + "/approve", json=turnout_command(2, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["cumulative_quantity"] == 111
        revision = officer.post(turnout + "/2/amend", json=turnout_draft(
            expected_revision=1, mode="fallback", fallback_activation_id=activation["id"],
            fallback_activation_revision=2, stock_snapshot_id=prepared["endpoint"]["id"],
            stock_snapshot_revision=1, event_at="2026-11-15T12:00:00+08:00",
            source_context="111 confirmed baseline plus five ordinary issues gives 116.",
            amendment_reason="Renew the P(15) source selection after the activation correction.",
        ))
        assert revision.status_code == 200
        assert revision.json()["source_basis"]["ordinary_issued_since_activation_quantity"] == 5
        assert revision.json()["source_basis"]["stock_derived_cumulative_quantity"] == 116
        assert officer.post(turnout + "/2/submit", json=turnout_command(2)).status_code == 200
        reviewed = setup["supervisor"].post(
            turnout + "/2/approve", json=turnout_command(2, password=READY_PASSWORD),
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["derived_hourly"] == 16
        assert reviewed.json()["derived_cumulative_end"] == 116
        history = officer.get(path + "/history")
        assert history.status_code == 200
        assert history.json() == {"items": [activation, confirmed.json()]}
        old_turnout = officer.get(turnout + "/2", params={"revision": 1})
        assert old_turnout.status_code == 200 and old_turnout.json() == prepared["approved"]
        unchanged_stock = officer.get(
            setup["base"] + f"/stock-snapshots/{prepared['endpoint']['id']}",
        )
        assert unchanged_stock.status_code == 200 and unchanged_stock.json() == prepared["endpoint"]
