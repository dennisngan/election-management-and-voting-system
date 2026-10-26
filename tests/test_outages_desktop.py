"""Outage and paper-record workflows through the public Qt desktop controller."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_support import stock_payload


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_outages_controller_is_exposed_as_a_public_desktop_service(
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "desktop-commands"))
    desktop = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        outages = desktop.property("outages")
        assert isinstance(outages, QObject), "DesktopController.outages must be public to QML."
    finally:
        desktop.shutdown()


def test_polling_officer_records_and_supervisor_reconciles_allocation_paper(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "desktop-commands"))
    stations = box_stations(admin)
    station = stations["N1"]
    clock = BoxClock()
    https_server.clock.value = clock.value
    station_id = station["id"]
    base = f"/api/workspace/stations/{station_id}"
    with (
        box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
            polling,
            polling_account,
        ),
        box_staff(admin, database_url, clock, "supervisor", [station_id]) as (
            _supervisor_api,
            supervisor_account,
        ),
    ):
        options = polling.get(base + "/allocations")
        assert options.status_code == 200, options.text
        counter_id = options.json()["counters"][0]["id"]
        series = "T25-DESKTOP-" + uuid4().hex[:8]
        received = polling.post(
            base + "/stock",
            json=stock_payload(
                series=series,
                event_at="2026-11-15T08:00:00+08:00",
            ),
        )
        assert received.status_code == 201, received.text

        start, end, event_at = (
            "2026-11-15T08:00:00+08:00",
            "2026-11-15T08:30:00+08:00",
            "2026-11-15T08:15:00+08:00",
        )
        desktop = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            desktop.signIn(https_server.url, polling_account["username"], READY_PASSWORD)
            wait_for(qt_app, lambda: desktop.property("state")["phase"] == "workspace")
            workspace = desktop.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            outages = desktop.property("outages")
            assert isinstance(outages, QObject)
            outages.open()
            wait_for_editor_idle(qt_app, outages)
            assert outages.property("state")["station_id"] == station_id
            assert outages.property("state")["writable"] is True

            outages.setField("reference", "T25 desktop network interruption")
            outages.setField("kind", "network")
            outages.setField("started_at", "2026-11-15 08:00")
            outages.setField("ended_at", "2026-11-15 08:30")
            outages.setField("notes", "Paper allocation retained during the outage.")
            outages.save()
            wait_for_editor_idle(qt_app, outages)
            created_outage = outages.property("state")["selected"]
            assert created_outage["reference"] == "T25 desktop network interruption"
            assert created_outage["revision"] == 1
            assert outages.property("state")["dirty"] is False

            # Refresh stays separate from the form: a newer server revision must not
            # replace a locally edited note without an explicit reload.
            outages.setField("notes", "Unsent local outage note.")
            successor = polling.put(
                f"{base}/outages/{created_outage['id']}",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "reference": created_outage["reference"],
                    "kind": created_outage["kind"],
                    "started_at": start,
                    "ended_at": end,
                    "notes": "Server-confirmed outage note.",
                    "amendment_reason": "Matched the supervisor's network log.",
                },
            )
            assert successor.status_code == 200, successor.text
            outages.refresh()
            wait_for_editor_idle(qt_app, outages)
            state = outages.property("state")
            assert state["dirty"] is True
            assert state["newer_revision"] is True
            assert state["forms"]["notes"] == "Unsent local outage note."
            assert outages.loadOutage(created_outage["id"], False) is False
            outages.discardAndReload()
            wait_for_editor_idle(qt_app, outages)
            state = outages.property("state")
            assert state["selected"]["revision"] == 2
            assert state["forms"]["notes"] == "Server-confirmed outage note."

            outages.beginPaper(0)
            outages.setPaperField("paper_reference", "T25-DESKTOP-ALLOC-" + uuid4().hex[:8])
            outages.setPaperField("workflow", "allocation")
            outages.setPaperField("action", "create")
            outages.setPaperField("original_event_at", "2026-11-15 08:15")
            outages.setPaperField("target_counter_id", str(counter_id))
            outages.setPaperField("notes", "Signed allocation sheet from the outage.")
            outages.savePaper()
            wait_for_editor_idle(qt_app, outages)
            state = outages.property("state")
            paper = state["selected"]["paper_records"][0]
            assert paper["status"] == "pending"
            assert paper["original_event_at"] == "2026-11-15T00:15:00Z"

            allocation = polling.post(
                base + "/allocations",
                json={
                    "request_id": str(uuid4()),
                    "counter_id": counter_id,
                    "series": series,
                    "serial_from": "000001",
                    "serial_to": "000002",
                    "event_at": event_at,
                    "paper_record_id": paper["id"],
                },
            )
            assert allocation.status_code == 201, allocation.text
            outages.refresh()
            wait_for_editor_idle(qt_app, outages)
            outages.loadOutage(created_outage["id"], True)
            wait_for_editor_idle(qt_app, outages)
            state = outages.property("state")
            entered = state["selected"]["paper_records"][0]
            assert entered["status"] == "entered"
            assert entered["reentry"]["record"] == allocation.json()
            serialized_state = json.dumps(state, ensure_ascii=False)
            assert READY_PASSWORD not in serialized_state
            assert "password" not in serialized_state.lower()
        finally:
            desktop.shutdown()

        supervisor_desktop = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            supervisor_desktop.signIn(
                https_server.url, supervisor_account["username"], READY_PASSWORD
            )
            wait_for(qt_app, lambda: supervisor_desktop.property("state")["phase"] == "workspace")
            supervisor_workspace = supervisor_desktop.property("workspace")
            wait_for_editor_idle(qt_app, supervisor_workspace)
            supervisor_workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, supervisor_workspace)
            outages = supervisor_desktop.property("outages")
            assert isinstance(outages, QObject)
            outages.open()
            wait_for_editor_idle(qt_app, outages)
            outage_id = created_outage["id"]
            assert outages.loadOutage(outage_id, False) is True
            wait_for_editor_idle(qt_app, outages)
            assert outages.property("state")["selected"]["paper_records"][0]["status"] == "entered"
            outages.approveReconciliation(
                READY_PASSWORD,
                "Supervisor checked the entered paper reference against the signed return.",
            )
            wait_for_editor_idle(qt_app, outages)
            state = outages.property("state")
            assert state["selected"]["reconciled"] is True
            assert state["selected"]["reconciliation"]["valid"] is True
            assert READY_PASSWORD not in json.dumps(state, ensure_ascii=False)
            assert "password" not in json.dumps(state, ensure_ascii=False).lower()
        finally:
            supervisor_desktop.shutdown()
