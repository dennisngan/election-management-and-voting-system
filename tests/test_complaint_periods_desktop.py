"""P19 reviewed snapshots and commands through public Qt over real HTTPS/MySQL."""

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QCoreApplication, QEvent, QMetaObject
from PySide6.QtTest import QSignalSpy, QTest
from starlette.responses import JSONResponse, StreamingResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.complaint_period_support import READY_PASSWORD, complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    complaint_payload,
    complaint_staff,
    station_categories,
)
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import arrange_finalized_turnout_election


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class PeriodBoundaryServer(HttpsServer):
    mutation_fault: str = ""
    partial_next_page: bool = False
    hold_station_id: int = 0
    held_entered: threading.Event = field(default_factory=threading.Event)
    release_held: threading.Event = field(default_factory=threading.Event)
    held_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def period_boundary_server(
    database_url: str, qt_app: QCoreApplication
) -> Iterator[PeriodBoundaryServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = PeriodBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        held = (
            request.method == "GET"
            and endpoint.hold_station_id
            and path == (f"/api/workspace/stations/{endpoint.hold_station_id}/complaint-periods")
        )
        if held:
            endpoint.hold_station_id = 0
            endpoint.held_entered.set()
            await asyncio.to_thread(endpoint.release_held.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_finished.set()
        mutation = request.method in ("PUT", "POST") and "/complaint-periods/" in path
        if response.status_code == 200 and mutation and endpoint.mutation_fault:
            fault = endpoint.mutation_fault
            endpoint.mutation_fault = ""
            if fault == "partial":
                return JSONResponse({"station_id": int(path.split("/")[4])})
            return StreamingResponse(
                iter([b'{"incomplete":']),
                media_type="application/json",
                headers={"Content-Length": "4096"},
            )
        if (
            response.status_code == 200
            and request.method == "GET"
            and path.endswith("/complaint-periods")
            and endpoint.partial_next_page
        ):
            endpoint.partial_next_page = False
            return JSONResponse({"context": {"station": None}})
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
def period_editor(
    server: HttpsServer, app: QCoreApplication, account: dict, station_id: int
) -> Iterator[tuple[DesktopController, Any]]:
    controller = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        controller.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(app, lambda: state_of(controller)["phase"] == "workspace")
        workspace = controller.property("workspace")
        wait_for(app, lambda: setup_idle(workspace))
        editor = controller.property("complaintPeriods")
        assert editor is not None
        editor.open()
        workspace.selectStation(station_id)
        wait_for(app, lambda: setup_idle(workspace) and setup_idle(editor))
        yield controller, editor
    finally:
        controller.shutdown()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_missing_periods_remain_distinct_from_explicit_zero_at_public_qt_boundary(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, clock = scope["station"]["id"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (_, account),
        period_editor(https_server, qt_app, account, sid) as (_, editor),
    ):
        state = editor.property("state")
        assert state["selected_period"] == 1
        assert state["selected"] == {} and state["current"]["status"] == "missing"
        assert state["period_count_display"] == "3"
        assert state["summary"]["missing_display"] == "3"
        assert state["forms"] == {"reason": ""}
        assert editor.formatTime("not a time") == "—"
        assert editor.formatTime("2026-11-15T00:30:00") == "—"
        assert editor.formatTime("9999-12-31T23:59:59Z") == "—"
        assert editor.formatTime("2026-11-15T00:30:00Z") == "2026-11-15 08:30 HKT"


def test_two_desktops_prepare_submit_and_approve_an_explicit_zero_with_fresh_password(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, clock = scope["station"]["id"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, officer),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (_, supervisor),
        period_editor(https_server, qt_app, officer, sid) as (_, editor),
    ):
        editor.prepare()
        wait_for(qt_app, lambda: setup_idle(editor))
        prepared = editor.property("state")
        assert prepared["error"] == "" and prepared["notice"] == "complaint_period_prepared"
        assert prepared["selected"]["revision"] == 1 and prepared["selected"]["status"] == "draft"
        assert prepared["selected"]["total_received_display"] == "0"
        assert prepared["selected"]["members"] == prepared["selected"]["group_counts"] == []
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["status"] == "submitted"
        with period_editor(https_server, qt_app, supervisor, sid) as (_, reviewer):
            erased = QSignalSpy(reviewer.erasePassword)
            reviewer.approve("wrong-existing-password")
            assert erased.count() >= 1
            wait_for(qt_app, lambda: setup_idle(reviewer))
            assert reviewer.property("state")["error"] == "invalid_credentials"
            before = erased.count()
            reviewer.approve(READY_PASSWORD)
            assert erased.count() > before
            wait_for(qt_app, lambda: setup_idle(reviewer))
            approved = reviewer.property("state")
            assert approved["error"] == "" and approved["notice"] == "complaint_period_approved"
            assert (
                approved["selected"]["status"] == "approved"
                and approved["selected"]["approval_valid"]
            )
            assert approved["summary"]["approved_current_display"] == "1"
            assert READY_PASSWORD not in repr(approved)
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["current"]["status"] == "approved"
        assert editor.property("state")["selected"]["status"] == "submitted"
        assert editor.property("state")["newer_revision"]
        assert editor.reload(True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["status"] == "approved"
        assert api.get(scope["path"] + "/1").json()["total_received"] == 0


def test_live_basis_changes_preserve_reviewed_members_and_reason_until_reasoned_renewal(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        category = station_categories(api, sid)[0]
        first = api.post(scope["case_path"], json=complaint_payload(category)).json()
        second = api.post(
            scope["case_path"],
            json=complaint_payload(
                category,
                case_reference="0002",
                work_status="completed",
                completed_at="2026-11-15T08:45:00+08:00",
            ),
        ).json()
        with period_editor(https_server, qt_app, account, sid) as (_, editor):
            editor.prepare()
            wait_for(qt_app, lambda: setup_idle(editor))
            prepared = editor.property("state")["selected"]
            assert prepared["total_received_display"] == "2"
            assert (
                prepared["total_completed_display"] == prepared["total_in_progress_display"] == "1"
            )
            assert [member["case_id"] for member in prepared["members"]] == [
                first["id"],
                second["id"],
            ]
            assert prepared["group_counts"][0]["label_tc"] == "投票安排"
            editor.submit()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert (
                sv.post(
                    path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
                ).status_code
                == 200
            )
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            original = editor.property("state")["selected"]
            reason = "保留本機更正原因，核對後重新匯報"
            editor.setReason(reason)
            changed = api.post(
                f"{scope['case_path']}/{first['id']}/amend",
                json=complaint_payload(
                    category,
                    expected_revision=1,
                    work_status="completed",
                    completed_at="2026-11-15T09:00:00+08:00",
                    reason="核對投訴紙本後更新處理狀態",
                ),
            )
            assert changed.status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            stale = editor.property("state")
            assert stale["selected"] == original
            assert stale["current"]["record"]["revision"] == original["revision"]
            assert not stale["current"]["approval_valid"] and not stale["current"]["basis_current"]
            assert stale["newer_revision"] and stale["forms"]["reason"] == reason and stale["dirty"]
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            amended = editor.property("state")
            assert amended["error"] == "" and amended["notice"] == "complaint_period_amended"
            assert amended["selected"]["revision"] == 2 and amended["selected"]["status"] == "draft"
            assert amended["selected"]["total_completed_display"] == "2"
            assert (
                amended["selected"]["members"][0]["case_revision_id"]
                == changed.json()["revision_id"]
            )
            assert amended["forms"]["reason"] == reason and not amended["dirty"]
            assert editor.loadRevision(1)
            wait_for(qt_app, lambda: setup_idle(editor))
            historical = editor.property("state")
            assert (
                historical["historical"]
                and historical["selected"]["total_completed_display"] == "1"
            )
            assert historical["current"]["record"]["total_completed_display"] == "2"
            editor.setReason("不應改動歷史")
            assert historical["forms"] == editor.property("state")["forms"]
            editor.prepare()
            assert editor.property("state")["error"] == "election_read_only"


@pytest.mark.parametrize("fault", ["truncated", "partial"])
def test_partial_success_keeps_pending_prepare_until_exact_saved_revision_is_read_back(
    admin: TestClient,
    database_url: str,
    period_boundary_server: PeriodBoundaryServer,
    qt_app: QCoreApplication,
    fault: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    server = period_boundary_server
    server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account),
        period_editor(server, qt_app, account, sid) as (_, editor),
    ):
        server.mutation_fault = fault
        editor.prepare()
        # Deliberate truncation can remain open until the transport's8s deadline.
        wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
        uncertain = editor.property("state")
        assert uncertain["selected"] == {} and uncertain["notice"] == ""
        assert uncertain["dirty"] and uncertain["error"] in ("request_failed", "disconnected")
        assert api.get(path + "/1").json()["revision"] == 1
        editor.prepare()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == "" and saved["notice"] == "complaint_period_prepared"
        assert saved["selected"]["revision"] == 1 and not saved["dirty"]
        assert len(api.get(path + "/1/history").json()["items"]) == 1
        assert server.request_count("PUT", path + "/1") == 2


def test_failed_page_readback_preserves_pending_after_the_write_and_exact_revision_succeed(
    admin: TestClient,
    database_url: str,
    period_boundary_server: PeriodBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    server = period_boundary_server
    server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account),
        period_editor(server, qt_app, account, sid) as (_, editor),
    ):
        server.partial_next_page = True
        editor.prepare()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["dirty"] and editor.property("state")["selected"] == {}
        assert (
            editor.property("state")["notice"] == ""
            and editor.property("state")["error"] == "request_failed"
        )
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["current"]["record"]["revision"] == 1
        assert editor.property("state")["selected"] == {}
        editor.prepare()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["notice"] == "complaint_period_prepared"
        assert not editor.property("state")["dirty"]
        assert len(api.get(path + "/1/history").json()["items"]) == 1


def test_stale_reason_keeps_dirty_navigation_and_station_discard_explicit(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, other, path, clock = (
        scope["station"]["id"],
        scope["N2"]["id"],
        scope["path"],
        ComplaintClock(),
    )
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid, other]) as (
            api,
            account,
        ),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        assert (
            sv.post(
                path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
            ).status_code
            == 200
        )
        with (
            period_editor(https_server, qt_app, account, sid) as (client, first),
            period_editor(https_server, qt_app, account, sid) as (_, second),
        ):
            first.setReason(" \n")
            first.amend()
            assert first.property("state")["error"] == "complaint_period_validation"
            first.setReason("第一台電腦未儲存原因")
            second.setReason("第二台電腦先提交更正原因")
            second.amend()
            wait_for(qt_app, lambda: setup_idle(second))
            first.refresh()
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["newer_revision"]
            assert first.property("state")["selected"]["revision"] == 1
            assert first.property("state")["current"]["record"]["revision"] == 2
            first.amend()
            wait_for(qt_app, lambda: setup_idle(first))
            assert first.property("state")["error"] == "revision_conflict"
            assert first.property("state")["forms"]["reason"] == "第一台電腦未儲存原因"
            for action in (
                lambda: first.reload(),
                lambda: first.selectPeriod(2),
                lambda: first.setPage(1),
                lambda: first.loadRevision(1),
            ):
                assert not action()
                assert first.property("state")["error"] == "unsaved_complaint_period_changes"
            assert not first.open(other, "polling_officer")
            workspace = client.property("workspace")
            workspace.selectStation(other)
            assert workspace.property("state")["error"] == "unsaved_station_changes"
            assert first.property("state")["station_id"] == sid
            workspace.selectStation(other, True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(first))
            assert first.property("state")["station_id"] == other
            assert first.property("state")["selected"] == {} and first.property("state")[
                "forms"
            ] == {"reason": ""}


def test_public_qt_period_slots_preserve_large_ordinals_and_bounded_page_sizes(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    sid, clock = scope["station"]["id"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (_, account),
        period_editor(https_server, qt_app, account, sid) as (_, editor),
    ):
        assert editor.property("state")["period_count_display"] == "4733542080"
        assert len(editor.property("state")["items"]) == 100
        assert QMetaObject.invokeMethod(
            editor,
            "selectPeriod",
            Q_RETURN_ARG(bool),
            Q_ARG("qlonglong", 4733542080),
            Q_ARG(bool, False),
        )
        wait_for(qt_app, lambda: setup_idle(editor))
        selected = editor.property("state")["selected_period_context"]
        assert selected["period_index_display"] == "4733542080"
        assert selected["end_at"] == "9999-12-31T23:59:59.999999Z"
        assert QMetaObject.invokeMethod(
            editor,
            "setPage",
            Q_RETURN_ARG(bool),
            Q_ARG("qlonglong", 4733542079),
            Q_ARG(bool, False),
        )
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["offset"] == 4733542079
        assert len(editor.property("state")["items"]) == 1
        assert not editor.selectPeriod(4733542081) and not editor.setPage(4733542080)


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_readers_cannot_prepare_or_amend_and_only_supervisor_can_approve(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    role: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, _),
        complaint_staff(admin, database_url, clock, role, [sid]) as (_, account),
    ):
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        with period_editor(https_server, qt_app, account, sid) as (_, editor):
            form = editor.property("state")["forms"]
            editor.setReason("不可改動")
            assert editor.property("state")["forms"] == form
            for action in (editor.prepare, editor.submit, editor.amend):
                action()
                assert editor.property("state")["error"] == "polling_officer_required"
            erased = QSignalSpy(editor.erasePassword)
            editor.approve(READY_PASSWORD)
            assert erased.count() >= 1
            wait_for(qt_app, lambda: setup_idle(editor))
            assert READY_PASSWORD not in repr(editor.property("state"))
            if role == "supervisor":
                assert editor.property("state")["selected"]["approval_valid"]
            else:
                assert editor.property("state")["error"] == "supervisor_required"


def test_retained_context_preserves_dirty_reason_and_logout_resets_public_state(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    https_server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        with period_editor(https_server, qt_app, account, sid) as (client, editor):
            reason = "選舉完結時仍保留的本機更正原因"
            editor.setReason(reason)
            arrange_finalized_turnout_election(database_url, scope["election"]["id"])
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["context"]["election"]["status"] == "finalized"
            editor.setReason("不應改動")
            assert editor.property("state")["forms"]["reason"] == reason
            editor.amend()
            assert editor.property("state")["error"] == "election_read_only"
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["status"] == "submitted"
            erased = QSignalSpy(editor.erasePassword)
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert (
                editor.property("state")["selected"] == {}
                and editor.property("state")["history"] == []
            )
            assert editor.property("state")["forms"] == {"reason": ""} and erased.count() >= 1


def test_pending_approval_retries_keep_uuid_after_basis_flags_change_and_require_fresh_password(
    admin: TestClient,
    database_url: str,
    period_boundary_server: PeriodBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    server = period_boundary_server
    server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (_, account),
    ):
        category = station_categories(api, sid)[0]
        case = api.post(scope["case_path"], json=complaint_payload(category)).json()
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert api.post(path + "/1/submit", json=period_command(1)).status_code == 200
        with period_editor(server, qt_app, account, sid) as (_, editor):
            erased = QSignalSpy(editor.erasePassword)
            server.mutation_fault = "partial"
            editor.approve(READY_PASSWORD)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert (
                editor.property("state")["dirty"]
                and editor.property("state")["selected"]["status"] == "submitted"
            )
            assert api.get(path + "/1").json()["status"] == "approved"
            assert (
                api.post(
                    f"{scope['case_path']}/{case['id']}/amend",
                    json=complaint_payload(
                        category,
                        expected_revision=1,
                        description="核對後更正投訴描述",
                        reason="紙本核對更正",
                    ),
                ).status_code
                == 200
            )
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["newer_revision"]
            assert not editor.property("state")["current"]["basis_current"]
            assert editor.property("state")["selected"]["status"] == "submitted"
            editor.approve("wrong-existing-password")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "invalid_credentials"
            before = erased.count()
            editor.approve(READY_PASSWORD)
            assert erased.count() > before
            wait_for(qt_app, lambda: setup_idle(editor))
            confirmed = editor.property("state")
            assert confirmed["error"] == "" and not confirmed["dirty"]
            assert confirmed["selected"]["status"] == "approved"
            assert (
                not confirmed["selected"]["approval_valid"]
                and confirmed["selected"]["review_required"]
            )
            assert len(api.get(path + "/1/history").json()["items"]) == 1
            assert READY_PASSWORD not in repr(confirmed)


def test_delayed_previous_station_read_cannot_replace_a_new_station_generation(
    admin: TestClient,
    database_url: str,
    period_boundary_server: PeriodBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    first, second, clock = scope["station"]["id"], scope["N2"]["id"], ComplaintClock()
    server = period_boundary_server
    server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [first, second]) as (
        api,
        account,
    ):
        category = station_categories(api, first)[0]
        second_cases = f"/api/workspace/stations/{second}/complaints"
        assert api.post(second_cases, json=complaint_payload(category)).status_code == 201
        for station_id in (first, second):
            assert (
                api.put(
                    f"/api/workspace/stations/{station_id}/complaint-periods/1",
                    json=period_command(),
                ).status_code
                == 200
            )
        with period_editor(server, qt_app, account, first) as (client, editor):
            assert editor.property("state")["selected"]["total_received_display"] == "0"
            server.hold_station_id = first
            editor.refresh()
            wait_for(qt_app, server.held_entered.is_set)
            workspace = client.property("workspace")
            workspace.selectStation(second)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["selected"]["total_received_display"] == "1"
            server.release_held.set()
            wait_for(qt_app, server.held_finished.is_set)
            QTest.qWait(100)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["station_id"] == second
            assert editor.property("state")["selected"]["total_received_display"] == "1"
            assert editor.property("state")["current"]["record"]["total_received_display"] == "1"
            assert editor.property("state")["error"] == ""


def test_period_end_is_server_authority_and_unchanged_submission_can_retry_at_the_boundary(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope = complaint_period_scope(admin)
    sid, clock = (
        scope["station"]["id"],
        ComplaintClock(datetime(2026, 11, 15, 0, 29, 59, tzinfo=UTC)),
    )
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (_, account),
        period_editor(https_server, qt_app, account, sid) as (_, editor),
    ):
        editor.prepare()
        wait_for(qt_app, lambda: setup_idle(editor))
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == "complaint_period_not_ended"
        assert editor.property("state")["selected"]["status"] == "draft"
        https_server.clock.value = datetime(2026, 11, 15, 0, 30, tzinfo=UTC)
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["status"] == "submitted"
        assert editor.property("state")["notice"] == "complaint_period_submitted"
