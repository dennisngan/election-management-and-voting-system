"""Two public Qt clients prepare and confirm fallback over verified TLS and MySQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QSignalSpy

from election.desktop.controller import DesktopController
from tests.desktop_support import (
    TLS_DIRECTORY,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import READY_PASSWORD


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def fallback_editor(
    server: HttpsServer, app: QCoreApplication, account: dict, station_id: int,
) -> Iterator[tuple[DesktopController, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for_editor_idle(app, workspace)
        workspace.selectStation(station_id)
        wait_for_editor_idle(app, workspace)
        editor = client.property("fallback")
        # First new-feature assertion: the public fallback Qt property is missing in RED.
        assert editor is not None
        assert editor.open() is True
        wait_for_editor_idle(app, editor)
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_polling_desktop_submits_frozen_activation_and_supervisor_confirms_exact_revision(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["snapshot"]["station_id"]
        with fallback_editor(https_server, qt_app, setup["account"], station_id) as (_, editor):
            initial = editor.property("state")
            assert initial["error"] == "" and initial["selected"] == {}
            assert initial["schedule_revision"] == 1
            editor.setField("event_time", "2026-11-15 11:20")
            editor.setField("cumulative_quantity", "110")
            editor.setField("stock_snapshot_id", str(setup["snapshot"]["id"]))
            editor.setField("stock_snapshot_revision", "1")
            editor.setField("source_context", setup["command"]["source_context"])
            entered = editor.property("state")["forms"]
            assert entered["cumulative_quantity"] == "110"
            assert editor.property("state")["dirty"] is True
            assert editor.reload() is False
            assert editor.property("state")["error"] == "unsaved_fallback_changes"
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["forms"] == entered
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            saved_state = editor.property("state")
            assert saved_state["error"] == "" and saved_state["notice"] == "fallback_saved"
            saved = saved_state["selected"]
            assert saved["kind"] == "activation" and saved["status"] == "draft"
            assert saved["revision"] == 1 and saved["cumulative_quantity"] == 110
            assert saved["event_at"] == "2026-11-15T03:20:00Z"
            assert saved["stock_snapshot"] == setup["snapshot"]
            assert saved["stock_snapshot"]["ordinary_issued_quantity"] == 110
            assert saved["stock_snapshot"]["counters"][0]["ordinary_remaining_quantity"] == 90
            assert saved_state["forms"]["cumulative_quantity"] == "110"
            assert saved_state["dirty"] is False
            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")["selected"]
            assert submitted["status"] == "submitted" and submitted["revision"] == 1
            pending = setup["officer"].get(setup["path"])
            assert pending.status_code == 200
            assert pending.json()["mode"] == "normal"
            assert pending.json()["active_activation_id"] is None
            with fallback_editor(
                https_server, qt_app, setup["supervisor_account"], station_id,
            ) as (_, reviewer):
                assert reviewer.selectRecord(saved["id"]) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.loadRevision(1) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.property("state")["selected"]["status"] == "submitted"
                erased = QSignalSpy(reviewer.erasePassword)
                reviewer.approve(READY_PASSWORD)
                wait_for_editor_idle(qt_app, reviewer)
                reviewed = reviewer.property("state")
                assert reviewed["error"] == "" and reviewed["notice"] == "fallback_approved"
                approved = reviewed["selected"]
                assert approved["status"] == "approved" and approved["revision"] == 1
                assert approved["approved_by"] == setup["supervisor_account"]["id"]
                assert approved["stock_snapshot"] == setup["snapshot"]
                assert reviewed["history"] == [approved]
                assert erased.count() >= 1 and READY_PASSWORD not in repr(reviewed)
                active = setup["officer"].get(setup["path"])
                assert active.status_code == 200
                assert active.json()["mode"] == "fallback"
                assert active.json()["active_activation_id"] == saved["id"]
                editor.refresh()
                wait_for_editor_idle(qt_app, editor)
                assert editor.property("state")["current"]["status"] == "approved"
                assert editor.property("state")["selected"] == submitted
                assert editor.property("state")["newer_revision"] is True
                assert editor.reload(True) is True
                wait_for_editor_idle(qt_app, editor)
                assert editor.property("state")["selected"] == approved


def test_polling_desktop_records_recovery_and_supervisor_confirms_116_without_changing_old_115(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        activation, endpoint, old_turnout = (
            prepared["activation"], prepared["endpoint"], prepared["approved"]
        )
        https_server.clock.value = setup["clock"].value
        station_id = endpoint["station_id"]
        with fallback_editor(https_server, qt_app, setup["account"], station_id) as (_, editor):
            # First new-feature call: starting a recovery through public Qt is missing in RED.
            assert editor.newRecord("recovery") is True
            initial = editor.property("state")
            assert initial["selected"] == {} and initial["dirty"] is False
            assert initial["forms"]["kind"] == "recovery"
            assert initial["forms"]["activation_id"] == str(activation["id"])
            assert initial["forms"]["activation_revision"] == "1"
            editor.setField("reason", "Keep this draft until an explicit discard.")
            pending = editor.property("state")["forms"]
            assert editor.newRecord("activation") is False
            assert editor.property("state")["error"] == "unsaved_fallback_changes"
            assert editor.property("state")["forms"] == pending
            assert editor.newRecord("recovery", True) is True
            assert editor.property("state")["forms"]["reason"] == ""
            editor.setField("event_time", "2026-11-15 12:00")
            editor.setField("cumulative_quantity", "116")
            editor.setField("stock_snapshot_id", str(endpoint["id"]))
            editor.setField("stock_snapshot_revision", "1")
            editor.setField("source_context", "Recovered manual register: cumulative 116 at noon.")
            editor.setField("reason", "Replace the fallback estimate 115 with recovered 116.")
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            saved_state = editor.property("state")
            assert saved_state["error"] == "" and saved_state["notice"] == "fallback_saved"
            saved = saved_state["selected"]
            assert saved["kind"] == "recovery" and saved["status"] == "draft"
            assert saved["revision"] == 1 and saved["cumulative_quantity"] == 116
            assert saved["activation_id"] == activation["id"]
            assert saved["activation_revision"] == 1
            assert saved["stock_snapshot"] == endpoint
            assert saved["reconciliation"]["stock_derived_cumulative_quantity"] == 115
            assert saved["reconciliation"]["recovered_cumulative_quantity"] == 116
            assert saved["reconciliation"]["difference"] == 1
            assert saved_state["forms"]["cumulative_quantity"] == "116"
            assert saved_state["forms"]["activation_id"] == str(activation["id"])
            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")["selected"]
            assert submitted["status"] == "submitted" and submitted["revision"] == 1
            pending_mode = setup["officer"].get(setup["path"])
            assert pending_mode.status_code == 200
            assert pending_mode.json()["mode"] == "fallback"
            assert pending_mode.json()["active_activation_id"] == activation["id"]
            with fallback_editor(
                https_server, qt_app, setup["supervisor_account"], station_id,
            ) as (_, reviewer):
                assert reviewer.selectRecord(saved["id"]) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.loadRevision(1) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.property("state")["selected"] == submitted
                reviewer.approve(READY_PASSWORD)
                wait_for_editor_idle(qt_app, reviewer)
                reviewed = reviewer.property("state")
                assert reviewed["error"] == "" and reviewed["notice"] == "fallback_approved"
                approved = reviewed["selected"]
                assert approved["status"] == "approved" and approved["revision"] == 1
                assert approved["reconciliation"]["recovered_cumulative_quantity"] == 116
                normal = setup["officer"].get(setup["path"])
                assert normal.status_code == 200
                assert normal.json()["mode"] == "normal"
                assert normal.json()["active_activation_id"] is None
                turnout = setup["officer"].get(setup["scope"]["path"])
                assert turnout.status_code == 200
                old_period = turnout.json()["items"][1]
                assert old_period["record"] == old_turnout
                assert old_period["approval_valid"] is False
                assert old_period["review_required"] is True
                retained = setup["officer"].get(setup["scope"]["path"] + "/2?revision=1")
                assert retained.status_code == 200 and retained.json() == old_turnout
                editor.refresh()
                wait_for_editor_idle(qt_app, editor)
                assert editor.property("state")["current"] == approved
                assert editor.property("state")["selected"] == submitted
                assert editor.property("state")["newer_revision"] is True
                assert editor.newRecord("recovery") is False
                assert editor.property("state")["error"] == "fallback_source_conflict"
                assert editor.property("state")["selected"] == submitted
                assert editor.newRecord("activation") is True
                fresh = editor.property("state")
                assert fresh["selected"] == {} and fresh["history"] == []
                assert fresh["forms"]["kind"] == "activation"
                assert fresh["forms"]["activation_id"] == ""
                assert fresh["forms"]["reason"] == "" and fresh["dirty"] is False
