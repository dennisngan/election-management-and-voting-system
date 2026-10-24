"""Every normal, recovered and fallback interval retains its approved sources."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.fallback_support import confirm_fallback_activation, fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


def test_two_fallback_episodes_in_one_hour_keep_each_source_interval(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        first = confirm_fallback_activation(setup)
        snapshots = []
        for time, serial in (("11:30", "000112"), ("11:40", "000114"), ("12:00", "000117")):
            result = officer.post(setup["base"] + "/stock-snapshots", json={
                "request_id": str(uuid4()), "event_at": f"2026-11-15T{time}:00+08:00",
                "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                    "series": "普通系列 A", "serial_from": serial, "serial_to": "000200",
                }]}],
            })
            assert result.status_code == 201
            snapshots.append(result.json())
        assert [row["ordinary_issued_quantity"] for row in snapshots] == [111, 113, 116]
        records = []
        for kind, event, cumulative, stock in (
            ("recovery", "11:30", 112, snapshots[0]),
            ("activation", "11:40", 114, snapshots[1]),
        ):
            values = {
                "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": kind,
                "event_at": f"2026-11-15T{event}:00+08:00", "cumulative_quantity": cumulative,
                "stock_snapshot_id": stock["id"], "stock_snapshot_revision": 1,
                "source_context": f"Confirmed register total {cumulative} at {event}.",
            }
            if kind == "recovery":
                values.update(activation_id=first["id"], activation_revision=1,
                              reason="Recovered register replaces the first stock estimate.")
            created = officer.post(path, json=values)
            assert created.status_code == 201
            target = path + f"/{created.json()['id']}"
            assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
            approved = setup["supervisor"].post(
                target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
            )
            assert approved.status_code == 200
            records.append(approved.json())
        second = records[1]
        formal = setup["scope"]["path"] + "/2"
        saved = officer.put(formal, json=turnout_draft(
            mode="fallback", fallback_activation_id=second["id"], fallback_activation_revision=1,
            stock_snapshot_id=snapshots[2]["id"], stock_snapshot_revision=1,
            event_at="2026-11-15T12:00:00+08:00",
            source_context="Two reviewed fallback episodes separated by normal register operation.",
        ))
        assert saved.status_code == 200
        basis = saved.json()["source_basis"]
        assert basis["stock_derived_cumulative_quantity"] == 117
        # First new assertion: the earlier fallback/recovery cannot be relabelled normal.
        assert basis["coverage"] == [
            {"mode": "normal", "start_at": "2026-11-15T03:00:00Z",
             "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
             "cumulative_end_quantity": 110, "hourly_quantity": 10},
            {"mode": "reconciled", "start_at": "2026-11-15T03:20:00Z",
             "end_at": "2026-11-15T03:30:00Z", "cumulative_start_quantity": 110,
             "cumulative_end_quantity": 112, "hourly_quantity": 2},
            {"mode": "normal", "start_at": "2026-11-15T03:30:00Z",
             "end_at": "2026-11-15T03:40:00Z", "cumulative_start_quantity": 112,
             "cumulative_end_quantity": 114, "hourly_quantity": 2},
            {"mode": "fallback", "start_at": "2026-11-15T03:40:00Z",
             "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 114,
             "cumulative_end_quantity": 117, "hourly_quantity": 3},
        ]
        assert [(row["id"], row["revision"], row["kind"]) for row in basis["source_events"]] == [
            (first["id"], 1, "activation"), (records[0]["id"], 1, "recovery"),
            (second["id"], 1, "activation"),
        ]
        assert officer.post(formal + "/submit", json=turnout_command(1)).status_code == 200
        approved = setup["supervisor"].post(
            formal + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert approved.status_code == 200
        assert approved.json()["derived_hourly"] == 17
        assert approved.json()["derived_cumulative_end"] == 117
        assert approved.json()["source_basis"] == basis
