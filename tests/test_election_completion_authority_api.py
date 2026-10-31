"""Queued completion reads recheck current public authentication and all-station access."""

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_staff
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import (
    lifecycle_database_url,
    lifecycle_test_state,
    prepared_election,
)
from tests.polling_support import transition_payload
from tests.test_constituency_recount_revocation_api import (
    AuthenticatedRequestGate,
    gate_authenticated_request,
)
from tests.test_outage_lock_order_api import tagged_client


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_completion_authority(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("revocation", ["disable", "remove_origin", "logout"])
def test_queued_completion_rechecks_revocation_or_logout_after_authentication(
    admin: TestClient, database_url: str, revocation: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        account = setup["accounts"]["supervisor"]
        response = admin.get(f"/api/accounts/{account['id']}")
        assert response.status_code == 200, response.text
        settings = response.json()
        station_ids = [row["id"] for row in setup["stations"].values()]
        with (
            box_staff(admin, database_url, setup["clock"], "supervisor", station_ids) as (
                observer, _,
            ),
            tagged_client(
                database_url, setup["clock"], account, "recount-revocation"
            ) as caller,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            before = observer.get(setup["completion_path"])
            assert before.status_code == 200, before.text
            assert before.json()["can_finalize"] is True
            gate = AuthenticatedRequestGate()
            with gate_authenticated_request(gate):
                future = pool.submit(caller.get, setup["completion_path"])
                try:
                    assert gate.ready.wait(5), "Authenticated completion did not reach its gate"
                    if revocation == "logout":
                        changed = caller.delete("/api/auth/session")
                        assert changed.status_code == 204, changed.text
                    else:
                        remaining = list(settings["station_ids"])
                        if revocation == "remove_origin":
                            remaining.remove(setup["stations"]["N2"]["id"])
                        changed = admin.put(f"/api/accounts/{account['id']}", json={
                            "revision": settings["revision"],
                            "display_name": settings["display_name"], "role": "supervisor",
                            "enabled": revocation != "disable", "station_ids": remaining,
                        })
                        assert changed.status_code == 200, changed.text
                        assert changed.json()["revision"] == settings["revision"] + 1
                finally:
                    gate.resume.set()
                queued = future.result(timeout=8)
            assert gate.entered and gate.session_read and gate.account_read
            assert not gate.timed_out
            after = observer.get(setup["completion_path"])
            assert after.status_code == 200, after.text
            fresh = caller.get("/api/auth/me")
            folder = os.getenv("ELECTION_LOCK_ORDER_EVIDENCE_DIR")
            if folder:
                path = Path(folder)
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                target = path / ("completion-queued-" + revocation + ".json")
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump({
                        "case": revocation, "actual_public_change_status": changed.status_code,
                        "session_and_account_read_before_gate": True,
                        "gate_timed_out": gate.timed_out,
                        "queued_status": queued.status_code, "fresh_auth_status": fresh.status_code,
                        "same_reviewed_basis": (
                            after.json()["basis_digest"] == before.json()["basis_digest"]
                        ),
                        "SQL_parameters_rows_and_responses_replaced": False,
                    }, output, indent=2)
            assert queued.status_code == 401, queued.text
            assert queued.json() == {"detail": {"code": "session_expired"}}
            assert fresh.status_code == 401
            assert after.json()["basis_digest"] == before.json()["basis_digest"]


def test_queued_finalization_rechecks_a_polling_amendment_after_authentication(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        polling = setup["clients"]["polling"]
        account = setup["accounts"]["supervisor"]
        election_id = setup["election"]["id"]
        station_id = setup["stations"]["N2"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        polling_path = f"/api/workspace/stations/{station_id}/polling/service_completion"
        original = setup["polling_completion_records"]["N2"]
        assert original["revision"] == 1 and original["status"] == "approved"
        before_response = supervisor.get(setup["completion_path"])
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["can_finalize"] is True
        request_id = str(uuid4())
        command = {
            "request_id": request_id,
            "expected_election_revision": before["election"]["revision"],
            "basis_digest": before["basis_digest"], "password": BOX_READY_PASSWORD,
        }
        reason = "Correct N2 service completion from the signed station duty log."
        with (
            tagged_client(database_url, setup["clock"], account, "recount-revocation") as caller,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            gate = AuthenticatedRequestGate()
            with gate_authenticated_request(gate):
                future = pool.submit(caller.post, base + "/finalizations", json=command)
                try:
                    assert gate.ready.wait(5), "Authenticated finalization did not reach its gate"
                    changed_response = polling.post(
                        polling_path + "/amend", json=transition_payload(
                            original["revision"], reason=reason,
                            event_at="2026-11-15T22:36:00+08:00", estimated_clear_at=None,
                        ),
                    )
                    assert changed_response.status_code == 200, changed_response.text
                    changed = changed_response.json()
                    assert changed["revision"] == 2 and changed["status"] == "draft"
                    assert changed["approved_at"] is None and changed["approved_by"] is None
                    assert changed["amendment_reason"] == reason
                finally:
                    gate.resume.set()
                queued = future.result(timeout=8)
            assert gate.entered and gate.session_read and gate.account_read
            assert not gate.timed_out
            assert queued.status_code == 409, queued.text
            assert queued.json() == {"detail": {"code": "election_completion_basis_conflict"}}
            after_response = supervisor.get(setup["completion_path"])
            assert after_response.status_code == 200, after_response.text
            after = after_response.json()
            assert after["election"] == before["election"]
            assert after["active_election_id"] == election_id
            assert after["can_finalize"] is False
            assert after["basis_digest"] != before["basis_digest"]
            assert {
                "code": "polling_completion_approval_required", "station_id": station_id,
                "constituency_id": setup["stations"]["N2"]["constituency_id"],
                "revision": 2, "status": "draft",
            } in after["blockers"]
            latest = next(
                row["record"] for row in after["sources"]["polling_completion"]
                if row["station_id"] == station_id
            )
            assert latest["revision"] == 2 and latest["status"] == "draft"
            assert latest["event_at"] == "2026-11-15T14:36:00Z"
            assert latest["amendment_reason"] == reason and latest["approved_at"] is None
            history = polling.get(polling_path + "/history")
            assert history.status_code == 200, history.text
            assert history.json()["items"] == [original, changed]
            outcome = caller.get(
                base + f"/request-outcomes/{request_id}?workflow=election_completion"
            )
            assert outcome.status_code == 200, outcome.text
            assert outcome.json() == {
                "request_id": request_id, "workflow": "election_completion", "status": "not_found",
            }
            active = supervisor.get("/api/active-election")
            assert active.status_code == 200, active.text
            assert active.json()["election"]["id"] == election_id
            assert active.json()["election"]["status"] == "active"
            assert active.json()["election"]["revision"] == before["election"]["revision"]
            folder = os.getenv("ELECTION_LOCK_ORDER_EVIDENCE_DIR")
            if folder:
                destination = Path(folder)
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
                target = destination / "completion-finalization-source-amendment.json"
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump({
                        "case": "finalization-after-polling-amendment",
                        "session_and_account_read_before_gate": (
                            gate.session_read and gate.account_read
                        ),
                        "gate_timed_out": gate.timed_out,
                        "actual_source_amendment_status": changed_response.status_code,
                        "current_source_revision": changed["revision"],
                        "current_source_status": changed["status"],
                        "queued_finalization_status": queued.status_code,
                        "basis_changed": after["basis_digest"] != before["basis_digest"],
                        "election_revision_unchanged": (
                            after["election"]["revision"] == before["election"]["revision"]
                        ),
                        "active_election_retained": after["active_election_id"] == election_id,
                        "original_request_status": outcome.json()["status"],
                        "SQL_parameters_rows_and_responses_replaced": False,
                    }, output, indent=2)
                    output.write("\n")


def test_reopening_and_other_election_activation_share_one_atomic_active_slot(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        competing, planned = prepared_election(admin)
        assert competing["id"] != election_id
        reviewed_response = supervisor.get(setup["completion_path"])
        assert reviewed_response.status_code == 200, reviewed_response.text
        reviewed = reviewed_response.json()
        assert reviewed["can_finalize"] is True
        finalized_response = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized_response.status_code == 201, finalized_response.text
        original = finalized_response.json()
        active_before = admin.get("/api/active-election")
        assert active_before.status_code == 200, active_before.text
        assert active_before.json()["election"] is None
        request_id = str(uuid4())
        reason = "Reopen the retained signed outcome while contending for the single active slot."
        reopening = {
            "request_id": request_id,
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": original["event"]["id"],
            "reason": reason, "password": BOX_READY_PASSWORD,
        }
        activation = {
            "election_revision": competing["revision"], "schedule_revision": planned["revision"],
        }
        start = Barrier(2)

        def contend(kind: str) -> tuple[int, object]:
            # Preserve the real clock under which each normal session was issued.
            application = (
                create_app(database_url, now=setup["clock"])
                if kind == "reopening" else create_app(database_url)
            )
            with TestClient(application, base_url="https://testserver") as caller:
                caller.headers.update(supervisor.headers if kind == "reopening" else admin.headers)
                path = (
                    base + "/reopenings" if kind == "reopening"
                    else f"/api/elections/{competing['id']}/activate"
                )
                body = reopening if kind == "reopening" else activation
                start.wait(timeout=5)
                response = caller.post(path, json=body)
                try:
                    response_body = response.json()
                except ValueError:
                    response_body = response.text
                return response.status_code, response_body

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {kind: pool.submit(contend, kind) for kind in ("reopening", "activation")}
            outcomes = {kind: future.result(timeout=8) for kind, future in futures.items()}
        reopening_status, reopening_body = outcomes["reopening"]
        activation_status, activation_body = outcomes["activation"]
        active_response = admin.get("/api/active-election")
        current_a_response = supervisor.get(setup["completion_path"])
        current_b_response = admin.get(f"/api/elections/{competing['id']}")
        history_response = supervisor.get(base + "/completion/history")
        outcome_path = base + f"/request-outcomes/{request_id}?workflow=election_completion"
        reopening_outcome = supervisor.get(outcome_path)
        original_outcome = supervisor.get(
            base + f"/request-outcomes/{original['request_id']}?workflow=election_completion"
        )
        observed_winners = [
            kind for kind, status, success in (
                ("reopening", reopening_status, 201), ("activation", activation_status, 200),
            ) if status == success
        ]
        folder = os.getenv("ELECTION_LOCK_ORDER_EVIDENCE_DIR")
        if folder:
            destination = Path(folder)
            destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                destination / "completion-reopening-versus-activation.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({
                    "case": "one-public-reopening-versus-activation-race",
                    "reopening_status": reopening_status, "activation_status": activation_status,
                    "observed_successes": observed_winners,
                    "scheduling_branches_exercised": observed_winners,
                    "race_attempts": 1, "barrier_participants": 2,
                    "real_HTTP_clients": 2, "SQL_gates_sleeps_retries_or_replacements": False,
                    "public_read_statuses": {
                        "active": active_response.status_code,
                        "election_a": current_a_response.status_code,
                        "election_b": current_b_response.status_code,
                        "history_a": history_response.status_code,
                        "reopening_outcome": reopening_outcome.status_code,
                        "original_outcome": original_outcome.status_code,
                    },
                }, output, indent=2)
                output.write("\n")
        assert (reopening_status, activation_status) in {(201, 409), (409, 200)}, outcomes
        assert len(observed_winners) == 1
        assert active_response.status_code == 200, active_response.text
        assert current_a_response.status_code == 200, current_a_response.text
        assert current_b_response.status_code == 200, current_b_response.text
        assert history_response.status_code == 200, history_response.text
        assert reopening_outcome.status_code == 200, reopening_outcome.text
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json() == {
            "request_id": original["request_id"], "workflow": "election_completion",
            "status": "committed", "record": original,
        }
        active = active_response.json()["election"]
        current_a = current_a_response.json()
        current_b = current_b_response.json()
        history = history_response.json()
        assert isinstance(active, dict)
        assert isinstance(reopening_body, dict) and isinstance(activation_body, dict)
        if reopening_status == 201:
            assert activation_body == {"detail": {"code": "active_election_conflict"}}
            receipt = reopening_body
            assert receipt["request_id"] == request_id
            assert receipt["election"] == {
                **original["election"], "status": "active",
                "revision": original["election"]["revision"] + 1,
            }
            assert receipt["active_election_id"] == election_id
            assert receipt["event"]["kind"] == "reopening"
            assert receipt["event"]["previous_finalization_id"] == original["event"]["id"]
            assert receipt["event"]["reason"] == reason
            assert receipt["event"]["actor_id"] == setup["accounts"]["supervisor"]["id"]
            assert current_a["election"] == receipt["election"]
            assert current_a["active_election_id"] == election_id
            assert active["id"] == election_id and active["status"] == "active"
            assert active["revision"] == receipt["election"]["revision"]
            assert current_b["status"] == "draft"
            assert current_b["revision"] == competing["revision"]
            assert reopening_outcome.json() == {
                "request_id": request_id, "workflow": "election_completion",
                "status": "committed", "record": receipt,
            }
            assert history["events"] == [receipt["event"], original["event"]]
            assert history["election"] == receipt["election"]
            assert history["active_election_id"] == election_id
        else:
            assert reopening_body == {"detail": {"code": "active_election_conflict"}}
            assert active_response.json() == activation_body
            assert active["id"] == competing["id"] and active["status"] == "active"
            assert active["revision"] == competing["revision"] + 1
            assert current_b["status"] == "active"
            assert current_b["revision"] == competing["revision"] + 1
            assert current_a["election"] == original["election"]
            assert current_a["active_election_id"] == competing["id"]
            assert reopening_outcome.json() == {
                "request_id": request_id, "workflow": "election_completion", "status": "not_found",
            }
            assert history["events"] == [original["event"]]
            assert history["election"] == original["election"]
            assert history["active_election_id"] == competing["id"]
