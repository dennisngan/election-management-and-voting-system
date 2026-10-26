"""Trace allocation station context and its initial public HTTPS read."""

import json

from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.allocation_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.stock_support import READY_PASSWORD
from tests.test_allocation_api import (
    allocation_payload,
)
from tests.test_allocation_api import (
    allocation_setup as allocation_setup,
)


def test_allocation_initial_read_uses_selected_station_context(
    allocation_setup: dict,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    setup = allocation_setup
    station_id = setup["station"]["id"]
    path = setup["base"] + "/allocations"
    created = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201, created.text
    allocation_id = created.json()["id"]
    public = setup["officer"].get(path)
    assert public.status_code == 200, public.text
    public_counters = public.json()["counters"]
    assert public_counters == [
        {
            "id": setup["counter"]["id"],
            "code": setup["counter"]["code"],
            "name": setup["counter"]["name"],
        }
    ]

    client = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(https_server.url, setup["account"]["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace_state = workspace.property("state")
        editor = client.property("allocations")
        before = editor.property("state")
        editor.open()
        wait_for(qt_app, lambda: setup_idle(editor))
        after = editor.property("state")
        requests = [
            {"method": row["method"], "status": row["status"]}
            for row in https_server.request_timings
            if row.get("path") == path
        ]
        diagnostic = {
            "expected_station_id": station_id,
            "workspace_error": workspace_state["error"],
            "workspace_context_station_ids": [row["station"]["id"] for row in workspace_state["contexts"]],
            "workspace_reads": [{"path": row["path"], "status": row["status"]}
                                for row in https_server.request_timings
                                if row["path"].startswith("/api/workspace/stations")],
            "workspace_station_id": workspace_state.get("selected", {})
            .get("station", {})
            .get("id"),
            "allocation_station_id_before": before["station_id"],
            "allocation_station_id_after": after["station_id"],
            "allocation_role": after["role"],
            "allocation_error": after["error"],
            "expected_counter_ids": [row["id"] for row in public_counters],
            "allocation_counter_ids": [row["id"] for row in after["counters"]],
            "expected_allocation_ids": [allocation_id],
            "allocation_ids": [row["id"] for row in after["items"]],
            "initial_allocation_gets": requests,
        }
        print("ALLOCATION_PUBLIC_READ_DIAGNOSTIC=" + json.dumps(diagnostic, sort_keys=True))
        assert diagnostic["workspace_station_id"] == station_id, diagnostic
        assert diagnostic["allocation_station_id_after"] == station_id, diagnostic
        assert after["counters"] == public_counters, diagnostic
        assert [row["id"] for row in after["items"]] == [
            row["id"] for row in public.json()["items"]
        ], diagnostic
        assert [row["quantity"] for row in after["items"]] == [
            row["quantity"] for row in public.json()["items"]
        ], diagnostic
        loaded = editor.loadAllocation(allocation_id, False)
        assert loaded is True, diagnostic
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["id"] == allocation_id
        detail_path = path + f"/{allocation_id}"
        detail_gets = [
            {"method": row["method"], "status": row["status"]}
            for row in https_server.request_timings
            if row.get("path") == detail_path
        ]
        assert detail_gets == [{"method": "GET", "status": 200}]
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
