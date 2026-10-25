"""F1 background/foreground behavior at public Qt/HTTPS/MySQL seams."""

import asyncio
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD, event_command
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@contextmanager
def f1_editor(
    server: HttpsServer, qt_app: QCoreApplication, account: dict, station_id: int, scope_id: int
) -> Iterator[tuple[DesktopController, Any]]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        client.signIn(server.url, account["username"], READY_PASSWORD)
        wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
        workspace = client.property("workspace")
        wait_for_editor_idle(qt_app, workspace)
        workspace.selectStation(station_id)
        wait_for_editor_idle(qt_app, workspace)
        editor = client.property("countingRounds")
        editor.open()
        wait_for_editor_idle(qt_app, editor)
        assert editor.selectScope(scope_id)
        wait_for_editor_idle(qt_app, editor)
        yield client, editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def test_f1_dirty_form_stays_anchored_and_historical_preview_survives_source_refresh(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        command = complete_f1_command(options, notes="Original frozen wording")
        created = counter.post(path, json=command)
        assert created.status_code == 201
        target = path + f"/{created.json()['id']}"
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.setField("notes", "Unsaved local tally notes")
            peer = counter.put(
                target,
                json={
                    **command,
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "notes": "Peer saved revision two",
                },
            )
            assert peer.status_code == 200
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["selected"]["revision"] == 1
            assert state["rounds"][0]["revision"] == 2
            assert state["forms"]["notes"] == "Unsaved local tally notes"
            assert state["newer_revision"] is True
            requests = https_server.request_count("PUT", target)
            editor.save()
            assert editor.property("state")["error"] == "revision_conflict"
            assert https_server.request_count("PUT", target) == requests
            assert editor.loadRevision(1) is False
            editor.discardAndReload()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["selected"]["revision"] == 2
            assert editor.property("state")["forms"]["notes"] == "Peer saved revision two"
            third = counter.put(
                target,
                json={
                    **command,
                    "request_id": str(uuid4()),
                    "expected_revision": 2,
                    "notes": "Peer saved revision three after the history list was loaded",
                },
            )
            assert third.status_code == 200
            assert editor.loadRevision(2)
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["selected"]["is_current"] is False
            assert editor.property("state")["historical"] is True
            assert editor.loadRevision(1)
            wait_for_editor_idle(qt_app, editor)
            editor.preview("en")
            wait_for_editor_idle(qt_app, editor)
            before = editor.property("state")
            assert before["report"]["revision"] == 1
            assert before["historical"] is True
            box = setup["boxes"]["local_n1"]
            correction = counter.put(
                setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
                json=event_command(
                    box["revision"],
                    "2026-11-15T22:46:00+08:00",
                    reason="Correct paper receipt time",
                ),
            )
            assert correction.status_code == 200
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            current = editor.property("state")
            assert current["selected"]["revision"] == 1
            assert current["selected"]["source_current"] is False
            assert current["newer_revision"] is False
            assert current["forms"] == before["forms"]
            assert current["report"] == before["report"]
            assert current["report_text"] == before["report_text"]


def test_f1_foreground_save_ignores_an_older_held_background_response(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        options = setup["counter"].get(setup["rounds_path"]).json()
        created = setup["counter"].post(setup["rounds_path"], json=complete_f1_command(options))
        assert created.status_code == 201
        target = setup["rounds_path"] + f"/{created.json()['id']}"
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            # Existing fixture barrier holds only a completed real HTTP GET response.
            https_server.hold_staff_response_path = setup["rounds_path"]
            editor.refresh()
            wait_for(qt_app, https_server.staff_response_entered.is_set)
            try:
                editor.setField("notes", "Foreground tally wins over the held poll")
                editor.save()
                wait_for(qt_app, lambda: https_server.request_count("PUT", target) == 1)
            finally:
                https_server.release_staff_response.set()
            wait_for_editor_idle(qt_app, editor)
            wait_for(qt_app, https_server.staff_response_finished.is_set)
            state = editor.property("state")
            assert state["selected"]["revision"] == 2
            assert state["forms"]["notes"] == "Foreground tally wins over the held poll"
            assert state["error"] == ""
            assert state["notice"] == "f1_saved"


@dataclass
class F1WriteBoundary(HttpsServer):
    hold_write_path: str = ""
    write_committed: threading.Event = field(default_factory=threading.Event)
    release_write: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def f1_write_boundary(
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[F1WriteBoundary]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = F1WriteBoundary(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def hold_committed_response(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        if (
            request.method == "PUT"
            and request.url.path == endpoint.hold_write_path
            and response.status_code == 200
        ):
            # This is only the transport of an ordinary committed real API write.
            # A separate public actor can save the next revision before delivery.
            endpoint.hold_write_path = ""
            endpoint.write_committed.set()
            await asyncio.to_thread(endpoint.release_write.wait)
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            loop="asyncio",
            ws="none",
            ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
            ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
            log_level="warning",
            access_log=False,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        endpoint.release_write.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()


def test_f1_save_acknowledges_own_revision_and_flags_a_peer_head_before_readback(
    admin: TestClient,
    database_url: str,
    f1_write_boundary: F1WriteBoundary,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        endpoint = f1_write_boundary
        endpoint.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        command = complete_f1_command(options, notes="Original revision one")
        created = counter.post(path, json=command)
        assert created.status_code == 201
        target = path + f"/{created.json()['id']}"
        with f1_editor(
            endpoint,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            endpoint.hold_write_path = target
            editor.setField("notes", "My committed revision two")
            editor.save()
            wait_for(qt_app, endpoint.write_committed.is_set)
            try:
                peer = setup["clients"]["bothcounting"].put(
                    target,
                    json={
                        **command,
                        "request_id": str(uuid4()),
                        "expected_revision": 2,
                        "notes": "Another officer committed revision three",
                    },
                )
                assert peer.status_code == 200
            finally:
                endpoint.release_write.set()
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["selected"]["revision"] == 2
            assert state["selected"]["actor_id"] == setup["accounts"]["receiveronly"]["id"]
            assert state["forms"]["notes"] == "My committed revision two"
            assert state["notice"] == "f1_saved"
            assert state["newer_revision"] is True
            assert state["history"][0]["revision"] == 3
            assert state["rounds"][0]["revision"] == 3
            assert state["history"][0]["actor_id"] == setup["accounts"]["bothcounting"]["id"]
            assert endpoint.request_count("PUT", target) == 1


def test_unsaved_f1_keeps_its_scope_revision_when_a_peer_submits_a_new_basis(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            assert editor.property("state")["scope"]["revision"] == 1
            editor.setField("event_at", "2026-11-15 23:15:12.123456")
            editor.setCandidateQuantity(options["candidates"][0]["id"], "7")
            editor.setField("notes", "Observed against source scope revision one")
            scope = setup["scope"]
            target = setup["paths"]["n1_counting_scopes"] + f"/{scope['id']}"
            peer = setup["clients"]["bothcounting"]
            changed = peer.put(
                target,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "reference": scope["reference"],
                    "event_at": scope["event_at"],
                    "box_revisions": [
                        {"box_id": row["id"], "revision": row["revision"]}
                        for row in scope["box_basis"]
                    ],
                    "accounting_revisions": [
                        {"station_id": row["station_id"], "revision": row["revision"]}
                        for row in scope["accounting_basis"]
                    ],
                    "notes": "Peer reviewed the source preparation again",
                    "amendment_reason": (
                        "Preserve the original prepared basis and renew this scope."
                    ),
                },
            )
            assert changed.status_code == 200
            assert (
                peer.post(
                    target + "/submit",
                    json={
                        "request_id": str(uuid4()),
                        "expected_revision": 2,
                    },
                ).status_code
                == 200
            )
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["scope"]["revision"] == 1
            assert state["scopes"][0]["revision"] == 2
            assert state["candidate_inputs"][0]["quantity"] == "7"
            assert state["forms"]["notes"] == "Observed against source scope revision one"
            assert state["newer_revision"] is True
            editor.save()
            assert editor.property("state")["error"] == "count_scope_revision_conflict"
            assert https_server.request_count("POST", path) == 0
            assert counter.get(path).json()["rounds"] == []
            editor.discardAndReload()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["scope"]["revision"] == 2
            assert editor.property("state")["candidate_inputs"][0]["quantity"] == ""
