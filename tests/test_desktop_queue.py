"""Queue forms and reminder snapshots through real Qt, verified TLS and MySQL."""

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import JSONResponse, StreamingResponse

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
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.queue_support import (
    READY_PASSWORD,
    QueueClock,
    active_queue_stations,
    arrange_retained_queue_election,
    observation,
    queue_account,
    queue_client,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class QueueBoundaryServer(HttpsServer):
    truncate_next_command: bool = False
    truncate_next_read: bool = False
    unavailable_next_read: bool = False
    hold_station_id: int = 0
    held_read_entered: threading.Event = field(default_factory=threading.Event)
    release_held_read: threading.Event = field(default_factory=threading.Event)
    held_read_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def queue_boundary_server(
    database_url: str, qt_app: QCoreApplication
) -> Iterator[QueueBoundaryServer]:
    """Fail or delay actual HTTPS responses after ordinary API handling, never repositories."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = QueueBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def queue_boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        if request.method == "GET" and path.endswith("/queue") and endpoint.unavailable_next_read:
            endpoint.unavailable_next_read = False
            return JSONResponse(
                status_code=503, content={"detail": {"code": "database_unavailable"}}
            )
        held = bool(
            request.method == "GET"
            and endpoint.hold_station_id
            and path == f"/api/workspace/stations/{endpoint.hold_station_id}/queue"
        )
        if held:
            endpoint.hold_station_id = 0
            endpoint.held_read_entered.set()
            await asyncio.to_thread(endpoint.release_held_read.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_read_finished.set()
        queue_path = path.endswith("/queue") or path.endswith("/queue/confirm")
        truncate = queue_path and (
            (request.method == "POST" and endpoint.truncate_next_command)
            or (request.method == "GET" and endpoint.truncate_next_read)
        )
        if truncate and response.status_code in (200, 201):
            if request.method == "POST":
                endpoint.truncate_next_command = False
            else:
                endpoint.truncate_next_read = False
            # The real command has committed. An incomplete HTTP body must remain
            # an uncertain outcome, then a deliberate retry must not append twice.
            return StreamingResponse(
                iter([b'{"incomplete":']),
                media_type="application/json",
                headers={"Content-Length": "4096"},
            )
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
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
        endpoint.release_held_read.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive()


@contextmanager
def queue_editor(
    server: HttpsServer, qt_app: QCoreApplication, account: dict, station_id: int
) -> Iterator[tuple[DesktopController, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: setup_idle(workspace))
        editor = client.property("queue")
        assert editor is not None
        assert editor.open(station_id, account["role"])
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_queue_desktop_records_observation_and_explicit_confirmation_with_server_reminders(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock) as api:
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            editor = client.property("queue")
            assert editor is not None
            assert editor.open(station_id, "polling_officer")
            wait_for(qt_app, lambda: setup_idle(editor))
            missing = editor.property("state")
            assert missing["missing"] is True
            assert missing["current"] is None
            assert missing["latest_current"] is None
            assert missing["due_at"] is None
            assert missing["reminder_due"] is False
            editor.setField("band", "30_59")
            editor.setField("event_time", "2026-11-15 08:00")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["notice"] == "queue_saved"
            assert saved["revision"] == 1
            assert saved["current"]["band"] == "30_59"
            assert saved["current"]["event_at"] == "2026-11-15T00:00:00Z"
            assert saved["dirty"] is False
            assert saved["forms"] == {"band": "30_59", "event_time": "", "reason": ""}
            original = saved["current"]
            https_server.clock.value += timedelta(minutes=29, seconds=59)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["reminder_due"] is False
            https_server.clock.value += timedelta(seconds=1)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["reminder_due"] is True
            assert editor.property("state")["overdue_periods"] == 1
            https_server.clock.value += timedelta(minutes=30)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["overdue_periods"] == 2
            editor.setField("event_time", "2026-11-15 09:00")
            editor.confirmUnchanged()
            wait_for(qt_app, lambda: setup_idle(editor))
            confirmed = editor.property("state")
            assert confirmed["error"] == ""
            assert confirmed["notice"] == "queue_confirmed"
            assert confirmed["current"]["kind"] == "unchanged_confirmation"
            assert confirmed["current"]["confirmed_event_id"] == original["id"]
            assert confirmed["revision"] == 2
            assert confirmed["due_at"] == "2026-11-15T01:30:00Z"
            assert confirmed["reminder_due"] is False
            assert confirmed["items"] == [original, confirmed["current"]]
            assert editor.formatTime("2026-11-15T01:00:00Z") == "2026-11-15 09:00 HKT"
            assert editor.formatTime("invalid") == "—"
            path = f"/api/workspace/stations/{station_id}/queue"
            assert api.get(path).json()["items"] == confirmed["items"]
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_opening_queue_without_a_station_loads_the_subsequently_selected_station(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    stations = active_queue_stations(admin)
    first, second = [row["station"]["id"] for row in stations]
    account = queue_account(admin, [first, second])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock) as api:
        saved = api.post(
            f"/api/workspace/stations/{second}/queue", json=observation(clock, band="60_90")
        )
        assert saved.status_code == 201
        with queue_editor(https_server, qt_app, account, first) as (client, editor):
            assert editor.open(0, "polling_officer")
            assert editor.property("state")["station_id"] == 0
            client.property("workspace").selectStation(second)
            wait_for(
                qt_app,
                lambda: setup_idle(client.property("workspace")) and setup_idle(editor),
            )
            assert editor.property("state")["station_id"] == second
            assert editor.property("state")["current"] == saved.json()


def test_queue_refresh_preserves_reviewed_target_and_dirty_input_until_explicit_reload(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as api:
        original = api.post(path, json=observation(clock, band="30_59"))
        assert original.status_code == 201
        with queue_editor(https_server, qt_app, account, station_id) as (client, editor):
            editor.setField("band", "60_90")
            editor.setField("event_time", "2026-11-15 08:01")
            editor.setField("reason", "保留尚未儲存的紙本觀察")
            form = editor.property("state")["forms"]
            clock.value += timedelta(minutes=1)
            https_server.clock.value = clock.value
            newer = api.post(path, json=observation(clock, expected_revision=1, band="over_90"))
            assert newer.status_code == 201
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            stale = editor.property("state")
            assert stale["current"] == original.json()
            assert stale["revision"] == 1
            assert stale["latest_current"] == newer.json()
            assert stale["latest_revision"] == 2
            assert stale["forms"] == form
            assert stale["newer_revision"] is True
            assert stale["due_at"] == "2026-11-15T00:31:00Z"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "revision_conflict"
            assert editor.property("state")["forms"] == form
            assert not editor.reload()
            assert editor.property("state")["error"] == "unsaved_queue_changes"
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            reloaded = editor.property("state")
            assert reloaded["current"] == newer.json()
            assert reloaded["revision"] == 2
            assert reloaded["forms"] == {"band": "over_90", "event_time": "", "reason": ""}
            assert reloaded["newer_revision"] is False
            backdated = api.post(
                path,
                json=observation(
                    clock, expected_revision=2, event_at="2026-11-15T00:00:30Z", band="under_30"
                ),
            )
            assert backdated.status_code == 201
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["current"] == newer.json()
            assert editor.property("state")["latest_current"] == newer.json()
            assert editor.property("state")["latest_revision"] == 3
            assert editor.property("state")["revision"] == 2
            assert editor.property("state")["newer_revision"] is True
            editor.setField("event_time", "2026-11-15 08:01")
            editor.confirmUnchanged()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "revision_conflict"
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_time", "2026-11-15 08:01")
            editor.confirmUnchanged()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["revision"] == 4
            assert editor.property("state")["current"]["confirmed_event_id"] == newer.json()["id"]
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["current"] is None
            assert editor.property("state")["items"] == []
            assert editor.property("state")["forms"] == {
                "band": "under_30",
                "event_time": "",
                "reason": "",
            }


@pytest.mark.parametrize("changed_field,value", [("band", "over_90"), ("reason", "新觀察原因")])
def test_unchanged_confirmation_does_not_discard_a_changed_observation_form(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    changed_field: str,
    value: str,
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as api:
        original = api.post(path, json=observation(clock, band="30_59"))
        assert original.status_code == 201
        with queue_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.setField("event_time", "2026-11-15 08:00")
            editor.setField(changed_field, value)
            before = https_server.request_count("POST", path + "/confirm")
            editor.confirmUnchanged()
            assert editor.property("state")["error"] == "queue_confirmation_requires_current"
            assert editor.property("state")["forms"][changed_field] == value
            assert https_server.request_count("POST", path + "/confirm") == before
            assert api.get(path).json()["items"] == [original.json()]


def test_queue_form_guards_invalid_time_and_read_only_election_without_losing_input(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    context = active_queue_stations(admin)[0]
    station_id = context["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock):
        with queue_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.confirmUnchanged()
            assert editor.property("state")["error"] == "queue_observation_conflict"
            editor.setField("event_time", "not a date")
            editor.setField("reason", "保留觀察說明")
            editor.save()
            assert editor.property("state")["error"] == "queue_validation"
            assert editor.property("state")["forms"]["event_time"] == "not a date"
            editor.setField("event_time", "2026-11-15 08:01")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "queue_validation"
            assert editor.property("state")["forms"]["reason"] == "保留觀察說明"
            arrange_retained_queue_election(database_url, context["election"]["id"])
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["context"]["election"]["status"] == "finalized"
            before = editor.property("state")["forms"]
            editor.setField("reason", "這個已完結選舉不應再更改表單")
            assert editor.property("state")["forms"] == before
            editor.save()
            assert editor.property("state")["error"] == "active_election_required"


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_queue_desktop_role_controls_match_the_server_operational_permissions(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    role: str,
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    writer_account = queue_account(admin, [station_id])
    reader_account = queue_account(admin, [station_id], role)
    clock = QueueClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station_id}/queue"
    with (
        queue_client(database_url, writer_account, clock) as writer,
        queue_client(database_url, reader_account, clock),
    ):
        saved = writer.post(path, json=observation(clock, band="60_90"))
        assert saved.status_code == 201
        with queue_editor(https_server, qt_app, reader_account, station_id) as (_, editor):
            assert editor.property("state")["current"] == saved.json()
            editor.setField("event_time", "2026-11-15 08:00")
            if role == "polling_officer":
                editor.save()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["revision"] == 2
                assert editor.property("state")["error"] == ""
            else:
                assert editor.property("state")["forms"]["event_time"] == ""
                before = https_server.request_count("POST", path)
                editor.save()
                assert editor.property("state")["error"] == "polling_officer_required"
                editor.confirmUnchanged()
                assert editor.property("state")["error"] == "polling_officer_required"
                assert https_server.request_count("POST", path) == before
                assert writer.get(path).json()["items"] == [saved.json()]


def test_queue_station_switch_requires_explicit_discard_and_clears_the_previous_form(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    stations = active_queue_stations(admin)
    first, second = [row["station"]["id"] for row in stations]
    account = queue_account(admin, [first, second])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock):
        with queue_editor(https_server, qt_app, account, first) as (client, editor):
            editor.setField("event_time", "2026-11-15 08:00")
            editor.setField("reason", "尚未儲存的站內觀察")
            assert not editor.open(second, "polling_officer")
            assert editor.property("state")["error"] == "unsaved_queue_changes"
            workspace = client.property("workspace")
            workspace.selectStation(second)
            assert workspace.property("state")["error"] == "unsaved_station_changes"
            assert state_of(client)["station"]["id"] == first
            assert editor.property("state")["forms"]["reason"] == "尚未儲存的站內觀察"
            workspace.selectStation(second, True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == second
            assert editor.property("state")["context"]["station"]["id"] == second
            assert editor.property("state")["forms"] == {
                "band": "under_30",
                "event_time": "",
                "reason": "",
            }
            assert editor.property("state")["dirty"] is False
            assert editor.property("state")["current"] is None


@pytest.mark.parametrize("lost_stage", ["command", "review_get"])
def test_queue_retry_after_incomplete_http_response_has_one_persisted_effect(
    admin: TestClient,
    database_url: str,
    queue_boundary_server: QueueBoundaryServer,
    qt_app: QCoreApplication,
    lost_stage: str,
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    server = queue_boundary_server
    server.clock.value = clock.value
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as api:
        with queue_editor(server, qt_app, account, station_id) as (_, editor):
            editor.setField("band", "30_59")
            editor.setField("event_time", "2026-11-15 08:00")
            editor.setField("reason", "紙本觀察一次提交")
            original_form = editor.property("state")["forms"]
            if lost_stage == "command":
                server.truncate_next_command = True
            else:
                server.truncate_next_read = True
            before = server.request_count("POST", path)
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
            uncertain = editor.property("state")
            assert uncertain["error"] == "disconnected"
            assert uncertain["notice"] == ""
            assert uncertain["dirty"] is True
            assert uncertain["forms"] == original_form
            assert uncertain["revision"] == 0
            persisted = api.get(path).json()["items"]
            assert len(persisted) == 1
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            retried = editor.property("state")
            assert retried["error"] == ""
            assert retried["notice"] == "queue_saved"
            assert retried["revision"] == 1
            assert retried["items"] == persisted
            assert server.request_count("POST", path) == before + 2
            assert api.get(path).json()["items"] == persisted

            editor.setField("reason", "連線中斷期間保留下一次觀察")
            dirty_form = editor.property("state")["forms"]
            server.truncate_next_read = True
            editor.refresh()
            # The real transport uses an eight-second inactivity deadline; a
            # deliberately incomplete keep-alive response can reach that deadline.
            wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
            assert editor.property("state")["error"] == "disconnected"
            assert editor.property("state")["forms"] == dirty_form
            assert editor.property("state")["current"] == persisted[0]
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["forms"] == dirty_form
            assert editor.property("state")["dirty"] is True


def test_delayed_queue_reply_cannot_replace_a_newly_selected_station(
    admin: TestClient,
    database_url: str,
    queue_boundary_server: QueueBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    stations = active_queue_stations(admin)
    first, second = [row["station"]["id"] for row in stations]
    account = queue_account(admin, [first, second])
    clock = QueueClock()
    server = queue_boundary_server
    server.clock.value = clock.value
    with queue_client(database_url, account, clock) as api:
        first_saved = api.post(
            f"/api/workspace/stations/{first}/queue", json=observation(clock, band="30_59")
        )
        second_saved = api.post(
            f"/api/workspace/stations/{second}/queue", json=observation(clock, band="60_90")
        )
        assert first_saved.status_code == second_saved.status_code == 201
        with queue_editor(server, qt_app, account, first) as (client, editor):
            server.hold_station_id = first
            editor.refresh()
            wait_for(qt_app, server.held_read_entered.is_set)
            assert editor.property("state")["refreshing"] is True
            workspace = client.property("workspace")
            workspace.selectStation(second)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["current"] == second_saved.json()
            server.release_held_read.set()
            wait_for(qt_app, server.held_read_finished.is_set)
            # A further real refresh drains any queued completion and verifies that
            # the old station reply did not leave a stale error or reviewed target.
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            final = editor.property("state")
            assert final["station_id"] == second
            assert final["current"] == second_saved.json()
            assert final["latest_current"] == second_saved.json()
            assert final["items"] == [second_saved.json()]
            assert final["error"] == ""


def test_reopening_after_an_initial_load_outage_preserves_a_new_dirty_form(
    admin: TestClient,
    database_url: str,
    queue_boundary_server: QueueBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    stations = active_queue_stations(admin)
    first, second = [row["station"]["id"] for row in stations]
    account = queue_account(admin, [first, second])
    clock = QueueClock()
    server = queue_boundary_server
    server.clock.value = clock.value
    with queue_client(database_url, account, clock):
        with queue_editor(server, qt_app, account, first) as (client, editor):
            assert editor.open(0, "polling_officer")
            server.unavailable_next_read = True
            workspace = client.property("workspace")
            workspace.selectStation(second)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["error"] == "database_unavailable"
            editor.setField("event_time", "2026-11-15 08:00")
            editor.setField("reason", "初次載入失敗後輸入，應先確認才可捨棄")
            form = editor.property("state")["forms"]
            assert not editor.open(second, "polling_officer")
            assert editor.property("state")["error"] == "unsaved_queue_changes"
            assert editor.property("state")["forms"] == form
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["dirty"] is False


def test_two_desktops_share_queue_updates_while_preserving_an_unsaved_observation(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock):
        with (
            queue_editor(https_server, qt_app, account, station_id) as (_, first),
            queue_editor(https_server, qt_app, account, station_id) as (_, second),
        ):
            first.setField("event_time", "2026-11-15 08:00")
            first.setField("reason", "第一部電腦尚未儲存")
            form = first.property("state")["forms"]
            second.setField("band", "over_90")
            second.setField("event_time", "2026-11-15 08:00")
            second.save()
            wait_for(qt_app, lambda: setup_idle(second))
            assert second.property("state")["revision"] == 1
            first.refresh()
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["latest_current"] == second.property("state")["current"]
            assert first.property("state")["current"] is None
            assert first.property("state")["forms"] == form
            assert first.property("state")["newer_revision"] is True
            first.save()
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["error"] == "revision_conflict"
            assert first.property("state")["forms"] == form
            assert first.reload(True)
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["current"] == second.property("state")["current"]


@pytest.mark.parametrize("opened", [False, True])
def test_count_scope_polling_does_not_block_clean_queue_station_selection(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    opened: bool,
) -> None:
    stations = active_queue_stations(admin)
    first, second = [row["station"]["id"] for row in stations]
    account = queue_account(admin, [first, second])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock) as api:
        saved = api.post(
            f"/api/workspace/stations/{second}/queue", json=observation(clock, band="60_90")
        )
        assert saved.status_code == 201
        with queue_editor(https_server, qt_app, account, first) as (client, editor):
            scopes = client.property("countingScopes")
            if opened:
                scopes.open()
                wait_for(qt_app, lambda: setup_idle(scopes))
                assert scopes.property("state")["scopes"] == []
            assert editor.open(0, "polling_officer")
            scopes.refresh()
            assert scopes.property("state")["busy"] is False
            assert client.property("workspace").property("selectionGuarded") is False
            client.property("workspace").selectStation(second)
            wait_for(
                qt_app,
                lambda: (
                    setup_idle(client.property("workspace"))
                    and setup_idle(editor)
                    and editor.property("state")["station_id"] == second
                ),
            )
            assert editor.property("state")["current"] == saved.json()
            assert client.property("workspace").property("state")["error"] == ""
