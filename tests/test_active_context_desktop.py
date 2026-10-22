"""An older active-election reply cannot roll back a completed desktop activation."""

import asyncio
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QTimer

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import ready_setup
from tests.desktop_support import (
    PERSONAL_PASSWORD,
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    state_of,
    wait_for,
)
from tests.lifecycle_support import (
    lifecycle_database_url,
    lifecycle_test_state,
    prepared_election,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class DelayedActiveServer(HttpsServer):
    hold_next_active_response: bool = True
    old_active_response_ready: threading.Event = field(default_factory=threading.Event)
    release_old_active_response: threading.Event = field(default_factory=threading.Event)
    old_active_response_released: threading.Event = field(default_factory=threading.Event)
    release_election_lists: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def https_server(database_url: str, qt_app: QCoreApplication) -> Iterator[DelayedActiveServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = DelayedActiveServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def delay_old_active_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        # Lifecycle refresh chains its active GET after this list. Holding the list
        # leaves the independent root GET as the only active reply held below.
        if request.method == "GET" and request.url.path == "/api/elections":
            await asyncio.to_thread(endpoint.release_election_lists.wait, 30)
        response = await call_next(request)
        if (
            request.method == "GET"
            and request.url.path == "/api/active-election"
            and endpoint.hold_next_active_response
        ):
            endpoint.hold_next_active_response = False
            # SQL and JSON response construction have already completed with null.
            endpoint.old_active_response_ready.set()
            await asyncio.to_thread(endpoint.release_old_active_response.wait, 30)
            endpoint.old_active_response_released.set()
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
            ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
            loop="asyncio",
            ws="none",
            lifespan="on",
            log_level="warning",
            access_log=False,
            timeout_keep_alive=1,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        endpoint.release_old_active_response.set()
        endpoint.release_election_lists.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive(), "The delayed-response HTTPS test server did not stop"


def test_older_null_active_reply_cannot_clear_new_activation_or_unlock_configuration(
    desktop: DesktopController,
    https_server: DelayedActiveServer,
    account: dict[str, str],
    database_url: str,
    qt_app: QCoreApplication,
) -> None:
    configuration = ready_setup(desktop, https_server, account, qt_app)
    try:
        wait_for(qt_app, https_server.old_active_response_ready.is_set)
        assert state_of(desktop)["active_election"] is None
        with TestClient(create_app(database_url, now=https_server.clock)) as other:
            login = other.post(
                "/api/auth/login",
                json={"username": account["username"], "password": PERSONAL_PASSWORD},
            )
            assert login.status_code == 200
            other.headers["Authorization"] = "Bearer " + login.json()["token"]
            assert other.get("/api/active-election").json() == {"election": None}
            election, _ = prepared_election(other)

        lifecycle = desktop.property("lifecycle")
        assert lifecycle.loadElection(election["id"], False)
        wait_for(qt_app, lambda: lifecycle.property("state")["schedule"] != {})
        assert configuration.load("election", election["id"], False)
        wait_for(
            qt_app,
            lambda: configuration.property("state")["selected"]["election"] != {},
        )
        configuration.setField("election", "name", "必須保留的未儲存選舉名稱")
        assert configuration.property("state")["read_only"] is False
        lifecycle.activate()
        wait_for(
            qt_app,
            lambda: (state_of(desktop)["active_election"] or {}).get("id") == election["id"],
        )
        active = state_of(desktop)["active_election"]
        assert active["status"] == "active"
        assert configuration.property("state")["read_only"] is True

        https_server.release_old_active_response.set()
        wait_for(qt_app, https_server.old_active_response_released.is_set)
        delivered = threading.Event()
        QTimer.singleShot(250, delivered.set)
        wait_for(qt_app, delivered.is_set)
        assert lifecycle.property("state")["active_election"] == active
        assert state_of(desktop)["active_election"] == active
        assert state_of(desktop)["election"] == active
        state = configuration.property("state")
        assert state["read_only"] is True
        assert state["election_status"] == "active"
        assert state["dirty"]["election"] is True
        assert state["forms"]["election"]["name"] == "必須保留的未儲存選舉名稱"
        configuration.setField("election", "name", "不應接受的後續編輯")
        assert (
            configuration.property("state")["forms"]["election"]["name"]
            == "必須保留的未儲存選舉名稱"
        )
    finally:
        https_server.release_old_active_response.set()
        https_server.release_election_lists.set()
