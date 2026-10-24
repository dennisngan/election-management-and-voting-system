"""Staff directory refresh progresses concurrently through real TLS/MySQL reads."""

import json
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_support import create_constituency, create_election
from tests.desktop_support import (
    PERSONAL_PASSWORD,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.test_staff_desktop import create_officer
from tests.test_staff_desktop import ready_staff as ready_staff


def new_directory_station(admin: TestClient) -> dict:
    election = create_election(admin)
    constituency = create_constituency(admin, election["id"])
    response = admin.post(
        f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations",
        json={"name": "Concurrent staff directory marker", "code": "PARALLEL",
              "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


def test_staff_refresh_reads_catalogs_and_selected_audit_while_another_response_is_held(
    admin: TestClient, qt_app: QCoreApplication, https_server: HttpsServer, ready_staff: Any,
) -> None:
    staff = ready_staff
    created, _ = create_officer(staff, qt_app)
    wait_for_editor_idle(qt_app, staff)
    staff.setField("display_name", "Local staff draft retained during directory refresh")
    before = staff.state
    station_id = new_directory_station(admin)["id"]
    updated = admin.put(f"/api/accounts/{created['id']}", json={
        "display_name": "Peer saved staff directory marker", "role": "polling_officer",
        "enabled": True, "station_ids": [station_id], "revision": 1,
    })
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    paths = ("/api/accounts", "/api/accounts/station-options",
             f"/api/accounts/{created['id']}/audit")
    with https_server.lock:
        timing_start = len(https_server.request_timings)
    https_server.hold_staff_response_path = paths[0]
    states: list[bool] = []

    def observe() -> None:
        states.append(staff.state["refreshing"])

    def completed_headers() -> set[str]:
        with https_server.lock:
            return {str(row["path"]) for row in https_server.request_timings[timing_start:]
                    if row["method"] == "GET" and row["status"] == 200}

    staff.stateChanged.connect(observe)
    try:
        staff.refresh()
        assert staff.state["refreshing"] is True and staff.state["busy"] is False
        wait_for(qt_app, https_server.staff_response_entered.is_set)
        # First new behavior: both other real reads must progress before the held
        # account response is released. The serial implementation times out here.
        wait_for(qt_app, lambda: set(paths[1:]) <= completed_headers())
        pending = staff.state
        assert pending["refreshing"] is True and pending["busy"] is False
        assert pending["accounts"] == before["accounts"]
        assert pending["station_options"] == before["station_options"]
        assert pending["audit"] == before["audit"]
        assert pending["selected"] == created and pending["form"] == before["form"]
        assert states == [True]
        staff.setField("display_name", "Still editing while parallel reads are pending")
        form = staff.state["form"]
        request_counts = {path: https_server.request_count("GET", path) for path in paths}
        staff.refresh()
        qt_app.processEvents()
        assert {path: https_server.request_count("GET", path) for path in paths} == request_counts
        assert staff.state["refreshing"] is True and all(states)
        https_server.release_staff_response.set()
        wait_for_editor_idle(qt_app, staff)
        finished = staff.state
        assert states.index(False) == 2
        assert finished["error"] == "" and finished["dirty"] is True
        assert finished["form"] == form and finished["selected"] == created
        assert updated.json() in finished["accounts"]
        assert any(row["station"]["id"] == station_id for row in finished["station_options"])
        assert [row["action"] for row in finished["audit"]] == ["staff_created", "staff_updated"]
    finally:
        https_server.release_staff_response.set()
        staff.stateChanged.disconnect(observe)
        print("Staff parallel refresh proof:", json.dumps({
            "completed_header_paths": sorted(completed_headers()), "refreshing_states": states,
            "held_response_released": https_server.release_staff_response.is_set(),
        }))


def test_selected_audit_keeps_refresh_pending_and_late_reply_cannot_restore_signed_out_state(
    desktop: DesktopController, qt_app: QCoreApplication, account: dict[str, str],
    https_server: HttpsServer, ready_staff: Any,
) -> None:
    staff = ready_staff
    created, _ = create_officer(staff, qt_app)
    wait_for_editor_idle(qt_app, staff)
    audit_path = f"/api/accounts/{created['id']}/audit"
    with https_server.lock:
        start = len(https_server.request_timings)
    https_server.hold_staff_response_path = audit_path
    try:
        staff.refresh()
        wait_for(qt_app, https_server.staff_response_entered.is_set)

        def directories_finished() -> bool:
            with https_server.lock:
                paths = {row["path"] for row in https_server.request_timings[start:]
                         if row["status"] == 200}
            return {"/api/accounts", "/api/accounts/station-options"} <= paths

        wait_for(qt_app, directories_finished)
        assert staff.state["refreshing"] is True and staff.state["busy"] is False
        desktop.signOut()
        signed_out = staff.state
        assert state_of(desktop)["phase"] == "signed_out"
        assert signed_out["accounts"] == [] and signed_out["station_options"] == []
        assert signed_out["audit"] == [] and signed_out["refreshing"] is False
        https_server.release_staff_response.set()
        wait_for(qt_app, https_server.staff_response_finished.is_set)
        desktop.signIn(https_server.url, account["username"], PERSONAL_PASSWORD)
        wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
        assert staff.state == signed_out
    finally:
        https_server.release_staff_response.set()


def test_failed_directory_retains_its_old_data_while_successful_reads_publish_after_settlement(
    admin: TestClient, qt_app: QCoreApplication, https_server: HttpsServer, ready_staff: Any,
) -> None:
    staff = ready_staff
    create_officer(staff, qt_app)
    wait_for_editor_idle(qt_app, staff)
    before = staff.state
    station_id = new_directory_station(admin)["id"]
    https_server.fail_staff_response_path = "/api/accounts"
    https_server.hold_staff_response_path = "/api/accounts/station-options"
    try:
        staff.refresh()
        wait_for(qt_app, https_server.staff_response_entered.is_set)
        wait_for(qt_app, https_server.staff_response_failed.is_set)
        assert staff.state["refreshing"] is True
        assert staff.state["accounts"] == before["accounts"]
        assert staff.state["station_options"] == before["station_options"]
        https_server.release_staff_response.set()
        wait_for_editor_idle(qt_app, staff)
        finished = staff.state
        assert finished["error"] == "request_failed" and finished["notice"] == ""
        assert finished["accounts"] == before["accounts"]
        assert any(row["station"]["id"] == station_id for row in finished["station_options"])
        assert finished["selected"] == before["selected"] and finished["form"] == before["form"]
    finally:
        https_server.release_staff_response.set()
