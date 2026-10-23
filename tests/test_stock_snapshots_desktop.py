"""Remaining-stock forms use public Qt controls over verified TLS and real MySQL."""

from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.stock_support import stock_payload
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_officer_saves_remaining_stock_and_another_client_reads_the_same_snapshot(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        receipt = api.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = api.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocation = api.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("stockSnapshots")
            assert editor is not None
            assert https_server.request_count("GET", base + "/stock-snapshots") == 0
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            initial = editor.property("state")
            assert initial["error"] == ""
            assert initial["snapshot_state"] == "missing" and initial["items"] == []
            assert initial["selected"] == {} and initial["current_ordinary_issued_quantity"] is None
            assert initial["role"] == "polling_officer"
            assert initial["counters"] == options.json()["counters"]
            assert initial["counter_reports"][0]["reported"] is False
            editor.setField("event_time", "2026-11-15 09:30")
            editor.setCounterReported(counter["id"], True)
            editor.addRange(counter["id"])
            editor.setRangeField(counter["id"], 0, "series", "普通系列 A")
            editor.setRangeField(counter["id"], 0, "serial_from", "000004")
            editor.setRangeField(counter["id"], 0, "serial_to", "000006")
            form = editor.property("state")
            assert form["dirty"] is True
            assert form["counter_reports"][0]["ranges"][0]["quantity_display"] == "3"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == ""
            assert saved["notice"] == "stock_snapshot_saved" and saved["dirty"] is False
            selected = saved["selected"]
            assert selected["revision"] == 1 and selected["provenance"] == "stock_derived"
            assert selected["ordinary_allocated_quantity"] == 6
            assert selected["ordinary_remaining_quantity"] == 3
            assert selected["ordinary_issued_quantity"] == 3
            assert saved["totals"]["ordinary_allocated_display"] == "6"
            assert saved["totals"]["ordinary_remaining_display"] == "3"
            assert saved["totals"]["ordinary_issued_display"] == "3"
            assert saved["latest_basis_current"] is True
            assert saved["current_ordinary_issued_display"] == "3"
            assert selected["event_at"] == "2026-11-15T01:30:00Z"
            reopened = api.get(base + f"/stock-snapshots/{selected['id']}")
            assert reopened.status_code == 200 and reopened.json() == selected
            collection = api.get(base + "/stock-snapshots")
            assert collection.status_code == 200 and collection.json()["latest"] == selected
            normal_turnout = api.get(scope["path"])
            assert normal_turnout.status_code == 200
            periods = normal_turnout.json()["items"]
            assert periods and all(row["record"] is None for row in periods)
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["selected"] == {}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
