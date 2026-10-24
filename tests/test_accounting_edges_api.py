"""Source authorization, source invalidation and replay at P(18)'s public API."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import BoxClock, box_staff, box_stations
from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.special_paper_support import special_paper_setup
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def selection(special: dict, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "special_paper_id": special["id"],
        "special_paper_revision": special["revision"],
        "notes": "Checked source-station paper records",
        **changes,
    }


def command(revision: int, **changes: object) -> dict:
    return {"request_id": str(uuid4()), "expected_revision": revision, **changes}


def test_receiving_assignment_does_not_grant_source_station_accounting_access(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = box_stations(admin)
    source_id, destination_id = scope["N2"]["id"], scope["N1"]["id"]
    assert scope["N2"]["counting_mode"] == "send"
    assert scope["N2"]["destination_station_id"] == destination_id
    path = f"/api/workspace/stations/{source_id}/accounting"
    with (
        box_staff(admin, database_url, BoxClock(), "counting_officer", [destination_id]) as (
            receiver,
            _,
        ),
        box_staff(admin, database_url, BoxClock(), "counting_officer", [source_id]) as (
            source,
            _,
        ),
    ):
        denied = receiver.get(path)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "station_access_denied"
        assert receiver.get(path + "/revisions/1").status_code == 403
        assert receiver.put(path, json=selection({"id": 1, "revision": 1})).status_code == 403
        allowed = source.get(path)
        assert allowed.status_code == 200
        assert allowed.json()["station"]["id"] == source_id
        assert allowed.json()["record"] is None
        assert allowed.json()["history"] == []


def test_polling_read_access_does_not_grant_accounting_write_or_count_approval(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        path = setup["base"] + "/accounting"
        station_id = special.json()["station_id"]
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, _):
            assert setup["officer"].get(path).status_code == 200
            denied = setup["officer"].put(path, json=selection(special.json()))
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "counting_officer_required"
            saved = counter.put(path, json=selection(special.json()))
            assert saved.status_code == 200
            denied = counter.post(path + "/approve", json=command(1, password=READY_PASSWORD))
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "supervisor_required"
            assert counter.get(path).json()["record"]["status"] == "draft"
            assert admin.get(path).status_code == 403


def test_approval_replay_reconfirms_current_password_and_conflicting_commands_fail(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id, path = special.json()["station_id"], setup["base"] + "/accounting"
        with (
            turnout_staff(
                admin, database_url, setup["clock"], [station_id], "counting_officer"
            ) as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id], "supervisor") as (
                supervisor,
                _,
            ),
        ):
            save = selection(special.json())
            saved = counter.put(path, json=save)
            assert saved.status_code == 200
            conflicting = counter.put(path, json={**save, "notes": "Different effect"})
            assert conflicting.status_code == 409
            assert conflicting.json()["detail"]["code"] == "request_conflict"
            stale = counter.put(path, json={**save, "request_id": str(uuid4())})
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "revision_conflict"
            assert counter.post(path + "/submit", json=command(1)).status_code == 200
            approve = command(1, password=READY_PASSWORD)
            approved = supervisor.post(path + "/approve", json=approve)
            assert approved.status_code == 200
            assert approved.json()["approval_valid"] is True
            wrong = supervisor.post(path + "/approve", json={**approve, "password": "wrong"})
            assert wrong.status_code == 401
            assert wrong.json()["detail"]["code"] == "invalid_credentials"
            assert supervisor.post(path + "/approve", json=approve).json() == approved.json()
            assert len(counter.get(path).json()["history"]) == 1


def test_corrected_special_source_invalidates_approval_without_changing_frozen_values(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id, path = special.json()["station_id"], setup["base"] + "/accounting"
        with (
            turnout_staff(
                admin, database_url, setup["clock"], [station_id], "counting_officer"
            ) as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id], "supervisor") as (
                supervisor,
                _,
            ),
        ):
            saved = counter.put(path, json=selection(special.json()))
            assert saved.status_code == 200
            assert counter.post(path + "/submit", json=command(1)).status_code == 200
            approved = supervisor.post(path + "/approve", json=command(1, password=READY_PASSWORD))
            assert approved.status_code == 200
            original = approved.json()
            corrected = setup["officer"].put(
                setup["path"] + f"/{special.json()['id']}",
                json={
                    **setup["command"],
                    "request_id": str(uuid4()),
                    "revision": 1,
                    "reason": "Corrected replacement and found-paper reference",
                    "series": [
                        {
                            **setup["entered_series"],
                            "replacement_issued_quantity": 3,
                            "spoilt_original_quantity": 3,
                            "retrieved_found_quantity": 0,
                        }
                    ],
                },
            )
            assert corrected.status_code == 200
            retained = counter.get(path + "/revisions/1")
            assert retained.status_code == 200
            assert retained.json()["source_current"] is False
            assert retained.json()["approval_valid"] is False
            assert retained.json()["summary"] == original["summary"]
            assert retained.json()["special_papers"] == original["special_papers"]
            assert retained.json()["approved_at"] == original["approved_at"]
            assert retained.json()["summary"]["estimated_box_from_stock_quantity"] == 2
            renewed = counter.put(
                path,
                json=selection(
                    corrected.json(),
                    expected_revision=1,
                    amendment_reason="Use corrected source",
                ),
            )
            assert renewed.status_code == 200
            assert renewed.json()["revision"] == 2
            assert renewed.json()["status"] == "draft"
            assert renewed.json()["approval_valid"] is False
            assert renewed.json()["summary"]["estimated_box_from_stock_quantity"] == 3
            assert renewed.json()["summary"]["never_issued_quantity"] == 6


@pytest.mark.parametrize("same_request", [True, False])
def test_simultaneous_draft_creation_has_one_effect_and_visible_stale_conflict(
    admin: TestClient,
    database_url: str,
    same_request: bool,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id, path = special.json()["station_id"], setup["base"] + "/accounting"
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, _):
            payloads = [selection(special.json())]
            payloads.append(dict(payloads[0]) if same_request else selection(special.json()))
            clients_ready = Barrier(3)

            def save(payload: dict) -> tuple[int, dict]:
                with TestClient(create_app(database_url, now=setup["clock"])) as peer:
                    peer.headers.update(counter.headers)
                    clients_ready.wait(timeout=5)
                    response = peer.put(path, json=payload)
                    return response.status_code, response.json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(save, payload) for payload in payloads]
                clients_ready.wait(timeout=5)
                outcomes = [future.result() for future in futures]
            assert sorted(status for status, _ in outcomes) == (
                [200, 200] if same_request else [200, 409]
            )
            if same_request:
                assert outcomes[0][1] == outcomes[1][1]
            else:
                rejected = next(body for status, body in outcomes if status == 409)
                assert rejected["detail"]["code"] == "revision_conflict"
            current = counter.get(path)
            assert current.status_code == 200
            assert current.json()["record"]["revision"] == 1
            assert len(current.json()["history"]) == 1


def test_recovery_preserves_115_stock_estimate_and_replaces_approved_turnout_with_116(
    admin: TestClient,
    database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        station_id = setup["scope"]["stations"][0]["id"]
        path, officer = setup["base"] + "/accounting", setup["officer"]
        options = officer.get(setup["base"] + "/special-papers")
        assert options.status_code == 200
        special = options.json()["items"][-1]
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, _):
            original_response = counter.put(
                path,
                json=selection(
                    special,
                    turnout_period_index=2,
                    turnout_revision=1,
                ),
            )
            assert original_response.status_code == 200, original_response.text
            original = original_response.json()
            assert original["summary"]["received_quantity"] == 205
            assert original["summary"]["ordinary_at_desks_quantity"] == 85
            assert original["summary"]["ordinary_issued_quantity"] == 115
            assert original["summary"]["replacement_issued_quantity"] == 3
            assert original["summary"]["tendered_issued_quantity"] == 2
            assert original["summary"]["estimated_box_from_stock_quantity"] == 115
            assert original["summary"]["estimated_box_from_turnout_quantity"] == 115
            assert original["summary"]["observed_counted_quantity"] is None
            assert original["turnout"]["approval_valid"] is True
            assert original["turnout"]["record"]["provenance"] == "mixed"
            assert (
                original["turnout"]["record"]["source_basis"]["activation_id"]
                == (prepared["activation"]["id"])
            )
            assert counter.post(path + "/submit", json=command(1)).status_code == 200
            approved = setup["supervisor"].post(
                path + "/approve",
                json=command(1, password=READY_PASSWORD),
            )
            assert approved.status_code == 200
            assert approved.json()["approval_valid"] is True
            recovery_response = officer.post(
                setup["path"],
                json={
                    "request_id": str(uuid4()),
                    "expected_schedule_revision": 1,
                    "kind": "recovery",
                    "activation_id": prepared["activation"]["id"],
                    "activation_revision": 1,
                    "event_at": "2026-11-15T12:00:00+08:00",
                    "cumulative_quantity": 116,
                    "stock_snapshot_id": prepared["endpoint"]["id"],
                    "stock_snapshot_revision": 1,
                    "source_context": "Recovered external register: 116 at noon",
                    "reason": "Reconcile recovered turnout against 115 stock-derived estimate",
                },
            )
            assert recovery_response.status_code == 201
            recovery = recovery_response.json()
            target = setup["path"] + f"/{recovery['id']}"
            assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
            confirmed = setup["supervisor"].post(
                target + "/approve",
                json=turnout_command(1, password=READY_PASSWORD),
            )
            assert confirmed.status_code == 200
            stale = counter.get(path).json()["record"]
            assert stale["source_current"] is False
            assert stale["approval_valid"] is False
            assert stale["turnout"] == original["turnout"]
            assert stale["summary"] == original["summary"]
            turnout_path = setup["scope"]["path"]
            amended = officer.post(
                turnout_path + "/2/amend",
                json=turnout_draft(
                    expected_revision=1,
                    mode="recovery",
                    fallback_recovery_id=recovery["id"],
                    fallback_recovery_revision=1,
                    supplied_hourly=None,
                    supplied_cumulative=None,
                    event_at="2026-11-15T12:00:00+08:00",
                    source_context="Recovered external 116",
                    amendment_reason="Replace fallback endpoint with the reviewed recovered total",
                ),
            )
            assert amended.status_code == 200
            assert (
                officer.post(turnout_path + "/2/submit", json=turnout_command(2)).status_code == 200
            )
            renewed_turnout = setup["supervisor"].post(
                turnout_path + "/2/approve",
                json=turnout_command(2, password=READY_PASSWORD),
            )
            assert renewed_turnout.status_code == 200
            renewed = counter.put(
                path,
                json=selection(
                    special,
                    expected_revision=1,
                    turnout_period_index=2,
                    turnout_revision=2,
                    amendment_reason="Use reviewed recovered turnout; retain physical stock",
                ),
            )
            assert renewed.status_code == 200, renewed.text
            record = renewed.json()
            assert record["revision"] == 2
            assert record["status"] == "draft"
            assert record["summary"]["estimated_box_from_stock_quantity"] == 115
            assert record["summary"]["estimated_box_from_turnout_quantity"] == 116
            assert record["summary"]["observed_counted_quantity"] is None
            assert record["stock_snapshot"] == original["stock_snapshot"]
            assert record["turnout"]["record"]["provenance"] == "external_reconciled"
            basis = record["turnout"]["record"]["source_basis"]
            assert basis["recovery_id"] == recovery["id"]
            assert basis["stock_derived_cumulative_quantity"] == 115
            assert basis["recovered_cumulative_quantity"] == 116
            assert basis["reconciliation_difference"] == 1
            assert counter.get(path + "/revisions/1").json()["summary"] == original["summary"]


def test_new_incomplete_p12_cannot_be_hidden_by_submitting_an_older_accounting_basis(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id, path = special.json()["station_id"], setup["base"] + "/accounting"
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, _):
            original = counter.put(path, json=selection(special.json()))
            assert original.status_code == 200
            assert original.json()["source_current"] is True
            incomplete = setup["officer"].post(
                setup["base"] + "/stock-snapshots",
                json={
                    "request_id": str(uuid4()),
                    "event_at": "2026-11-15T10:00:00+08:00",
                    "counters": [],
                },
            )
            assert incomplete.status_code == 201
            assert incomplete.json()["complete"] is False
            assert incomplete.json()["ordinary_issued_quantity"] is None
            stale = counter.get(path)
            assert stale.status_code == 200
            assert stale.json()["record"]["source_current"] is False
            assert stale.json()["record"]["summary"] == original.json()["summary"]
            assert stale.json()["record"]["summary"]["observed_counted_quantity"] is None
            rejected = counter.post(path + "/submit", json=command(1))
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "accounting_source_stale"
            rejected = counter.put(path, json=selection(special.json(), expected_revision=1))
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "accounting_source_stale"
            assert len(counter.get(path).json()["history"]) == 1
