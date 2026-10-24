"""Fallback command boundaries are verified through authenticated public MySQL APIs."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.fallback_support import (
    approved_mixed_period,
    confirm_fallback_activation,
    fallback_setup,
)
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


def read(client: TestClient, path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.json()


def test_fallback_role_scope_replay_and_current_password_checks_preserve_one_effect(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, supervisor, path = setup["officer"], setup["supervisor"], setup["path"]
        station_id, other_id = [row["id"] for row in setup["scope"]["stations"]]
        with (
            turnout_staff(admin, database_url, setup["clock"], [station_id],
                          "counting_officer") as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [other_id],
                          "supervisor") as (unassigned, _),
        ):
            before = read(officer, path)
            assert before["items"] == []
            for actor in (admin, supervisor, counter):
                denied = actor.post(path, json={**setup["command"], "request_id": str(uuid4())})
                assert denied.status_code == 403
                assert read(officer, path) == before
            assert admin.get(path).status_code == 403
            assert unassigned.get(path).status_code == 403
            created = officer.post(path, json=setup["command"])
            assert created.status_code == 201
            saved = created.json()
            target = path + f"/{saved['id']}"
            replay = officer.post(path, json=setup["command"])
            assert replay.status_code == 201 and replay.json() == saved
            conflict = officer.post(path, json={
                **setup["command"], "source_context": "A changed source with the same command ID.",
            })
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "request_conflict"
            for actor in (supervisor, counter):
                denied = actor.post(target + "/submit", json=turnout_command(1))
                assert denied.status_code == 403
            submit_command = turnout_command(1)
            submitted = officer.post(target + "/submit", json=submit_command)
            assert submitted.status_code == 200
            assert submitted.json()["status"] == "submitted"
            assert officer.post(target + "/submit", json=submit_command).json() == submitted.json()
            approval_command = turnout_command(1, password=READY_PASSWORD)
            for actor in (officer, counter, unassigned):
                denied = actor.post(target + "/approve", json=approval_command)
                assert denied.status_code == 403
            wrong = {**approval_command, "password": "Wrong-current-password-42!"}
            denied = supervisor.post(target + "/approve", json=wrong)
            assert denied.status_code == 401
            assert read(officer, target) == submitted.json()
            confirmed = supervisor.post(target + "/approve", json=approval_command)
            assert confirmed.status_code == 200
            approved = confirmed.json()
            assert approved["status"] == "approved"
            assert approved["approved_by"] == setup["supervisor_account"]["id"]
            cached = supervisor.post(target + "/approve", json=approval_command)
            assert cached.status_code == 200 and cached.json() == approved
            assert supervisor.post(target + "/approve", json=wrong).status_code == 401
            assert unassigned.post(target + "/approve", json=approval_command).status_code == 403
            assert counter.post(path, json=setup["command"]).status_code == 403
            # An original cached draft remains the original outcome after approval.
            assert officer.post(path, json=setup["command"]).json() == saved
            current = read(officer, path)
            assert current["items"] == [approved] and current["mode"] == "fallback"
            assert read(counter, target) == approved
            assert read(counter, target + "/history") == {"items": [approved]}
            assert read(officer, setup["scope"]["path"]) == setup["turnout"]


def test_malformed_fallback_quantities_times_and_context_create_no_event(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        before = read(officer, path)
        snapshot_path = setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}"
        changes = [
            ("negative", {"cumulative_quantity": -1}),
            ("boolean", {"cumulative_quantity": True}),
            ("float", {"cumulative_quantity": 110.0}),
            ("ASCII-string", {"cumulative_quantity": "110"}),
            ("Arabic-digits", {"cumulative_quantity": "١١٠"}),
            ("fullwidth-digits", {"cumulative_quantity": "１１０"}),
            ("above-signed64", {"cumulative_quantity": 9223372036854775808}),
            ("boolean-source", {"stock_snapshot_id": True}),
            ("string-source", {"stock_snapshot_id": str(setup["snapshot"]["id"])}),
            ("zero-source-revision", {"stock_snapshot_revision": 0}),
            ("naive-time", {"event_at": "2026-11-15T11:20:00"}),
            ("future-time", {"event_at": "2026-11-15T13:00:00+08:00"}),
            ("unsupported-year", {"event_at": "0001-01-01T00:00:00Z"}),
            ("blank-source-context", {"source_context": " \n "}),
            ("too-long-source-context", {"source_context": "x" * 2001}),
            ("unknown-field", {"unrequested_field": "outside the public contract"}),
        ]
        assert before["items"] == []
        for label, changed in changes:
            response = officer.post(path, json={
                **setup["command"], "request_id": str(uuid4()), **changed,
            })
            assert response.status_code == 422, (label, response.status_code)
            assert read(officer, path) == before, label
            assert read(officer, snapshot_path) == setup["snapshot"], label
            assert read(officer, setup["scope"]["path"]) == setup["turnout"], label


def test_fallback_rejects_wrong_time_foreign_stale_and_incomplete_sources_without_events(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path, snapshot = setup["officer"], setup["path"], setup["snapshot"]
        before = read(officer, path)
        assert before["items"] == []

        def rejected(changes: dict, code: str, status: int = 409) -> None:
            response = officer.post(path, json={
                **setup["command"], "request_id": str(uuid4()), **changes,
            })
            assert response.status_code == status, (code, response.status_code)
            assert response.json()["detail"]["code"] == code
            assert read(officer, path) == before

        rejected({"event_at": "2026-11-15T11:21:00+08:00"}, "fallback_balance_time_required")
        other_id = setup["scope"]["stations"][1]["id"]
        with turnout_staff(admin, database_url, setup["clock"], [other_id]) as (other, _):
            other_base = f"/api/workspace/stations/{other_id}"
            options = read(other, other_base + "/allocations")
            foreign = other.post(other_base + "/stock-snapshots", json={
                "request_id": str(uuid4()), "event_at": "2026-11-15T11:20:00+08:00",
                "counters": [{"counter_id": row["id"], "ranges": []}
                             for row in options["counters"]],
            })
            assert foreign.status_code == 201 and foreign.json()["complete"] is True
            rejected({"stock_snapshot_id": foreign.json()["id"]}, "stock_snapshot_not_found", 404)

        corrected = officer.put(setup["base"] + f"/stock-snapshots/{snapshot['id']}", json={
            "request_id": str(uuid4()), "revision": 1,
            "reason": "Confirm the same original counter balance against its paper record.",
            "event_at": snapshot["event_at"],
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000111", "serial_to": "000200",
            }]}],
        })
        assert corrected.status_code == 200
        assert corrected.json()["revision"] == 2 and corrected.json()["complete"] is True
        rejected({}, "stock_snapshot_basis_stale")
        original = officer.get(setup["base"] + f"/stock-snapshots/{snapshot['id']}",
                               params={"revision": 1})
        assert original.status_code == 200 and original.json() == snapshot
        incomplete = officer.post(setup["base"] + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T11:30:00+08:00", "counters": [],
        })
        assert incomplete.status_code == 201 and incomplete.json()["complete"] is False
        rejected({"stock_snapshot_id": incomplete.json()["id"],
                  "event_at": "2026-11-15T11:30:00+08:00"}, "stock_snapshot_incomplete")

        receipt = setup["receipt"]
        corrected_receipt = officer.put(setup["base"] + f"/stock/{receipt['id']}", json={
            "request_id": str(uuid4()), "revision": 1, "series": receipt["series"],
            "event_at": receipt["event_at"], "ordinary_quantity": 200,
            "replacement_quantity": 3, "tendered_quantity": 2,
            "reason": "Confirm receipt documentation without changing stock or its original time.",
            "ranges": [{key: row[key] for key in ("pool", "serial_from", "serial_to")}
                       for row in receipt["ranges"]],
        })
        assert corrected_receipt.status_code == 200
        assert corrected_receipt.json()["revision"] == 2
        rejected({"stock_snapshot_revision": 2},
                 "stock_snapshot_basis_stale")
        assert read(officer, path) == before


def test_an_older_schedule_expectation_rejects_after_draft_revision_and_activation(
    admin: TestClient, database_url: str,
) -> None:
    scope = turnout_scope(
        admin, activate=False, planned_opening_at="2026-11-15T10:00:00+08:00",
        planned_closing_at="2026-11-15T13:00:00+08:00", reporting_interval_minutes=60,
    )
    election = scope["election"]
    schedule_path = f"/api/elections/{election['id']}/schedule"
    revised = admin.put(schedule_path, json={
        "election_date": "2026-11-15", "revision": 1,
        "planned_opening_at": "2026-11-15T10:00:00+08:00",
        "planned_closing_at": "2026-11-15T13:00:00+08:00", "reporting_interval_minutes": 60,
    })
    assert revised.status_code == 200 and revised.json()["revision"] == 2
    activated = admin.post(f"/api/elections/{election['id']}/activate", json={
        "election_revision": election["revision"], "schedule_revision": 2,
    })
    assert activated.status_code == 200
    station_id = scope["stations"][0]["id"]
    with turnout_staff(admin, database_url, TurnoutClock(), [station_id]) as (officer, _):
        base = f"/api/workspace/stations/{station_id}"
        counters = read(officer, base + "/allocations")["counters"]
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T11:20:00+08:00",
            "counters": [{"counter_id": row["id"], "ranges": []} for row in counters],
        })
        assert observed.status_code == 201 and observed.json()["complete"] is True
        source = observed.json()
        assert source["ordinary_issued_quantity"] == 0
        path = base + "/fallback"
        before = read(officer, path)
        rejected = officer.post(path, json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1,
            "kind": "activation", "event_at": "2026-11-15T11:20:00+08:00",
            "cumulative_quantity": 0, "stock_snapshot_id": source["id"],
            "stock_snapshot_revision": 1, "source_context": "Confirmed external zero at 11:20.",
        })
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "turnout_schedule_conflict"
        assert read(officer, path) == before and before["items"] == []
        assert read(officer, base + f"/stock-snapshots/{source['id']}") == source


def test_reasoned_correction_rejects_blank_reason_and_stale_revision_with_original_history(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        original = confirm_fallback_activation(setup)
        target = path + f"/{original['id']}"
        before = read(officer, target)
        command = {
            **setup["command"], "request_id": str(uuid4()), "expected_revision": 1,
            "cumulative_quantity": 111,
            "source_context": "Corrected confirmed register baseline is 111 at 11:20.",
            "reason": " \n ",
        }
        rejected = officer.post(target + "/amend", json=command)
        assert rejected.status_code == 422
        assert read(officer, target) == before
        assert read(officer, target + "/history") == {"items": [original]}
        valid = {**command, "reason": "Correct the supplied baseline from 110 to 111."}
        amended = officer.post(target + "/amend", json=valid)
        assert amended.status_code == 201
        corrected = amended.json()
        assert corrected["revision"] == 2 and corrected["status"] == "draft"
        assert corrected["cumulative_quantity"] == 111
        assert corrected["reason"] == valid["reason"]
        cached = officer.post(target + "/amend", json=valid)
        assert cached.status_code == 201 and cached.json() == corrected
        conflict = officer.post(target + "/amend", json={**valid, "reason": "Different reason."})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "request_conflict"
        stale = officer.post(target + "/amend", json={**valid, "request_id": str(uuid4())})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"
        stale_submit = officer.post(target + "/submit", json=turnout_command(1))
        assert stale_submit.status_code == 409
        assert stale_submit.json()["detail"]["code"] == "revision_conflict"
        assert read(officer, target) == corrected
        assert read(officer, target + "/history") == {"items": [original, corrected]}
        retained = officer.get(target, params={"revision": 1})
        assert retained.status_code == 200 and retained.json() == original
        assert read(officer, setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}") == (
            setup["snapshot"]
        )
        assert read(officer, setup["scope"]["path"]) == setup["turnout"]


def test_recovered_114_preserves_negative_difference_and_renewed_14_hourly_with_old_115(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        officer, supervisor, path = setup["officer"], setup["supervisor"], setup["path"]
        activation, endpoint, original = (
            prepared["activation"], prepared["endpoint"], prepared["approved"],
        )
        turnout_path = setup["scope"]["path"]
        old_read = officer.get(turnout_path + "/2", params={"revision": 1})
        assert old_read.status_code == 200 and old_read.json() == original
        old_bytes = old_read.content
        created = officer.post(path, json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 114,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "source_context": "Recovered supplied register confirms 114 at noon.",
            "reason": "Retain the recovered figure one below the stock-derived 115 estimate.",
        })
        assert created.status_code == 201
        recovery = created.json()
        assert recovery["status"] == "draft"
        assert type(recovery["reconciliation"]["difference"]) is int
        assert recovery["reconciliation"]["difference"] == -1
        assert recovery["reconciliation"]["stock_derived_cumulative_quantity"] == 115
        assert recovery["reconciliation"]["recovered_cumulative_quantity"] == 114
        target = path + f"/{recovery['id']}"
        assert read(officer, path)["mode"] == "fallback"
        assert read(officer, turnout_path)["approved_prefix"]["cumulative_end"] == 115
        submitted = officer.post(target + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
        assert submitted.json()["reconciliation"]["difference"] == -1
        assert read(officer, path)["mode"] == "fallback"
        confirmed = supervisor.post(target + "/approve", json=turnout_command(
            1, password=READY_PASSWORD,
        ))
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "approved"
        assert type(confirmed.json()["reconciliation"]["difference"]) is int
        assert confirmed.json()["reconciliation"]["difference"] == -1
        assert read(officer, path)["mode"] == "normal"
        pending = read(officer, turnout_path)
        assert pending["items"][1]["record"] == original
        assert pending["items"][1]["approval_valid"] is False
        assert pending["items"][1]["review_required"] is True
        assert pending["approved_prefix"]["cumulative_end"] == 100
        assert officer.get(turnout_path + "/2", params={"revision": 1}).content == old_bytes
        amended = officer.post(turnout_path + "/2/amend", json=turnout_draft(
            expected_revision=1, mode="recovery", fallback_recovery_id=recovery["id"],
            fallback_recovery_revision=1, supplied_hourly=None, supplied_cumulative=None,
            event_at="2026-11-15T12:00:00+08:00",
            source_context="Recovered 114 replaces, rather than adds to, the old estimate 115.",
            amendment_reason=("Review the signed minus-one reconciliation "
                              "using the recovered source."),
        ))
        assert amended.status_code == 200 and amended.json()["revision"] == 2
        assert amended.json()["provenance"] == "external_reconciled"
        basis = amended.json()["source_basis"]
        assert type(basis["reconciliation_difference"]) is int
        assert basis["reconciliation_difference"] == -1
        assert basis["stock_derived_cumulative_quantity"] == 115
        assert basis["recovered_cumulative_quantity"] == 114
        assert basis["coverage"] == [
            {"mode": "normal", "start_at": "2026-11-15T03:00:00Z",
             "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
             "cumulative_end_quantity": 110, "hourly_quantity": 10},
            {"mode": "reconciled", "start_at": "2026-11-15T03:20:00Z",
             "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 110,
             "cumulative_end_quantity": 114, "hourly_quantity": 4},
        ]
        resubmitted = officer.post(turnout_path + "/2/submit", json=turnout_command(2))
        assert resubmitted.status_code == 200
        approved_response = supervisor.post(turnout_path + "/2/approve", json=turnout_command(
            2, password=READY_PASSWORD,
        ))
        assert approved_response.status_code == 200
        approved = approved_response.json()
        assert approved["revision"] == 2 and approved["status"] == "approved"
        assert approved["derived_cumulative_start"] == 100
        assert approved["derived_hourly"] == 14 and approved["derived_cumulative_end"] == 114
        assert approved["source_basis"]["reconciliation_difference"] == -1
        assert read(officer, turnout_path + "/2/history") == {"items": [original, approved]}
        retained = officer.get(turnout_path + "/2", params={"revision": 1})
        assert retained.status_code == 200 and retained.content == old_bytes
        current = read(officer, turnout_path)
        assert current["approved_prefix"]["periods"] == 2
        assert current["approved_prefix"]["cumulative_end"] == 114
        assert current["items"][1]["record"] == approved
        assert read(officer, setup["base"] + f"/stock-snapshots/{endpoint['id']}") == endpoint
        assert read(officer, target)["reconciliation"]["difference"] == -1
