"""Source refresh preserves an unsaved public-Qt special-paper observation."""

from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.special_paper_support import special_paper_setup
from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.test_special_papers_boundaries_desktop import open_editor


def test_refresh_preserves_dirty_series_until_the_officer_explicitly_discards_the_draft(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, base = setup["officer"], setup["base"]
        https_server.clock.value = setup["clock"].value
        reserve_command = stock_payload(
            series="Draft reserve A", event_at="2026-11-15T09:15:11.223344+08:00",
            ordinary_quantity=0, replacement_quantity=3, tendered_quantity=0,
            ranges=[{
                "pool": "replacement", "serial_from": "000011", "serial_to": "000013",
            }],
        )
        received = officer.post(base + "/stock", json=reserve_command)
        assert received.status_code == 201
        reserve = received.json()
        source = officer.get(base + "/stock-snapshots")
        assert source.status_code == 200
        assert source.json()["latest_basis_current"] is True
        assert source.json()["latest"] == setup["snapshot"]
        empty = officer.get(setup["path"])
        assert empty.status_code == 200 and empty.json()["items"] == []
        with open_editor(
            https_server, qt_app, setup["account"], setup["snapshot"]["station_id"],
        ) as (_, _, editor):
            editor.setField("event_time", "2026-11-15 09:45:17.123456")
            editor.selectBasis(setup["snapshot"]["id"])
            editor.zeroAll()
            editor.setSeriesField("Draft reserve A", "replacement_issued_quantity", "2")
            editor.setSeriesField("Draft reserve A", "spoilt_original_quantity", "2")
            before = editor.property("state")
            assert before["selected"] == {} and before["dirty"] is True
            assert before["basis"] == setup["snapshot"]
            assert {row["series"] for row in before["series_reports"]} == {
                "Draft reserve A", "普通系列 A",
            }
            reserve_draft = next(
                row for row in before["series_reports"] if row["series"] == "Draft reserve A"
            )
            assert reserve_draft["replacement_issued_quantity"] == "2"
            assert reserve_draft["spoilt_original_quantity"] == "2"
            main_draft = next(
                row for row in before["series_reports"] if row["series"] == "普通系列 A"
            )
            assert all(value == "0" for key, value in main_draft.items() if key != "series")
            amended = officer.put(base + f"/stock/{reserve['id']}", json={
                **reserve_command, "request_id": str(uuid4()), "revision": reserve["revision"],
                "reason": "Correct the unallocated reserve series without changing time or stock.",
                "series": "Draft reserve B",
            })
            assert amended.status_code == 200
            assert amended.json()["revision"] == 2
            assert amended.json()["series"] == "Draft reserve B"
            assert amended.json()["ranges"] == reserve["ranges"]
            assert amended.json()["event_at"] == reserve["event_at"]
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            refreshed = editor.property("state")
            # First new preservation assertion; later discard checks are unreached in RED.
            assert refreshed["series_reports"] == before["series_reports"]
            assert refreshed["source_changed"] is True
            assert refreshed["forms"] == before["forms"]
            assert refreshed["basis"] == before["basis"]
            assert refreshed["dirty"] is True and refreshed["selected"] == {}
            assert refreshed["error"] == ""
            assert editor.newSnapshot(True) is True
            wait_for_editor_idle(qt_app, editor)
            discarded = editor.property("state")
            assert discarded["dirty"] is False and discarded["selected"] == {}
            assert discarded["source_changed"] is False
            assert discarded["forms"] == {"event_time": "", "reason": ""}
            assert discarded["basis"] == {}
            editor.setField("event_time", "2026-11-15 09:45:17.123456")
            editor.selectBasis(setup["snapshot"]["id"])
            replacement = editor.property("state")
            assert {row["series"] for row in replacement["series_reports"]} == {
                "Draft reserve B", "普通系列 A",
            }
            fresh_reserve = next(
                row for row in replacement["series_reports"] if row["series"] == "Draft reserve B"
            )
            assert all(value == "" for key, value in fresh_reserve.items() if key != "series")
            saved = officer.get(setup["path"])
            assert saved.status_code == 200 and saved.json()["items"] == []
            source_after = officer.get(base + f"/stock-snapshots/{setup['snapshot']['id']}")
            assert source_after.status_code == 200 and source_after.json() == setup["snapshot"]
            turnout = officer.get(base + "/turnout")
            assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
