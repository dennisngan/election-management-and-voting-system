"""Desktop-selected count forms keep exact revision identity and real export contents."""

from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer


def test_desktop_selects_count_forms_and_exports_requested_language_and_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, questionable_quantity=3, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 2
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        command = complete_f2_command(
            options, determination_started_at="2026-11-15T23:18:12.123456+08:00"
        )
        command["accepted_votes"][0]["quantity"] = 2
        uncertainty = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        next(row for row in command["rejected_papers"] if row["reason_id"] == uncertainty["id"])[
            "quantity"
        ] = 1
        saved = counter.put(path + f"/{created.json()['id']}/f2", json=command)
        assert saved.status_code == 200, saved.text
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            assert editor.selectReportForm("f2") is True
            editor.preview("en")
            wait_for_editor_idle(qt_app, editor)
            f2 = editor.property("state")
            assert f2["report_form"] == "f2" and f2["report"]["form"] == "f2"
            assert f2["report"]["revision"] == 2
            assert "Accepted questionable papers total · 2" in f2["report_text"]
            assert f2["notice"] == "count_report_ready"
            assert editor.selectReportForm("f3") is True
            assert editor.property("state")["report"] == {}
            editor.preview("sc")
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["report"]["title"] == "F3 无效选票总览"
            csv_path = tmp_path / "f3-sc.csv"
            editor.exportStatement("csv", "sc", str(csv_path))
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["notice"] == "count_exported"
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            assert "F3 无效选票总览" in csv_text and "Void for uncertainty" in csv_text
            assert editor.selectReportForm("f4") is True
            pdf_path = tmp_path / "f4-tc.pdf"
            editor.exportStatement("pdf", "tc", str(pdf_path))
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["export_path"] == str(pdf_path)
            pages = PdfReader(pdf_path).pages
            assert len(pages) > 0
            page_text = "\n".join(page.extract_text() for page in pages)
            assert "F4 最終點票總覽" in page_text
            assert "F2 問題選票判定" not in page_text
            assert "F2 判定事件紀錄" in page_text
            assert "2026-11-15 23:18:12.123456 HKT" in page_text
            assert "F2 伺服器記錄時間（香港時間）" in page_text
            assert editor.selectReportForm("count") is True
            editor.preview("en")
            wait_for_editor_idle(qt_app, editor)
            whole = editor.property("state")
            assert whole["report"]["title"] == "Count Record"
            assert whole["report"]["record"]["final_candidate_votes"][0]["quantity"] == 4
            assert editor.selectReportForm("f9") is False
            assert editor.property("state")["report_form"] == "count"
            editor.setF2Field("notes", "Unsaved observation remains protected")
            assert editor.selectReportForm("f2") is False
            assert editor.property("state")["error"] == "unsaved_count_changes"
            assert (
                editor.property("state")["f2_forms"]["notes"]
                == "Unsaved observation remains protected"
            )
