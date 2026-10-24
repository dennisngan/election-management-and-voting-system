"""P(18) journeys use the public Qt controller against real HTTPS and MySQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.special_paper_support import special_paper_setup
from tests.turnout_support import READY_PASSWORD, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def accounting_editor(
    server: HttpsServer,
    qt_app: QCoreApplication,
    account: dict,
    station_id: int,
) -> Iterator[tuple[DesktopController, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: setup_idle(workspace))
        editor = client.property("accounting")
        assert editor is not None, "The public workspace must expose P(18) accounting"
        editor.open()
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_counter_saves_conserved_source_accounting_and_resumes_without_observed_count(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            with accounting_editor(https_server, qt_app, account, station_id) as (_, editor):
                assert editor.property("state")["selected"] == {}
                editor.selectSpecial(special.json()["id"], 1)
                editor.selectTurnout(1, 1)
                editor.setField("notes", "核對十五張收到選票，尚未觀察點票數量。")
                editor.save()
                wait_for(qt_app, lambda: setup_idle(editor))
                saved = editor.property("state")
                assert saved["error"] == ""
                assert saved["selected"]["revision"] == 1
                assert saved["selected"]["summary"]["received_quantity"] == 15
                assert saved["selected"]["summary"]["never_issued_quantity"] == 7
                assert saved["selected"]["summary"]["estimated_box_from_stock_quantity"] == 2
                assert saved["selected"]["summary"]["observed_counted_quantity"] is None
                assert saved["summary"]["observed_counted_quantity_display"] == "—"
                assert saved["summary"]["estimated_box_from_turnout_quantity_display"] == "—"
                assert saved["dirty"] is False
                editor.setField("notes", "未儲存的核對文字")
                editor.refresh()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["forms"]["notes"] == "未儲存的核對文字"
                assert editor.reload() is False
                assert editor.property("state")["error"] == "unsaved_accounting_changes"
                assert editor.reload(True) is True
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["forms"]["notes"].startswith("核對十五張")
                editor.submit()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["selected"]["status"] == "submitted"
            current = counter.get(setup["base"] + "/accounting")
            assert current.status_code == 200
            assert current.json()["record"]["status"] == "submitted"
            with accounting_editor(https_server, qt_app, account, station_id) as (_, editor):
                assert editor.property("state")["selected"]["notes"].startswith("核對十五張")
                editor.preview("tc")
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["report"]["revision"] == 1
                assert editor.property("state")["report_text"]


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_counter_downloads_the_reviewed_revision_through_authenticated_exports(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    locale: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            path = setup["base"] + "/accounting"
            saved = counter.put(
                path,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "special_paper_id": special.json()["id"],
                    "special_paper_revision": 1,
                    "notes": "保留的帳目備註 Unicode source notes",
                },
            )
            assert saved.status_code == 200
            with accounting_editor(https_server, qt_app, account, station_id) as (_, editor):
                editor.setField("notes", "Unsaved notes must not replace a saved report")
                editor.preview(locale)
                wait_for(qt_app, lambda: setup_idle(editor))
                state = editor.property("state")
                assert state["report"]["revision"] == 1
                assert "保留的帳目備註" in state["report_text"]
                assert "Unsaved notes" not in state["report_text"]
                assert state["forms"]["notes"].startswith("Unsaved notes")
                for format in ("csv", "pdf"):
                    destination = tmp_path / f"帳目-{locale}.{format}"
                    editor.download(format, destination.as_uri(), locale)
                    wait_for(qt_app, lambda: setup_idle(editor))
                    exported = editor.property("state")
                    assert exported["error"] == ""
                    assert exported["notice"] == "accounting_exported"
                    assert exported["export_path"] == str(destination)
                    content = destination.read_bytes()
                    assert (
                        content.startswith(b"%PDF")
                        if format == "pdf"
                        else ("保留的帳目備註" in content.decode("utf-8-sig"))
                    )


def test_stale_peer_revision_preserves_unsaved_input_until_explicit_reload(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            content = {"special_paper_id": special.json()["id"], "special_paper_revision": 1}
            path = setup["base"] + "/accounting"
            saved = counter.put(
                path,
                json={
                    **content,
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                },
            )
            assert saved.status_code == 200
            with accounting_editor(https_server, qt_app, account, station_id) as (_, editor):
                editor.setField("notes", "My unsubmitted reconciliation notes")
                peer = counter.put(
                    path,
                    json={
                        **content,
                        "request_id": str(uuid4()),
                        "expected_revision": 1,
                        "notes": "Peer's saved source-station notes",
                    },
                )
                assert peer.status_code == 200
                editor.refresh()
                wait_for(qt_app, lambda: setup_idle(editor))
                state = editor.property("state")
                assert state["newer_revision"] is True
                assert state["current"]["revision"] == 2
                assert state["selected"]["revision"] == 1
                assert state["forms"]["notes"] == "My unsubmitted reconciliation notes"
                editor.save()
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == "revision_conflict"
                assert editor.property("state")["forms"]["notes"].startswith("My unsubmitted")
                assert editor.reload(True)
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["selected"]["revision"] == 2
                assert (
                    editor.property("state")["forms"]["notes"]
                    == "Peer's saved source-station notes"
                )


def test_polling_officer_can_read_but_cannot_prepare_source_accounting(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = setup["snapshot"]["station_id"]
        https_server.clock.value = setup["clock"].value
        with accounting_editor(https_server, qt_app, setup["account"], station_id) as (_, editor):
            editor.setField("notes", "An unauthorized attempted edit")
            assert editor.property("state")["forms"]["notes"] == ""
            assert editor.selectSpecial(special.json()["id"], 1) is False
            editor.save()
            assert editor.property("state")["error"] == "counting_officer_required"
            assert editor.property("state")["dirty"] is False
            current = setup["officer"].get(setup["base"] + "/accounting")
            assert current.status_code == 200
            assert current.json()["record"] is None
