"""Queued recount requests recheck authority after an Administrator revokes access."""

import json
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.box_support import READY_PASSWORD, box_staff
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_outage_lock_order_api import REQUEST_KIND, tagged_client


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_revocation_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class AuthenticatedRequestGate:
    """Pause one actual DB call after authentication, without changing its SQL or rows."""

    ready: threading.Event = field(default_factory=threading.Event)
    resume: threading.Event = field(default_factory=threading.Event)
    session_read: bool = False
    account_read: bool = False
    entered: bool = False
    timed_out: bool = False

    def before(
        self, _connection: Any, _cursor: Any, statement: str, _parameters: Any,
        _context: Any, _executemany: bool,
    ) -> None:
        if REQUEST_KIND.get() != "recount-revocation":
            return
        sql = " ".join(statement.lower().replace("`", " ").split())
        if not sql.startswith("select"):
            return
        if "from sessions" in sql:
            self.session_read = True
        if "from accounts" in sql:
            self.account_read = True
        if "from active_election" not in sql or "for update" not in sql or self.entered:
            return
        assert self.session_read and self.account_read
        self.entered = True
        self.ready.set()
        if not self.resume.wait(5):
            self.timed_out = True
            raise AssertionError("Revocation arrangement was not explicitly released")


@contextmanager
def gate_authenticated_request(gate: AuthenticatedRequestGate) -> Iterator[None]:
    event.listen(Engine, "before_cursor_execute", gate.before)
    try:
        yield
    finally:
        gate.resume.set()
        event.remove(Engine, "before_cursor_execute", gate.before)


@pytest.mark.parametrize("operation", ["create", "replay", "outcome", "local"])
@pytest.mark.parametrize("revocation", ["remove_station", "disable"])
def test_queued_recount_request_cannot_use_authority_revoked_after_authentication(
    admin: TestClient, database_url: str, operation: str, revocation: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        account = setup["accounts"]["supervisor"]
        target = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        assert options["can_instruct"] is True
        setup["clock"].value += timedelta(minutes=10)
        request_id = str(uuid4())
        command = {
            "request_id": request_id, "basis_digest": options["basis_digest"],
            "scope_sources": options["scope_sources"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "A queued request must not retain revoked constituency authority.",
            "password": READY_PASSWORD,
        }
        queued_target = target
        if operation == "local":
            source = options["scope_sources"][0]
            queued_target = (
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}/recounts"
            )
            command = {
                "request_id": request_id,
                "scope_revision": source["scope_revision"],
                "expected_selection_revision": source["expected_selection_revision"],
                "source_round_id": source["source_round_id"],
                "source_round_revision": source["source_round_revision"],
                "event_at": command["event_at"], "reason": command["reason"],
                "password": READY_PASSWORD,
            }
        if operation in {"replay", "outcome"}:
            committed = supervisor.post(target, json=command)
            assert committed.status_code == 201, committed.text
        settings_response = admin.get(f"/api/accounts/{account['id']}")
        assert settings_response.status_code == 200, settings_response.text
        settings = settings_response.json()
        station_ids = [row["id"] for row in setup["stations"].values()]
        with (
            box_staff(admin, database_url, setup["clock"], "supervisor", station_ids) as (
                observer, _,
            ),
            tagged_client(database_url, setup["clock"], account, "recount-revocation") as caller,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            initial = observer.get(target)
            assert initial.status_code == 200, initial.text
            expected_instruction_count = 1 if operation in {"replay", "outcome"} else 0
            assert len(initial.json()["instructions"]) == expected_instruction_count
            paths = [
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}/rounds"
                for source in options["scope_sources"]
            ]
            before_rounds = {}
            for path in paths:
                response = observer.get(path)
                assert response.status_code == 200, response.text
                before_rounds[path] = {row["id"] for row in response.json()["rounds"]}
            gate = AuthenticatedRequestGate()
            with gate_authenticated_request(gate):
                if operation == "outcome":
                    path = (
                        f"/api/workspace/constituencies/{setup['constituency_id']}"
                        f"/request-outcomes/{request_id}?workflow=constituency_recount"
                    )
                    future = pool.submit(caller.get, path)
                else:
                    future = pool.submit(caller.post, queued_target, json=command)
                try:
                    assert gate.ready.wait(5), "Actual authenticated request never reached its gate"
                    remaining = list(settings["station_ids"])
                    if revocation == "remove_station":
                        code = "N1" if operation == "local" else "N2"
                        remaining.remove(setup["stations"][code]["id"])
                    changed = admin.put(f"/api/accounts/{account['id']}", json={
                        "revision": settings["revision"],
                        "display_name": settings["display_name"], "role": "supervisor",
                        "enabled": revocation != "disable", "station_ids": remaining,
                    })
                    assert changed.status_code == 200, changed.text
                    assert changed.json()["revision"] == settings["revision"] + 1
                    assert changed.json()["enabled"] is (revocation != "disable")
                finally:
                    gate.resume.set()
                response = future.result(timeout=8)
            assert gate.entered and not gate.timed_out
            after = observer.get(target)
            assert after.status_code == 200, after.text
            after_rounds = {}
            for path in paths:
                current = observer.get(path)
                assert current.status_code == 200, current.text
                after_rounds[path] = {row["id"] for row in current.json()["rounds"]}
            fresh_auth = caller.get("/api/auth/me")
            assert fresh_auth.status_code == 401
            folder = os.getenv("ELECTION_LOCK_ORDER_EVIDENCE_DIR")
            if folder:
                destination = Path(folder)
                destination.mkdir(parents=True, mode=0o700, exist_ok=True)
                evidence = destination / f"recount-revocation-{operation}-{revocation}.json"
                descriptor = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump({
                        "operation": operation, "revocation": revocation,
                        "authenticated_session_and_account_read_before_gate": (
                            gate.session_read and gate.account_read
                        ),
                        "barrier": "Passive DBAPI pause before first ActiveElection locking read",
                        "SQL_parameters_responses_or_rows_replaced": False,
                        "gate_timed_out": gate.timed_out,
                        "revocation_committed": changed.status_code == 200,
                        "queued_response_status": response.status_code,
                        "fresh_auth_status": fresh_auth.status_code,
                        "instructions_before": expected_instruction_count,
                        "instructions_after": len(after.json()["instructions"]),
                        "round_counts_before": [len(before_rounds[path]) for path in paths],
                        "round_counts_after": [len(after_rounds[path]) for path in paths],
                    }, output, indent=2)
                    output.write("\n")
            assert response.status_code == 401, response.text
            assert response.json() == {"detail": {"code": "session_expired"}}
            assert len(after.json()["instructions"]) == expected_instruction_count
            assert after_rounds == before_rounds
