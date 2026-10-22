"""Use a named, disposable MySQL test database; never substitute SQLite."""

import asyncio
import os
import socket
import threading
from collections.abc import Awaitable, Callable, Iterator
from uuid import uuid4

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi import Request, Response
from PySide6.QtCore import QCoreApplication, QEvent
from sqlalchemy.engine import make_url

from election.desktop.controller import DesktopController
from election.manage import bootstrap_account
from election.server.app import create_app
from tests.desktop_support import (
    INITIAL_PASSWORD,
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    wait_for,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.getenv("ELECTION_TEST_DATABASE_URL") or dotenv_values(".env").get(
        "ELECTION_TEST_DATABASE_URL"
    )
    if not url:
        pytest.fail("Set ELECTION_TEST_DATABASE_URL to a dedicated MySQL database ending in _test")
    parsed = make_url(url)
    assert parsed.drivername == "mysql+pymysql", "These checks require real MySQL"
    assert parsed.database and parsed.database.endswith("_test"), "Refusing non-test database"
    original = os.environ.get("ELECTION_DATABASE_URL")
    os.environ["ELECTION_DATABASE_URL"] = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield url
    finally:
        if original is None:
            os.environ.pop("ELECTION_DATABASE_URL", None)
        else:
            os.environ["ELECTION_DATABASE_URL"] = original


@pytest.fixture(scope="session")
def qt_app() -> QCoreApplication:
    instance = QCoreApplication.instance()
    return instance if instance is not None else QCoreApplication([])


@pytest.fixture
def https_server(database_url: str, qt_app: QCoreApplication) -> Iterator[HttpsServer]:
    for name in ("server.pem", "server-key.pem", "ca.pem"):
        assert (TLS_DIRECTORY / name).is_file(), "Prepare local TLS with election.manage tls-dev"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = HttpsServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def observe_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Observe only public method/path, never credentials, bodies, or authorization headers.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        delayed_profile = (
            request.method == "GET" and request.url.path == "/api/auth/me" and endpoint.hold_profile
        )
        if delayed_profile:
            endpoint.hold_profile = False
            endpoint.profile_entered.set()
            await asyncio.to_thread(endpoint.release_profile.wait, 5)
        if (
            request.method == "GET"
            and request.url.path == "/api/elections"
            and endpoint.hold_configuration_list
        ):
            endpoint.hold_configuration_list = False
            endpoint.configuration_list_entered.set()
            await asyncio.to_thread(endpoint.release_configuration_list.wait, 5)
        response = await call_next(request)
        if delayed_profile:
            endpoint.delayed_profile_status = response.status_code
            endpoint.profile_finished.set()
        if request.method == "POST" and request.url.path == "/api/auth/password":
            endpoint.password_committed.set()
            if endpoint.hold_password_response:
                await asyncio.to_thread(endpoint.release_password_response.wait, 5)
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
        endpoint.release_configuration_list.set()
        endpoint.release_profile.set()
        endpoint.release_password_response.set()
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()
        assert not thread.is_alive(), "The temporary HTTPS test server did not stop"


@pytest.fixture
def desktop(https_server: HttpsServer, qt_app: QCoreApplication) -> Iterator[DesktopController]:
    controller = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        yield controller
    finally:
        controller.shutdown()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


@pytest.fixture
def account(database_url: str) -> dict[str, str]:
    username = "desktop_" + uuid4().hex[:16]
    bootstrap_account(database_url, username, "桌面測試職員", INITIAL_PASSWORD)
    return {"username": username, "password": INITIAL_PASSWORD}
