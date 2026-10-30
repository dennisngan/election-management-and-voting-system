"""Queued completion reads recheck current public authentication and all-station access."""

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_staff
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
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
