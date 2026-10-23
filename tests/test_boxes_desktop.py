"""Ballot-box workflows through public Qt controls, verified HTTPS and real MySQL."""

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import StreamingResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import (
    READY_PASSWORD,
    BoxClock,
    box_staff,
    box_stations,
    event_command,
    prepared_box,
)
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import arrange_retained_polling_election


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class BoxBoundaryServer(HttpsServer):
    truncate_next_write: bool = False
    hold_station_id: int = 0
    held_started: threading.Event = field(default_factory=threading.Event)
    release_held: threading.Event = field(default_factory=threading.Event)
    held_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def box_boundary_server(database_url: str, qt_app: QCoreApplication) -> Iterator[BoxBoundaryServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = BoxBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def response_boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        held = (
            request.method == "GET"
            and path == (f"/api/workspace/stations/{endpoint.hold_station_id}/boxes")
            and endpoint.hold_station_id > 0
        )
        if held:
            endpoint.hold_station_id = 0
            endpoint.held_started.set()
            await asyncio.to_thread(endpoint.release_held.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_finished.set()
        if (
            endpoint.truncate_next_write
            and "/boxes" in path
            and request.method in ("POST", "PUT")
            and response.status_code in (200, 201)
        ):
            endpoint.truncate_next_write = False
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
        endpoint.release_held.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive()


@contextmanager
def boxes_editor(
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
        editor = client.property("boxes")
        assert editor is not None and editor.open(station_id, account["role"])
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def fill_box(editor: Any, reference: str = "票箱 0001") -> None:
    editor.setField("box_reference", reference)
    editor.setField("seal_reference", "封條 000099")
    editor.setField("prepared_time", "2026-11-15 22:40")


def test_origin_officer_creates_a_frozen_box_and_records_departure_through_qt(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (api, account):
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(origin["id"])
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("boxes")
            assert editor is not None
            assert editor.open(origin["id"], account["role"])
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("box_reference", "票箱 0001")
            editor.setField("seal_reference", "封條 000099")
            editor.setField("prepared_time", "2026-11-15 22:40")
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            state = editor.property("state")
            assert state["error"] == ""
            assert state["selected"]["revision"] == 1
            assert state["selected"]["origin_station_id"] == origin["id"]
            assert state["selected"]["destination_station_id"] == destination["id"]
            assert state["selected"]["prepared_at"] == "2026-11-15T14:40:00Z"
            assert state["count_completion"] is None
            editor.setField("event_time", "2026-11-15 22:45")
            editor.depart()
            wait_for(qt_app, lambda: setup_idle(editor))
            departed = editor.property("state")
            assert departed["error"] == ""
            assert departed["selected"]["revision"] == 2
            assert departed["selected"]["status"] == "departed"
            assert departed["selected"]["departure_at"] == "2026-11-15T14:45:00Z"
            assert [row["kind"] for row in departed["history"]] == ["prepared", "departure"]
            saved = api.get(f"/api/workspace/stations/{origin['id']}/boxes").json()
            assert saved["items"] == [departed["selected"]]
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_counting_officer_records_and_corrects_received_box_milestones_without_count_completion(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        created = po.post(path, json=prepared_box())
        assert created.status_code == 201
        box_id = created.json()["id"]
        with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (
            api,
            account,
        ):
            received = api.post(
                f"{path}/{box_id}/receipt", json=event_command(1, "2026-11-15T22:45:00+08:00")
            )
            assert received.status_code == 201
            with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
                editor.setMilestoneField("event_time", "2026-11-15 22:50")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                first = editor.property("state")
                assert first["error"] == ""
                assert first["selected_milestone"]["kind"] == "conversion_complete"
                assert first["selected_milestone"]["revision"] == 1
                assert first["selected_milestone"]["event_at"] == "2026-11-15T14:50:00Z"
                editor.setMilestoneField("event_time", "2026-11-15 22:51")
                editor.setMilestoneField("reason", "按現場紀錄修正轉換完成時間")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["selected_milestone"]["revision"] == 2
                assert editor.setKind("first_box_opening")
                editor.setMilestoneField("event_time", "2026-11-15 22:55")
                editor.setMilestoneField("box_id", str(box_id))
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                opened = editor.property("state")
                assert opened["error"] == ""
                assert opened["selected_milestone"]["box_id"] == box_id
                assert editor.setKind("questionable_determination_start")
                editor.setMilestoneField("event_time", "2026-11-15 23:00")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                final = editor.property("state")
                assert final["error"] == "" and final["count_completion"] is None
                assert [(row["kind"], row["revision"]) for row in final["milestones"]] == [
                    ("conversion_complete", 2),
                    ("first_box_opening", 1),
                    ("questionable_determination_start", 1),
                ]
                assert len(final["milestone_history"]) == 4
                assert api.get(path).json()["milestones"] == final["milestones"]


def test_two_station_clients_keep_reviewed_heads_until_explicit_reload_and_preserve_corrections(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, target = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (_, po):
        with box_staff(admin, database_url, clock, "counting_officer", [target["id"]]) as (api, co):
            with boxes_editor(https_server, qt_app, po, origin["id"]) as (_, sender):
                with boxes_editor(https_server, qt_app, co, target["id"]) as (_, receiver):
                    fill_box(sender)
                    sender.create()
                    wait_for(qt_app, lambda: setup_idle(sender))
                    box_id = sender.property("state")["selected"]["id"]
                    receiver.refresh()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    assert receiver.loadBox(box_id)
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    receiver.setField("event_time", "2026-11-15 23:10")
                    receiver.receive()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    assert receiver.property("state")["error"] == "box_departure_required"
                    assert receiver.property("state")["forms"]["event_time"] == "2026-11-15 23:10"
                    sender.setField("event_time", "2026-11-15 22:45")
                    sender.depart()
                    wait_for(qt_app, lambda: setup_idle(sender))
                    receiver.refresh()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    stale = receiver.property("state")
                    assert stale["items"][0]["revision"] == 2
                    assert stale["selected"]["revision"] == 1 and stale["newer_revision"] is True
                    receiver.receive()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    assert receiver.property("state")["error"] == "revision_conflict"
                    assert receiver.property("state")["selected"]["revision"] == 1
                    assert receiver.reload(True)
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    receiver.setField("event_time", "2026-11-15 23:10")
                    receiver.receive()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    assert receiver.property("state")["selected"]["revision"] == 3
                    sender.refresh()
                    wait_for(qt_app, lambda: setup_idle(sender))
                    assert sender.property("state")["selected"]["revision"] == 2
                    assert [row["kind"] for row in sender.property("state")["history"]] == [
                        "prepared",
                        "departure",
                    ]
                    assert sender.reload(True)
                    wait_for(qt_app, lambda: setup_idle(sender))
                    sender.setField("event_time", "2026-11-15 22:46")
                    sender.setField("reason", "核對送箱紙本紀錄後修正")
                    sender.correctDeparture()
                    wait_for(qt_app, lambda: setup_idle(sender))
                    revised = sender.property("state")
                    assert revised["error"] == "" and revised["selected"]["revision"] == 4
                    assert revised["selected"]["receipt_at"] == "2026-11-15T15:10:00Z"
                    assert revised["history"][-1]["kind"] == "departure_correction"
                    receiver.reload(True)
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    receiver.setField("event_time", "2026-11-15 23:11")
                    receiver.setField("reason", "核對接收時間後修正")
                    receiver.correctReceipt()
                    wait_for(qt_app, lambda: setup_idle(receiver))
                    final = receiver.property("state")
                    assert final["error"] == "" and final["selected"]["revision"] == 5
                    assert final["selected"]["receipt"]["actor_id"] == co["id"]
                    assert [row["kind"] for row in final["history"]] == [
                        "prepared",
                        "departure",
                        "receipt",
                        "departure_correction",
                        "receipt_correction",
                    ]
                    assert api.get(f"/api/workspace/stations/{target['id']}/boxes").json()[
                        "items"
                    ] == [final["selected"]]


def test_box_and_milestone_drafts_have_independent_discard_guards(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (_, account):
        with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            editor.setField("event_time", "2026-11-15 22:47")
            editor.setMilestoneField("event_time", "2026-11-15 22:50")
            assert not editor.loadBox(0)
            assert editor.property("state")["error"] == "unsaved_box_changes"
            assert editor.loadBox(0, True)
            discarded = editor.property("state")
            assert discarded["forms"]["event_time"] == ""
            assert discarded["milestone_forms"]["event_time"] == "2026-11-15 22:50"
            assert discarded["dirty"] is True
            assert not editor.setKind("first_box_opening")
            assert editor.property("state")["milestone_kind"] == "conversion_complete"
            editor.setField("event_time", "2026-11-15 22:48")
            assert editor.setKind("first_box_opening", True)
            switched = editor.property("state")
            assert switched["forms"]["event_time"] == "2026-11-15 22:48"
            assert switched["milestone_forms"]["event_time"] == "" and switched["dirty"] is True
            assert not editor.reload()
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["dirty"] is False


@pytest.mark.parametrize("dirty_form", ["milestone", "box"])
def test_changing_one_review_target_preserves_the_other_dirty_form_without_discard(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    dirty_form: str,
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        created = po.post(path, json=prepared_box())
        assert created.status_code == 201
        with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (
            _,
            account,
        ):
            with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
                if dirty_form == "milestone":
                    editor.setMilestoneField("event_time", "2026-11-15 22:50")
                    editor.setMilestoneField("reason", "保留事項草稿")
                    draft = editor.property("state")["milestone_forms"]
                    assert editor.loadBox(created.json()["id"])
                    wait_for(qt_app, lambda: setup_idle(editor))
                    selected = editor.property("state")
                    assert selected["selected"]["id"] == created.json()["id"]
                    assert selected["milestone_forms"] == draft and selected["dirty"] is True
                    assert editor.loadBox(0)
                    assert editor.property("state")["milestone_forms"] == draft
                else:
                    editor.setField("event_time", "2026-11-15 22:45")
                    editor.setField("reason", "保留交收草稿")
                    draft = editor.property("state")["forms"]
                    assert editor.setKind("first_box_opening")
                    switched = editor.property("state")
                    assert switched["milestone_kind"] == "first_box_opening"
                    assert switched["forms"] == draft and switched["dirty"] is True
                assert not editor.reload()
                assert editor.property("state")["error"] == "unsaved_box_changes"


def test_dynamic_arrivals_exceed_four_boxes_and_local_receipts_need_no_departure(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        for index in range(6):
            assert (
                po.post(path, json=prepared_box(box_reference=f"本地票箱 {index:04d}")).status_code
                == 201
            )
        with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (
            _,
            account,
        ):
            with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
                items = editor.property("state")["items"]
                assert len(items) == 6
                for row in items:
                    assert editor.loadBox(row["id"])
                    wait_for(qt_app, lambda: setup_idle(editor))
                    editor.setField("event_time", "2026-11-15 22:45")
                    editor.receive()
                    wait_for(qt_app, lambda: setup_idle(editor))
                    state = editor.property("state")
                    assert state["error"] == ""
                    assert state["selected"]["status"] == "received"
                    assert state["selected"]["departure_at"] is None
                assert all(row["status"] == "received" for row in editor.property("state")["items"])


@pytest.mark.parametrize("action", ["create", "departure", "receipt", "milestone"])
def test_uncertain_box_writes_retry_the_same_command_once_after_live_refresh(
    admin: TestClient,
    database_url: str,
    box_boundary_server: BoxBoundaryServer,
    qt_app: QCoreApplication,
    action: str,
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, target = stations["N2"], stations["N1"]
    box_boundary_server.clock.value = clock.value
    source = f"/api/workspace/stations/{origin['id']}/boxes"
    destination = f"/api/workspace/stations/{target['id']}/boxes"
    with ExitStack() as stack:
        po, po_account = stack.enter_context(
            box_staff(
                admin,
                database_url,
                clock,
                "polling_officer",
                [origin["id"]],
            )
        )
        co, co_account = stack.enter_context(
            box_staff(
                admin,
                database_url,
                clock,
                "counting_officer",
                [target["id"]],
            )
        )
        box_id = 0
        if action in ("departure", "receipt"):
            prepared = po.post(source, json=prepared_box())
            assert prepared.status_code == 201
            box_id = prepared.json()["id"]
            if action == "receipt":
                assert (
                    po.post(
                        f"{source}/{box_id}/departure",
                        json=event_command(1, "2026-11-15T22:45:00+08:00"),
                    ).status_code
                    == 201
                )
        station = origin if action in ("create", "departure") else target
        account = po_account if action in ("create", "departure") else co_account
        with boxes_editor(box_boundary_server, qt_app, account, station["id"]) as (_, editor):
            if box_id:
                assert editor.loadBox(box_id)
                wait_for(qt_app, lambda: setup_idle(editor))
            if action == "create":
                fill_box(editor)
                command = editor.create
            elif action == "milestone":
                editor.setMilestoneField("event_time", "2026-11-15 22:50")
                command = editor.saveMilestone
            else:
                editor.setField(
                    "event_time",
                    "2026-11-15 22:45" if action == "departure" else "2026-11-15 23:10",
                )
                command = editor.depart if action == "departure" else editor.receive
            before = editor.property("state")
            box_boundary_server.truncate_next_write = True
            command()
            wait_for(qt_app, lambda: setup_idle(editor), timeout=12)
            failed = editor.property("state")
            assert failed["error"] == "disconnected"
            assert failed["forms"] == before["forms"]
            assert failed["milestone_forms"] == before["milestone_forms"]
            assert failed["selected"] == before["selected"]
            assert failed["selected_milestone"] == before["selected_milestone"]
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["forms"] == before["forms"]
            command()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["dirty"] is False
            api, path = (po, source) if action in ("create", "departure") else (co, destination)
            snapshot = api.get(path).json()
            if action == "milestone":
                assert len(snapshot["milestone_history"]) == 1
                assert saved["selected_milestone"]["revision"] == 1
            else:
                assert len(snapshot["items"]) == 1
                expected = {"create": 1, "departure": 2, "receipt": 3}[action]
                assert saved["selected"]["revision"] == expected
                assert len(saved["history"]) == expected


def test_late_box_snapshot_cannot_replace_a_different_selected_station(
    admin: TestClient,
    database_url: str,
    box_boundary_server: BoxBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    first, second = stations["N1"], stations["S1"]
    box_boundary_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [first["id"], second["id"]]) as (
        _,
        account,
    ):
        with boxes_editor(box_boundary_server, qt_app, account, first["id"]) as (client, editor):
            box_boundary_server.hold_station_id = first["id"]
            editor.refresh()
            wait_for(qt_app, box_boundary_server.held_started.is_set)
            workspace = client.property("workspace")
            workspace.selectStation(second["id"])
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == second["id"]
            box_boundary_server.release_held.set()
            wait_for(qt_app, box_boundary_server.held_finished.is_set)
            qt_app.processEvents()
            final = editor.property("state")
            assert final["station_id"] == second["id"]
            assert final["context"]["station"]["id"] == second["id"]
            assert final["items"] == [] and final["selected"] == {}


def test_current_server_box_reports_preserve_dirty_forms_and_reviewed_heads_in_three_languages(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station, clock = box_stations(admin)["N2"], BoxClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        prepared = api.post(path, json=prepared_box())
        assert prepared.status_code == 201
        with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            assert editor.loadBox(prepared.json()["id"])
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setField("event_time", "2026-11-15 22:45")
            editor.setField("reason", "UNSAVED_ONLY_SOURCE")
            before = editor.property("state")
            departed = api.post(
                f"{path}/{prepared.json()['id']}/departure",
                json=event_command(1, "2026-11-15T22:45:00+08:00"),
            )
            assert departed.status_code == 201
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["newer_revision"] is True
            for locale in ("tc", "sc", "en"):
                editor.preview(locale)
                wait_for(qt_app, lambda: setup_idle(editor))
                state = editor.property("state")
                assert state["error"] == ""
                expected = api.get(path + f"/statement?locale={locale}")
                assert expected.status_code == 200 and state["report"] == expected.json()
                assert state["report_text"] == "\n".join(expected.json()["preview_lines"])
                assert state["report"]["items"][0]["revision"] == 2
                assert state["selected"] == before["selected"]
                assert state["forms"] == before["forms"] and state["dirty"] is True
                assert "UNSAVED_ONLY_SOURCE" not in state["report_text"]
                for extension in ("csv", "pdf"):
                    destination = tmp_path / f"box-current-{locale}.{extension}"
                    editor.download(extension, destination.as_uri(), locale)
                    wait_for(qt_app, lambda: setup_idle(editor))
                    assert editor.property("state")["error"] == "" and destination.is_file()
                    if extension == "csv":
                        assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
                        text = destination.read_text(encoding="utf-8-sig")
                    else:
                        text = "\n".join(
                            page.extract_text() for page in PdfReader(destination).pages
                        )
                    assert "票箱 0001" in text and "UNSAVED_ONLY_SOURCE" not in text
                    assert editor.property("state")["forms"] == before["forms"]
                    assert editor.property("state")["selected"] == before["selected"]


def test_stale_milestone_validation_preserves_inputs_until_reasoned_reload_and_correction(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        prepared = po.post(path, json=prepared_box())
        assert prepared.status_code == 201
        box_id = prepared.json()["id"]
        with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (
            api,
            account,
        ):
            with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
                editor.setMilestoneField("event_time", "2026-11-15 22:50")
                external = api.put(
                    path + "/milestones/conversion_complete",
                    json=event_command(0, "2026-11-15T22:49:00+08:00", box_id=None),
                )
                assert external.status_code == 200
                editor.refresh()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["newer_revision"] is True
                assert editor.property("state")["selected_milestone"] == {}
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == "revision_conflict"
                assert (
                    editor.property("state")["milestone_forms"]["event_time"] == "2026-11-15 22:50"
                )
                assert editor.reload(True)
                wait_for(qt_app, lambda: setup_idle(editor))
                editor.setMilestoneField("event_time", "2026-11-15 22:50")
                editor.saveMilestone()
                assert editor.property("state")["error"] == "box_correction_reason_required"
                editor.setMilestoneField("reason", "核對轉換紀錄後修正")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["selected_milestone"]["revision"] == 2
                assert editor.setKind("first_box_opening")
                editor.setMilestoneField("event_time", "2026-11-15 22:55")
                for invalid in ("", "0", "-1", "1.5", "١"):
                    editor.setMilestoneField("box_id", invalid)
                    editor.saveMilestone()
                    assert editor.property("state")["error"] == "box_validation"
                editor.setMilestoneField("box_id", str(box_id))
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == "box_receipt_required"
                assert (
                    editor.property("state")["milestone_forms"]["event_time"] == "2026-11-15 22:55"
                )
                assert (
                    api.post(
                        f"{path}/{box_id}/receipt",
                        json=event_command(1, "2026-11-15T22:45:00+08:00"),
                    ).status_code
                    == 201
                )
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["selected_milestone"]["box_id"] == box_id
                assert editor.setKind("questionable_determination_start")
                editor.setMilestoneField("event_time", "2026-11-15 22:54")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == "box_validation"
                assert (
                    editor.property("state")["milestone_forms"]["event_time"] == "2026-11-15 22:54"
                )
                editor.setMilestoneField("event_time", "2026-11-15 23:00")
                editor.saveMilestone()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == ""
                assert editor.property("state")["count_completion"] is None


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_box_role_and_local_guards_leave_retained_election_reports_readable(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    role: str,
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    station = stations["N1"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        prepared = po.post(path, json=prepared_box())
        assert prepared.status_code == 201
        with box_staff(admin, database_url, clock, role, [station["id"]]) as (_, account):
            with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
                assert editor.loadBox(prepared.json()["id"])
                wait_for(qt_app, lambda: setup_idle(editor))
                if role == "polling_officer":
                    editor.setField("event_time", "2026-11-15 22:45")
                    editor.depart()
                    wait_for(qt_app, lambda: setup_idle(editor))
                    assert editor.property("state")["error"] == "box_validation"
                    assert editor.property("state")["forms"]["event_time"] == "2026-11-15 22:45"
                    editor.saveMilestone()
                    assert editor.property("state")["error"] == "counting_officer_required"
                else:
                    editor.create()
                    assert editor.property("state")["error"] == "polling_officer_required"
                if role == "supervisor":
                    original = editor.property("state")["forms"]
                    editor.setField("reason", "不可修改")
                    assert editor.property("state")["forms"] == original
                    editor.receive()
                    assert editor.property("state")["error"] == "counting_officer_required"
                arrange_retained_polling_election(database_url, stations["election"]["id"])
                editor.refresh()
                wait_for(qt_app, lambda: setup_idle(editor))
                before = editor.property("state")
                assert before["context"]["election"]["status"] == "finalized"
                editor.setField("reason", "不能修改已完成選舉")
                editor.setMilestoneField("reason", "不能修改已完成選舉")
                assert editor.property("state")["forms"] == before["forms"]
                assert editor.property("state")["milestone_forms"] == before["milestone_forms"]
                editor.preview("en")
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == ""
                assert (
                    editor.property("state")["report"]["scope"]["election"]["status"] == "finalized"
                )


def test_box_report_transport_and_destination_failures_preserve_files_and_both_drafts(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station, clock = box_stations(admin)["N1"], BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (_, account):
        with boxes_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            editor.setField("event_time", "2026-11-15 22:45")
            editor.setMilestoneField("event_time", "2026-11-15 22:50")
            before = editor.property("state")
            destination = tmp_path / "reviewed-box-report.pdf"
            original = b"Retain the reviewed export after a failed transport."
            destination.write_bytes(original)
            https_server.truncate_next_report = True
            editor.download("pdf", destination.as_uri(), "tc")
            wait_for(qt_app, lambda: setup_idle(editor), timeout=12)
            failed = editor.property("state")
            assert failed["error"] == "disconnected" and failed["notice"] != "box_exported"
            assert destination.read_bytes() == original and failed["export_path"] == ""
            assert (
                failed["forms"] == before["forms"]
                and failed["milestone_forms"] == before["milestone_forms"]
            )
            editor.download("pdf", str(destination), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "box_exported"
            assert (
                saved["forms"] == before["forms"]
                and saved["milestone_forms"] == before["milestone_forms"]
            )
            assert saved["dirty"] is True
            assert PdfReader(destination).pages
            exported = destination.read_bytes()
            editor.download("csv", str(tmp_path), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "box_export_failed"
            assert destination.read_bytes() == exported
            editor.download("csv", "relative-box-history.csv", "en")
            assert editor.property("state")["error"] == "box_export_failed"
