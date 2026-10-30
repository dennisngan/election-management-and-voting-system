"""Received stock is edited and exported through real TLS/MySQL desktop controls."""

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_desktop_support import fill_ordinary_receipt, stock_editor
from tests.stock_support import (
    READY_PASSWORD,
    ready_client,
    staff_account,
    stock_payload,
    stock_stations,
)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    # These draft/assignment checks must not inherit another test's active election.
    with lifecycle_test_state(database_url):
        yield


def test_officer_records_corrects_previews_and_exports_a_received_stock_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    stations = stock_stations(admin)
    station_id = stations[0]["id"]
    account = staff_account(admin, [station_id])
    with ready_client(database_url, account) as api:
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stock")
            assert editor is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["items"] == []
            editor.setField("series", "收票系列 甲")
            editor.setField("event_at", "2026-11-08 08:00")
            editor.setField("ordinary_quantity", "8")
            editor.setField("replacement_quantity", "1")
            editor.setField("tendered_quantity", "1")
            editor.setRange(0, "serial_from", "000001")
            editor.setRange(0, "serial_to", "000008")
            editor.addRange()
            editor.setRange(1, "pool", "replacement")
            editor.setRange(1, "serial_from", "000009")
            editor.setRange(1, "serial_to", "000009")
            editor.addRange()
            editor.setRange(2, "pool", "tendered")
            editor.setRange(2, "serial_from", "000010")
            editor.setRange(2, "serial_to", "000010")
            assert editor.property("state")["calculated_total_display"] == "10"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            receipt_id = saved["selected"]["id"]
            assert saved["selected"]["revision"] == 1
            assert saved["selected"]["total_display"] == "10"
            assert saved["items"] == [saved["selected"]]
            assert saved["ranges"][0]["serial_from"] == "000001"
            editor.setRange(0, "serial_to", "000007")
            editor.setField("ordinary_quantity", "7")
            editor.setField("reason", "核對紙本收票記錄後修正")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            corrected = editor.property("state")
            assert corrected["error"] == ""
            assert corrected["selected"]["revision"] == 2
            assert corrected["selected"]["total_display"] == "9"
            assert [row["revision"] for row in corrected["history"]] == [1, 2]
            assert corrected["history"][0]["total_display"] == "10"
            assert corrected["history"][1]["reason"] == "核對紙本收票記錄後修正"
            path = f"/api/workspace/stations/{station_id}/stock/{receipt_id}"
            assert api.get(path).json()["ordinary_quantity"] == 7
            for locale, title in (
                ("tc", "選票接收及儲備報表"),
                ("sc", "选票接收及储备报表"),
                ("en", "Ballot stock receipt and reserves"),
            ):
                client.setLocale(locale)
                editor.preview(locale)
                wait_for(qt_app, lambda: setup_idle(editor))
                preview = editor.property("state")
                assert preview["error"] == ""
                assert preview["report"]["items"][0]["revision"] == 2
                assert title in preview["report_text"]
                assert "收票系列 甲" in preview["report_text"]
                assert "000001" in preview["report_text"]
                assert "2026-11-08 08:00" in preview["report_text"]
            csv_path = tmp_path / "received-stock.csv"
            editor.download("csv", str(csv_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["export_path"] == str(csv_path)
            with csv_path.open(encoding="utf-8-sig", newline="") as exported:
                rows = list(csv.reader(exported))
            assert ["普通選票", "7"] in rows
            assert ["替換選票儲備", "1"] in rows
            assert ["重複選票儲備", "1"] in rows
            assert ["普通選票", "000001", "000007", "7"] in rows
            pdf_path = tmp_path / "received-stock.pdf"
            editor.download("pdf", pdf_path.as_uri(), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["export_path"] == str(pdf_path)
            text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            assert "選票接收及儲備報表" in text
            assert "收票系列 甲" in text
            assert "000001" in text and "000007" in text
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["report_text"] == ""
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_stock_arithmetic_and_display_preserve_integers_above_javascript_safe_precision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station = stock_stations(admin)[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as api:
        with stock_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            fill_ordinary_receipt(editor, last="009007199254740993", quantity="9007199254740993")
            editor.setRange(0, "serial_from", "000000000000000001")
            editor.addRange()
            assert len(editor.property("state")["ranges"]) == 2
            editor.removeRange(1)
            assert len(editor.property("state")["ranges"]) == 1
            before = editor.property("state")
            assert before["calculated_total_display"] == "9007199254740993"
            assert before["ranges"][0]["quantity_display"] == "9007199254740993"
            assert before["forms"]["replacement_quantity"] == "0"
            assert before["forms"]["tendered_quantity"] == "0"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["selected"]["total_display"] == "9007199254740993"
            assert saved["selected"]["ordinary_display"] == "9007199254740993"
            assert saved["selected"]["replacement_display"] == "0"
            assert saved["selected"]["tendered_display"] == "0"
            assert saved["selected"]["ranges"][0]["serial_from"] == "000000000000000001"
            assert saved["selected"]["ranges"][0]["serial_to"] == "009007199254740993"
            receipt_id = saved["selected"]["id"]
            raw = api.get(f"/api/workspace/stations/{station['id']}/stock/{receipt_id}")
            assert raw.status_code == 200
            assert raw.json()["total_quantity"] == 9007199254740993
            assert editor.loadReceipt(receipt_id, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["forms"]["ordinary_quantity"] == "9007199254740993"
            editor.preview("sc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert "普通选票: 9007199254740993" in editor.property("state")["report_text"]
            assert "替换选票储备: 0" in editor.property("state")["report_text"]
            assert "重复选票储备: 0" in editor.property("state")["report_text"]
            destination = tmp_path / "large-integers.csv"
            editor.download("csv", str(destination), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            with destination.open(encoding="utf-8-sig", newline="") as exported:
                rows = list(csv.reader(exported))
            assert ["Ordinary papers", "9007199254740993"] in rows
            assert ["Replacement reserve", "0"] in rows
            assert ["Tendered reserve", "0"] in rows


def test_stock_background_refresh_stale_updates_history_and_station_guards_preserve_reviewed_input(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    first, second = stock_stations(admin)[:2]
    account = staff_account(admin, [first["id"], second["id"]])
    with ready_client(database_url, account) as api:
        with stock_editor(https_server, qt_app, account, first["id"]) as (client, editor):
            editor.setField("series", "尚未儲存的普通系列")
            workspace = client.property("workspace")
            workspace.refresh()
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["forms"]["series"] == "尚未儲存的普通系列"
            assert not editor.loadReceipt(0, False)
            assert editor.property("state")["error"] == "unsaved_stock_changes"
            base = f"/api/workspace/stations/{first['id']}/stock"
            saved = api.post(base, json=stock_payload())
            assert saved.status_code == 201
            receipt_id = saved.json()["id"]
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert len(editor.property("state")["items"]) == 1
            assert editor.property("state")["forms"]["series"] == "尚未儲存的普通系列"
            assert not editor.loadReceipt(receipt_id, False)
            assert editor.loadReceipt(receipt_id, True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 1
            editor.setField("reason", "保留尚未儲存的修正原因")
            newer = api.put(
                base + f"/{receipt_id}",
                json=stock_payload(revision=1, reason="另一部電腦修正系列", series="另一普通系列"),
            )
            assert newer.status_code == 200
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            stale = editor.property("state")
            assert stale["newer_revision"] is True
            assert stale["selected"]["revision"] == 1
            assert stale["forms"]["series"] == "普通系列 A"
            assert stale["forms"]["reason"] == "保留尚未儲存的修正原因"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "revision_conflict"
            assert editor.property("state")["forms"]["reason"] == "保留尚未儲存的修正原因"
            assert not editor.loadReceipt(receipt_id, False)
            assert editor.loadReceipt(receipt_id, True)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 2
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            historical = editor.property("state")
            assert historical["historical"] is True
            assert historical["selected"]["revision"] == 1
            assert historical["forms"]["series"] == "普通系列 A"
            editor.setField("series", "不能修改歷史版本")
            assert editor.property("state")["forms"]["series"] == "普通系列 A"
            editor.save()
            assert editor.property("state")["error"] == "election_read_only"
            editor.preview("en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["report"]["revision_state"] == "historical"
            assert "Historical revision" in editor.property("state")["report_text"]
            assert editor.loadRevision(2, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["historical"] is False
            assert editor.property("state")["forms"]["series"] == "另一普通系列"
            editor.setField("reason", "跨票站前保留的輸入")
            workspace.selectStation(second["id"])
            assert state_of(client)["station"]["id"] == first["id"]
            assert editor.property("state")["forms"]["reason"] == "跨票站前保留的輸入"
            workspace.selectStation(second["id"], True)
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == second["id"]
            assert editor.property("state")["forms"]["reason"] == ""
            assert editor.property("state")["report_text"] == ""


@pytest.mark.parametrize(
    ("target", "value"),
    [
        pytest.param("ordinary_quantity", "-1", id="negative-quantity"),
        pytest.param("ordinary_quantity", "1" * 5000, id="oversized-quantity"),
        pytest.param("ordinary_quantity", "１０", id="non-ascii-quantity"),
        pytest.param("ordinary_quantity", "9", id="unbalanced-pools"),
        pytest.param("serial_from", "A01", id="nonnumeric-serial"),
        pytest.param("serial_to", "0", id="reversed-range"),
        pytest.param("serial_to", "1234567890123456789", id="oversized-serial"),
        pytest.param("event_at", "not a time", id="invalid-time"),
        pytest.param("series", "   ", id="blank-series"),
    ],
)
def test_stock_validation_keeps_invalid_input_without_creating_a_receipt(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    target: str,
    value: str,
) -> None:
    station = stock_stations(admin)[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as api:
        with stock_editor(https_server, qt_app, account, station["id"]) as (client, editor):
            fill_ordinary_receipt(editor)
            if target.startswith("serial_"):
                editor.setRange(0, target, value)
            else:
                editor.setField(target, value)
            before = editor.property("state")
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "stock_validation"
            assert editor.property("state")["forms"] == before["forms"]
            assert editor.property("state")["ranges"] == before["ranges"]
            for locale in ("tc", "sc", "en"):
                client.setLocale(locale)
                assert editor.property("state")["forms"] == before["forms"]
                assert editor.property("state")["ranges"] == before["ranges"]
            assert api.get(f"/api/workspace/stations/{station['id']}/stock").json()["items"] == []


def test_stock_export_failures_and_dirty_preview_guards_preserve_saved_and_entered_values(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station = stock_stations(admin)[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as api:
        created = api.post(
            f"/api/workspace/stations/{station['id']}/stock",
            json=stock_payload(series="保留字形 𠮷"),
        )
        assert created.status_code == 201
        receipt_id = created.json()["id"]
        with stock_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            assert editor.loadReceipt(receipt_id, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            before = editor.property("state")
            editor.preview("tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert "保留字形 𠮷" in editor.property("state")["report_text"]
            # A server-side glyph refusal is delivered through the binary adapter's error path.
            missing_glyph_path = tmp_path / "unsupported-glyph.pdf"
            editor.download("pdf", str(missing_glyph_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "report_glyph_unavailable"
            assert editor.property("state")["export_path"] == ""
            assert not missing_glyph_path.exists()
            assert editor.property("state")["forms"] == before["forms"]
            # CSV preserves the source text; an unwritable destination remains a visible failure.
            editor.download("csv", str(tmp_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == "stock_export_failed"
            assert editor.property("state")["forms"] == before["forms"]
            editor.download("zip", str(tmp_path / "unsupported.zip"), "tc")
            assert editor.property("state")["error"] == "stock_export_failed"
            editor.download("csv", "relative-path.csv", "tc")
            assert editor.property("state")["error"] == "stock_export_failed"
            editor.setField("reason", "尚未儲存的修正理由")
            editor.preview("en")
            assert editor.property("state")["error"] == "unsaved_stock_changes"
            guarded_path = tmp_path / "unsaved.csv"
            editor.download("csv", str(guarded_path), "en")
            assert editor.property("state")["error"] == "unsaved_stock_changes"
            assert not guarded_path.exists()
            assert editor.property("state")["forms"]["reason"] == "尚未儲存的修正理由"
            assert not editor.loadRevision(1, False)
            assert editor.loadReceipt(receipt_id, True)
            wait_for(qt_app, lambda: setup_idle(editor))
            preserved_path = tmp_path / "source-glyphs.csv"
            preserved_path.write_text("previous contents", encoding="utf-8")
            editor.download("csv", str(preserved_path), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert "保留字形 𠮷" in preserved_path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_reviewers_read_and_export_stock_without_editing_even_after_client_restart(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    role: str,
) -> None:
    station = stock_stations(admin)[0]
    author = staff_account(admin, [station["id"]])
    reader = staff_account(admin, [station["id"]], role)
    with ready_client(database_url, author) as officer, ready_client(database_url, reader):
        created = officer.post(
            f"/api/workspace/stations/{station['id']}/stock", json=stock_payload()
        )
        assert created.status_code == 201
        receipt_id = created.json()["id"]
        for restart in (False, True):
            with stock_editor(https_server, qt_app, reader, station["id"]) as (_, editor):
                assert len(editor.property("state")["items"]) == 1
                assert editor.loadReceipt(receipt_id, False)
                wait_for(qt_app, lambda: setup_idle(editor))
                before = editor.property("state")
                assert before["role"] == role
                assert before["selected"]["revision"] == 1
                assert before["history"][0]["total_display"] == "10"
                editor.setField("series", "未授權修改")
                editor.addRange()
                editor.removeRange(0)
                editor.setRange(0, "serial_to", "999999")
                assert editor.property("state")["forms"] == before["forms"]
                assert editor.property("state")["ranges"] == before["ranges"]
                assert editor.property("state")["dirty"] is False
                editor.save()
                assert editor.property("state")["error"] == "election_read_only"
                editor.preview("en")
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == ""
                assert (
                    "Ballot stock receipt and reserves" in editor.property("state")["report_text"]
                )
                destination = tmp_path / f"{role}-{restart}.csv"
                editor.download("csv", str(destination), "en")
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == ""
                assert "Ordinary papers,8" in destination.read_text(encoding="utf-8-sig")
        unchanged = officer.get(f"/api/workspace/stations/{station['id']}/stock/{receipt_id}")
        assert unchanged.status_code == 200
        assert unchanged.json() == created.json()


def test_reloading_a_corrected_receipt_updates_the_saved_list_and_protects_older_revisions(
    admin: TestClient, database_url: str, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    station = stock_stations(admin)[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as api:
        base = f"/api/workspace/stations/{station['id']}/stock"
        original = api.post(base, json=stock_payload())
        assert original.status_code == 201
        receipt_id = original.json()["id"]
        with stock_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            assert editor.loadReceipt(receipt_id, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            corrected = api.put(
                base + f"/{receipt_id}",
                json=stock_payload(revision=1, reason="另一部電腦更正", series="更新後系列"),
            )
            assert corrected.status_code == 200
            assert editor.loadReceipt(receipt_id, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"]["revision"] == 2
            assert editor.property("state")["items"][0]["revision"] == 2
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["historical"] is True
            editor.setField("reason", "歷史版本不可直接編輯")
            assert editor.property("state")["dirty"] is False


def test_a_truncated_https_stock_download_reports_failure_and_preserves_the_previous_export(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station = stock_stations(admin)[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as api:
        created = api.post(
            f"/api/workspace/stations/{station['id']}/stock", json=stock_payload()
        )
        assert created.status_code == 201
        with stock_editor(https_server, qt_app, account, station["id"]) as (_, editor):
            assert editor.loadReceipt(created.json()["id"], False)
            wait_for(qt_app, lambda: setup_idle(editor))
            before = editor.property("state")
            destination = tmp_path / "previous-reviewed-export.pdf"
            original_bytes = b"Existing reviewed export must survive a failed network transfer."
            destination.write_bytes(original_bytes)
            https_server.truncate_next_report = True
            editor.download("pdf", str(destination), "tc")
            wait_for(qt_app, lambda: setup_idle(editor), timeout=12)
            failed = editor.property("state")
            assert failed["error"] == "disconnected"
            assert failed["notice"] != "stock_exported"
            assert failed["export_path"] == ""
            assert destination.read_bytes() == original_bytes
            assert failed["forms"] == before["forms"]
            assert failed["selected"] == before["selected"]
            editor.download("pdf", str(destination), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["notice"] == "stock_exported"
            assert editor.property("state")["export_path"] == str(destination)
            exported = "\n".join(page.extract_text() for page in PdfReader(destination).pages)
            assert "選票接收及儲備報表" in exported
            assert "普通系列 A" in exported
            assert editor.property("state")["forms"] == before["forms"]
