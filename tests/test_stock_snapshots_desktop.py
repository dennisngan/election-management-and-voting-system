"""Remaining-stock forms use public Qt controls over verified TLS and real MySQL."""

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import JSONResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    state_of,
    wait_for,
)
from tests.stock_support import stock_payload
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def arrange_counter_stock(api: TestClient, base: str) -> tuple[dict, list[dict]]:
    """Receive eight ordinary papers and allocate the first six through the real API."""
    receipt = api.post(base + "/stock", json=stock_payload())
    assert receipt.status_code == 201
    options = api.get(base + "/allocations")
    assert options.status_code == 200
    counters = options.json()["counters"]
    counter = next(row for row in counters if row["code"] == "C1")
    allocation = api.post(
        base + "/allocations",
        json={
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": "2026-11-15T09:00:00+08:00",
        },
    )
    assert allocation.status_code == 201
    return counter, counters


def test_officer_saves_remaining_stock_and_another_client_reads_the_same_snapshot(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, counters = arrange_counter_stock(api, base)
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stockSnapshots")
            assert editor is not None
            assert https_server.request_count("GET", base + "/stock-snapshots") == 0
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            initial = editor.property("state")
            assert initial["error"] == ""
            assert initial["snapshot_state"] == "missing" and initial["items"] == []
            assert initial["selected"] == {} and initial["current_ordinary_issued_quantity"] is None
            assert initial["role"] == "polling_officer"
            assert initial["counters"] == counters
            assert initial["counter_reports"][0]["reported"] is False
            editor.setField("event_time", "2026-11-15 09:30")
            editor.setCounterReported(counter["id"], True)
            editor.addRange(counter["id"])
            editor.setRangeField(counter["id"], 0, "series", "普通系列 A")
            editor.setRangeField(counter["id"], 0, "serial_from", "000004")
            editor.setRangeField(counter["id"], 0, "serial_to", "000006")
            form = editor.property("state")
            assert form["dirty"] is True
            assert form["counter_reports"][0]["ranges"][0]["quantity_display"] == "3"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["notice"] == "stock_snapshot_saved" and saved["dirty"] is False
            selected = saved["selected"]
            assert selected["revision"] == 1 and selected["provenance"] == "stock_derived"
            assert selected["ordinary_allocated_quantity"] == 6
            assert selected["ordinary_remaining_quantity"] == 3
            assert selected["ordinary_issued_quantity"] == 3
            assert saved["totals"]["ordinary_allocated_display"] == "6"
            assert saved["totals"]["ordinary_remaining_display"] == "3"
            assert saved["totals"]["ordinary_issued_display"] == "3"
            assert saved["latest_basis_current"] is True
            assert saved["current_ordinary_issued_display"] == "3"
            assert selected["event_at"] == "2026-11-15T01:30:00Z"
            reopened = api.get(base + f"/stock-snapshots/{selected['id']}")
            assert reopened.status_code == 200 and reopened.json() == selected
            collection = api.get(base + "/stock-snapshots")
            assert collection.status_code == 200 and collection.json()["latest"] == selected
            normal_turnout = api.get(scope["path"])
            assert normal_turnout.status_code == 200
            periods = normal_turnout.json()["items"]
            assert periods and all(row["record"] is None for row in periods)
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["selected"] == {}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


@dataclass
class SnapshotBoundaryServer(HttpsServer):
    save_fault: str = ""
    collection_fault: str = ""
    commands: list[dict] = field(default_factory=list)


@pytest.fixture
def snapshot_boundary_server(
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[SnapshotBoundaryServer]:
    """Change only an actual committed response, retaining the real TLS/MySQL command."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    endpoint = SnapshotBoundaryServer(
        f"https://localhost:{listener.getsockname()[1]}", ControlledClock()
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        mutation = request.method == "POST" and request.url.path.endswith("/stock-snapshots")
        if mutation:
            # Whitelist the stock command body; never capture headers or authentication bodies.
            command = await request.json()
            with endpoint.lock:
                endpoint.commands.append(
                    {key: command[key] for key in ("request_id", "event_at", "counters")}
                )
        response = await call_next(request)
        collection = request.method == "GET" and request.url.path.endswith("/stock-snapshots")
        if (
            mutation
            and response.status_code in (200, 201)
            and endpoint.save_fault
            or collection
            and response.status_code == 200
            and endpoint.collection_fault
        ):
            if mutation:
                fault, endpoint.save_fault = endpoint.save_fault, ""
            else:
                fault, endpoint.collection_fault = endpoint.collection_fault, ""
            body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
            if fault == "missing_reported_counter":
                body["counters"] = []
            elif fault == "malformed_counter":
                body["counters"] = [{}]
            else:
                body.pop(fault)
            return JSONResponse(body, status_code=response.status_code)
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=listener.getsockname()[1],
            ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
            ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
            loop="asyncio",
            ws="none",
            lifespan="on",
            log_level="warning",
            access_log=False,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=1,
        )
    )
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
        assert not thread.is_alive()


@pytest.mark.parametrize(
    ("kind", "fault"),
    [
        pytest.param("save", "missing_reported_counter", id="ack-missing-reported-counter"),
        pytest.param("save", "malformed_counter", id="ack-malformed-counter"),
        pytest.param("collection", "latest_basis_current", id="collection-missing-basis-state"),
        pytest.param(
            "collection", "current_ordinary_issued_quantity", id="collection-missing-issued"
        ),
    ],
)
def test_incomplete_stock_responses_keep_draft_and_recover_at_public_tls_boundary(
    admin: TestClient,
    database_url: str,
    snapshot_boundary_server: SnapshotBoundaryServer,
    qt_app: QCoreApplication,
    kind: str,
    fault: str,
) -> None:
    server = snapshot_boundary_server
    scope, clock = turnout_scope(admin), TurnoutClock()
    server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stockSnapshots")
            assert editor is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_time", "2026-11-15 09:30:17.123456")
            editor.setCounterReported(counter["id"], True)
            editor.addRange(counter["id"])
            editor.setRangeField(counter["id"], 0, "series", "普通系列 A")
            editor.setRangeField(counter["id"], 0, "serial_from", "000004")
            editor.setRangeField(counter["id"], 0, "serial_to", "000006")
            draft = editor.property("state")
            if kind == "save":
                server.save_fault = fault
                editor.save()
            else:
                server.collection_fault = fault
                editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            failed = editor.property("state")
            assert failed["error"] == "request_failed"
            assert failed["notice"] == "" and failed["dirty"] is True
            assert failed["selected"] == {}
            assert failed["forms"] == draft["forms"]
            assert failed["counter_reports"] == draft["counter_reports"]
            with server.lock:
                first_commands = list(server.commands)
            assert len(first_commands) == (1 if kind == "save" else 0)
            if first_commands:
                assert first_commands[0]["counters"] == [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000004",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ]
            server.save_fault = ""
            server.collection_fault = ""
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            recovered = editor.property("state")
            assert recovered["error"] == "" and recovered["notice"] == "stock_snapshot_saved"
            assert recovered["dirty"] is False
            assert recovered["selected"]["revision"] == 1
            assert recovered["selected"]["ordinary_issued_quantity"] == 3
            with server.lock:
                commands = list(server.commands)
            assert len(commands) == (2 if kind == "save" else 1)
            if kind == "save":
                assert commands[0] == commands[1]
            collection = api.get(base + "/stock-snapshots")
            assert collection.status_code == 200
            assert collection.json()["items"] == [recovered["selected"]]
            saved_id = recovered["selected"]["id"]
            history = api.get(base + f"/stock-snapshots/{saved_id}/history")
            assert history.status_code == 200 and history.json()["items"] == [recovered["selected"]]
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_reasoned_snapshot_amendment_preserves_precise_time_and_immutable_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-snapshots"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        created = api.post(
            path,
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:17.123456+08:00",
                "counters": [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000004",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ],
            },
        )
        assert created.status_code == 201
        original = created.json()
        assert original["ordinary_issued_quantity"] == 3
        target = path + f"/{original['id']}"
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stockSnapshots")
            assert editor is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadSnapshot(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            reviewed = editor.property("state")
            assert reviewed["selected"] == original and reviewed["history"] == [original]
            assert reviewed["editing"] is False and reviewed["historical"] is False
            assert reviewed["forms"]["event_time"] == "2026-11-15 09:30"
            editor.setRangeField(counter["id"], 0, "serial_from", "000005")
            assert editor.property("state")["counter_reports"] == reviewed["counter_reports"]
            assert editor.editSelected()
            assert editor.property("state")["editing"] is True
            editor.setRangeField(counter["id"], 0, "serial_from", "000005")
            reason = "核對紙本：第四號已經發出。\n第二行：保留原有快照時間。"
            editor.setField("reason", reason)
            draft = editor.property("state")
            assert draft["dirty"] is True and draft["forms"]["event_time"] == "2026-11-15 09:30"
            assert editor.loadRevision(1, False) is False
            assert editor.newSnapshot(False) is False
            assert editor.property("state")["error"] == "unsaved_stock_snapshot_changes"
            assert editor.property("state")["counter_reports"] == draft["counter_reports"]
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "stock_snapshot_saved"
            assert saved["dirty"] is False and saved["editing"] is False
            corrected = saved["selected"]
            assert corrected["id"] == original["id"] and corrected["revision"] == 2
            assert corrected["reason"] == reason
            assert corrected["event_at"] == original["event_at"] == "2026-11-15T01:30:17.123456Z"
            assert corrected["ordinary_allocated_quantity"] == 6
            assert corrected["ordinary_remaining_quantity"] == 2
            assert corrected["ordinary_issued_quantity"] == 4
            assert saved["history"] == [original, corrected]
            current = api.get(target)
            assert current.status_code == 200 and current.json() == corrected
            history = api.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [original, corrected]
            normal = api.get(scope["path"])
            assert normal.status_code == 200
            assert normal.json()["items"] and all(
                row["record"] is None for row in normal.json()["items"]
            )
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            historical = editor.property("state")
            assert historical["selected"] == original
            assert historical["historical"] is True and historical["editing"] is False
            assert historical["history"] == [original, corrected]
            assert historical["totals"]["ordinary_allocated_display"] == "6"
            assert historical["totals"]["ordinary_remaining_display"] == "3"
            assert historical["totals"]["ordinary_issued_display"] == "3"
            writes = https_server.request_count("PUT", target)
            assert writes == 1
            assert editor.editSelected() is False
            editor.setRangeField(counter["id"], 0, "serial_from", "000006")
            editor.save()
            assert editor.property("state")["counter_reports"] == historical["counter_reports"]
            assert https_server.request_count("PUT", target) == writes
            retained = api.get(target + "/history")
            assert retained.status_code == 200 and retained.json()["items"] == [original, corrected]
            assert editor.newSnapshot(False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"] == {}
            assert editor.property("state")["forms"] == {"event_time": "", "reason": ""}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
