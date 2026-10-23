"""Saved turnout reports use explicit public Qt scopes over real TLS and MySQL."""

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication

from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import HttpsServer, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.test_turnout_desktop import turnout_editor
from tests.turnout_support import TurnoutClock, turnout_draft, turnout_scope, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_turnout_preview_and_download_use_explicit_saved_scopes_without_changing_dirty_input(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        saved = api.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=10,
                event_at="2026-11-15T01:30:00Z",
                source_context="已儲存的外部紙本甲",
            ),
        )
        assert saved.status_code == 200
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.setField("source_context", "尚未儲存，不可匯出此內容")
            form = editor.property("state")["forms"]
            selected = editor.property("state")["selected"]
            editor.preview("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            preview = editor.property("state")
            assert preview["error"] == ""
            assert preview["report"]["report_scope"] == "period_revision"
            assert preview["report"]["revision"] == 1
            assert "已儲存的外部紙本甲" in preview["report_text"]
            assert "尚未儲存，不可匯出此內容" not in preview["report_text"]
            assert preview["forms"] == form and preview["selected"] == selected
            assert preview["dirty"] is True
            editor.previewStation("en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["report_scope"] == "station_current"
            assert editor.property("state")["forms"] == form
            csv_path = tmp_path / "selected-turnout.csv"
            editor.download("csv", str(csv_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["export_path"] == str(csv_path)
            with csv_path.open(encoding="utf-8-sig", newline="") as exported:
                rows = list(csv.reader(exported))
            assert ["外部來源及涵蓋資料", "已儲存的外部紙本甲"] in rows
            assert ["外部提供的本時段人數", "10"] in rows
            pdf_path = tmp_path / "selected-turnout.pdf"
            editor.download("pdf", pdf_path.as_uri(), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            assert "已儲存的外部紙本甲" in text
            station_path = tmp_path / "station-turnout.csv"
            editor.download("csv", str(station_path), "en", True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["notice"] == "turnout_exported"
            assert "Current saved station P(15)" in station_path.read_text(encoding="utf-8-sig")
            assert editor.property("state")["forms"] == form
            assert editor.property("state")["selected"] == selected
            assert editor.property("state")["dirty"] is True


@pytest.mark.parametrize(
    "locale,title",
    [
        ("tc", "P(15) 時段及累計投票人數報表"),
        ("sc", "P(15) 时段及累计投票人数报表"),
        ("en", "P(15) period and cumulative turnout"),
    ],
)
def test_historical_selected_report_stays_separate_from_current_station_in_every_language(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    locale: str,
    title: str,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        first = api.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=9007199254740993,
                event_at="2026-11-15T01:30:00Z",
                source_context="歷史原始外部數字",
            ),
        )
        assert first.status_code == 200
        assert (
            api.put(
                path + "/1",
                json=turnout_draft(1, supplied_hourly=5, source_context="目前已修訂數字"),
            ).status_code
            == 200
        )
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            assert editor.loadRevision(1)
            wait_for(qt_app, lambda: setup_idle(editor))
            selected, form = editor.property("state")["selected"], editor.property("state")["forms"]
            assert editor.property("state")["historical"] is True
            editor.preview(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            report = editor.property("state")["report"]
            assert report["revision"] == 1 and report["revision_state"] == "historical"
            assert report["items"][0]["supplied_hourly"] == 9007199254740993
            assert title in editor.property("state")["report_text"]
            assert "9007199254740993" in editor.property("state")["report_text"]
            assert "目前已修訂數字" not in editor.property("state")["report_text"]
            csv_path, pdf_path = (
                tmp_path / f"history-{locale}.csv",
                tmp_path / f"history-{locale}.pdf",
            )
            editor.download("csv", csv_path.as_uri(), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert "9007199254740993" in csv_path.read_text(encoding="utf-8-sig")
            editor.download("pdf", str(pdf_path), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            assert "9007199254740993" in text
            editor.previewStation(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["items"][0]["revision"] == 2
            assert editor.property("state")["report"]["items"][0]["supplied_hourly"] == 5
            assert editor.property("state")["selected"] == selected
            assert editor.property("state")["forms"] == form
            assert editor.property("state")["historical"] is True
            assert editor.reload(True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report_text"] == ""
            assert editor.property("state")["export_path"] == ""


def test_report_paths_and_incomplete_download_preserve_existing_file_and_dirty_form(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        assert (
            api.put(
                path + "/1",
                json=turnout_draft(supplied_hourly=10, source_context="伺服器已儲存來源"),
            ).status_code
            == 200
        )
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.setField("source_context", "保留本機未儲存來源")
            form = editor.property("state")["forms"]
            target = tmp_path / "preserved.pdf"
            target.write_bytes(b"previously saved report")
            for format, destination in (
                ("txt", str(target)),
                ("csv", "relative.csv"),
                ("csv", "https://example.invalid/report.csv"),
            ):
                editor.download(format, destination, "tc")
                assert editor.property("state")["error"] == "turnout_export_failed"
            editor.download("csv", str(tmp_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "turnout_export_failed"
            https_server.truncate_next_report = True
            editor.download("pdf", str(target), "tc")
            wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
            assert editor.property("state")["error"] == "disconnected"
            assert target.read_bytes() == b"previously saved report"
            assert editor.property("state")["notice"] == ""
            assert editor.property("state")["forms"] == form
            assert editor.property("state")["dirty"] is True
            editor.preview("fr")
            assert editor.property("state")["error"] == "turnout_validation"
            csv_path = tmp_path / "retry.csv"
            editor.download("csv", str(csv_path), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["notice"] == "turnout_exported"
            assert "伺服器已儲存來源" in csv_path.read_text(encoding="utf-8-sig")
            assert "保留本機未儲存來源" not in csv_path.read_text(encoding="utf-8-sig")
            assert editor.property("state")["forms"] == form


def test_unrenderable_saved_glyph_keeps_pdf_unchanged_and_csv_fallback_preserves_source(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    https_server.clock.value = clock.value
    source = "保留外部原始字 \U0001f600"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        assert (
            api.put(
                path + "/1", json=turnout_draft(supplied_hourly=0, source_context=source)
            ).status_code
            == 200
        )
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.setField("source_context", "不可替代已儲存來源的本機草稿")
            form = editor.property("state")["forms"]
            editor.preview("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert source in editor.property("state")["report_text"]
            pdf_path = tmp_path / "glyph.pdf"
            pdf_path.write_bytes(b"keep prior PDF")
            editor.download("pdf", str(pdf_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "report_glyph_unavailable"
            assert pdf_path.read_bytes() == b"keep prior PDF"
            csv_path = tmp_path / "glyph.csv"
            editor.download("csv", str(csv_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert source in csv_path.read_text(encoding="utf-8-sig")
            assert editor.property("state")["forms"] == form
            assert editor.property("state")["dirty"] is True


def test_missing_selected_record_never_silently_becomes_a_station_report(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    scope = turnout_scope(admin)
    station_id, clock = scope["stations"][0]["id"], TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (_, account),
        turnout_editor(https_server, qt_app, account, station_id) as (_, editor),
    ):
        editor.setField("supplied_hourly", "0")
        form = editor.property("state")["forms"]
        editor.preview("tc")
        assert editor.property("state")["error"] == "turnout_record_not_found"
        absent = tmp_path / "no-selected.csv"
        editor.download("csv", str(absent), "tc")
        assert not absent.exists()
        editor.previewStation("tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        report = editor.property("state")["report"]
        assert report["report_scope"] == "station_current"
        assert report["items"] == [] and report["missing_period_count"] == 3
        assert report["approved_prefix"]["cumulative_end"] is None
        station = tmp_path / "explicit-station.csv"
        editor.download("csv", str(station), "tc", True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == ""
        assert station.is_file()
        assert editor.property("state")["forms"] == form
        assert editor.property("state")["dirty"] is True
