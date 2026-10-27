"""Public outage/flagged-allocation concurrency avoids transaction lock cycles."""

import json
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from election.server.app import create_app
from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_support import stock_payload
from tests.tally_support import tally_setup
from tests.test_outage_reconciliation_edges_api import _count_draft, _create_outage_and_paper

REQUEST_KIND: ContextVar[str | None] = ContextVar("outage_lock_order_request", default=None)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lock_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def tagged_client(database_url: str, clock: Any, account: dict, kind: str) -> Iterator[TestClient]:
    application = create_app(database_url, now=clock)

    async def tagged(scope: dict, receive: Any, send: Any) -> None:
        token = REQUEST_KIND.set(kind)
        try:
            await application(scope, receive, send)
        finally:
            REQUEST_KIND.reset(token)

    with TestClient(tagged, base_url="https://testserver", raise_server_exceptions=False) as client:
        login = client.post("/api/auth/login", json={
            "username": account["username"], "password": READY_PASSWORD,
        })
        assert login.status_code == 200, login.text
        assert login.json()["account"]["must_change_password"] is False
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        yield client


@dataclass
class PassiveLockProbe:
    """Gate actual acquired locks; never alter SQL, parameters, responses or rows."""

    mode: str
    first_ready: threading.Event = field(default_factory=threading.Event)
    peer_ready: threading.Event = field(default_factory=threading.Event)
    mutex: threading.Lock = field(default_factory=threading.Lock)
    stages: list[str] = field(default_factory=list)
    errors: list[dict[str, str | int]] = field(default_factory=list)
    gate_timeouts: list[str] = field(default_factory=list)
    early_revision: bool = False
    early_active: bool = False
    first_stage_seen: bool = False

    def acquired(
        self, _connection: Any, _cursor: Any, statement: str, _parameters: Any,
        _context: Any, _executemany: bool,
    ) -> None:
        kind = REQUEST_KIND.get()
        if kind not in ("reader", "writer", "allocation", "peer"):
            return
        sql = " ".join(statement.lower().replace("`", " ").split())
        if not sql.lstrip().startswith("select") or "for update" not in sql:
            return
        table = next((name for name in (
            "application_outage_revisions", "outage_paper_records", "active_election", "elections"
        ) if "from " + name in sql), None)
        if table is None:
            return
        wait_for_peer = False
        with self.mutex:
            self.stages.append(kind + ":" + table)
            if self.mode == "reader":
                if kind == "reader" and table == "application_outage_revisions":
                    if not self.first_stage_seen:
                        self.early_revision = True
                elif kind == "reader" and table == "outage_paper_records":
                    if not self.first_stage_seen:
                        self.first_stage_seen = True
                        wait_for_peer = not self.early_revision
                        self.first_ready.set()
                elif kind == "writer" and table == "application_outage_revisions":
                    self.peer_ready.set()
            else:
                if kind == "allocation" and table == "active_election":
                    self.early_active = True
                elif kind == "allocation" and table == "elections":
                    if not self.first_stage_seen:
                        self.first_stage_seen = True
                        wait_for_peer = not self.early_active
                        self.first_ready.set()
                elif kind == "peer" and table == "active_election":
                    self.peer_ready.set()
        if wait_for_peer and not self.peer_ready.wait(5):
            with self.mutex:
                self.gate_timeouts.append(kind + ":peer-lock-not-observed")
            raise AssertionError("Passive lock arrangement did not reach its peer stage")

    def failed(self, context: Any) -> None:
        kind = REQUEST_KIND.get()
        if kind not in ("reader", "writer", "allocation", "peer"):
            return
        values = getattr(context.original_exception, "args", ())
        code = values[0] if values and type(values[0]) is int else None
        if code is not None:
            with self.mutex:
                self.errors.append({"request": kind, "code": code})


@contextmanager
def observe_locks(probe: PassiveLockProbe, case: str) -> Iterator[None]:
    event.listen(Engine, "after_cursor_execute", probe.acquired)
    event.listen(Engine, "handle_error", probe.failed)
    try:
        yield
    finally:
        probe.peer_ready.set()
        event.remove(Engine, "after_cursor_execute", probe.acquired)
        event.remove(Engine, "handle_error", probe.failed)
        folder = os.getenv("ELECTION_LOCK_ORDER_EVIDENCE_DIR")
        if folder:
            destination = Path(folder)
            destination.mkdir(parents=True, mode=0o700, exist_ok=True)
            path = destination / (case + ".json")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump({"case": case, "stages": probe.stages, "errors": probe.errors,
                           "gate_timeouts": probe.gate_timeouts,
                           "observation": "Passive stage labels/error codes only; no SQL/params"},
                          output, indent=2)
                output.write("\n")


def test_outage_detail_read_and_reasoned_amendment_finish_without_a_lock_cycle(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _options, _round_path, count_round = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        before = setup["counter"].get(outage_path)
        assert before.status_code == 200, before.text
        original = before.json()["record"]
        command = {"request_id": str(uuid4()), "expected_revision": original["revision"],
                   "reference": original["reference"], "kind": original["kind"],
                   "started_at": original["started_at"], "ended_at": original["ended_at"],
                   "notes": "A concurrent reasoned amendment must remain reportable.",
                   "amendment_reason": "Compared the signed outage interval with the network log."}
        probe = PassiveLockProbe("reader")
        with (
            tagged_client(database_url, setup["clock"], setup["accounts"]["supervisor"],
                          "reader") as reader,
            tagged_client(database_url, setup["clock"], setup["accounts"]["receiveronly"],
                          "writer") as writer,
            observe_locks(probe, "outage-read-amend"),
            ThreadPoolExecutor(max_workers=2) as workers,
        ):
            read_future = workers.submit(reader.get, outage_path)
            assert probe.first_ready.wait(5), "The public read did not acquire its paper stage"
            write_future = workers.submit(writer.put, outage_path, json=command)
            read_response, write_response = read_future.result(5), write_future.result(5)
        assert not probe.gate_timeouts, probe.gate_timeouts
        assert not probe.errors, probe.errors  # Detect1213 even if a wrapper later retries it.
        assert read_response.status_code == 200, read_response.text
        assert write_response.status_code == 200, write_response.text
        assert read_response.json()["record"]["revision"] == (
            read_response.json()["history"][0]["revision"]
        )
        final = setup["clients"]["supervisor"].get(outage_path)
        assert final.status_code == 200, final.text
        assert final.json()["record"]["revision"] == original["revision"] + 1
        assert final.json()["record"]["notes"] == command["notes"]
        assert [row["id"] for row in final.json()["record"]["paper_records"]] == [paper["id"]]


@pytest.mark.parametrize("action", ["create", "amend"])
def test_flagged_allocation_and_outage_writer_finish_without_a_lock_cycle(
    admin: TestClient, database_url: str, action: str,
) -> None:
    stations = box_stations(admin)
    station_id = stations["N1"]["id"]
    clock = BoxClock()
    base = f"/api/workspace/stations/{station_id}"
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        polling, account,
    ):
        options = polling.get(base + "/allocations")
        assert options.status_code == 200, options.text
        counter_id = options.json()["counters"][0]["id"]
        series = "LOCK-ORDER-" + uuid4().hex[:8]
        received = polling.post(base + "/stock", json=stock_payload(
            series=series, event_at="2026-11-15T08:00:00+08:00",
        ))
        assert received.status_code == 201, received.text
        allocation_path = base + "/allocations"
        allocation_revision = 0
        allocation_id = None
        if action == "amend":
            original = polling.post(allocation_path, json={
                "request_id": str(uuid4()), "counter_id": counter_id, "series": series,
                "serial_from": "000001", "serial_to": "000002",
                "event_at": "2026-11-15T08:00:00+08:00",
            })
            assert original.status_code == 201, original.text
            allocation_id, allocation_revision = original.json()["id"], original.json()["revision"]
            allocation_path += f"/{allocation_id}"
        outage_body = {"request_id": str(uuid4()), "reference": "Source outage " + uuid4().hex[:8],
                       "kind": "network", "started_at": "2026-11-15T08:00:00+08:00",
                       "ended_at": "2026-11-15T08:30:00+08:00", "notes": "Signed paper."}
        outage = polling.post(base + "/outages", json=outage_body)
        assert outage.status_code == 201, outage.text
        target = {"counter_id": counter_id}
        if allocation_id is not None:
            target["allocation_id"] = allocation_id
        paper_response = polling.post(base + f"/outages/{outage.json()['id']}/paper-records", json={
            "request_id": str(uuid4()), "expected_outage_revision": outage.json()["revision"],
            "paper_reference": "LOCK-PAPER-" + uuid4().hex[:8], "workflow": "allocation",
            "action": action, "original_event_at": "2026-11-15T08:15:00+08:00",
            "target": target, "notes": "The public paper-aware allocation is concurrent.",
        })
        assert paper_response.status_code == 201, paper_response.text
        request_id = str(uuid4())
        command = {"request_id": request_id, "counter_id": counter_id, "series": series,
                   "serial_from": "000001", "serial_to": "000003",
                   "event_at": "2026-11-15T08:15:00+08:00",
                   "paper_record_id": paper_response.json()["id"]}
        if action == "amend":
            command.update(
                revision=allocation_revision, reason="Matched the original signed range.",
            )
        peer_body = {**outage_body, "request_id": str(uuid4()),
                     "reference": "Concurrent peer outage " + uuid4().hex[:8]}
        probe = PassiveLockProbe("allocation")
        with (
            tagged_client(database_url, clock, account, "allocation") as allocation_client,
            tagged_client(database_url, clock, account, "peer") as peer,
            observe_locks(probe, "allocation-" + action),
            ThreadPoolExecutor(max_workers=2) as workers,
        ):
            send = allocation_client.post if action == "create" else allocation_client.put
            allocation_future = workers.submit(send, allocation_path, json=command)
            assert probe.first_ready.wait(5), "Allocation did not acquire its election stage"
            peer_future = workers.submit(peer.post, base + "/outages", json=peer_body)
            allocation_response, peer_response = allocation_future.result(5), peer_future.result(5)
        assert not probe.gate_timeouts, probe.gate_timeouts
        assert not probe.errors, probe.errors
        assert allocation_response.status_code == (201 if action == "create" else 200)
        assert peer_response.status_code == 201, peer_response.text
        assert allocation_response.json()["quantity"] == 3
        current = polling.get(base + f"/outages/{outage.json()['id']}")
        assert current.status_code == 200, current.text
        entered = next(row for row in current.json()["record"]["paper_records"]
                       if row["id"] == paper_response.json()["id"])
        assert entered["status"] == "entered"
        assert entered["reentry"]["request_id"] == request_id
        assert entered["reentry"]["record"] == allocation_response.json()
