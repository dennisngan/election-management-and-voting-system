"""Counter allocation forms cross the public Qt and real TLS/MySQL seams."""

import csv
from pathlib import Path

from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.allocation_desktop_support import allocation_editor
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.stock_support import READY_PASSWORD
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


def test_officer_saves_counter_allocation_and_reads_current_shared_availability(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    setup = allocation_setup
    station_id = setup["station"]["id"]
    client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(https_server.url, setup["account"]["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: setup_idle(workspace))
        editor = client.property("allocations")
        assert editor is not None
        editor.open()
        wait_for(qt_app, lambda: setup_idle(editor))
        initial = editor.property("state")
        assert initial["items"] == []
        assert initial["counters"] == [
            {"id": setup["counter"]["id"], "code": "C1", "name": "發票櫃台一"}
        ]
        assert initial["availability"][0]["available_display"] == "8"
        editor.setField("counter_id", str(setup["counter"]["id"]))
        editor.setField("series", "普通系列 A")
        editor.setField("serial_from", "000001")
        editor.setField("serial_to", "000003")
        editor.setField("event_at", "2026-11-08 08:05")
        assert editor.property("state")["quantity_display"] == "3"
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == ""
        assert saved["selected"]["revision"] == 1
        assert saved["selected"]["quantity_display"] == "3"
        assert saved["forms"]["serial_from"] == "000001"
        assert saved["availability"][0]["available_display"] == "5"
        public = setup["officer"].get(setup["base"] + "/allocations").json()
        assert public["items"][0]["id"] == saved["selected"]["id"]
        assert public["items"][0]["counter"]["id"] == setup["counter"]["id"]
        assert public["availability"][0]["available_quantity"] == 5
        client.signOut()
        assert editor.property("state")["station_id"] == 0
        assert editor.property("state")["items"] == []
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_reasoned_amendment_and_history_preserve_exact_time_and_protect_unsaved_input(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    setup = allocation_setup
    original = setup["officer"].post(
        setup["base"] + "/allocations",
        json=allocation_payload(
            setup["counter"]["id"], event_at="2026-11-08T08:05:17.123456+08:00"
        ),
    )
    assert original.status_code == 201
    allocation_id = original.json()["id"]
    with allocation_editor(https_server, qt_app, setup["account"], setup["station"]["id"]) as (
        _,
        editor,
    ):
        assert editor.loadAllocation(allocation_id, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["forms"]["event_at"] == "2026-11-08 08:05:17.123456"
        editor.setField("serial_to", "000004")
        editor.setField("reason", "核對交收單，更正櫃台範圍")
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == ""
        assert saved["selected"]["revision"] == 2
        assert saved["selected"]["event_at"] == "2026-11-08T00:05:17.123456Z"
        assert saved["availability"][0]["available_display"] == "4"
        assert [row["revision"] for row in saved["history"]] == [1, 2]
        assert editor.loadRevision(1, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        historical = editor.property("state")
        assert historical["historical"] and historical["selected"]["quantity_display"] == "3"
        editor.setField("serial_to", "000006")
        assert editor.property("state")["forms"] == historical["forms"]
        editor.save()
        assert editor.property("state")["error"] == "election_read_only"
        assert editor.loadAllocation(allocation_id, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        editor.setField("serial_to", "000005")
        assert not editor.loadAllocation(0, False)
        assert editor.property("state")["error"] == "unsaved_allocation_changes"
        assert editor.property("state")["forms"]["serial_to"] == "000005"
        assert editor.loadAllocation(0, True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"] == {}
        assert editor.property("state")["forms"]["serial_to"] == ""
        current = setup["officer"].get(setup["base"] + f"/allocations/{allocation_id}").json()
        assert current["revision"] == 2 and current["serial_to"] == "000004"


def test_desktop_exports_the_selected_revision_and_previews_current_stock_separately(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication, tmp_path: Path
) -> None:
    setup = allocation_setup
    path, api = setup["base"] + "/allocations", setup["officer"]
    created = api.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    allocation_id = created.json()["id"]
    changed = api.put(
        path + f"/{allocation_id}",
        json=allocation_payload(
            setup["counter"]["id"], revision=1, serial_to="000004", reason="核對交收單"
        ),
    )
    assert changed.status_code == 200
    with allocation_editor(https_server, qt_app, setup["account"], setup["station"]["id"]) as (
        _,
        editor,
    ):
        assert editor.loadAllocation(allocation_id, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.loadRevision(1, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        editor.setReportScope("allocation_revision")
        for locale, title in (
            ("tc", "P(14) 發票櫃台選票派發紀錄"),
            ("sc", "P(14) 发票柜台选票分配记录"),
            ("en", "P(14) Counter ballot allocations"),
        ):
            editor.preview(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            report = editor.property("state")
            assert report["error"] == ""
            assert report["report"]["revision"] == 1
            assert report["report"]["revision_state"] == "historical"
            assert report["report"]["availability"] is None
            assert report["report_text"].startswith(title)
        csv_path, pdf_path = tmp_path / "p14-r1.csv", tmp_path / "p14-r1.pdf"
        for format, destination in (("csv", csv_path), ("pdf", pdf_path)):
            editor.download(format, destination.as_uri(), "tc")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert editor.property("state")["export_path"] == str(destination)
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        assert any(row[-3:] == ["000001", "000003", "3"] for row in rows)
        assert "歷史版本" in "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
        editor.setReportScope("station_current")
        editor.preview("sc")
        wait_for(qt_app, lambda: setup_idle(editor))
        state = editor.property("state")
        assert state["report"]["report_scope"] == "station_current"
        assert state["report"]["items"][0]["revision"] == 2
        assert state["report"]["availability"][0]["available_quantity"] == 4
        assert state["historical"] and state["selected"]["revision"] == 1
        assert editor.loadAllocation(allocation_id, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        editor.setField("serial_to", "000005")
        editor.preview("tc")
        assert editor.property("state")["error"] == "unsaved_allocation_changes"
        blocked = tmp_path / "unsaved.csv"
        editor.download("csv", str(blocked), "tc")
        assert not blocked.exists()
