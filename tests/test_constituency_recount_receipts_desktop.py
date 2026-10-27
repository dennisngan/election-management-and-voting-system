"""A malformed aggregate acknowledgement stays unknown until its exact outcome is checked."""

import json
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtTest import QSignalSpy

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class AggregateReceiptBoundary(HttpsServer):
    alter_next_post_path: str = ""
    post_fault: str = "truncated_candidates"
    foreign_constituency_id: int = 0
    foreign_station_id: int = 0
    original_source_context: dict = field(default_factory=dict)
    delivered_source_context: dict = field(default_factory=dict)
    original_round_id: int = 0
    delivered_round_id: int | float = 0
    altered_response_count: int = 0
    original_candidate_ids: list[int] = field(default_factory=list)
    delivered_candidate_ids: list[int] = field(default_factory=list)
    null_context_next_get_path: str = ""
    altered_read_count: int = 0


@pytest.fixture
def aggregate_receipt_boundary(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[AggregateReceiptBoundary]:
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare the existing local TLS fixture first"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = AggregateReceiptBoundary(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def alter_only_the_armed_public_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        with endpoint.lock:
            alter_write = (
                request.method == "POST"
                and request.url.path == endpoint.alter_next_post_path
                and response.status_code == 201
            )
            alter_read = (
                request.method == "GET"
                and request.url.path == endpoint.null_context_next_get_path
                and response.status_code == 200
            )
            if alter_write:
                endpoint.alter_next_post_path = ""
                post_fault = endpoint.post_fault
            if alter_read:
                endpoint.null_context_next_get_path = ""
        if not (alter_write or alter_read):
            return response
        # The real route has completed. Change only the explicitly armed response;
        # authentication, business rules, SQL and every outcome GET stay real.
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(chunk.encode() if isinstance(chunk, str) else chunk for chunk in chunks)
        payload = json.loads(body)
        if alter_write:
            first_round = payload["members"][0]["round"]
            member = payload["instruction"]["members"][0]
            votes = first_round["candidate_votes"]
            assert len(votes) == 2
            original_ids = [row["candidate_id"] for row in votes]
            original_context = deepcopy(member["source_context"])
            original_round_id = first_round["id"]
            assert type(original_round_id) is int
            if post_fault == "truncated_candidates":
                votes.pop()
            elif post_fault == "duplicate_candidate_ids":
                votes[1]["candidate_id"] = votes[0]["candidate_id"]
            elif post_fault == "empty_source_context":
                member["source_context"] = {}
            elif post_fault == "foreign_source_constituency":
                assert endpoint.foreign_constituency_id > 0
                member["source_context"]["context"]["constituency"]["id"] = (
                    endpoint.foreign_constituency_id
                )
            elif post_fault == "foreign_source_station":
                assert endpoint.foreign_station_id > 0
                member["source_context"]["context"]["station"]["id"] = (
                    endpoint.foreign_station_id
                )
            elif post_fault == "float_round_id":
                first_round["id"] = float(original_round_id)
            else:
                raise AssertionError("An explicitly supported aggregate receipt fault is required")
            with endpoint.lock:
                endpoint.original_candidate_ids = original_ids
                endpoint.delivered_candidate_ids = [row["candidate_id"] for row in votes]
                endpoint.original_source_context = original_context
                endpoint.delivered_source_context = deepcopy(member["source_context"])
                endpoint.original_round_id = original_round_id
                endpoint.delivered_round_id = first_round["id"]
                endpoint.altered_response_count += 1
        else:
            assert isinstance(payload["context"]["constituency"], dict)
            payload["context"]["constituency"] = None
            with endpoint.lock:
                endpoint.altered_read_count += 1
        preserved_headers = {
            name: value for name, value in response.headers.items()
            if name.lower() not in {"content-length", "content-type", "transfer-encoding"}
        }
        return JSONResponse(
            payload, status_code=response.status_code, headers=preserved_headers,
            background=response.background,
        )

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=port, loop="asyncio", ws="none",
        ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
        ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
        log_level="warning", access_log=False,
        timeout_keep_alive=5, timeout_graceful_shutdown=1,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive(), "The owned aggregate-receipt HTTPS fixture did not stop"


@pytest.mark.parametrize("receipt_fault", [
    "truncated_candidates", "duplicate_candidate_ids", "empty_source_context",
    "foreign_source_constituency", "foreign_source_station", "float_round_id",
])
def test_noncanonical_blank_receipt_remains_unknown_until_exact_aggregate_outcome(
    receipt_fault: str,
    admin: TestClient,
    database_url: str,
    aggregate_receipt_boundary: AggregateReceiptBoundary,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "constituency-recount-receipt-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        constituency_id = setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        priors = [saved, setup["n3_round"]]
        before_rounds = []
        for prior in priors:
            response = supervisor.get(prior["round_path"].rsplit("/", 1)[0])
            assert response.status_code == 200, response.text
            before_rounds.append([row["id"] for row in response.json()["rounds"]])
        assert before_rounds == [[prior["selected"]["id"]] for prior in priors]
        setup["clock"].value += timedelta(minutes=10)
        endpoint = aggregate_receipt_boundary
        endpoint.clock.value = setup["clock"].value
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(
                endpoint.url, setup["accounts"]["supervisor"]["username"], READY_PASSWORD,
            )
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            results = client.property("constituencyResults")
            results.open()
            wait_for_editor_idle(qt_app, results)
            recounts = results.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            initial = deepcopy(recounts.property("state"))
            assert initial["can_instruct"] is True and initial["instructions"] == []
            assert len(initial["scope_sources"]) == 2
            recounts.setField("event_at", "2026-11-16 00:05:42.123456")
            recounts.setField(
                "reason", "Check every blank candidate row before confirming this recount.",
            )
            original_forms = deepcopy(recounts.property("state")["forms"])
            instructed = QSignalSpy(recounts.instructed)
            assert instructed.isValid()
            with endpoint.lock:
                endpoint.alter_next_post_path = target
                endpoint.post_fault = receipt_fault
                endpoint.foreign_constituency_id = setup["stations"]["S1"]["constituency_id"]
                endpoint.foreign_station_id = setup["stations"]["S1"]["id"]
            recounts.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, recounts)
            wait_for_editor_idle(qt_app, results)
            failed = deepcopy(recounts.property("state"))

            # Establish the genuine one-parent/two-round commit before the first RED.
            response = supervisor.get(target)
            assert response.status_code == 200, response.text
            committed_view = response.json()
            assert len(committed_view["instructions"]) == 1
            parent = committed_view["instructions"][0]
            request_id = parent["request_id"]
            assert str(UUID(request_id)) == request_id
            assert parent["member_count"] == 2 and len(parent["members"]) == 2
            assert parent["actor_id"] == setup["accounts"]["supervisor"]["id"]
            assert parent["reason"] == original_forms["reason"]
            blank_views = []
            for member, prior, prior_ids in zip(
                parent["members"], priors, before_rounds, strict=True,
            ):
                rounds_path = prior["round_path"].rsplit("/", 1)[0]
                listed = supervisor.get(rounds_path)
                assert listed.status_code == 200, listed.text
                assert {row["id"] for row in listed.json()["rounds"]} == {
                    *prior_ids, member["new_round_id"],
                }
                assert len(listed.json()["rounds"]) == 2
                blank_response = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
                assert blank_response.status_code == 200, blank_response.text
                blank_view = blank_response.json()
                blank = blank_view["record"]
                assert len(blank_view["history"]) == 1
                assert blank["revision"] == 1 and blank["round_number"] == 2
                assert blank["status"] == "draft" and blank["actual_counted_quantity"] is None
                assert blank["scope_basis"] == prior["selected"]["scope_basis"]
                assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
                blank_views.append(blank_view)
            assert endpoint.altered_response_count == 1
            assert endpoint.original_candidate_ids == [
                row["candidate_id"] for row in blank_views[0]["record"]["candidate_votes"]
            ]
            if receipt_fault == "truncated_candidates":
                assert endpoint.delivered_candidate_ids == endpoint.original_candidate_ids[:-1]
            elif receipt_fault == "duplicate_candidate_ids":
                assert endpoint.delivered_candidate_ids == [
                    endpoint.original_candidate_ids[0], endpoint.original_candidate_ids[0],
                ]
            else:
                assert endpoint.delivered_candidate_ids == endpoint.original_candidate_ids
            original_context = endpoint.original_source_context
            delivered_context = endpoint.delivered_source_context
            assert original_context == parent["members"][0]["source_context"]
            assert original_context["context"]["constituency"]["id"] == constituency_id
            assert original_context["context"]["station"]["id"] == station_id
            if receipt_fault == "empty_source_context":
                assert delivered_context == {}
            elif receipt_fault == "foreign_source_constituency":
                assert endpoint.foreign_constituency_id != constituency_id
                assert delivered_context["context"]["constituency"]["id"] == (
                    endpoint.foreign_constituency_id
                )
                assert delivered_context["context"]["station"] == original_context["context"][
                    "station"
                ]
            elif receipt_fault == "foreign_source_station":
                assert endpoint.foreign_station_id != station_id
                assert delivered_context["context"]["station"]["id"] == endpoint.foreign_station_id
                assert delivered_context["context"]["constituency"] == original_context["context"][
                    "constituency"
                ]
            else:
                assert delivered_context == original_context
            assert endpoint.original_round_id == blank_views[0]["record"]["id"]
            if receipt_fault == "float_round_id":
                assert type(endpoint.delivered_round_id) is float
                assert endpoint.delivered_round_id == endpoint.original_round_id
            else:
                assert type(endpoint.delivered_round_id) is int
                assert endpoint.delivered_round_id == endpoint.original_round_id
            assert endpoint.request_count("POST", target) == 1

            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            command = deepcopy(next(row for row in recovery.property("state")["commands"]
                                    if row["request_id"] == request_id))
            original_payload = deepcopy(command["payload"])
            assert command["workflow"] == "constituency_recount"
            assert command["server_url"] == endpoint.url and command["station_id"] == station_id
            assert command["actor_id"] == parent["actor_id"]
            assert command["path"] == target and command["method"] == "POST"
            assert command["confirmation_required"] is True
            assert original_payload == {
                "request_id": request_id, "basis_digest": initial["basis_digest"],
                "scope_sources": initial["scope_sources"],
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": original_forms["reason"],
            }
            durable = [json.loads(path.read_text(encoding="utf-8"))
                       for path in journal_directory.glob("*.json")]
            original_durable = next(row for row in durable if row["request_id"] == request_id)
            assert READY_PASSWORD not in json.dumps(command)
            assert "password" not in json.dumps(original_payload).lower()

            # Expected first RED at4c56b5a: a truncated local blank DTO is called saved.
            assert failed["uncertain_save"] is True, {
                "child_error": failed["error"], "child_notice": failed["notice"],
                "journal_status": command["status"], "instructed_signals": instructed.count(),
            }
            assert failed["dirty"] is True and failed["forms"] == original_forms
            assert failed["pending_request_id"] == request_id
            assert instructed.count() == 0
            assert command["status"] == original_durable["status"] == "uncertain"
            assert command["payload"] == original_durable["payload"] == original_payload
            assert workspace.property("unresolvedRequest") is True

            outcome_path = (
                f"/api/workspace/constituencies/{constituency_id}/request-outcomes/{request_id}"
            )
            assert endpoint.request_count("GET", outcome_path) == 0
            recounts.checkOutcome()
            wait_for_editor_idle(qt_app, recovery)
            wait_for_editor_idle(qt_app, recounts)
            wait_for_editor_idle(qt_app, results)
            checked = next(row for row in recovery.property("state")["commands"]
                           if row["request_id"] == request_id)
            assert checked["status"] == "committed" and checked["error"] == ""
            assert checked["payload"] == original_payload
            canonical_response = supervisor.get(outcome_path + "?workflow=constituency_recount")
            assert canonical_response.status_code == 200, canonical_response.text
            canonical = canonical_response.json()
            assert canonical["status"] == "committed"
            assert canonical["request_id"] == request_id
            assert canonical["workflow"] == "constituency_recount"
            assert_public_business_fields(checked["receipt"]["record"], canonical["record"])
            settled = recounts.property("state")
            assert settled["uncertain_save"] is False and settled["dirty"] is False
            assert settled["pending_request_id"] == "" and settled["error"] == ""
            assert settled["forms"] == {"event_at": "", "reason": ""}
            assert instructed.count() == 1
            assert workspace.property("unresolvedRequest") is False
            assert endpoint.request_count("GET", outcome_path) == 1
            assert endpoint.request_count("POST", target) == 1
            after = supervisor.get(target)
            assert after.status_code == 200 and after.json() == committed_view
            for member, prior, blank_view in zip(
                parent["members"], priors, blank_views, strict=True,
            ):
                rounds_path = prior["round_path"].rsplit("/", 1)[0]
                current = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
                assert current.status_code == 200 and current.json() == blank_view
                listed = supervisor.get(rounds_path)
                assert listed.status_code == 200 and len(listed.json()["rounds"]) == 2
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_null_constituency_read_context_preserves_the_current_recount_draft(
    admin: TestClient,
    database_url: str,
    aggregate_receipt_boundary: AggregateReceiptBoundary,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "recount-read-journal"))
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        target = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        setup["clock"].value += timedelta(minutes=10)
        endpoint = aggregate_receipt_boundary
        endpoint.clock.value = setup["clock"].value
        client = DesktopController(endpoint.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(
                endpoint.url, setup["accounts"]["supervisor"]["username"], READY_PASSWORD,
            )
            wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            results = client.property("constituencyResults")
            results.open()
            wait_for_editor_idle(qt_app, results)
            recounts = results.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            ready = deepcopy(recounts.property("state"))
            assert ready["can_instruct"] is True and ready["error"] == ""
            assert len(ready["scope_sources"]) == 2 and ready["instructions"] == []
            assert ready["basis_digest"]
            recounts.setField("event_at", "2026-11-16 00:05:42.123456")
            recounts.setField("reason", "Preserve this draft when a read has invalid context.")
            original = deepcopy(recounts.property("state"))
            instructed = QSignalSpy(recounts.instructed)
            assert instructed.isValid()
            assert endpoint.altered_read_count == endpoint.altered_response_count == 0
            assert endpoint.request_count("POST", target) == 0

            with endpoint.lock:
                endpoint.null_context_next_get_path = target
            recounts.reload()
            wait_for(qt_app, lambda: endpoint.altered_read_count == 1)
            wait_for_editor_idle(qt_app, recounts)
            rejected = recounts.property("state")
            assert rejected["busy"] is False and rejected["refreshing"] is False
            # Expected first RED at3e7375b: .get on the null child context raises
            # instead of reporting the invalid read through the public Qt state.
            assert rejected["error"] == "constituency_recount_invalid_response"
            for key in ("basis_digest", "scope_sources", "instructions", "forms", "context"):
                assert rejected[key] == original[key]
            assert rejected["dirty"] is True and rejected["uncertain_save"] is False
            assert rejected["pending_request_id"] == "" and rejected["notice"] == ""
            assert instructed.count() == 0
            assert endpoint.altered_read_count == 1 and endpoint.altered_response_count == 0
            assert endpoint.request_count("POST", target) == 0
            unchanged = supervisor.get(target)
            assert unchanged.status_code == 200, unchanged.text
            assert unchanged.json()["instructions"] == []
            assert unchanged.json()["basis_digest"] == original["basis_digest"]
            assert unchanged.json()["scope_sources"] == original["scope_sources"]
            assert READY_PASSWORD not in json.dumps(rejected)
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
