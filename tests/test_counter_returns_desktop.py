"""Never-issued counter stock returns use public Qt/TLS controls and real MySQL."""

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
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_officer_returns_unissued_counter_stock_without_rewriting_an_earlier_snapshot(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, counters = arrange_counter_stock(api, base)
        observed = api.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
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
        assert observed.status_code == 201
        snapshot = observed.json()
        assert snapshot["ordinary_allocated_quantity"] == 6
        assert snapshot["ordinary_remaining_quantity"] == 3
        assert snapshot["ordinary_issued_quantity"] == 3
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            assert editor is not None
            assert https_server.request_count("GET", path) == 0
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            initial = editor.property("state")
            assert initial["error"] == "" and initial["items"] == [] and initial["selected"] == {}
            assert initial["counters"] == counters and initial["role"] == "polling_officer"
            editor.setField("counter_id", str(counter["id"]))
            editor.setField("series", "普通系列 A")
            editor.setField("serial_from", "000006")
            editor.setField("serial_to", "000006")
            editor.setField("event_time", "2026-11-15 10:00")
            assert editor.property("state")["dirty"] is True
            assert editor.property("state")["quantity_display"] == "1"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "counter_return_saved"
            assert saved["dirty"] is False and saved["quantity_display"] == "1"
            selected = saved["selected"]
            assert selected["revision"] == 1 and selected["kind"] == "unissued_counter_to_pro"
            assert selected["quantity"] == 1 and selected["counter"] == counter
            assert selected["serial_from"] == selected["serial_to"] == "000006"
            assert selected["series"] == "普通系列 A" and selected["actor_id"] == account["id"]
            assert selected["event_at"] == "2026-11-15T02:00:00Z"
            assert selected["entered_at"] == "2026-11-15T04:00:00Z"
            reopened = api.get(path + f"/{selected['id']}")
            assert reopened.status_code == 200 and reopened.json() == selected
            collection = api.get(path)
            assert collection.status_code == 200 and collection.json()["items"] == [selected]
            p14 = api.get(base + "/allocations/statement?locale=en")
            assert p14.status_code == 200
            assert p14.json()["availability"][0]["allocated_quantity"] == 5
            assert p14.json()["availability"][0]["available_quantity"] == 3
            original = api.get(base + f"/stock-snapshots/{snapshot['id']}")
            assert original.status_code == 200 and original.json() == snapshot
            current = api.get(base + "/stock-snapshots")
            assert current.status_code == 200 and current.json()["latest"] == snapshot
            assert current.json()["latest_basis_current"] is True
            assert current.json()["current_ordinary_issued_quantity"] == 3
            normal = api.get(scope["path"])
            assert normal.status_code == 200
            assert normal.json()["items"] and all(
                row["record"] is None for row in normal.json()["items"]
            )
            editor.setField("serial_to", "000005")
            assert editor.property("state")["forms"]["serial_to"] == "000006"
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["selected"] == {}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_reasoned_return_correction_preserves_precise_time_and_read_only_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        response = api.post(path, json={
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:17.123456+08:00",
        })
        assert response.status_code == 201
        original = response.json()
        target = path + f"/{original['id']}"
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            loaded = editor.property("state")
            assert loaded["selected"] == original and loaded["history"] == [original]
            assert loaded["history_verified"] is True and loaded["editing"] is False
            assert loaded["forms"]["event_time"] == "2026-11-15 10:00"
            editor.setField("serial_from", "000005")
            assert editor.property("state")["forms"]["serial_from"] == "000006"
            assert editor.editSelected() is True
            editor.setField("serial_from", "000005")
            editor.save()
            assert editor.property("state")["error"] == "counter_return_validation"
            assert editor.property("state")["dirty"] is True
            editor.setField("reason", "核對實際退回範圍\n保留原始發生時間")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            revised = saved["selected"]
            assert saved["error"] == "" and saved["notice"] == "counter_return_saved"
            assert revised["id"] == original["id"] and revised["revision"] == 2
            assert revised["quantity"] == 2 and saved["quantity_display"] == "2"
            assert revised["serial_from"] == "000005" and revised["serial_to"] == "000006"
            assert revised["event_at"] == "2026-11-15T02:00:17.123456Z"
            assert revised["reason"] == "核對實際退回範圍\n保留原始發生時間"
            assert revised["actor_id"] == account["id"]
            assert saved["dirty"] is False and saved["editing"] is False
            assert saved["history_verified"] is True
            assert saved["history"] == [original, revised]
            assert api.get(target).json() == revised
            history = api.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [original, revised]
            p14 = api.get(base + "/allocations/statement?locale=en")
            assert p14.status_code == 200
            assert p14.json()["availability"][0]["allocated_quantity"] == 4
            assert p14.json()["availability"][0]["available_quantity"] == 4
            assert editor.editSelected() is True
            editor.setField("reason", "未儲存的原因")
            assert editor.loadRevision(1, False) is False
            retained = editor.property("state")
            assert retained["error"] == "unsaved_counter_return_changes"
            assert retained["selected"] == revised and retained["forms"]["reason"] == "未儲存的原因"
            assert editor.loadRevision(1, True) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            historical = editor.property("state")
            assert historical["selected"] == original and historical["historical"] is True
            assert historical["newer_revision"] is True and historical["history_verified"] is True
            assert editor.editSelected() is False
            editor.setField("serial_from", "000001")
            editor.save()
            assert editor.property("state")["forms"]["serial_from"] == "000006"
            assert api.get(target + "?revision=1").json() == original
            assert api.get(target + "/history").json()["items"] == [original, revised]
            assert editor.newReturn(False) is True
            fresh = editor.property("state")
            assert fresh["selected"] == {} and fresh["history"] == []
            assert fresh["historical"] is False and fresh["editing"] is False
            assert all(value == "" for value in fresh["forms"].values())
            editor.setField("series", "未儲存草稿")
            assert editor.loadReturn(original["id"], False) is False
            assert editor.property("state")["forms"]["series"] == "未儲存草稿"
            assert editor.newReturn(True) is True
            assert editor.property("state")["forms"]["series"] == ""
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_peer_head_refresh_preserves_local_return_input_and_requires_verified_reload(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:17.123456+08:00",
        }
        created = api.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        target = path + f"/{original['id']}"
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.editSelected() is True
            editor.setField("reason", "本機未儲存的核對原因")
            draft = editor.property("state")
            peer = api.put(target, json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "serial_from": "000005",
                "reason": "另一位職員核對退回五至六號",
            })
            assert peer.status_code == 200
            revised = peer.json()
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            stale = editor.property("state")
            assert stale["selected"] == original
            assert stale["forms"] == draft["forms"] and stale["dirty"] is True
            assert stale["items"] == [revised] and stale["newer_revision"] is True
            assert stale["history_verified"] is False and stale["historical"] is True
            assert editor.editSelected() is False
            writes = https_server.request_count("PUT", target)
            editor.save()
            assert https_server.request_count("PUT", target) == writes == 0
            assert editor.loadReturn(original["id"], False) is False
            assert editor.property("state")["forms"] == draft["forms"]
            assert editor.loadReturn(original["id"], True) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            loaded = editor.property("state")
            assert loaded["selected"] == revised and loaded["history"] == [original, revised]
            assert loaded["history_verified"] is True and loaded["historical"] is False
            assert editor.editSelected() is True
            editor.setField("event_time", "2026-11-15 10:05")
            editor.setField("reason", "明確修正為十分零五分")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["selected"]["revision"] == 3
            assert saved["selected"]["event_at"] == "2026-11-15T02:05:00Z"
            assert saved["selected"]["quantity"] == 2
            assert api.get(target + "?revision=1").json() == original
            assert api.get(target + "?revision=2").json() == revised
            assert api.get(target + "/history").json()["items"] == [
                original, revised, saved["selected"]
            ]
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


@dataclass
class ReturnBoundaryServer(HttpsServer):
    save_fault: str = ""
    history_fault: str = ""
    commands: list[dict] = field(default_factory=list)


@pytest.fixture
def return_boundary_server(
    database_url: str, qt_app: QCoreApplication,
) -> Iterator[ReturnBoundaryServer]:
    """Alter only public HTTP responses after real TLS/MySQL operations."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    endpoint = ReturnBoundaryServer(
        f"https://localhost:{listener.getsockname()[1]}", ControlledClock()
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        mutation = request.method in ("POST", "PUT") and "/stock-returns" in request.url.path
        if mutation:
            command = await request.json()
            # Only synthetic stock fields; never headers or authentication bodies.
            with endpoint.lock:
                endpoint.commands.append({
                    key: command[key]
                    for key in (
                        "request_id", "counter_id", "series", "serial_from", "serial_to",
                        "event_at", "revision", "reason",
                    )
                    if key in command
                })
        response = await call_next(request)
        if (
            request.method == "GET"
            and "/stock-returns/" in request.url.path
            and request.url.path.endswith("/history")
            and response.status_code == 200
            and endpoint.history_fault
        ):
            fault, endpoint.history_fault = endpoint.history_fault, ""
            if fault == "truncated":
                body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
                return JSONResponse({"items": body["items"][:1]})
            return JSONResponse({"items": [{}]})
        if mutation and response.status_code in (200, 201) and endpoint.save_fault:
            fault, endpoint.save_fault = endpoint.save_fault, ""
            body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
            if fault == "missing_quantity":
                body.pop("quantity")
            elif fault == "wrong_counter":
                body["counter"]["id"] += 1000000
            else:
                body[fault] += 1
            return JSONResponse(body, status_code=response.status_code)
        return response

    server = uvicorn.Server(uvicorn.Config(
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
        assert not thread.is_alive()


@pytest.mark.parametrize("fault", ["id", "revision", "wrong_counter", "missing_quantity"])
@pytest.mark.parametrize("history_fault", ["malformed", "truncated"])
def test_malformed_return_acknowledgement_reuses_uuid_and_failed_history_stays_read_only(
    admin: TestClient,
    database_url: str,
    return_boundary_server: ReturnBoundaryServer,
    qt_app: QCoreApplication,
    fault: str,
    history_fault: str,
) -> None:
    server = return_boundary_server
    scope, clock = turnout_scope(admin), TurnoutClock()
    server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        created = api.post(path, json={
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:17.123456+08:00",
        })
        assert created.status_code == 201
        original = created.json()
        target = path + f"/{original['id']}"
        client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.editSelected() is True
            editor.setField("serial_from", "000005")
            editor.setField("reason", "核對退回五至六號")
            draft = editor.property("state")
            server.save_fault = fault
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            failed = editor.property("state")
            assert failed["error"] == "request_failed" and failed["notice"] == ""
            assert failed["selected"] == original and failed["forms"] == draft["forms"]
            assert failed["dirty"] is True
            committed = api.get(target)
            assert committed.status_code == 200
            revised = committed.json()
            assert revised["revision"] == 2 and revised["quantity"] == 2
            assert revised["event_at"] == "2026-11-15T02:00:17.123456Z"
            assert len(server.commands) == 1
            server.history_fault = history_fault
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            acknowledged = editor.property("state")
            assert acknowledged["selected"] == revised and acknowledged["dirty"] is False
            assert acknowledged["error"] == "request_failed" and acknowledged["notice"] == ""
            assert acknowledged["history_verified"] is False and acknowledged["editing"] is False
            assert acknowledged["history"] == [original]
            assert editor.editSelected() is False
            assert len(server.commands) == 2 and server.commands[0] == server.commands[1]
            assert api.get(target + "/history").json()["items"] == [original, revised]
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["history"] == [original, revised]
            server.history_fault = history_fault
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            historical = editor.property("state")
            assert historical["selected"] == original and historical["historical"] is True
            assert historical["history_verified"] is False and historical["newer_revision"] is True
            assert historical["history"] == [original, revised]
            assert editor.editSelected() is False
            editor.setField("serial_from", "000001")
            editor.save()
            assert len(server.commands) == 2
            assert editor.property("state")["forms"]["serial_from"] == "000006"
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["history_verified"] is True
            assert editor.editSelected() is False
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"] == revised
            assert editor.editSelected() is True
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_stale_return_correction_fails_visibly_without_losing_input_or_changing_uuid(
    admin: TestClient,
    database_url: str,
    return_boundary_server: ReturnBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    server = return_boundary_server
    scope, clock = turnout_scope(admin), TurnoutClock()
    server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:17.123456+08:00",
        }
        created = api.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        target = path + f"/{original['id']}"
        client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadReturn(original["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.editSelected() is True
            editor.setField("serial_from", "000005")
            editor.setField("reason", "本機尚未提交的修正")
            draft = editor.property("state")
            peer = api.put(target, json={
                **command, "request_id": str(uuid4()), "revision": 1,
                "reason": "另一部電腦已核對原退回範圍",
            })
            assert peer.status_code == 200
            revised = peer.json()
            for _ in range(2):
                editor.save()
                wait_for(qt_app, lambda: setup_idle(editor))
                failed = editor.property("state")
                assert failed["error"] == "revision_conflict" and failed["notice"] == ""
                assert failed["selected"] == original and failed["dirty"] is True
                assert failed["forms"] == draft["forms"]
            assert len(server.commands) == 2 and server.commands[0] == server.commands[1]
            assert api.get(target + "/history").json()["items"] == [original, revised]
            assert editor.loadReturn(original["id"], False) is False
            assert editor.property("state")["forms"] == draft["forms"]
            assert editor.loadReturn(original["id"], True) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"] == revised
            assert editor.property("state")["dirty"] is False
            assert editor.property("state")["history_verified"] is True
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
