"""Never-issued counter stock returns use public Qt/TLS controls and real MySQL."""

from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_officer_returns_unissued_counter_stock_without_rewriting_an_earlier_snapshot(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/stock-returns"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, counters = arrange_counter_stock(api, base)
        observed = api.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:00+08:00",
                "counters": [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000004",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ],
            },
        )
        assert observed.status_code == 201
        snapshot = observed.json()
        assert snapshot["ordinary_allocated_quantity"] == 6
        assert snapshot["ordinary_remaining_quantity"] == 3
        assert snapshot["ordinary_issued_quantity"] == 3
        client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(https_server.url, account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            workspace = client.property("workspace")
            wait_for(qt_app, lambda: setup_idle(workspace))
            workspace.selectStation(station_id)
            wait_for(qt_app, lambda: setup_idle(workspace))
            editor = client.property("counterReturns")
            assert editor is not None
            assert https_server.request_count("GET", path) == 0
            editor.open()
            wait_for(qt_app, lambda: setup_idle(editor))
            initial = editor.property("state")
            assert initial["error"] == "" and initial["items"] == [] and initial["selected"] == {}
            assert initial["counters"] == counters and initial["role"] == "polling_officer"
            editor.setField("counter_id", str(counter["id"]))
            editor.setField("series", "普通系列 A")
            editor.setField("serial_from", "000006")
            editor.setField("serial_to", "000006")
            editor.setField("event_time", "2026-11-15 10:00")
            assert editor.property("state")["dirty"] is True
            assert editor.property("state")["quantity_display"] == "1"
            editor.save()
            wait_for(qt_app, lambda: setup_idle(editor))
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "counter_return_saved"
            assert saved["dirty"] is False and saved["quantity_display"] == "1"
            selected = saved["selected"]
            assert selected["revision"] == 1 and selected["kind"] == "unissued_counter_to_pro"
            assert selected["quantity"] == 1 and selected["counter"] == counter
            assert selected["serial_from"] == selected["serial_to"] == "000006"
            assert selected["series"] == "普通系列 A" and selected["actor_id"] == account["id"]
            assert selected["event_at"] == "2026-11-15T02:00:00Z"
            assert selected["entered_at"] == "2026-11-15T04:00:00Z"
            reopened = api.get(path + f"/{selected['id']}")
            assert reopened.status_code == 200 and reopened.json() == selected
            collection = api.get(path)
            assert collection.status_code == 200 and collection.json()["items"] == [selected]
            p14 = api.get(base + "/allocations/statement?locale=en")
            assert p14.status_code == 200
            assert p14.json()["availability"][0]["allocated_quantity"] == 5
            assert p14.json()["availability"][0]["available_quantity"] == 3
            original = api.get(base + f"/stock-snapshots/{snapshot['id']}")
            assert original.status_code == 200 and original.json() == snapshot
            current = api.get(base + "/stock-snapshots")
            assert current.status_code == 200 and current.json()["latest"] == snapshot
            assert current.json()["latest_basis_current"] is True
            assert current.json()["current_ordinary_issued_quantity"] == 3
            normal = api.get(scope["path"])
            assert normal.status_code == 200
            assert normal.json()["items"] and all(
                row["record"] is None for row in normal.json()["items"]
            )
            editor.setField("serial_to", "000005")
            assert editor.property("state")["forms"]["serial_to"] == "000006"
            client.signOut()
            assert editor.property("state")["station_id"] == 0
            assert editor.property("state")["selected"] == {}
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
