"""Queued completion reads recheck current public authentication and all-station access."""

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.box_support import box_staff
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
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
