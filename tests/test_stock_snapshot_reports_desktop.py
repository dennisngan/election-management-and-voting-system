"""Selected P(12) reports use saved revisions through public Qt and verified TLS."""

import asyncio
import csv
import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtNetwork import QNetworkAccessManager
from starlette.responses import JSONResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


@dataclass
class ReportServer(HttpsServer):
    report_fault: str = ""
    hold_report: bool = False
    report_entered: threading.Event = field(default_factory=threading.Event)
    release_report: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def https_server(database_url: str, qt_app: QCoreApplication) -> Iterator[ReportServer]:
    """Fault only real report responses after the authenticated MySQL route completes."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    endpoint = ReportServer(f"https://localhost:{listener.getsockname()[1]}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def report_boundary(request: Request, call_next: Any) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        if (
            request.method != "GET"
            or "/stock-snapshots/statement" not in request.url.path
            or response.status_code != 200
        ):
            return response
        if endpoint.hold_report:
            endpoint.report_entered.set()
            await asyncio.to_thread(endpoint.release_report.wait)
        fault, endpoint.report_fault = endpoint.report_fault, ""
        if fault == "mime":
            response.headers["content-type"] = "application/json"
            return response
        if fault:
            body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
            if fault == "revision":
                body["revision"] += 1
            elif fault == "scope":
                body["scope"]["constituency"]["id"] += 1
            elif fault == "saved_values":
                body["items"][0]["ordinary_remaining_quantity"] = 99
            elif fault == "preview_line":
                body["preview_lines"].append(42)
            elif fault == "generated_at":
                body.pop("generated_at")
            return JSONResponse(body)
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
        endpoint.release_report.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive()


@dataclass
class ReviewedSnapshot:
    editor: Any
    client: DesktopController
    server: ReportServer
    api: TestClient
    path: str
    counter_id: int
    original: dict
    current: dict


@pytest.fixture
def reviewed_snapshot(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> Iterator[ReviewedSnapshot]:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-snapshots"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": counter["id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = api.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        corrected = api.put(
            path + f"/{original['id']}",
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "紙本核對：第四號已發出。\n第二行：保留原快照時間。",
                "counters": [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000005",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ],
            },
        )
        assert corrected.status_code == 200
        current = corrected.json()
        assert original["ordinary_remaining_quantity"] == original["ordinary_issued_quantity"] == 3
        assert current["ordinary_remaining_quantity"] == 2
        assert current["ordinary_issued_quantity"] == 4
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stockSnapshots")
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadSnapshot(current["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"] == current
            yield ReviewedSnapshot(
                editor, client, https_server, api, path, counter["id"], original, current
            )
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_preview_uses_reviewed_saved_revision_without_replacing_dirty_input(
    reviewed_snapshot: ReviewedSnapshot,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    setup = reviewed_snapshot
    editor = setup.editor
    assert editor.editSelected()
    editor.setRangeField(setup.counter_id, 0, "serial_from", "000006")
    editor.setField("reason", "UNSAVED correction must stay outside the report")
    draft = editor.property("state")
    assert draft["dirty"] is True
    editor.preview("en")
    wait_for(qt_app, lambda: setup_idle(editor))
    result = editor.property("state")
    assert result["error"] == "" and result["notice"] == "stock_report_ready"
    report = result["report"]
    assert report["report_scope"] == "snapshot_revision" and report["revision_state"] == "current"
    assert report["snapshot_id"] == setup.current["id"] and report["revision"] == 2
    assert report["items"] == [setup.current] and report["availability"] is None
    assert "P(12) Counter remaining stock and issuance" in result["report_text"]
    assert "Ordinary papers remaining · 2" in result["report_text"]
    assert "Stock-derived ordinary issuance · 4" in result["report_text"]
    assert "2026-11-15 09:30:17.123456 HKT" in result["report_text"]
    assert "not verified elector counts" in result["report_text"]
    assert "UNSAVED" not in result["report_text"]
    assert (
        result["forms"] == draft["forms"] and result["counter_reports"] == draft["counter_reports"]
    )
    assert result["dirty"] is True and result["selected"] == setup.current
    destination = tmp_path / "current-dirty.csv"
    editor.download("csv", str(destination), "en")
    wait_for(qt_app, lambda: setup_idle(editor))
    rows = list(csv.reader(StringIO(destination.read_text(encoding="utf-8-sig"))))
    assert ["Ordinary papers remaining", "2"] in rows
    assert ["Stock-derived ordinary issuance", "4"] in rows
    assert "UNSAVED" not in destination.read_text(encoding="utf-8-sig")
    exported = editor.property("state")
    assert exported["dirty"] is True and exported["selected"] == setup.current
    assert exported["forms"] == draft["forms"]
    assert exported["counter_reports"] == draft["counter_reports"]
    history = setup.api.get(setup.path + f"/{setup.current['id']}/history")
    assert history.status_code == 200 and history.json()["items"] == [setup.original, setup.current]


@pytest.mark.parametrize(
    ("locale", "labels"),
    [
        (
            "en",
            {
                "title": "P(12) Counter remaining stock and issuance",
                "basis": "Report basis",
                "selected": "Selected saved snapshot revision",
                "state": "Revision state",
                "historical": "Historical revision",
                "id": "Snapshot ID",
                "revision": "Revision",
                "remaining": "Ordinary papers remaining",
                "issued": "Stock-derived ordinary issuance",
                "disclaimer": "not verified elector counts",
            },
        ),
        (
            "tc",
            {
                "title": "P(12) 發票櫃台結餘及發票紀錄",
                "basis": "報表基準",
                "selected": "所選已儲存快照版本",
                "state": "版本狀態",
                "historical": "歷史版本",
                "id": "快照記錄編號",
                "revision": "修訂版本",
                "remaining": "剩餘普通選票數量",
                "issued": "庫存推算普通發票數量",
                "disclaimer": "並非已核實選民人數",
            },
        ),
        (
            "sc",
            {
                "title": "P(12) 发票柜台结余及发票记录",
                "basis": "报表依据",
                "selected": "所选已保存快照版本",
                "state": "版本状态",
                "historical": "历史版本",
                "id": "快照记录编号",
                "revision": "修订版本",
                "remaining": "剩余普通选票数量",
                "issued": "库存推算普通发票数量",
                "disclaimer": "并非已核实选民人数",
            },
        ),
    ],
)
def test_historical_preview_and_download_keep_the_original_saved_revision(
    reviewed_snapshot: ReviewedSnapshot,
    qt_app: QCoreApplication,
    tmp_path: Path,
    locale: str,
    labels: dict[str, str],
) -> None:

    setup = reviewed_snapshot
    editor = setup.editor
    assert editor.loadRevision(1, False)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["historical"] is True
    editor.preview(locale)
    wait_for(qt_app, lambda: setup_idle(editor))
    preview = editor.property("state")
    assert preview["report"]["items"] == [setup.original]
    assert preview["report"]["revision_state"] == "historical"
    assert labels["remaining"] + " · 3" in preview["report_text"]
    assert labels["issued"] + " · 3" in preview["report_text"]
    csv_path = tmp_path / "historical.csv"
    editor.download("csv", QUrl.fromLocalFile(str(csv_path)).toString(), locale)
    wait_for(qt_app, lambda: setup_idle(editor))
    exported = editor.property("state")
    assert exported["error"] == "" and exported["notice"] == "stock_exported"
    assert exported["export_path"] == str(csv_path)
    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(StringIO(raw.decode("utf-8-sig"))))
    assert [labels["basis"], labels["selected"]] in rows
    assert [labels["state"], labels["historical"]] in rows
    assert [labels["id"], str(setup.original["id"])] in rows
    assert [labels["revision"], "1"] in rows
    assert [labels["remaining"], "3"] in rows
    assert [labels["issued"], "3"] in rows
    assert ["普通系列 A", "000004", "000006", "3"] in rows
    assert [labels["remaining"], "2"] not in rows
    pdf_path = tmp_path / "historical.pdf"
    editor.download("pdf", str(pdf_path), locale)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["export_path"] == str(pdf_path)
    assert pdf_path.read_bytes().startswith(b"%PDF-")
    text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
    for expected in (
        labels["title"],
        labels["historical"],
        "000004",
        "000006",
        "2026-11-15 09:30:17.123456 HKT",
        labels["disclaimer"],
    ):
        assert expected in text
    retained = editor.property("state")
    assert retained["selected"] == setup.original and retained["historical"] is True
    assert retained["forms"] == preview["forms"]
    history = setup.api.get(setup.path + f"/{setup.current['id']}/history")
    assert history.status_code == 200 and history.json()["items"] == [setup.original, setup.current]


@pytest.mark.parametrize(
    "fault", ["revision", "scope", "saved_values", "preview_line", "generated_at"]
)
def test_unconfirmed_report_responses_do_not_acknowledge_or_replace_the_draft(
    reviewed_snapshot: ReviewedSnapshot,
    qt_app: QCoreApplication,
    fault: str,
) -> None:
    setup = reviewed_snapshot
    editor = setup.editor
    assert editor.editSelected()
    editor.setField("reason", "UNSAVED report-boundary correction")
    draft = editor.property("state")
    setup.server.report_fault = fault
    editor.preview("en")
    wait_for(qt_app, lambda: setup_idle(editor))
    rejected = editor.property("state")
    assert rejected["error"] == "request_failed" and rejected["notice"] == ""
    assert rejected["report"] == {} and rejected["report_text"] == ""
    assert rejected["dirty"] is True and rejected["selected"] == setup.current
    assert rejected["forms"] == draft["forms"]
    assert rejected["counter_reports"] == draft["counter_reports"]
    editor.preview("en")
    wait_for(qt_app, lambda: setup_idle(editor))
    recovered = editor.property("state")
    assert recovered["error"] == "" and recovered["notice"] == "stock_report_ready"
    assert recovered["report"]["items"] == [setup.current]
    assert recovered["forms"] == draft["forms"] and recovered["dirty"] is True
    history = setup.api.get(setup.path + f"/{setup.current['id']}/history")
    assert history.status_code == 200 and history.json()["items"] == [setup.original, setup.current]


def test_export_rejects_unsafe_destinations_and_wrong_mime_without_replacing_a_file(
    reviewed_snapshot: ReviewedSnapshot,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    setup = reviewed_snapshot
    editor = setup.editor
    destination = tmp_path / "preserved.csv"
    destination.write_bytes(b"preserve existing local contents")
    csv_route = setup.path + "/statement.csv"
    before = setup.server.request_count("GET", csv_route)
    for format, path, locale in (
        ("xlsx", str(destination), "en"),
        ("csv", "relative.csv", "en"),
        ("csv", "https://example.invalid/report.csv", "en"),
        ("csv", str(destination), "unknown"),
    ):
        editor.download(format, path, locale)
        state = editor.property("state")
        assert state["error"] in ("stock_export_failed", "stock_snapshot_validation")
        assert state["notice"] == "" and state["export_path"] == ""
        assert destination.read_bytes() == b"preserve existing local contents"
    assert setup.server.request_count("GET", csv_route) == before
    setup.server.report_fault = "mime"
    editor.download("csv", str(destination), "en")
    wait_for(qt_app, lambda: setup_idle(editor))
    rejected = editor.property("state")
    assert rejected["error"] == "stock_export_failed" and rejected["notice"] == ""
    assert rejected["export_path"] == ""
    assert destination.read_bytes() == b"preserve existing local contents"
    assert setup.server.request_count("GET", csv_route) == before + 1
    editor.download("csv", str(destination), "en")
    wait_for(qt_app, lambda: setup_idle(editor))
    recovered = editor.property("state")
    assert recovered["error"] == "" and recovered["notice"] == "stock_exported"
    assert recovered["export_path"] == str(destination)
    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert recovered["selected"] == setup.current and recovered["dirty"] is False


@pytest.mark.parametrize("operation", ["preview", "download"])
def test_a_report_completed_after_logout_cannot_publish_or_write_to_the_old_session(
    reviewed_snapshot: ReviewedSnapshot,
    qt_app: QCoreApplication,
    tmp_path: Path,
    operation: str,
) -> None:
    setup = reviewed_snapshot
    editor = setup.editor
    destination = tmp_path / "late-report.csv"
    destination.write_bytes(b"do not replace after logout")
    expected_path = setup.path + ("/statement" if operation == "preview" else "/statement.csv")
    completed = threading.Event()

    def finished(reply: Any) -> None:
        if reply.url().path() == expected_path:
            completed.set()

    for manager in setup.client.findChildren(QNetworkAccessManager):
        manager.finished.connect(finished)
    setup.server.hold_report = True
    if operation == "preview":
        editor.preview("en")
    else:
        editor.download("csv", str(destination), "en")
    wait_for(qt_app, setup.server.report_entered.is_set)
    setup.client.signOut()
    reset = editor.property("state")
    assert reset["station_id"] == 0 and reset["selected"] == {}
    assert reset["report"] == {} and reset["report_text"] == "" and reset["export_path"] == ""
    setup.server.release_report.set()
    wait_for(qt_app, completed.is_set)
    retained = editor.property("state")
    assert retained["station_id"] == 0 and retained["selected"] == {}
    assert (
        retained["report"] == {} and retained["report_text"] == "" and retained["export_path"] == ""
    )
    assert retained["busy"] is False and retained["notice"] == ""
    assert destination.read_bytes() == b"do not replace after logout"
