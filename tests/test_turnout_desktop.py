"""Turnout review uses public Qt controls over verified HTTPS and real MySQL."""

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
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QCoreApplication, QEvent, QMetaObject
from PySide6.QtTest import QSignalSpy
from starlette.responses import StreamingResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    approve_period,
    arrange_finalized_turnout_election,
    submit_period,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class TurnoutBoundaryServer(HttpsServer):
    truncate_next_mutation: bool = False
    truncate_next_page: bool = False
    hold_station_id: int = 0
    held_read_entered: threading.Event = field(default_factory=threading.Event)
    release_held_read: threading.Event = field(default_factory=threading.Event)
    held_read_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def turnout_boundary_server(
    database_url: str, qt_app: QCoreApplication
) -> Iterator[TurnoutBoundaryServer]:
    """Exercise uncertainty at real HTTP boundaries after ordinary API execution."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = TurnoutBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        held = bool(
            request.method == "GET"
            and endpoint.hold_station_id
            and path == f"/api/workspace/stations/{endpoint.hold_station_id}/turnout"
        )
        if held:
            endpoint.hold_station_id = 0
            endpoint.held_read_entered.set()
            await asyncio.to_thread(endpoint.release_held_read.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_read_finished.set()
        mutation = request.method in ("PUT", "POST") and "/turnout/" in path
        page = request.method == "GET" and path.endswith("/turnout")
        if response.status_code == 200 and (
            (mutation and endpoint.truncate_next_mutation) or (page and endpoint.truncate_next_page)
        ):
            if mutation:
                endpoint.truncate_next_mutation = False
            else:
                endpoint.truncate_next_page = False
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
def turnout_editor(
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
        editor = client.property("turnout")
        assert editor is not None
        editor.open()
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def fill_turnout(
    editor: Any, *, hourly: str = "10", cumulative: str = "", source: str = "外部紙本報表"
) -> None:
    editor.setField("supplied_hourly", hourly)
    editor.setField("supplied_cumulative", cumulative)
    editor.setField("event_time", "2026-11-15 09:30")
    editor.setField("source_context", source)


def test_two_desktops_submit_explicit_zero_and_supervisor_approves_its_exact_revision(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, po_account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (_, sv_account),
        turnout_editor(https_server, qt_app, po_account, station_id) as (_, editor),
    ):
        missing = editor.property("state")
        assert missing["selected_period"] == 1
        assert missing["current"]["status"] == "missing"
        assert missing["selected"] == {}
        assert missing["approved_prefix"]["hourly_total_display"] == "—"
        assert missing["period_count_display"] == "3"
        assert editor.formatTime("not a timestamp") == "—"
        assert editor.formatTime("2026-11-15T01:30:00") == "—"
        assert editor.formatTime("9999-12-31T23:59:59Z") == "—"
        editor.setField("supplied_hourly", "0")
        editor.setField("event_time", "2026-11-15 09:30")
        editor.setField("source_context", "紙本明確零人，開站確認仍待處理")
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == ""
        assert saved["notice"] == "turnout_saved"
        assert saved["selected"]["revision"] == 1
        assert saved["selected"]["supplied_hourly_display"] == "0"
        assert saved["forms"]["supplied_hourly"] == "0"
        assert saved["forms"]["supplied_cumulative"] == ""
        assert saved["dirty"] is False
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["status"] == "submitted"
        with turnout_editor(https_server, qt_app, sv_account, station_id) as (_, reviewer):
            erased = QSignalSpy(reviewer.erasePassword)
            reviewer.approve("wrong-existing-password")
            wait_for(qt_app, lambda: setup_idle(reviewer))
            assert reviewer.property("state")["error"] == "invalid_credentials"
            assert erased.count() >= 1
            before = erased.count()
            reviewer.approve(READY_PASSWORD)
            wait_for(qt_app, lambda: setup_idle(reviewer))
            approved = reviewer.property("state")
            assert approved["error"] == ""
            assert approved["notice"] == "turnout_approved"
            assert approved["selected"]["derived_hourly_display"] == "0"
            assert approved["approved_prefix"]["cumulative_end_display"] == "0"
            assert erased.count() > before
            assert READY_PASSWORD not in repr(approved)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["current"]["status"] == "approved"
            assert editor.property("state")["selected"]["status"] == "submitted"
            assert editor.property("state")["newer_revision"] is True
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["status"] == "approved"
            assert api.get(path).json()["approved_prefix"]["cumulative_end"] == 0


def test_two_desktops_keep_dirty_input_separate_from_live_revisions_and_read_only_history(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, first),
        turnout_editor(https_server, qt_app, account, station_id) as (_, second),
    ):
        fill_turnout(first, hourly="10", source="第一部電腦未儲存的資料")
        form = first.property("state")["forms"]
        fill_turnout(second, hourly="20", source="第二部電腦先儲存")
        second.save()
        wait_for(qt_app, lambda: setup_idle(second))
        first.refresh()
        wait_for(qt_app, lambda: setup_idle(first))
        stale = first.property("state")
        assert stale["selected"] == {}
        assert stale["current"]["record"]["revision"] == 1
        assert stale["current"]["record"]["supplied_hourly_display"] == "20"
        assert stale["newer_revision"] is True
        assert stale["forms"] == form
        first.save()
        wait_for(qt_app, lambda: setup_idle(first))
        assert first.property("state")["error"] == "revision_conflict"
        assert first.property("state")["forms"] == form
        assert not first.reload()
        assert not first.selectPeriod(2)
        assert not first.setPage(1)
        assert not first.loadRevision(1)
        assert first.property("state")["error"] == "unsaved_turnout_changes"
        assert first.reload(True)
        wait_for(qt_app, lambda: setup_idle(first))
        assert first.property("state")["forms"]["supplied_hourly"] == "20"
        first.setField("supplied_hourly", "21")
        first.submit()
        assert first.property("state")["error"] == "unsaved_turnout_changes"
        first.save()
        wait_for(qt_app, lambda: setup_idle(first))
        assert first.property("state")["selected"]["revision"] == 2
        assert len(first.property("state")["history"]) == 2
        assert first.loadRevision(1)
        wait_for(qt_app, lambda: setup_idle(first))
        historical = first.property("state")
        assert historical["historical"] is True
        assert historical["selected"]["supplied_hourly_display"] == "20"
        assert historical["current"]["record"]["supplied_hourly_display"] == "21"
        first.setField("supplied_hourly", "99")
        assert first.property("state")["forms"]["supplied_hourly"] == "20"
        first.save()
        assert first.property("state")["error"] == "election_read_only"
        assert first.reload(True)
        wait_for(qt_app, lambda: setup_idle(first))
        assert first.property("state")["historical"] is False
        assert first.property("state")["forms"]["supplied_hourly"] == "21"
        assert api.get(path + "/1").json()["supplied_hourly"] == 21


def test_upstream_amendment_updates_live_approval_flags_without_replacing_a_reviewed_form(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            api,
            path,
            1,
            supplied_hourly=100,
            event_at="2026-11-15T01:30:00Z",
            source_context="首時段紙本",
        )
        approve_period(supervisor, path, 1)
        submit_period(
            api,
            path,
            2,
            supplied_cumulative=115,
            event_at="2026-11-15T02:30:00Z",
            source_context="第二時段累計",
        )
        approve_period(supervisor, path, 2)
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            assert editor.selectPeriod(2)
            wait_for(qt_app, lambda: setup_idle(editor))
            original = editor.property("state")["selected"]
            assert editor.property("state")["current"]["approval_valid"] is True
            editor.setField("source_context", "保留本機尚未儲存的來源說明")
            form = editor.property("state")["forms"]
            amended = api.post(
                path + "/1/amend",
                json=turnout_draft(
                    1,
                    supplied_hourly=110,
                    event_at="2026-11-15T01:30:00Z",
                    source_context="首時段修正",
                    amendment_reason="核對紙本應為110人",
                ),
            )
            assert amended.status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            invalid = editor.property("state")
            assert invalid["selected"] == original
            assert invalid["current"]["record"]["revision"] == original["revision"]
            assert invalid["current"]["approval_valid"] is False
            assert invalid["current"]["review_required"] is True
            assert invalid["newer_revision"] is True
            assert invalid["approved_prefix"]["hourly_total_display"] == "—"
            assert invalid["forms"] == form
            editor.save()
            assert editor.property("state")["error"] == "turnout_state_conflict"
            editor.amend()
            assert editor.property("state")["error"] == "turnout_validation"
            editor.setField("amendment_reason", "上游更正後重新覆核第二時段")
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["notice"] == "turnout_amended"
            assert editor.property("state")["selected"]["revision"] == 2
            assert editor.property("state")["selected"]["status"] == "draft"
            assert (
                editor.property("state")["forms"]["amendment_reason"]
                == "上游更正後重新覆核第二時段"
            )
            editor.setField("supplied_cumulative", "116")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 3
            assert (
                editor.property("state")["selected"]["amendment_reason"]
                == "上游更正後重新覆核第二時段"
            )


def test_public_qt_period_and_page_arguments_support_the_full_configured_ordinal_range(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    station_id, clock = scope["stations"][0]["id"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (_, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        assert editor.property("state")["period_count_display"] == "4733542080"
        assert QMetaObject.invokeMethod(
            editor,
            "selectPeriod",
            Q_RETURN_ARG(bool),
            Q_ARG("qlonglong", 4733542080),
            Q_ARG(bool, False),
        )
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected_period"] == 4733542080
        assert (
            editor.property("state")["selected_period_context"]["end_at"]
            == "9999-12-31T23:59:59.999999Z"
        )
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


def test_turnout_page_changes_preserve_dirty_forms_and_cover_overnight_partial_periods(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(
        admin,
        planned_opening_at="2026-11-15T22:30:00+08:00",
        planned_closing_at="2026-11-16T02:01:00+08:00",
        reporting_interval_minutes=2,
    )
    station_id, clock = scope["stations"][0]["id"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (_, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        assert editor.property("state")["period_count_display"] == "106"
        assert len(editor.property("state")["items"]) == 100
        assert editor.setPage(100)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected_period"] == 101
        assert len(editor.property("state")["items"]) == 6
        assert editor.selectPeriod(106)
        wait_for(qt_app, lambda: setup_idle(editor))
        selected = editor.property("state")["selected_period_context"]
        assert selected["start_at"] == "2026-11-15T18:00:00Z"
        assert selected["end_at"] == "2026-11-15T18:01:00Z"
        assert editor.formatTime(selected["end_at"]) == "2026-11-16 02:01 HKT"
        editor.setField("supplied_hourly", "0")
        assert not editor.setPage(0)
        assert editor.property("state")["error"] == "unsaved_turnout_changes"
        assert editor.property("state")["forms"]["supplied_hourly"] == "0"
        assert editor.setPage(0, True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected_period"] == 1
        assert editor.property("state")["forms"]["supplied_hourly"] == ""
        assert editor.selectPeriod(106)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["offset"] == 100
        assert editor.property("state")["selected_period"] == 106
        assert not editor.selectPeriod(107)
        assert not editor.setPage(106)


def test_turnout_amount_forms_and_live_totals_preserve_integers_above_javascript_precision(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        fill_turnout(editor, hourly="9007199254740993", cumulative="9007199254740993")
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == ""
        assert saved["forms"]["supplied_hourly"] == "9007199254740993"
        assert saved["forms"]["supplied_cumulative"] == "9007199254740993"
        assert saved["selected"]["supplied_hourly_display"] == "9007199254740993"
        assert saved["selected"]["derived_hourly_display"] == "—"
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        approve_period(supervisor, path, 1)
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        latest = editor.property("state")
        assert latest["approved_prefix"]["hourly_total_display"] == "9007199254740993"
        assert latest["current"]["record"]["derived_cumulative_end_display"] == "9007199254740993"
        assert editor.reload(True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["derived_hourly_display"] == "9007199254740993"
        assert (
            editor.property("state")["history"][0]["supplied_hourly_display"] == "9007199254740993"
        )
        assert api.get(path + "/1").json()["supplied_hourly"] == 9007199254740993


def test_optional_empty_amounts_and_local_validation_do_not_turn_missing_data_into_zero(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["supplied_hourly_display"] == "—"
        assert editor.property("state")["forms"]["supplied_hourly"] == ""
        assert api.get(path + "/1").json()["supplied_hourly"] is None
        editor.submit()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == "turnout_validation"
        before = https_server.request_count("PUT", path + "/1")
        for invalid in ("１０", "-1", "1.5", "9223372036854775808"):
            editor.setField("supplied_hourly", invalid)
            editor.save()
            assert editor.property("state")["error"] == "turnout_validation"
            assert editor.property("state")["forms"]["supplied_hourly"] == invalid
        assert https_server.request_count("PUT", path + "/1") == before
        editor.setField("supplied_hourly", "0")
        editor.setField("event_time", "not a date")
        editor.save()
        assert editor.property("state")["error"] == "turnout_validation"
        assert editor.property("state")["forms"]["supplied_hourly"] == "0"
        assert len(api.get(path + "/1/history").json()["items"]) == 1


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_turnout_desktop_readers_cannot_prepare_records_and_only_supervisor_can_approve(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    role: str,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, _),
        turnout_staff(admin, database_url, clock, [station_id], role) as (_, account),
    ):
        submit_period(
            api,
            path,
            1,
            supplied_hourly=10,
            event_at="2026-11-15T01:30:00Z",
            source_context="待主管覆核",
        )
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            form = editor.property("state")["forms"]
            editor.setField("supplied_hourly", "99")
            assert editor.property("state")["forms"] == form
            for action in (editor.save, editor.submit, editor.amend):
                action()
                assert editor.property("state")["error"] == "polling_officer_required"
            erased = QSignalSpy(editor.erasePassword)
            editor.approve(READY_PASSWORD)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert erased.count() >= 1
            assert READY_PASSWORD not in repr(editor.property("state"))
            if role == "supervisor":
                assert editor.property("state")["selected"]["status"] == "approved"
            else:
                assert editor.property("state")["error"] == "supervisor_required"
                assert editor.property("state")["selected"]["status"] == "submitted"


def test_turnout_station_discard_and_finalized_read_only_context_preserve_staff_input(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    first, second = [station["id"] for station in scope["stations"]]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [first, second]) as (_, account),
        turnout_editor(https_server, qt_app, account, first) as (client, editor),
    ):
        fill_turnout(editor, source="尚未儲存的第一票站來源")
        assert not editor.open(second, "polling_officer")
        workspace = client.property("workspace")
        workspace.selectStation(second)
        assert workspace.property("state")["error"] == "unsaved_station_changes"
        assert state_of(client)["station"]["id"] == first
        workspace.selectStation(second, True)
        wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
        assert editor.property("state")["station_id"] == second
        assert editor.property("state")["selected_period"] == 1
        assert editor.property("state")["forms"]["source_context"] == ""
        assert editor.open(0, "polling_officer")
        workspace.selectStation(first)
        wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
        assert editor.property("state")["period_count_display"] == "3"
        fill_turnout(editor, source="選舉完結時保留的本機草稿")
        form = editor.property("state")["forms"]
        arrange_finalized_turnout_election(database_url, scope["election"]["id"])
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["context"]["election"]["status"] == "finalized"
        editor.setField("source_context", "不應改動")
        assert editor.property("state")["forms"] == form
        editor.save()
        assert editor.property("state")["error"] == "election_read_only"
        assert editor.property("state")["forms"] == form
        assert editor.reload(True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["history"] == []
        client.signOut()
        assert editor.property("state")["station_id"] == 0
        assert editor.property("state")["selected_period"] == 0
        assert editor.property("state")["selected"] == {}


def test_explicit_discard_when_reselecting_the_current_period_reloads_its_saved_values(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    scope = turnout_scope(admin)
    station_id, clock = scope["stations"][0]["id"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (_, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        fill_turnout(editor, source="明確選擇捨棄的本機草稿")
        assert editor.selectPeriod(1, True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["dirty"] is False
        assert editor.property("state")["forms"]["source_context"] == ""
        assert editor.property("state")["selected"] == {}


@pytest.mark.parametrize("lost_stage", ["mutation", "review_page"])
def test_turnout_uncertain_save_retry_keeps_one_revision_and_preserves_dirty_refresh_input(
    admin: TestClient,
    database_url: str,
    turnout_boundary_server: TurnoutBoundaryServer,
    qt_app: QCoreApplication,
    lost_stage: str,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    server = turnout_boundary_server
    server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_editor(server, qt_app, account, station_id) as (_, editor),
    ):
        fill_turnout(editor, source="只能新增一次的紙本資料")
        form = editor.property("state")["forms"]
        if lost_stage == "mutation":
            server.truncate_next_mutation = True
        else:
            server.truncate_next_page = True
        editor.save()
        # A deliberately incomplete response may reach the transport's8s deadline.
        wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
        uncertain = editor.property("state")
        assert uncertain["error"] == "disconnected"
        assert uncertain["notice"] == ""
        assert uncertain["dirty"] is True
        assert uncertain["forms"] == form
        assert uncertain["selected"] == {}
        persisted = api.get(path + "/1/history").json()["items"]
        assert len(persisted) == 1
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        retried = editor.property("state")
        assert retried["error"] == ""
        assert retried["notice"] == "turnout_saved"
        assert retried["selected"]["revision"] == 1
        assert retried["selected"]["id"] == persisted[0]["id"]
        assert api.get(path + "/1/history").json()["items"] == persisted
        editor.setField("source_context", "網絡失敗時保留下一次草稿")
        dirty = editor.property("state")["forms"]
        server.truncate_next_page = True
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
        assert editor.property("state")["error"] == "disconnected"
        assert editor.property("state")["forms"] == dirty
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == ""
        assert editor.property("state")["forms"] == dirty
        assert editor.property("state")["dirty"] is True


def test_delayed_turnout_page_cannot_replace_a_newly_selected_station(
    admin: TestClient,
    database_url: str,
    turnout_boundary_server: TurnoutBoundaryServer,
    qt_app: QCoreApplication,
) -> None:
    scope = turnout_scope(admin)
    first, second = [station["id"] for station in scope["stations"]]
    clock = TurnoutClock()
    server = turnout_boundary_server
    server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [first, second]) as (api, account):
        for station_id, hourly in ((first, 10), (second, 20)):
            response = api.put(
                f"/api/workspace/stations/{station_id}/turnout/1",
                json=turnout_draft(supplied_hourly=hourly, source_context="指定票站來源"),
            )
            assert response.status_code == 200
        with turnout_editor(server, qt_app, account, first) as (client, editor):
            server.hold_station_id = first
            editor.refresh()
            wait_for(qt_app, server.held_read_entered.is_set)
            workspace = client.property("workspace")
            workspace.selectStation(second)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["selected"]["supplied_hourly_display"] == "20"
            server.release_held_read.set()
            wait_for(qt_app, server.held_read_finished.is_set)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            final = editor.property("state")
            assert final["station_id"] == second
            assert final["selected"]["supplied_hourly_display"] == "20"
            assert final["current"]["record"]["supplied_hourly_display"] == "20"
            assert final["history"][0]["supplied_hourly_display"] == "20"
            assert final["error"] == ""


@pytest.mark.parametrize("status", ["draft", "submitted"])
def test_content_edits_keep_precise_original_time_until_the_officer_changes_its_minute(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    status: str,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    original_time = "2026-11-15T01:30:17.123456Z"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        created = api.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=10,
                event_at=original_time,
                source_context="外部報表保留秒及微秒",
            ),
        )
        assert created.status_code == 200
        if status == "submitted":
            submitted = api.post(path + "/1/submit", json=turnout_command(1))
            assert submitted.status_code == 200
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            assert editor.property("state")["forms"]["event_time"] == "2026-11-15 09:30"
            editor.setField("source_context", "只更正外部來源說明，原始時間不變")
            if status == "submitted":
                editor.setField("amendment_reason", "核對外部報表來源")
                editor.amend()
            else:
                editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["selected"]["revision"] == 2
            assert saved["selected"]["event_at"] == original_time
            current = api.get(path + "/1")
            assert current.status_code == 200
            assert current.json()["event_at"] == original_time
            history = api.get(path + "/1/history")
            assert history.status_code == 200
            assert [row["event_at"] for row in history.json()["items"]] == [
                original_time, original_time
            ]
            if status == "submitted":
                assert saved["selected"]["amendment_reason"] == "核對外部報表來源"

            editor.setField("event_time", "2026-11-15 09:31")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["selected"]["revision"] == 3
            current = api.get(path + "/1")
            assert current.status_code == 200
            assert current.json()["event_at"] == "2026-11-15T01:31:00Z"
            history = api.get(path + "/1/history")
            assert history.status_code == 200
            assert [row["revision"] for row in history.json()["items"]] == [1, 2, 3]
            assert [row["event_at"] for row in history.json()["items"]] == [
                original_time, original_time, "2026-11-15T01:31:00Z"
            ]
