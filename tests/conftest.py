"""Use a named, disposable MySQL test database; never substitute SQLite."""

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Generator, Iterator
from uuid import uuid4

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from sqlalchemy.engine import make_url
from starlette.responses import StreamingResponse

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


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[object]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if report.when != "call" or not report.failed:
        return report
    fixtures = getattr(item, "funcargs", {})
    desktop, endpoint = fixtures.get("desktop"), fixtures.get("https_server")
    if not isinstance(desktop, DesktopController) or not isinstance(endpoint, HttpsServer):
        return report
    try:
        # Read public state only after the unchanged assertion has failed. Never
        # process more events, wait, retry, or replace the original test verdict.
        staff = desktop.property("staff").property("state")
        selected = staff.get("selected", {})
        diagnostic = {
            "observed_at": time.monotonic(),
            "staff": {
                **{
                    key: staff.get(key)
                    for key in ("busy", "refreshing", "error", "notice")
                },
                "selected_id": selected.get("id"),
                "account_count": len(staff.get("accounts", [])),
                "station_count": len(staff.get("station_options", [])),
            },
            "timing_boundary": "ASGI response-header readiness; not full transport completion",
        }
        with endpoint.lock:
            diagnostic["recent_arrivals"] = endpoint.requests[-20:]
            diagnostic["recent_header_timings"] = [
                {
                    key: row.get(key)
                    for key in (
                        "method", "path", "arrived_at", "headers_ready_at", "elapsed", "status"
                    )
                }
                for row in endpoint.request_timings[-20:]
            ]
        report.sections.append(("Staff HTTP diagnostic", json.dumps(diagnostic, indent=2)))
    except AttributeError, RuntimeError, TypeError:
        # A test may intentionally dispose its Qt objects. Diagnostic collection
        # must not replace its original failure with a reporting error.
        pass
    return report


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
        arrived_at = time.monotonic()
        # Observe only public method/path, never credentials, bodies, or authorization headers.
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        delayed_profile = (
            request.method == "GET" and request.url.path == "/api/auth/me" and endpoint.hold_profile
        )
        if delayed_profile:
            endpoint.hold_profile = False
            endpoint.profile_entered.set()
            # This controlled barrier ends only on explicit release; fixture
            # cleanup also releases it, including after a failed assertion.
            await asyncio.to_thread(endpoint.release_profile.wait)
        if (
            request.method == "GET"
            and request.url.path == "/api/elections"
            and endpoint.hold_configuration_list
        ):
            endpoint.hold_configuration_list = False
            endpoint.configuration_list_entered.set()
            await asyncio.to_thread(endpoint.release_configuration_list.wait, 5)
        delayed_allocations = (
            request.method == "GET"
            and request.url.path.endswith("/allocations")
            and endpoint.hold_allocation_list
        )
        if delayed_allocations:
            endpoint.hold_allocation_list = False
            endpoint.allocation_list_entered.set()
        held_staff_response = bool(
            request.method == "GET" and endpoint.hold_staff_response_path
            and request.url.path == endpoint.hold_staff_response_path
        )
        if held_staff_response:
            endpoint.hold_staff_response_path = ""
        response = await call_next(request)
        headers_ready_at = time.monotonic()
        # Observe only method/path/status and monotonic times. This is ASGI
        # response-header readiness, not full body delivery or Qt transport completion.
        with endpoint.lock:
            endpoint.request_timings.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "arrived_at": arrived_at,
                    "headers_ready_at": headers_ready_at,
                    "elapsed": headers_ready_at - arrived_at,
                    "status": response.status_code,
                }
            )
        if (
            request.method == "GET" and request.url.path == endpoint.fail_staff_response_path
            and response.status_code == 200
        ):
            endpoint.fail_staff_response_path = ""
            endpoint.staff_response_failed.set()
            # The authenticated read ran against MySQL. Substitute only its
            # public HTTP response with a complete failure for the batch guard.
            return Response(
                content='{"detail":{"code":"request_failed"}}', status_code=503,
                media_type="application/json",
            )
        if held_staff_response:
            # Hold only the transport of a completed real staff read. The test
            # releases explicitly; fixture cleanup also releases after failures.
            endpoint.staff_response_entered.set()
            await asyncio.to_thread(endpoint.release_staff_response.wait)
            endpoint.staff_response_finished.set()
        if delayed_allocations:
            await asyncio.to_thread(endpoint.release_allocation_list.wait, 5)
        if (
            request.method in ("POST", "PUT")
            and "/allocations" in request.url.path
            and response.status_code in (200, 201)
            and endpoint.truncate_next_allocation_write
        ):
            # Commit the real authenticated command, then interrupt only its TLS
            # response. Public retries must recover its one saved effect.
            endpoint.truncate_next_allocation_write = False
            return StreamingResponse(
                iter([b'{"incomplete":']),
                media_type="application/json",
                headers={"Content-Length": "4096"},
            )
        if delayed_profile:
            endpoint.delayed_profile_status = response.status_code
            endpoint.profile_finished.set()
        if request.method == "POST" and request.url.path == "/api/auth/password":
            endpoint.password_committed.set()
            if endpoint.hold_password_response:
                await asyncio.to_thread(endpoint.release_password_response.wait, 5)
        if (
            request.method == "GET"
            and request.url.path.endswith("/statement.pdf")
            and response.status_code == 200
            and endpoint.truncate_next_report
        ):
            # The authorized real report route has completed; fail only its transport.
            # A mismatched length makes Uvicorn close TLS after sending HTTP 200 headers.
            endpoint.truncate_next_report = False
            return StreamingResponse(
                iter([b"%PDF-1.4\ntruncated"]),
                media_type="application/pdf",
                headers={"Content-Length": "4096"},
            )
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
            # Match the production server. A test-only one-second idle timeout can
            # close a reused Qt connection before a large-directory command arrives.
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
        endpoint.release_configuration_list.set()
        endpoint.release_profile.set()
        endpoint.release_password_response.set()
        endpoint.release_allocation_list.set()
        endpoint.release_staff_response.set()
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


@pytest.fixture
def admin(database_url: str) -> Iterator[TestClient]:
    username = "config_" + uuid4().hex[:12]
    password = "Configuration-Initial-42!"
    bootstrap_account(database_url, username, "設定管理員", password)
    with TestClient(create_app(database_url), base_url="https://testserver") as client:
        login = client.post("/api/auth/login", json={"username": username, "password": password})
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        changed = client.post(
            "/api/auth/password",
            json={"current_password": password, "new_password": "Configuration-Ready-84!"},
        )
        client.headers["Authorization"] = "Bearer " + changed.json()["token"]
        yield client
