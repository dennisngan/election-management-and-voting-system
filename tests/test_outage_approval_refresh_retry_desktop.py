"""Original outage-approval retry survives refresh and preserves current membership."""

import json
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.tally_support import tally_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_workflow_retry_desktop import LostSelectionResponse, TransparentTlsProxy
from tests.test_outage_reconciliation_edges_api import _count_draft, _create_outage_and_paper
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_outage_approval_retry(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class OutageApprovalResponseLoss(LostSelectionResponse):
    arm_current_after_path: str = ""
    current_read_path: str = ""
    block_current_reads: bool = False
    current_read_tagged: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def lost_outage_approval_response(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[OutageApprovalResponseLoss]:
    """Drop only a real committed POST/approve200 reply through the opaque proxy."""
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare local TLS with election.manage tls-dev"
    backend_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    backend_listener.bind(("127.0.0.1", 0))
    backend_listener.listen()
    backend_port = backend_listener.getsockname()[1]
    client_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_listener.bind(("127.0.0.1", 0))
    client_listener.listen()
    endpoint = OutageApprovalResponseLoss(
        f"https://localhost:{client_listener.getsockname()[1]}", ControlledClock()
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def drop_after_real_approval(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        peer = request.client
        if response.status_code == 200 and peer is not None:
            with endpoint.lock:
                if request.method == "POST" and request.url.path == endpoint.arm_current_after_path:
                    endpoint.block_current_reads = True
                    endpoint.arm_current_after_path = ""
                original_reply = request.method == "POST" and request.url.path == endpoint.drop_path
                current_reply = (request.method == "GET" and endpoint.block_current_reads
                                 and request.url.path == endpoint.current_read_path)
                if original_reply or current_reply:
                    endpoint.drop_peer = (peer.host, peer.port)
                    if original_reply:
                        endpoint.drop_path = ""
                    if current_reply:
                        endpoint.current_read_tagged.set()
                    endpoint.response_tagged.set()
        return response  # Actual handler response; no substituted503 or business DTO.

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=backend_port, loop="asyncio", ws="none",
        ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
        ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
        log_level="warning", access_log=False,
        timeout_keep_alive=5, timeout_graceful_shutdown=1,
    ))
    server_thread = threading.Thread(
        target=server.run, kwargs={"sockets": [backend_listener]}, daemon=True
    )
    proxy = TransparentTlsProxy(client_listener, backend_port, endpoint)
    server_thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        proxy.start()
        yield endpoint
    finally:
        proxy.stop()
        server.should_exit = True
        wait_for(qt_app, lambda: not server_thread.is_alive())
        server_thread.join(timeout=0)
        backend_listener.close()
        client_listener.close()
        assert not server_thread.is_alive(), "The owned outage-approval HTTPS server did not stop"


@pytest.mark.parametrize("add_pending_paper", [False, True], ids=["unchanged", "new-pending"])
def test_uncertain_outage_approval_retries_original_after_refresh_and_reads_current_membership(
    admin: TestClient,
    database_url: str,
    lost_outage_approval_response: LostSelectionResponse,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    add_pending_paper: bool,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "outage-refresh-retry"))
    with tally_setup(admin, database_url) as setup:
        endpoint = lost_outage_approval_response
        endpoint.clock.value = setup["clock"].value
        counter, supervisor = setup["counter"], setup["clients"]["supervisor"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        options, round_path, count_round = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        submitted = counter.post(round_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 2,
            "scope_revision": options["scope"]["revision"], "paper_record_id": paper["id"],
        })
        assert submitted.status_code == 200, submitted.text
        ready_response = supervisor.get(outage_path)
        assert ready_response.status_code == 200, ready_response.text
        ready = ready_response.json()
        original_record = ready["record"]
        outage_id = original_record["id"]
        assert original_record["reconciled"] is False
        assert original_record["reconciliation_history"] == []
        assert len(original_record["paper_records"]) == 1
        assert original_record["paper_records"][0]["status"] == "entered"
        assert original_record["paper_records"][0]["reentry"]["record"] == submitted.json()
        approval_path = outage_path + "/approve"
        reason = "Settle this original reconciliation against its signed paper and receipt."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, _editor):
            outages = client.property("outages")
            assert isinstance(outages, QObject)
            outages.open()
            wait_for_editor_idle(qt_app, outages)
            assert outages.loadOutage(outage_id, False) is True
            wait_for_editor_idle(qt_app, outages)
            assert_public_business_fields(outages.property("state")["selected"], original_record)
            pending_ids: set[str] = set()

            def retain_public_request_identity() -> None:
                request = outages.property("state")["pending_request_id"]
                if request:
                    pending_ids.add(request)

            outages.stateChanged.connect(retain_public_request_identity)
            try:
                endpoint.drop_path = approval_path
                outages.approveReconciliation(READY_PASSWORD, reason)
                wait_for_editor_idle(qt_app, outages)
                assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
                unknown = outages.property("state")
                assert unknown["uncertain_save"] is True and unknown["dirty"] is True
                request_id = unknown["pending_request_id"]
                assert str(UUID(request_id)) == request_id and pending_ids == {request_id}
                assert endpoint.request_count("POST", approval_path) == 1
                committed_response = supervisor.get(outage_path)
                assert committed_response.status_code == 200, committed_response.text
                original_ack = committed_response.json()
                original_decision = original_ack["record"]["reconciliation"]
                assert original_ack["record"]["reconciled"] is True
                assert len(original_ack["record"]["reconciliation_history"]) == 1
                assert original_decision["revision"] == 1 and original_decision["valid"] is True
                assert original_decision["reason"] == reason
                original_body = {
                    "request_id": request_id,
                    "expected_revision": original_record["revision"],
                    "expected_reconciliation_revision": 0,
                    "paper_revisions": [
                        {"paper_id": row["id"], "revision": row["revision"]}
                        for row in original_record["paper_records"]
                    ],
                    "reason": reason, "password": READY_PASSWORD,
                }
                assert original_decision["basis"]["paper_revisions"] == (
                    original_body["paper_revisions"]
                )
                setup["clock"].value += timedelta(minutes=1)
                endpoint.clock.value = setup["clock"].value
                pending_paper_id = None
                if add_pending_paper:
                    later = counter.post(outage_path + "/paper-records", json={
                        "request_id": str(uuid4()),
                        "expected_outage_revision": original_record["revision"],
                        "paper_reference": "LATER-PENDING-" + uuid4().hex[:12],
                        "workflow": "count", "action": "submit",
                        "original_event_at": "2026-11-15T23:36:00+08:00",
                        "target": {"scope_id": scope_id, "round_id": count_round["id"]},
                        "notes": (
                            "A later paper is still pending; the original approval stays history."
                        ),
                    })
                    assert later.status_code == 201, later.text
                    assert later.json()["status"] == "pending"
                    pending_paper_id = later.json()["id"]
                current_response = supervisor.get(outage_path)
                assert current_response.status_code == 200, current_response.text
                current = current_response.json()
                assert current["record"]["reconciled"] is (not add_pending_paper)
                assert current["record"]["reconciliation"]["valid"] is (not add_pending_paper)
                assert len(current["record"]["reconciliation_history"]) == 1
                assert current["record"]["reconciliation"]["id"] == original_decision["id"]

                # This is the same public refresh used by the normal polling path.
                outages.refresh()
                wait_for_editor_idle(qt_app, outages)
                refreshed = outages.property("state")
                assert refreshed["newer_revision"] is True
                assert refreshed["uncertain_save"] is True
                assert refreshed["pending_request_id"] == request_id
                assert_public_business_fields(refreshed["selected"], original_record)
                assert endpoint.request_count("POST", approval_path) == 1
                assert READY_PASSWORD not in json.dumps(refreshed, ensure_ascii=False)

                detail_reads_before_retry = endpoint.request_count("GET", outage_path)
                outages.approveReconciliation(READY_PASSWORD, reason)
                wait_for_editor_idle(qt_app, outages)
                # Intended first RED at9a74: unconditional newer_revision rejects sealed retry.
                assert endpoint.request_count("POST", approval_path) == 2
                assert endpoint.request_count("GET", outage_path) >= detail_reads_before_retry + 1
                settled = outages.property("state")
                assert settled["error"] == ""
                assert settled["uncertain_save"] is False and settled["dirty"] is False
                assert settled["pending_request_id"] == "" and settled["pending_kind"] == ""
                assert settled["newer_revision"] is False
                assert pending_ids == {request_id}
                # A cached immutable ACK is not today's membership/reconciliation projection.
                assert_public_business_fields(settled["selected"], current["record"])
                assert_public_business_fields(settled["history"], current["history"])
                assert settled["selected"]["reconciled"] is (not add_pending_paper)
                assert settled["selected"]["reconciliation"]["valid"] is (not add_pending_paper)
                if pending_paper_id is not None:
                    pending = next(row for row in settled["selected"]["paper_records"]
                                   if row["id"] == pending_paper_id)
                    assert pending["status"] == "pending" and pending["reentry"] is None
                assert READY_PASSWORD not in json.dumps(settled, ensure_ascii=False)

                # Explicit known-committed same-body API replay inspects the original ACK.
                # This is separate from the two observed Qt POSTs and creates no new effect.
                replay = supervisor.post(approval_path, json=original_body)
                assert replay.status_code == 200, replay.text
                assert replay.json() == original_ack
                final_response = supervisor.get(outage_path)
                assert final_response.status_code == 200, final_response.text
                assert final_response.json() == current
                assert len(final_response.json()["record"]["reconciliation_history"]) == 1
                assert endpoint.request_count("POST", approval_path) == 2
                assert pending_ids == {request_id}
            finally:
                endpoint.drop_path = ""
                outages.stateChanged.disconnect(retain_public_request_identity)



def test_committed_reconciliation_stays_stale_until_its_current_detail_can_be_read(
    admin: TestClient,
    database_url: str,
    lost_outage_approval_response: OutageApprovalResponseLoss,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Additional acceptance: a lost current GET must not impersonate today's approval."""
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "outage-current-read"))
    with tally_setup(admin, database_url) as setup:
        endpoint = lost_outage_approval_response
        endpoint.clock.value = setup["clock"].value
        counter, supervisor = setup["counter"], setup["clients"]["supervisor"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        options, round_path, count_round = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        submitted = counter.post(round_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 2,
            "scope_revision": options["scope"]["revision"], "paper_record_id": paper["id"],
        })
        assert submitted.status_code == 200, submitted.text
        ready = supervisor.get(outage_path)
        assert ready.status_code == 200, ready.text
        outage_id = ready.json()["record"]["id"]
        approval_path = outage_path + "/approve"
        reason = "Check the original approval separately from a failed current read."
        with f1_editor(
            endpoint, qt_app, setup["accounts"]["supervisor"], station_id, scope_id
        ) as (client, _editor):
            outages = client.property("outages")
            outages.open()
            wait_for_editor_idle(qt_app, outages)
            assert outages.loadOutage(outage_id, False) is True
            wait_for_editor_idle(qt_app, outages)
            endpoint.drop_path = approval_path
            outages.approveReconciliation(READY_PASSWORD, reason)
            wait_for_editor_idle(qt_app, outages)
            assert endpoint.response_tagged.is_set() and endpoint.response_dropped.is_set()
            original_id = outages.property("state")["pending_request_id"]
            assert str(UUID(original_id)) == original_id
            assert outages.property("state")["uncertain_save"] is True
            current_response = supervisor.get(outage_path)
            assert current_response.status_code == 200, current_response.text
            current = current_response.json()
            assert current["record"]["reconciled"] is True
            assert len(current["record"]["reconciliation_history"]) == 1
            endpoint.response_tagged.clear()
            endpoint.response_dropped.clear()
            endpoint.current_read_path = outage_path
            endpoint.arm_current_after_path = approval_path
            try:
                outages.approveReconciliation(READY_PASSWORD, reason)
                wait_for(qt_app, lambda: endpoint.current_read_tagged.is_set()
                         and endpoint.response_dropped.is_set())
                wait_for_editor_idle(qt_app, outages)
                stale = outages.property("state")
                assert endpoint.request_count("POST", approval_path) == 2
                assert stale["uncertain_save"] is False and stale["dirty"] is False
                assert stale["pending_request_id"] == "" and stale["pending_kind"] == ""
                assert stale["newer_revision"] is True and stale["error"]
                assert stale["notice"] != "outage_reconciled"
                assert stale["selected"]["reconciled"] is False
                report_path = outage_path + "/statement"
                reports_before = endpoint.request_count("GET", report_path)
                outages.previewReport("en")
                assert outages.property("state")["newer_revision"] is True
                assert endpoint.request_count("GET", report_path) == reports_before
            finally:
                with endpoint.lock:
                    endpoint.block_current_reads = False
                    endpoint.arm_current_after_path = ""
                    endpoint.drop_peer = None
            assert outages.loadOutage(outage_id, True) is True
            wait_for_editor_idle(qt_app, outages)
            loaded = outages.property("state")
            assert loaded["newer_revision"] is False and loaded["error"] == ""
            assert_public_business_fields(loaded["selected"], current["record"])
            assert_public_business_fields(loaded["history"], current["history"])
            assert endpoint.request_count("POST", approval_path) == 2
