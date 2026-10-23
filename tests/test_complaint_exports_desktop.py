"""Saved P19 report scopes through public Qt over real HTTPS and MySQL."""

import asyncio
import csv
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from starlette.responses import JSONResponse, StreamingResponse

from election.server.app import create_app
from tests.complaint_period_support import complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    complaint_payload,
    complaint_staff,
    station_categories,
)
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.test_complaint_periods_desktop import period_editor


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class ExportBoundaryServer(HttpsServer):
    wrong_mime: bool = False
    truncate_download: bool = False
    partial_mutation: bool = False
    hold_path: str = ""
    held_entered: threading.Event = field(default_factory=threading.Event)
    release_held: threading.Event = field(default_factory=threading.Event)
    held_finished: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def export_server(database_url: str, qt_app: QCoreApplication) -> Iterator[ExportBoundaryServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = ExportBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        held = bool(request.method == "GET" and endpoint.hold_path and path == endpoint.hold_path)
        if held:
            endpoint.hold_path = ""
            endpoint.held_entered.set()
            await asyncio.to_thread(endpoint.release_held.wait, 5)
        response = await call_next(request)
        if held:
            endpoint.held_finished.set()
        if (
            response.status_code == 200
            and request.method in ("PUT", "POST")
            and "/complaint-periods/" in path
            and endpoint.partial_mutation
        ):
            endpoint.partial_mutation = False
            return JSONResponse({"incomplete": True})
        if (
            response.status_code == 200
            and request.method == "GET"
            and path.endswith("/statement.pdf")
        ):
            if endpoint.wrong_mime:
                endpoint.wrong_mime = False
                response.headers["Content-Type"] = "application/octet-stream"
            elif endpoint.truncate_download:
                endpoint.truncate_download = False
                return StreamingResponse(
                    iter([b"%PDF-1.4\ntruncated"]),
                    media_type="application/pdf",
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


def saved_case_report(api: TestClient, scope: dict, reference: str) -> tuple[dict, dict]:
    category = station_categories(api, scope["station"]["id"])[0]
    response = api.post(
        scope["case_path"], json=complaint_payload(category, case_reference=reference)
    )
    assert response.status_code == 201
    assert api.put(scope["path"] + "/1", json=period_command()).status_code == 200
    assert api.post(scope["path"] + "/1/submit", json=period_command(1)).status_code == 200
    return category, response.json()


def test_saved_selected_and_current_station_reports_preserve_dirty_reason_and_reviewed_members(
    admin: TestClient,
    database_url: str,
    export_server: ExportBoundaryServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = complaint_period_scope(admin)
    sid, clock = scope["station"]["id"], ComplaintClock()
    export_server.clock.value = clock.value
    reference = "已儲存投訴甲0001"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        saved_case_report(api, scope, reference)
        with period_editor(export_server, qt_app, account, sid) as (_, editor):
            editor.setReason("尚未儲存，不可匯出此原因")
            form, selected = editor.property("state")["forms"], editor.property("state")["selected"]
            editor.preview("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            preview = editor.property("state")
            assert preview["error"] == "" and preview["notice"] == "complaint_report_ready"
            assert preview["report"]["report_scope"] == "period_revision"
            assert preview["report"]["revision"] == 1 and reference in preview["report_text"]
            assert "尚未儲存，不可匯出此原因" not in preview["report_text"]
            editor.previewStation("en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["report_scope"] == "station_current"
            csv_path = tmp_path / "selected.csv"
            editor.download("csv", str(csv_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["notice"] == "complaint_exported"
            with csv_path.open(encoding="utf-8-sig", newline="") as exported:
                assert ["投訴參考編號", reference] in list(csv.reader(exported))
            pdf_path = tmp_path / "selected.pdf"
            editor.download("pdf", pdf_path.as_uri(), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert reference in "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            station_csv = tmp_path / "station.csv"
            editor.download("csv", str(station_csv), "en", True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert "Current saved station P(19)" in station_csv.read_text(encoding="utf-8-sig")
            station_pdf = tmp_path / "station.pdf"
            editor.download("pdf", str(station_pdf), "sc", True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert "P(19) 投诉时段统计报表" in "\n".join(
                page.extract_text() for page in PdfReader(station_pdf).pages
            )
            assert (
                editor.property("state")["forms"] == form
                and editor.property("state")["selected"] == selected
            )
            assert editor.property("state")["dirty"]
            export_server.partial_mutation = True
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "request_failed"
            assert len(api.get(scope["path"] + "/1/history").json()["items"]) == 2
            editor.previewStation("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["items"][0]["revision"] == 2
            assert (
                editor.property("state")["selected"] == selected
                and editor.property("state")["forms"] == form
            )
            editor.download("csv", str(tmp_path / "pending-selected.csv"), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.amend()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["notice"] == "complaint_period_amended"
            assert editor.property("state")["selected"]["revision"] == 2
            assert len(api.get(scope["path"] + "/1/history").json()["items"]) == 2


@pytest.mark.parametrize(
    "locale,title",
    [
        ("tc", "P(19) 投訴時段統計報表"),
        ("sc", "P(19) 投诉时段统计报表"),
        ("en", "P(19) complaint period statistics"),
    ],
)
def test_historical_selected_report_remains_distinct_from_current_station_in_all_languages(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    locale: str,
    title: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    https_server.clock.value = clock.value
    historical_reference, current_reference = "歷史投訴0001", "目前修訂投訴0001"
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        category = station_categories(api, sid)[0]
        first = api.post(
            scope["case_path"],
            json=complaint_payload(category, case_reference=historical_reference),
        ).json()
        assert api.put(path + "/1", json=period_command()).status_code == 200
        assert (
            api.put(
                f"{scope['case_path']}/{first['id']}",
                json=complaint_payload(
                    category,
                    expected_revision=1,
                    case_reference=current_reference,
                ),
            ).status_code
            == 200
        )
        assert api.put(path + "/1", json=period_command(1)).status_code == 200
        with period_editor(https_server, qt_app, account, sid) as (_, editor):
            assert editor.loadRevision(1)
            wait_for(qt_app, lambda: setup_idle(editor))
            selected, form = editor.property("state")["selected"], editor.property("state")["forms"]
            assert editor.property("state")["historical"]
            editor.preview(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            report = editor.property("state")["report"]
            assert report["revision"] == 1 and report["revision_state"] == "historical"
            assert title in editor.property("state")["report_text"]
            assert historical_reference in editor.property("state")["report_text"]
            assert current_reference not in editor.property("state")["report_text"]
            csv_path, pdf_path = (
                tmp_path / f"history-{locale}.csv",
                tmp_path / f"history-{locale}.pdf",
            )
            editor.download("csv", csv_path.as_uri(), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert historical_reference in csv_path.read_text(encoding="utf-8-sig")
            assert current_reference not in csv_path.read_text(encoding="utf-8-sig")
            editor.download("pdf", str(pdf_path), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            assert title in text and historical_reference in text and current_reference not in text
            editor.previewStation(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["items"][0]["revision"] == 2
            assert (
                editor.property("state")["report"]["items"][0]["members"][0]["case_reference"]
                == current_reference
            )
            assert (
                editor.property("state")["selected"] == selected
                and editor.property("state")["forms"] == form
            )
            assert editor.property("state")["historical"]
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert (
                editor.property("state")["report_text"] == ""
                and editor.property("state")["export_path"] == ""
            )


def test_missing_selected_record_requires_explicit_station_scope_and_invalid_locale_is_visible(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = complaint_period_scope(admin)
    sid, clock = scope["station"]["id"], ComplaintClock()
    https_server.clock.value = clock.value
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (_, account),
        period_editor(https_server, qt_app, account, sid) as (_, editor),
    ):
        editor.preview("tc")
        assert editor.property("state")["error"] == "complaint_period_record_not_found"
        absent = tmp_path / "no-selected.csv"
        editor.download("csv", str(absent), "tc")
        assert not absent.exists()
        editor.previewStation("tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        report = editor.property("state")["report"]
        assert report["report_scope"] == "station_current" and report["items"] == []
        assert report["summary"]["missing"] == 3
        editor.previewStation("fr")
        assert editor.property("state")["error"] == "complaint_period_validation"
        station = tmp_path / "explicit-station.csv"
        editor.download("csv", str(station), "en", True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["notice"] == "complaint_exported" and station.is_file()
        assert editor.property("state")["selected"] == {}


def test_failed_exports_preserve_existing_file_and_glyph_fallback_preserves_saved_source(
    admin: TestClient,
    database_url: str,
    export_server: ExportBoundaryServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, clock = scope["station"]["id"], scope["path"], ComplaintClock()
    server = export_server
    server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (api, account):
        category, case = saved_case_report(api, scope, "已儲存投訴甲")
        with period_editor(server, qt_app, account, sid) as (_, editor):
            editor.setReason("保留本機尚未儲存原因")
            form = editor.property("state")["forms"]
            target = tmp_path / "preserved.pdf"
            target.write_bytes(b"keep prior PDF")
            for format, destination in (
                ("txt", str(target)),
                ("csv", "relative.csv"),
                ("csv", "https://example.invalid/report.csv"),
            ):
                editor.download(format, destination, "tc")
                assert editor.property("state")["error"] == "complaint_export_failed"
            editor.download("csv", str(tmp_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "complaint_export_failed"
            server.wrong_mime = True
            editor.download("pdf", str(target), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "complaint_export_failed"
            assert target.read_bytes() == b"keep prior PDF"
            server.truncate_download = True
            editor.download("pdf", str(target), "tc")
            wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
            assert editor.property("state")["error"] == "disconnected"
            assert target.read_bytes() == b"keep prior PDF"
            assert editor.property("state")["forms"] == form and editor.property("state")["dirty"]
            source = "保留投訴字 \U0001f600"
            assert (
                api.post(
                    f"{scope['case_path']}/{case['id']}/amend",
                    json=complaint_payload(
                        category,
                        expected_revision=1,
                        case_reference=source,
                        reason="核對來源字形後修訂參考編號",
                    ),
                ).status_code
                == 200
            )
            assert (
                api.post(
                    path + "/1/amend", json=period_command(1, reason="更新凍結個案參考編號")
                ).status_code
                == 200
            )
            assert api.post(path + "/1/submit", json=period_command(2)).status_code == 200
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            editor.setReason("不得替代已儲存來源的本機原因")
            form, selected = editor.property("state")["forms"], editor.property("state")["selected"]
            editor.preview("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert source in editor.property("state")["report_text"]
            editor.download("pdf", str(target), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "report_glyph_unavailable"
            assert target.read_bytes() == b"keep prior PDF"
            csv_path = tmp_path / "glyph.csv"
            editor.download("csv", str(csv_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["notice"] == "complaint_exported"
            assert source in csv_path.read_text(encoding="utf-8-sig")
            assert "不得替代已儲存來源的本機原因" not in csv_path.read_text(encoding="utf-8-sig")
            assert (
                editor.property("state")["forms"] == form
                and editor.property("state")["selected"] == selected
            )
            assert editor.property("state")["dirty"]


def test_delayed_report_preview_and_download_cannot_cross_a_station_generation(
    admin: TestClient,
    database_url: str,
    export_server: ExportBoundaryServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = complaint_period_scope(admin)
    first, second, clock = scope["station"]["id"], scope["N2"]["id"], ComplaintClock()
    server = export_server
    server.clock.value = clock.value
    with complaint_staff(admin, database_url, clock, "polling_officer", [first, second]) as (
        api,
        account,
    ):
        saved_case_report(api, scope, "第一票站已儲存投訴")
        second_path = f"/api/workspace/stations/{second}/complaint-periods"
        assert api.put(second_path + "/1", json=period_command()).status_code == 200
        with period_editor(server, qt_app, account, first) as (client, editor):
            server.hold_path = scope["path"] + "/1/statement"
            editor.preview("tc")
            wait_for(qt_app, server.held_entered.is_set)
            workspace = client.property("workspace")
            workspace.selectStation(second, True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            server.release_held.set()
            wait_for(qt_app, server.held_finished.is_set)
            QTest.qWait(100)
            assert editor.property("state")["station_id"] == second
            assert (
                editor.property("state")["report"] == {} and editor.property("state")["error"] == ""
            )
            server.held_entered.clear()
            server.release_held.clear()
            server.held_finished.clear()
            server.hold_path = second_path + "/1/statement.pdf"
            target = tmp_path / "generation.pdf"
            target.write_bytes(b"preserve previous file")
            editor.download("pdf", str(target), "tc")
            wait_for(qt_app, server.held_entered.is_set)
            workspace.selectStation(first, True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            server.release_held.set()
            wait_for(qt_app, server.held_finished.is_set)
            QTest.qWait(100)
            assert target.read_bytes() == b"preserve previous file"
            assert editor.property("state")["station_id"] == first
            assert (
                editor.property("state")["export_path"] == ""
                and editor.property("state")["error"] == ""
            )
