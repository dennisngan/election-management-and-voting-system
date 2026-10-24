"""Special-paper observations through public Qt controls over TLS and real MySQL."""

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD


def test_officer_records_categories_and_exhausts_reserves_without_changing_turnout(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["snapshot"]["station_id"]
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, setup["account"]["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("specialPapers")
            assert editor is not None
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            initial = editor.property("state")
            assert initial["error"] == "" and initial["items"] == []
            assert initial["latest"] is None and initial["latest_basis_current"] is None
            assert initial["selected"] == {} and initial["basis"] == {}
            assert initial["totals"]["never_issued_display"] == "—"
            editor.setField("event_time", "2026-11-15 09:45:17.123456")
            editor.selectBasis(setup["snapshot"]["id"])
            assert editor.property("state")["basis"] == setup["snapshot"]
            assert editor.property("state")["series_reports"][0]["series"] == "普通系列 A"
            for key, value in setup["entered_series"].items():
                if key != "series":
                    editor.setSeriesField("普通系列 A", key, str(value))
            assert editor.property("state")["dirty"] is True
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "special_paper_saved"
            assert saved["dirty"] is False and saved["history_verified"] is True
            selected = saved["selected"]
            assert selected["revision"] == 1
            assert selected["event_at"] == "2026-11-15T01:45:17.123456Z"
            assert selected["stock_snapshot_id"] == setup["snapshot"]["id"]
            assert selected["stock_snapshot_revision"] == 1
            assert (
                selected["replacement_issued_quantity"],
                selected["spoilt_original_quantity"],
                selected["tendered_issued_quantity"],
            ) == (2, 2, 1)
            assert (
                selected["retrieved_refused_quantity"],
                selected["retrieved_found_quantity"],
                selected["retrieved_held_quantity"],
                selected["retrieved_unused_quantity"],
            ) == (1, 1, 1, 3)
            assert (
                selected["never_issued_quantity"],
                selected["estimated_box_papers_quantity"],
            ) == (7, 2)
            assert saved["totals"]["never_issued_display"] == "7"
            target = setup["path"] + f"/{selected['id']}"
            observed = setup["officer"].get(target)
            assert observed.status_code == 200 and observed.json() == selected
            assert editor.editSelected() is True
            editor.setField("reason", "核對儲備：已全部發出。\n保留原始觀察時間。")
            for key, value in {
                "replacement_issued_quantity": "3",
                "spoilt_original_quantity": "3",
                "tendered_issued_quantity": "2",
                "retrieved_found_quantity": "0",
                "retrieved_held_quantity": "0",
            }.items():
                editor.setSeriesField("普通系列 A", key, value)
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            corrected = editor.property("state")
            assert corrected["error"] == "" and corrected["dirty"] is False
            current = corrected["selected"]
            assert current["revision"] == 2
            assert current["event_at"] == selected["event_at"]
            assert (
                current["replacement_unissued_quantity"],
                current["tendered_unissued_quantity"],
                current["never_issued_quantity"],
                current["estimated_box_papers_quantity"],
            ) == (0, 0, 5, 4)
            assert len(corrected["history"]) == 2
            turnout = setup["officer"].get(setup["base"] + "/turnout")
            assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
            snapshot = setup["officer"].get(
                setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}"
            )
            assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
            assert editor.loadRevision(1) is True
            wait_for(qt_app, lambda: setup_idle(editor))
            old = editor.property("state")
            assert old["selected"] == selected and old["historical"] is True
            assert old["totals"]["never_issued_display"] == "7"
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["selected"] == {}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
