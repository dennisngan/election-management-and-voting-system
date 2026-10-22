"""Queue statements through public Qt controls, verified HTTPS and real MySQL."""

import csv
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.queue_support import (
    READY_PASSWORD,
    QueueClock,
    active_queue_stations,
    arrange_retained_queue_election,
    observation,
    queue_account,
    queue_client,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def queue_editor(
    server: HttpsServer, qt_app: QCoreApplication, account: dict, station_id: int
) -> Iterator[tuple[DesktopController, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for(qt_app, lambda: setup_idle(workspace))
        workspace.selectStation(station_id)
        wait_for(qt_app, lambda: setup_idle(workspace))
        editor = client.property("queue")
        assert editor is not None
        assert editor.open(station_id, account["role"])
        wait_for(qt_app, lambda: setup_idle(editor))
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


@pytest.fixture
def saved_queue(admin: TestClient, database_url: str, https_server: HttpsServer) -> Iterator[dict]:
    context = active_queue_stations(admin)[0]
    account = queue_account(admin, [context["station"]["id"]])
    clock = QueueClock()
    https_server.clock.value = clock.value
    path = f"/api/workspace/stations/{context['station']['id']}/queue"
    with queue_client(database_url, account, clock) as api:
        created = api.post(
            path, json=observation(clock, band="60_90", reason="現場輪候 <保留> & raw source")
        )
        assert created.status_code == 201
        yield {
            "api": api,
            "path": path,
            "context": context,
            "account": account,
            "clock": clock,
            "event": created.json(),
        }


def test_desktop_previews_server_lines_and_downloads_real_queue_reports_in_three_languages(
    saved_queue: dict, https_server: HttpsServer, qt_app: QCoreApplication, tmp_path: Path
) -> None:
    with queue_editor(
        https_server, qt_app, saved_queue["account"], saved_queue["context"]["station"]["id"]
    ) as (client, editor):
        reviewed = editor.property("state")
        for locale, title in (
            ("tc", "輪候觀察及提醒報表"),
            ("sc", "轮候观察及提醒报表"),
            ("en", "Queue observations and reminders"),
        ):
            client.setLocale(locale)
            editor.preview(locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            state = editor.property("state")
            assert state["error"] == ""
            expected = saved_queue["api"].get(
                saved_queue["path"] + f"/statement?revision=1&locale={locale}"
            )
            assert expected.status_code == 200
            assert state["report"] == expected.json()
            assert state["report_text"] == "\n".join(expected.json()["preview_lines"])
            assert title in state["report_text"]
            assert "現場輪候 <保留> & raw source" in state["report_text"]
            assert state["forms"] == reviewed["forms"] and state["revision"] == 1
            csv_path = tmp_path / f"queue-history-{locale}.csv"
            editor.download("csv", csv_path.as_uri(), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            exported = editor.property("state")
            assert exported["error"] == "" and exported["export_path"] == str(csv_path)
            assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            assert rows[0] == [title]
            assert any("現場輪候 <保留> & raw source" in row for row in rows)
            pdf_path = tmp_path / f"queue-history-{locale}.pdf"
            editor.download("pdf", str(pdf_path), locale)
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            text = " ".join(
                " ".join(page.extract_text().split()) for page in PdfReader(pdf_path).pages
            )
            assert title in text and "現場輪候 <保留> & raw source" in text
            assert "2026-11-15 08:00:00 HKT" in text
            assert editor.property("state")["forms"] == reviewed["forms"]
        client.signOut()
        reset = editor.property("state")
        assert reset["report"] == {} and reset["report_text"] == "" and reset["export_path"] == ""


def test_dirty_form_and_reviewed_revision_survive_preview_download_and_live_newer_history(
    saved_queue: dict, https_server: HttpsServer, qt_app: QCoreApplication, tmp_path: Path
) -> None:
    with queue_editor(
        https_server, qt_app, saved_queue["account"], saved_queue["context"]["station"]["id"]
    ) as (_, editor):
        editor.setField("band", "over_90")
        editor.setField("event_time", "2026-11-15 08:45")
        editor.setField("reason", "UNSAVED_ONLY_SOURCE 尚未儲存")
        form = editor.property("state")["forms"]
        saved_queue["clock"].value += timedelta(minutes=10)
        https_server.clock.value = saved_queue["clock"].value
        newer = saved_queue["api"].post(
            saved_queue["path"],
            json=observation(
                saved_queue["clock"],
                expected_revision=1,
                band="under_30",
                reason="SAVED_NEWER_ONLY",
            ),
        )
        assert newer.status_code == 201
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        before = editor.property("state")
        assert before["revision"] == 1 and before["latest_revision"] == 2
        assert before["newer_revision"] is True and before["dirty"] is True
        editor.preview("en")
        wait_for(qt_app, lambda: setup_idle(editor))
        reviewed = editor.property("state")
        assert reviewed["error"] == ""
        assert reviewed["report"]["revision"] == 1
        assert reviewed["report"]["revision_state"] == "historical"
        assert reviewed["report"]["items"] == [saved_queue["event"]]
        assert reviewed["forms"] == form and reviewed["dirty"] is True
        assert reviewed["newer_revision"] is True
        assert "UNSAVED_ONLY_SOURCE" not in reviewed["report_text"]
        assert "SAVED_NEWER_ONLY" not in reviewed["report_text"]
        destination = tmp_path / "reviewed-prefix.csv"
        editor.download("csv", str(destination), "en")
        wait_for(qt_app, lambda: setup_idle(editor))
        exported = editor.property("state")
        assert exported["error"] == "" and exported["forms"] == form and exported["dirty"] is True
        assert exported["revision"] == 1 and exported["newer_revision"] is True
        source = destination.read_text(encoding="utf-8-sig")
        assert "UNSAVED_ONLY_SOURCE" not in source and "SAVED_NEWER_ONLY" not in source
        assert "Historical revision" in source
        assert editor.reload(True)
        wait_for(qt_app, lambda: setup_idle(editor))
        editor.preview("en")
        wait_for(qt_app, lambda: setup_idle(editor))
        refreshed = editor.property("state")
        assert refreshed["report"]["revision"] == 2 and refreshed["dirty"] is False
        assert "SAVED_NEWER_ONLY" in refreshed["report_text"]


def test_partial_download_and_invalid_destination_preserve_previous_file_and_allow_retry(
    saved_queue: dict, https_server: HttpsServer, qt_app: QCoreApplication, tmp_path: Path
) -> None:
    with queue_editor(
        https_server, qt_app, saved_queue["account"], saved_queue["context"]["station"]["id"]
    ) as (_, editor):
        editor.setField("reason", "保留尚未儲存的輪候觀察")
        before = editor.property("state")
        destination = tmp_path / "reviewed-queue-history.pdf"
        previous = b"Existing reviewed file must survive an incomplete HTTPS response."
        destination.write_bytes(previous)
        https_server.truncate_next_report = True
        editor.download("pdf", destination.as_uri(), "tc")
        wait_for(qt_app, lambda: setup_idle(editor), timeout=12)
        failed = editor.property("state")
        assert failed["error"] == "disconnected" and failed["notice"] != "queue_exported"
        assert failed["export_path"] == "" and destination.read_bytes() == previous
        assert failed["forms"] == before["forms"] and failed["dirty"] is True
        assert failed["revision"] == before["revision"]
        editor.download("pdf", str(destination), "tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        retried = editor.property("state")
        assert retried["error"] == "" and retried["notice"] == "queue_exported"
        assert retried["export_path"] == str(destination)
        assert retried["forms"] == before["forms"] and retried["dirty"] is True
        assert "輪候觀察及提醒報表" in "\n".join(
            page.extract_text() for page in PdfReader(destination).pages
        )
        reviewed_bytes = destination.read_bytes()
        editor.download("csv", str(tmp_path), "en")
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == "queue_export_failed"
        assert destination.read_bytes() == reviewed_bytes
        editor.download("csv", "relative-queue.csv", "en")
        assert editor.property("state")["error"] == "queue_export_failed"
        assert editor.property("state")["forms"] == before["forms"]


@pytest.mark.parametrize("role", ["polling_officer", "supervisor", "counting_officer"])
def test_assigned_roles_preview_and_export_retained_election_history(
    saved_queue: dict,
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    role: str,
) -> None:
    context = saved_queue["context"]
    account = queue_account(admin, [context["station"]["id"]], role=role)
    with queue_client(database_url, account, saved_queue["clock"]):
        arrange_retained_queue_election(database_url, context["election"]["id"])
        with queue_editor(https_server, qt_app, account, context["station"]["id"]) as (_, editor):
            before = editor.property("state")
            assert before["context"]["election"]["status"] == "finalized"
            editor.preview("en")
            wait_for(qt_app, lambda: setup_idle(editor))
            reviewed = editor.property("state")
            assert reviewed["error"] == ""
            assert reviewed["report"]["scope"]["election"]["status"] == "finalized"
            assert "Finalized" in reviewed["report_text"]
            for extension in ("csv", "pdf"):
                destination = tmp_path / f"retained-{role}.{extension}"
                editor.download(extension, str(destination), "en")
                wait_for(qt_app, lambda: setup_idle(editor))
                assert editor.property("state")["error"] == "" and destination.is_file()
            assert editor.property("state")["forms"] == before["forms"]
            assert editor.property("state")["revision"] == 1


def test_unavailable_pdf_glyph_stays_visible_and_csv_preserves_the_source(
    saved_queue: dict, https_server: HttpsServer, qt_app: QCoreApplication, tmp_path: Path
) -> None:
    source = "現場補充🙂"
    saved = saved_queue["api"].post(
        saved_queue["path"],
        json=observation(
            saved_queue["clock"],
            expected_revision=1,
            reason=source,
        ),
    )
    assert saved.status_code == 201
    with queue_editor(
        https_server, qt_app, saved_queue["account"], saved_queue["context"]["station"]["id"]
    ) as (_, editor):
        editor.preview("tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        assert source in editor.property("state")["report_text"]
        pdf_path = tmp_path / "unsupported-source.pdf"
        pdf_path.write_bytes(b"Preserve existing export")
        editor.download("pdf", str(pdf_path), "tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == "report_glyph_unavailable"
        assert pdf_path.read_bytes() == b"Preserve existing export"
        csv_path = tmp_path / "source-values.csv"
        editor.download("csv", str(csv_path), "tc")
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["error"] == ""
        assert source in csv_path.read_text(encoding="utf-8-sig")


def test_an_empty_reviewed_queue_exports_missing_context_without_losing_dirty_input(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    https_server.clock.value = clock.value
    with queue_client(database_url, account, clock):
        with queue_editor(https_server, qt_app, account, station_id) as (_, editor):
            editor.setField("reason", "尚未儲存的第一次觀察")
            form = editor.property("state")["forms"]
            editor.preview("en")
            wait_for(qt_app, lambda: setup_idle(editor))
            state = editor.property("state")
            assert state["error"] == ""
            assert state["report"]["revision"] == 0 and state["report"]["missing"] is True
            assert "this does not mean there is no queue" in state["report_text"]
            assert state["forms"] == form and state["dirty"] is True
            destination = tmp_path / "missing-queue.csv"
            editor.download("csv", str(destination), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert "this does not mean there is no queue" in destination.read_text(
                encoding="utf-8-sig"
            )
            assert editor.property("state")["forms"] == form and editor.property("state")["dirty"]
