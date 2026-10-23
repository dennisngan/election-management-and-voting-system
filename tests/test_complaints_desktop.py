"""Complaint case work through public Qt controls, verified HTTPS and real MySQL."""

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import JSONResponse, StreamingResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.complaint_period_support import complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    category_edit,
    complaint_payload,
    complaint_staff,
    complaint_stations,
    station_categories,
)
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import arrange_retained_polling_election

READY_PASSWORD = "Complaint-Ready-Test-84!"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class ComplaintBoundaryServer(HttpsServer):
    fault: str = ""
    hold_station_id: int = 0
    held_started: threading.Event = field(default_factory=threading.Event)
    release_held: threading.Event = field(default_factory=threading.Event)
    held_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def complaint_boundary_server(
    database_url: str, qt_app: QCoreApplication
) -> Iterator[ComplaintBoundaryServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = ComplaintBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def response_boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        held = (
            endpoint.hold_station_id > 0
            and request.method == "GET"
            and path == f"/api/workspace/stations/{endpoint.hold_station_id}/complaints"
        )
        if held:
            endpoint.hold_station_id = 0
            endpoint.held_started.set()
            await asyncio.to_thread(endpoint.release_held.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_finished.set()
        fault = endpoint.fault
        target = (
            "/complaints" in path
            and (
                (fault in ("write", "partial_write") and request.method in ("POST", "PUT"))
                or (
                    fault in ("review", "partial_review")
                    and request.method == "GET"
                    and path.endswith("/history")
                )
            )
            and response.status_code in (200, 201)
        )
        if target:
            endpoint.fault = ""
            if fault.startswith("partial_"):
                return JSONResponse(
                    {"items": [{"revision": 1}]} if fault == "partial_review" else {"id": 1}
                )
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
def complaint_editor(
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
        editor = client.property("complaints")
        assert editor is not None
        assert editor.open(station_id, account["role"])
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_officer_records_and_completes_a_complaint_without_an_opening_record(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        assert api.get(path.removesuffix("complaints") + "polling").json()["items"] == []
        with complaint_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            categories = editor.property("state")["categories"]
            assert [row["code"] for row in categories] == ["9", "10", "11", "12", "30"]
            editor.setField("case_reference", "000AbC")
            editor.setField("received_time", "2026-11-15 08:15")
            editor.setField("category_id", str(categories[0]["id"]))
            editor.setField("description", "入口安排需要協助 <保留原文> & source")
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["dirty"] is False
            assert saved["selected"]["case_reference"] == "000AbC"
            assert saved["selected"]["revision"] == 1
            assert saved["selected"]["received_at"] == "2026-11-15T00:15:00Z"
            assert saved["selected"]["category_label_tc"] == "投票安排"
            assert saved["selected"]["period_index"] == 1
            editor.setField("work_status", "completed")
            editor.setField("completed_time", "2026-11-15 08:45")
            editor.edit()
            wait_for(qt_app, lambda: setup_idle(editor))
            completed = editor.property("state")
            assert completed["error"] == ""
            assert completed["selected"]["revision"] == 2
            assert completed["selected"]["work_status"] == "completed"
            assert completed["selected"]["completed_at"] == "2026-11-15T00:45:00Z"
            assert [row["revision"] for row in completed["history"]] == [1, 2]
            assert api.get(path).json()["items"] == [completed["selected"]]


def fill_case(editor: Any, *, reference: str = "0001", category: dict | None = None) -> None:
    category = category or editor.property("state")["categories"][0]
    editor.setField("case_reference", reference)
    editor.setField("received_time", "2026-11-15 08:15")
    editor.setField("category_id", str(category["id"]))
    editor.setField("description", "原始投訴內容 <文字> & retained")


def review_case(editor: Any, qt_app: QCoreApplication, case: dict) -> None:
    assert editor.loadCase(case["id"])
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["selected"]["id"] == case["id"]


def test_other_and_invalid_status_times_preserve_drafts_and_outside_period_is_not_clamped(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        with complaint_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            fill_case(editor, category=editor.property("state")["categories"][-1])
            editor.setField("description", "  ")
            before = editor.property("state")["forms"]
            editor.create()
            assert editor.property("state")["error"] == "complaint_description_required"
            assert editor.property("state")["forms"] == before
            editor.setField("description", "其他事項的必要解釋")
            editor.setField("received_time", "2026-11-15 07:29")
            editor.setField("work_status", "completed")
            editor.setField("completed_time", "2026-11-15 07:28")
            before = editor.property("state")["forms"]
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "complaint_validation"
            assert editor.property("state")["forms"] == before
            editor.setField("work_status", "in_progress")
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["selected"]["received_at"] == "2026-11-14T23:29:00Z"
            assert saved["selected"]["period_index"] is None
            assert saved["selected"]["coverage_status"] == "outside_configured_periods"
            assert saved["selected"]["completed_at"] is None
            assert api.get(path).json()["items"] == [saved["selected"]]


def test_frozen_disabled_category_and_fractional_source_times_survive_ordinary_edit(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope, clock = complaint_stations(admin), ComplaintClock()
    station = scope["N1"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        category = station_categories(api, station["id"])[0]
        original = api.post(
            path,
            json=complaint_payload(
                category,
                received_at="2026-11-15T08:15:17.123456+08:00",
                work_status="completed",
                completed_at="2026-11-15T09:15:33.654321+08:00",
            ),
        ).json()
        with complaint_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            review_case(editor, qt_app, original)
            changed = admin.put(
                f"/api/elections/{scope['election']['id']}/complaint-categories/{category['id']}",
                json=category_edit(category, label_tc="已重新命名", enabled=False),
            )
            assert changed.status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["categories"][0]["label_tc"] == "已重新命名"
            assert (
                editor.property("state")["form_category"]["label_tc"]
                == original["category_label_tc"]
            )
            editor.setField("description", "在凍結類別下更正內容")
            editor.edit()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["selected"]["revision"] == 2
            for name in ("received_at", "completed_at", "category_revision", "category_label_tc"):
                assert saved["selected"][name] == original[name]
            assert editor.loadCase(0)
            editor.setField("category_id", str(changed.json()["id"]))
            assert editor.property("state")["forms"]["category_id"] == ""
            assert editor.property("state")["error"] == "complaint_category_disabled"


def test_two_qt_clients_keep_reviewed_revision_until_explicit_discard_and_history_is_readonly(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        category = station_categories(api, station["id"])[0]
        original = api.post(path, json=complaint_payload(category)).json()
        with (
            complaint_editor(https_server, qt_app, account, station["id"]) as (_, first),
            complaint_editor(https_server, qt_app, account, station["id"]) as (_, second),
        ):
            review_case(first, qt_app, original)
            review_case(second, qt_app, original)
            first.setField("description", "第一個客戶端更正")
            first.edit()
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["selected"]["revision"] == 2
            second.setField("description", "第二個客戶端未存文字")
            before = second.property("state")
            second.refresh()
            wait_for(qt_app, lambda: setup_idle(second))
            refreshed = second.property("state")
            assert refreshed["selected"] == before["selected"]
            assert refreshed["forms"] == before["forms"] and refreshed["newer_revision"]
            second.edit()
            wait_for(qt_app, lambda: setup_idle(second))
            assert second.property("state")["error"] == "revision_conflict"
            assert second.property("state")["forms"] == before["forms"]
            assert not second.reload()
            assert not second.loadCase(0)
            assert not second.loadRevision(1)
            assert second.reload(True)
            wait_for(qt_app, lambda: setup_idle(second))
            assert second.property("state")["selected"]["revision"] == 2
            assert second.loadRevision(1)
            wait_for(qt_app, lambda: setup_idle(second))
            history = second.property("state")
            assert history["historical"] and history["newer_revision"]
            second.setField("description", "不可改寫歷史")
            second.edit()
            assert second.property("state")["error"] == "complaint_historical_readonly"
            assert second.property("state")["forms"] == history["forms"]
            assert len(api.get(f"{path}/{original['id']}/history").json()["items"]) == 2


def test_submitted_members_and_late_new_cases_use_reasoned_amendment_not_draft_edit(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    sid, path, periods = scope["station"]["id"], scope["case_path"], scope["path"]
    https_server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        original = api.post(path, json=complaint_payload(station_categories(api, sid)[0])).json()
        with complaint_editor(https_server, qt_app, account, sid) as (_, editor):
            review_case(editor, qt_app, original)
            editor.setField("description", "已提交前開始的本地草稿")
            assert api.put(periods + "/1", json=period_command()).status_code == 200
            assert api.post(periods + "/1/submit", json=period_command(1)).status_code == 200
            before = editor.property("state")["forms"]
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            protected = editor.property("state")
            assert protected["selected"]["ever_submitted"] is False
            assert protected["current"]["ever_submitted"] is True
            assert protected["requires_amendment"] is True and protected["forms"] == before
            editor.edit()
            assert editor.property("state")["error"] == "complaint_amendment_required"
            editor.amend()
            assert editor.property("state")["error"] == "complaint_amendment_reason_required"
            editor.setField("reason", "更正已提交統計的來源投訴")
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 2
            assert editor.property("state")["selected"]["ever_submitted"] is True
            assert editor.loadCase(0)
            fill_case(editor, reference="LATE0001")
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "complaint_late_reason_required"
            assert editor.property("state")["dirty"] and not editor.property("state")["selected"]
            editor.setField("reason", "事後補錄已提交時段的投訴")
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            late = editor.property("state")
            assert late["error"] == ""
            assert late["notice"] == "complaint_saved"
            assert late["selected"]["ever_submitted"] is False
            assert late["selected"]["requires_amendment"] is True
            editor.setField("description", "補錄後更正")
            editor.edit()
            assert editor.property("state")["error"] == "complaint_amendment_required"
            editor.setField("reason", "有理由的補錄更正")
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 2
            report = api.get(periods + "/1").json()
            assert report["total_received"] == 1 and not report["basis_current"]


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_read_roles_cannot_modify_cases_but_can_read_retained_election_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    role: str,
) -> None:
    scope, clock = complaint_stations(admin), ComplaintClock()
    sid = scope["N1"]["id"]
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{sid}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _):
        original = po.post(path, json=complaint_payload(station_categories(po, sid)[0])).json()
    with complaint_staff(admin, database_url, clock, role, [sid]) as (api, account):
        with complaint_editor(https_server, qt_app, account, sid) as (_, editor):
            review_case(editor, qt_app, original)
            before = editor.property("state")["forms"]
            editor.setField("description", "無權修改")
            for action in (editor.create, editor.edit, editor.amend):
                action()
                assert editor.property("state")["error"] == "polling_officer_required"
            assert editor.property("state")["forms"] == before
            arrange_retained_polling_election(database_url, scope["election"]["id"])
            complaint_stations(admin)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["context"]["election"]["status"] == "finalized"
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert (
                editor.property("state")["selected"]["case_reference"] == original["case_reference"]
            )
            assert api.get(path).status_code == 200


@pytest.mark.parametrize("fault", ["write", "review", "partial_write", "partial_review"])
def test_uncertain_creation_keeps_draft_and_retries_the_same_command_once(
    admin: TestClient,
    database_url: str,
    complaint_boundary_server: ComplaintBoundaryServer,
    qt_app: QCoreApplication,
    fault: str,
) -> None:
    station, clock = complaint_stations(admin)["N1"], ComplaintClock()
    server = complaint_boundary_server
    server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        with complaint_editor(server, qt_app, account, station["id"]) as (_, editor):
            fill_case(editor)
            before = editor.property("state")
            server.fault = fault
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor), timeout=12)
            failed = editor.property("state")
            assert failed["error"] in ("disconnected", "request_failed")
            assert failed["forms"] == before["forms"] and failed["dirty"]
            assert failed["selected"] == {} and failed["history"] == []
            assert failed["notice"] == ""
            committed = api.get(path).json()["items"]
            assert len(committed) == 1 and committed[0]["revision"] == 1
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["forms"] == before["forms"]
            assert not editor.property("state")["selected"]
            editor.create()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and not saved["dirty"]
            assert saved["selected"]["id"] == committed[0]["id"]
            assert saved["selected"]["revision"] == 1 and len(saved["history"]) == 1
            assert api.get(path).json()["items"] == [saved["selected"]]


def test_uncertain_edit_preserves_reviewed_head_until_authoritative_history_retry(
    admin: TestClient,
    database_url: str,
    complaint_boundary_server: ComplaintBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = complaint_period_scope(admin), ComplaintClock()
    station = scope["station"]
    server = complaint_boundary_server
    server.clock.value = clock.value
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        original = api.post(
            path, json=complaint_payload(station_categories(api, station["id"])[0])
        ).json()
        with complaint_editor(server, qt_app, account, station["id"]) as (_, editor):
            review_case(editor, qt_app, original)
            editor.setField("description", "已提交但回應未完整讀取")
            before = editor.property("state")
            server.fault = "partial_review"
            editor.edit()
            wait_for(qt_app, lambda: setup_idle(editor))
            failed = editor.property("state")
            assert failed["error"] == "request_failed" and failed["dirty"]
            assert failed["selected"] == before["selected"]
            assert failed["forms"] == before["forms"] and failed["history"] == before["history"]
            assert api.put(scope["path"] + "/1", json=period_command()).status_code == 200
            assert api.post(scope["path"] + "/1/submit", json=period_command(1)).status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["newer_revision"]
            assert editor.property("state")["requires_amendment"]
            editor.edit()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["selected"]["revision"] == 2
            assert saved["selected"]["ever_submitted"]
            assert len(api.get(f"{path}/{original['id']}/history").json()["items"]) == 2


def test_late_station_snapshot_is_fenced_and_dirty_context_switch_requires_discard(
    admin: TestClient,
    database_url: str,
    complaint_boundary_server: ComplaintBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    stations, clock = complaint_stations(admin), ComplaintClock()
    first, second = stations["N1"], stations["S1"]
    server = complaint_boundary_server
    server.clock.value = clock.value
    with complaint_staff(
        admin, database_url, clock, "polling_officer", [first["id"], second["id"]]
    ) as (_, account):
        with complaint_editor(server, qt_app, account, first["id"]) as (client, editor):
            workspace = client.property("workspace")
            fill_case(editor)
            before = editor.property("state")
            workspace.selectStation(second["id"])
            assert workspace.property("state")["error"] == "unsaved_station_changes"
            assert not editor.open(second["id"], account["role"])
            assert editor.property("state")["forms"] == before["forms"]
            workspace.selectStation(second["id"], True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == second["id"]
            assert editor.property("state")["forms"]["case_reference"] == ""
            server.hold_station_id = second["id"]
            editor.refresh()
            wait_for(qt_app, server.held_started.is_set)
            workspace.selectStation(first["id"])
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == first["id"]
            server.release_held.set()
            wait_for(qt_app, server.held_finished.is_set)
            qt_app.processEvents()
            final = editor.property("state")
            assert final["station_id"] == first["id"]
            assert final["context"]["station"]["id"] == first["id"]
            assert final["items"] == [] and final["selected"] == {} and not final["dirty"]
