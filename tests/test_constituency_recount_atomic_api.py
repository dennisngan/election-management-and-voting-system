"""An actual database-connection loss cannot leave half a wide instruction.

The passive hook only schedules the transport fault and identifies its live
connection. All business checks use public HTTP. Recount audit data has no public
read endpoint, so this case makes no separate audit-row verification claim.
"""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymysql.connections import Connection as MySQLConnection
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine, make_url

from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup

ATOMIC_POST: ContextVar[object | None] = ContextVar("constituency_atomic_post", default=None)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _assert_same_leased_database(driver: MySQLConnection, expected: URL) -> None:
    assert expected.drivername == "mysql+pymysql"
    assert expected.database and expected.database.endswith("_lifecycle_test")
    assert isinstance(driver, MySQLConnection) and driver.open
    assert driver.host == (expected.host or "localhost")
    assert driver.port == (expected.port or 3306)
    database = driver.db.decode(driver.encoding) if isinstance(driver.db, bytes) else driver.db
    assert database == expected.database


@dataclass
class FirstLocalInsertTransportGate:
    database_url: str = field(repr=False)
    path: str
    armed: bool = False
    entered: bool = False
    timed_out: bool = False
    target_thread_id: int = 0
    target_driver: Any = field(default=None, repr=False)
    ready: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def after(
        self, connection: Any, _cursor: Any, statement: str, _parameters: Any,
        _context: Any, _executemany: bool,
    ) -> None:
        if ATOMIC_POST.get() is not self or self.entered:
            return
        sql = " ".join(statement.lower().replace("`", " ").split())
        if not sql.startswith("insert into local_recount_instructions "):
            return
        # The real INSERT has already executed inside the request transaction.
        # Retain its actual driver connection while the caller identifies it;
        # this callback never changes SQL, parameters, rows or ASGI responses.
        expected = make_url(self.database_url)
        assert connection.engine.url == expected
        assert connection.in_transaction()
        driver = connection.connection.driver_connection
        _assert_same_leased_database(driver, expected)
        thread_id = driver.thread_id()
        assert type(thread_id) is int and thread_id > 0
        self.target_driver, self.target_thread_id = driver, thread_id
        self.entered = True
        self.ready.set()
        if not self.release.wait(5):
            self.timed_out = True
            raise AssertionError("The owned first-local transport gate was not explicitly released")


@contextmanager
def _observe_first_local_insert(gate: FirstLocalInsertTransportGate) -> Iterator[None]:
    event.listen(Engine, "after_cursor_execute", gate.after)
    try:
        yield
    finally:
        gate.armed = False
        gate.release.set()
        event.remove(Engine, "after_cursor_execute", gate.after)


@contextmanager
def _atomic_caller(
    database_url: str, clock: Any, account: dict, gate: FirstLocalInsertTransportGate,
) -> Iterator[TestClient]:
    application = create_app(database_url, now=clock)

    async def tag_only_the_armed_wide_post(scope: dict, receive: Any, send: Any) -> None:
        tagged = (
            gate.armed and scope.get("type") == "http"
            and scope.get("method") == "POST" and scope.get("path") == gate.path
        )
        token = ATOMIC_POST.set(gate if tagged else None)
        try:
            await application(scope, receive, send)
        finally:
            ATOMIC_POST.reset(token)

    with TestClient(
        tag_only_the_armed_wide_post, base_url="https://testserver", raise_server_exceptions=False,
    ) as client:
        response = client.post("/api/auth/login", json={
            "username": account["username"], "password": READY_PASSWORD,
        })
        assert response.status_code == 200, response.text
        assert response.json()["account"]["must_change_password"] is False
        client.headers["Authorization"] = "Bearer " + response.json()["token"]
        yield client


def test_connection_loss_after_first_local_insert_rolls_back_the_entire_wide_instruction(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        mixed = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}"
        target, result_path = base + "/recounts", base + "/results"
        before_result_response = supervisor.get(result_path)
        assert before_result_response.status_code == 200, before_result_response.text
        before_result = before_result_response.json()
        assert before_result["complete"] is True and before_result["pending"] == []
        assert [row["quantity"] for row in before_result["candidate_totals"]] == [6, 4]
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        assert options["can_instruct"] is True and options["instructions"] == []
        assert len(options["scope_sources"]) == 2
        priors = {setup["scope"]["id"]: mixed, setup["n3_scope"]["id"]: setup["n3_round"]}
        snapshots = {target: options, result_path: before_result}
        for source in options["scope_sources"]:
            scope_path = (
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}"
            )
            for path in (scope_path + "/rounds", scope_path + "/recounts",
                         priors[source["scope_id"]]["round_path"]):
                response = supervisor.get(path)
                assert response.status_code == 200, response.text
                snapshots[path] = response.json()
            assert snapshots[scope_path + "/recounts"]["instructions"] == []
            assert len(snapshots[scope_path + "/rounds"]["rounds"]) == 1
        setup["clock"].value += timedelta(minutes=10)
        request_id = str(uuid4())
        outcome_path = base + f"/request-outcomes/{request_id}?workflow=constituency_recount"
        command = {
            "request_id": request_id, "basis_digest": options["basis_digest"],
            "scope_sources": options["scope_sources"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "A transport failure must preserve both reviewed source scopes atomically.",
            "password": READY_PASSWORD,
        }
        missing = supervisor.get(outcome_path)
        assert missing.status_code == 200, missing.text
        assert missing.json() == {
            "request_id": request_id, "workflow": "constituency_recount", "status": "not_found",
        }
        gate = FirstLocalInsertTransportGate(database_url, target)
        # Establish and verify the separate connection before arming the request.
        # It uses the exact leased URL, bounded network timeouts and no new grants.
        killer_engine = create_engine(database_url, pool_pre_ping=True, connect_args={
            "charset": "utf8mb4", "connect_timeout": 5, "read_timeout": 5, "write_timeout": 5,
        })
        killer = None
        try:
            killer = killer_engine.raw_connection()
            killer_driver = killer.driver_connection
            _assert_same_leased_database(killer_driver, make_url(database_url))
            killer_id = killer_driver.thread_id()
            assert type(killer_id) is int and killer_id > 0
            with (
                _atomic_caller(
                    database_url, setup["clock"], setup["accounts"]["supervisor"], gate,
                ) as caller,
                _observe_first_local_insert(gate),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                gate.armed = True
                future = pool.submit(caller.post, target, json=command)
                kill_issued = False
                try:
                    assert gate.ready.wait(5), (
                        "The actual wide POST never reached its first local INSERT"
                    )
                    assert gate.entered and not gate.timed_out
                    target_id = gate.target_thread_id
                    assert type(target_id) is int and target_id > 0 and target_id != killer_id
                    _assert_same_leased_database(gate.target_driver, make_url(database_url))
                    assert gate.target_driver.thread_id() == target_id
                    assert gate.target_driver is not killer_driver
                    assert gate.target_driver.user == killer_driver.user
                    # Only this still-held, positively identified request connection
                    # is interrupted. No process-wide kill or business SQL occurs.
                    killer_driver.query(f"KILL CONNECTION {target_id:d}")
                    kill_issued = True
                finally:
                    gate.armed = False
                    gate.release.set()
                failed = future.result(timeout=8)
                assert kill_issued and gate.entered and not gate.timed_out
                # This is the app's existing SQLAlchemyError HTTP contract. A
                # different actual failure remains a failure for Root to diagnose.
                assert failed.status_code == 503, failed.text
                assert failed.json() == {"detail": {"code": "database_unavailable"}}

                # Public snapshots prove every observable parent/local/round/result
                # effect is absent; no business or audit tables are queried directly.
                for path, original in snapshots.items():
                    unchanged = supervisor.get(path)
                    assert unchanged.status_code == 200, unchanged.text
                    assert unchanged.json() == original
                uncommitted = supervisor.get(outcome_path)
                assert uncommitted.status_code == 200 and uncommitted.json() == missing.json()

                # One explicit retry keeps its original UUID/body and commits the
                # whole required set through the normal route, with the gate disarmed.
                retried = caller.post(target, json=command)
                assert retried.status_code == 201, retried.text
                receipt = retried.json()
                assert receipt["instruction"]["request_id"] == request_id
                assert receipt["instruction"]["member_count"] == 2
                assert len(receipt["members"]) == 2
                assert len({member["round"]["id"] for member in receipt["members"]}) == 2
                history = supervisor.get(target)
                assert history.status_code == 200, history.text
                assert len(history.json()["instructions"]) == 1
                assert history.json()["instructions"][0]["id"] == receipt["instruction"]["id"]
                committed = supervisor.get(outcome_path)
                assert committed.status_code == 200, committed.text
                assert committed.json() == {
                    "request_id": request_id, "workflow": "constituency_recount",
                    "status": "committed", "record": receipt,
                }
                for source, member in zip(
                    options["scope_sources"], receipt["members"], strict=True,
                ):
                    scope_path = (
                        f"/api/workspace/stations/{source['station_id']}"
                        f"/counting-scopes/{source['scope_id']}"
                    )
                    listed = supervisor.get(scope_path + "/rounds")
                    assert listed.status_code == 200, listed.text
                    assert len(listed.json()["rounds"]) == 2
                    assert {row["id"] for row in listed.json()["rounds"]} == {
                        source["source_round_id"], member["round"]["id"],
                    }
                    assert listed.json()["selection"] == (
                        snapshots[scope_path + "/rounds"]["selection"]
                    )
                    local = supervisor.get(scope_path + "/recounts")
                    assert local.status_code == 200, local.text
                    assert len(local.json()["instructions"]) == 1
                    assert local.json()["instructions"][0]["id"] == member["instruction"]["id"]
                    old_path = priors[source["scope_id"]]["round_path"]
                    preserved = supervisor.get(old_path)
                    assert preserved.status_code == 200, preserved.text
                    original = snapshots[old_path]
                    assert [row["revision_id"] for row in preserved.json()["history"]] == [
                        row["revision_id"] for row in original["history"]
                    ]
                    for key in (
                        "id", "revision", "revision_id", "status", "candidate_votes",
                        "invalid_papers",
                        "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                        "approved_at", "approved_by",
                    ):
                        assert preserved.json()["record"][key] == original["record"][key]
        finally:
            gate.armed = False
            gate.release.set()
            try:
                if killer is not None:
                    killer.close()
            finally:
                killer_engine.dispose()
