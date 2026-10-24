"""Role, explicit-count and dirty-selection boundaries through public Qt over TLS."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.desktop_support import (
    TLS_DIRECTORY,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_staff


@contextmanager
def open_editor(
    server: HttpsServer, app: QCoreApplication, account: dict, station_id: int,
) -> Iterator[tuple[DesktopController, Any, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for_editor_idle(app, workspace)
        workspace.selectStation(station_id)
        wait_for_editor_idle(app, workspace)
        editor = client.property("specialPapers")
        assert editor is not None
        editor.open()
        wait_for_editor_idle(app, editor)
        assert editor.property("state")["error"] == ""
        yield client, workspace, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def original_records(setup: dict, saved: dict) -> dict:
    target = setup["path"] + f"/{saved['id']}"
    snapshot = setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}"
    records = {}
    for path in (target, target + "/history", snapshot, snapshot + "/history",
                 setup["base"] + "/turnout"):
        response = setup["officer"].get(path)
        assert response.status_code == 200, path
        records[path] = response.json()
    return records


def draft(editor: Any) -> dict:
    state = editor.property("state")
    return {key: state[key] for key in ("forms", "basis", "series_reports", "selected", "dirty")}


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_readers_review_history_and_preview_but_cannot_mutate_special_counts(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication, role: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        created = setup["officer"].post(setup["path"], json=setup["command"])
        assert created.status_code == 201
        saved = created.json()
        before = original_records(setup, saved)
        with turnout_staff(
            admin, database_url, setup["clock"], [saved["station_id"]], role,
        ) as (_, account), open_editor(
            https_server, qt_app, account, saved["station_id"],
        ) as (_, _, editor):
            assert editor.loadSnapshot(saved["id"]) is True
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["selected"] == saved and state["history"] == [saved]
            assert state["history_verified"] is True
            editor.preview("en")
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["report"]["items"] == [saved]
            assert "Special ballot stock accounting" in editor.property("state")["report_text"]
            before_draft = draft(editor)
            assert editor.editSelected() is False
            editor.setField("event_time", "2026-11-15 10:45")
            editor.setField("reason", "A reader must not change this record.")
            editor.selectBasis(setup["snapshot"]["id"])
            for key in setup["entered_series"]:
                if key != "series":
                    editor.setSeriesField("普通系列 A", key, "99")
            editor.zeroAll()
            editor.save()
            assert draft(editor) == before_draft
            assert editor.property("state")["error"] == "election_read_only"
            assert https_server.request_count("POST", setup["path"]) == 0
            assert https_server.request_count("PUT", setup["path"] + f"/{saved['id']}") == 0
            assert original_records(setup, saved) == before


def test_officer_requires_explicit_counts_reason_and_discard_before_changing_context(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["snapshot"]["station_id"]
        with open_editor(
            https_server, qt_app, setup["account"], station_id,
        ) as (_, workspace, editor):
            editor.setField("event_time", "2026-11-15 09:45:17.123456")
            editor.selectBasis(setup["snapshot"]["id"])
            initial = editor.property("state")
            assert initial["series_reports"][0]["replacement_issued_quantity"] == ""
            posts = https_server.request_count("POST", setup["path"])
            editor.save()
            assert editor.property("state")["error"] == "special_paper_validation"
            assert https_server.request_count("POST", setup["path"]) == posts
            for invalid in ("two", "-1", "1.5"):
                editor.zeroAll()
                editor.setSeriesField("普通系列 A", "replacement_issued_quantity", invalid)
                editor.save()
                state = editor.property("state")
                assert state["error"] == "special_paper_validation"
                assert state["series_reports"][0]["replacement_issued_quantity"] == invalid
                assert https_server.request_count("POST", setup["path"]) == posts
            editor.zeroAll()
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["error"] == "" and state["notice"] == "special_paper_saved"
            saved = state["selected"]
            assert saved["never_issued_quantity"] == 10
            assert saved["estimated_box_papers_quantity"] == 5
            assert all(saved[key] == 0 for key in setup["entered_series"] if key != "series")
            assert https_server.request_count("POST", setup["path"]) == posts + 1
            before = original_records(setup, saved)
            target = setup["path"] + f"/{saved['id']}"
            puts = https_server.request_count("PUT", target)
            assert editor.editSelected() is True
            editor.setSeriesField("普通系列 A", "retrieved_found_quantity", "1")
            editor.save()
            assert editor.property("state")["error"] == "special_paper_validation"
            assert https_server.request_count("PUT", target) == puts
            editor.setField("reason", "Keep this unsaved count and reason until explicit discard.")
            pending = draft(editor)
            for select in (
                editor.newSnapshot, lambda: editor.loadRevision(1),
                lambda: editor.loadSnapshot(saved["id"]),
            ):
                assert select() is False
                assert editor.property("state")["error"] == "unsaved_special_paper_changes"
                assert draft(editor) == pending
            options = admin.get("/api/accounts/station-options")
            assert options.status_code == 200
            other_id = next(
                row["station"]["id"] for row in options.json()["items"]
                if row["election"]["id"] == saved["scope"]["election"]["id"]
                and row["station"]["id"] != station_id
            )
            workspace.selectStation(other_id)
            assert workspace.property("state")["error"] == "unsaved_station_changes"
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert draft(editor) == pending
            workspace.selectStation(other_id, True)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["error"] == "station_access_denied"
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert draft(editor) == pending
            assert editor.loadRevision(1, True) is True
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["selected"] == saved and state["dirty"] is False
            assert state["forms"]["reason"] == ""
            assert editor.editSelected() is True
            editor.setField("reason", "Explicitly discard this new draft.")
            assert editor.newSnapshot(True) is True
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["selected"] == {} and state["dirty"] is False
            assert state["forms"] == {"event_time": "", "reason": ""}
            assert https_server.request_count("POST", setup["path"]) == posts + 1
            assert https_server.request_count("PUT", target) == puts
            assert original_records(setup, saved) == before
