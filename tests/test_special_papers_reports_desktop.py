"""Historical special-paper reports use public Qt/TLS previews and real file downloads."""

import csv
from io import StringIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD


def test_historical_preview_and_download_preserve_selected_special_paper_quantities(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        reason = "修訂核對：補發三張，尋回零張。\n第二行：保留歷史版本及原始時間。"
        corrected = officer.put(target, json={
            **setup["command"], "request_id": str(uuid4()), "revision": 1,
            "reason": reason,
            "series": [{
                **setup["entered_series"], "replacement_issued_quantity": 3,
                "spoilt_original_quantity": 3, "retrieved_found_quantity": 0,
            }],
        })
        assert corrected.status_code == 200
        second = corrected.json()
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, setup["account"]["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(setup["snapshot"]["station_id"])
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("specialPapers")
            assert editor is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.loadSnapshot(first["id"]) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["selected"] == second
            assert editor.loadRevision(1) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            original_state = editor.property("state")
            assert original_state["selected"] == first
            assert original_state["historical"] is True
            assert original_state["history"] == [first, second]
            # First new report behavior. Later preview/download checks are unreached in RED.
            editor.preview("tc")
            for locale, title, labels in (
                ("tc", "補發、重複及未用選票核算", (
                    "補發選票數量", "已收回未用選票合計",
                    "從未發出選票合計", "庫存推算票箱選票數量",
                )),
                ("sc", "补发、重复及未用选票核算", (
                    "补发选票数量", "已收回未用选票合计",
                    "从未发出选票合计", "库存推算票箱选票数量",
                )),
                ("en", "Special ballot stock accounting", (
                    "Replacement papers issued", "Retrieved-unused papers total",
                    "Never-issued stock total", "Estimated box papers from stock",
                )),
            ):
                if locale != "tc":
                    editor.preview(locale)
                wait_for(qt_app, lambda: setup_idle(editor))
                preview_state = editor.property("state")
                assert preview_state["error"] == ""
                report = preview_state["report"]
                assert report["items"] == [first]
                assert report["snapshot_id"] == first["id"] and report["revision"] == 1
                assert report["revision_state"] == "historical" and report["locale"] == locale
                assert report.get("availability") is None
                text = preview_state["report_text"]
                assert text.startswith(title)
                for label, quantity in zip(labels, ("2", "3", "7", "2"), strict=True):
                    assert label + " · " + quantity in text
                assert "2026-11-15 09:45:17.123456 HKT" in text
                assert "2026-11-15 09:30:17.123456 HKT" in text
                assert "000011" in text and "000013" in text
                assert "000014" in text and "000015" in text
                assert reason not in text
                for format in ("csv", "pdf"):
                    destination = tmp_path / f"special-r1-{locale}.{format}"
                    editor.download(format, str(destination), locale)
                    wait_for(qt_app, lambda: setup_idle(editor))
                    exported = editor.property("state")
                    assert exported["error"] == "" and exported["export_path"] == str(destination)
                    raw = destination.read_bytes()
                    if format == "csv":
                        assert raw.startswith(b"\xef\xbb\xbf")
                        rows = list(csv.reader(StringIO(raw.decode("utf-8-sig"))))
                        assert rows[0] == [title]
                        for label, quantity in zip(labels, ("2", "3", "7", "2"), strict=True):
                            assert [label, quantity] in rows
                        cells = [cell for row in rows for cell in row]
                        assert "2026-11-15 09:45:17.123456 HKT" in cells
                        assert "2026-11-15 09:30:17.123456 HKT" in cells
                        assert any("000011" in row and "000013" in row for row in rows)
                        assert any("000014" in row and "000015" in row for row in rows)
                        assert reason not in cells
                    else:
                        assert raw.startswith(b"%PDF-")
                        pdf_text = "\n".join(
                            page.extract_text() for page in PdfReader(destination).pages
                        )
                        compact = "".join(pdf_text.split())
                        assert "".join(title.split()) in compact
                        for label, quantity in zip(labels, ("2", "3", "7", "2"), strict=True):
                            assert "".join((label + quantity).split()) in compact
                        for expected in (
                            "000011", "000013", "000014", "000015",
                            "2026-11-15 09:45:17.123456 HKT",
                            "2026-11-15 09:30:17.123456 HKT",
                        ):
                            assert "".join(expected.split()) in compact
                        assert "".join(reason.split()) not in compact
                retained = editor.property("state")
                assert retained["selected"] == first and retained["historical"] is True
                assert retained["history"] == [first, second]
                assert retained["forms"] == original_state["forms"]
                assert retained["dirty"] is False and retained["editing"] is False
            current = officer.get(target)
            assert current.status_code == 200 and current.json() == second
            history = officer.get(target + "/history")
            assert history.status_code == 200 and history.json()["items"] == [first, second]
            snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
            assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
            turnout = officer.get(setup["base"] + "/turnout")
            assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
