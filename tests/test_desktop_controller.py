"""Exercise public desktop slots over real HTTPS/MySQL; native controls use Computer."""

import socket
import ssl
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.manage import bootstrap_account
from election.server.app import create_app

INITIAL_PASSWORD = "Initial-Desktop-Password-42!"
PERSONAL_PASSWORD = "Personal-Desktop-Password-84!"
TLS_DIRECTORY = Path(".runtime/tls").resolve()


@dataclass
class ControlledClock:
    value: datetime = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


@dataclass
class HttpsServer:
    url: str
    clock: ControlledClock
    requests: list[tuple[str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def request_count(self, method: str, path: str) -> int:
        with self.lock:
            return self.requests.count((method, path))


@pytest.fixture(scope="session")
def qt_app() -> QCoreApplication:
    instance = QCoreApplication.instance()
    return instance if instance is not None else QCoreApplication([])


def wait_for(app: QCoreApplication, predicate: Callable[[], bool], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if predicate():
            return
        if time.monotonic() >= deadline:
            pytest.fail(
                f"Desktop public state did not reach the expected outcome in {timeout} seconds"
            )
        time.sleep(0.01)


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
        return await call_next(request)

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


def state_of(controller: DesktopController) -> dict[str, Any]:
    """Qt Property descriptors lack a precise instance-return type in the PySide stubs."""
    return cast("dict[str, Any]", controller.property("state"))


def texts_of(controller: DesktopController) -> dict[str, str]:
    return cast("dict[str, str]", controller.property("texts"))


def sign_in(
    controller: DesktopController,
    server: HttpsServer,
    account: dict[str, str],
    app: QCoreApplication,
) -> None:
    controller.signIn(server.url, account["username"], account["password"])
    wait_for(app, lambda: state_of(controller)["phase"] == "password_change")
    assert state_of(controller)["account"]["username"] == account["username"]
    assert state_of(controller)["busy"] is False


def test_three_languages_preserve_server_and_signed_out_state(
    desktop: DesktopController, https_server: HttpsServer
) -> None:
    for locale, label in (("tc", "登入"), ("sc", "登录"), ("en", "Sign in")):
        desktop.setLocale(locale)
        assert texts_of(desktop)["sign_in"] == label
        assert state_of(desktop)["locale"] == locale
        assert state_of(desktop)["phase"] == "signed_out"
        assert state_of(desktop)["server_url"] == https_server.url
        assert "token" not in state_of(desktop)


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:8443",
        "https://someone:password@localhost:8443",
        "https://localhost:8443?unexpected=value",
    ],
)
def test_invalid_server_address_is_rejected_without_replacing_valid_server(
    desktop: DesktopController, https_server: HttpsServer, address: str
) -> None:
    assert desktop.configureServer(address) is False
    assert state_of(desktop)["error"] == "invalid_server"
    assert state_of(desktop)["server_url"] == https_server.url
    assert state_of(desktop)["phase"] == "signed_out"


def test_first_sign_in_password_change_and_sign_out_use_real_tls_api(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    assert state_of(desktop)["account"]["must_change_password"] is True
    desktop.changePassword(INITIAL_PASSWORD, PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    assert state_of(desktop)["account"]["must_change_password"] is False
    assert state_of(desktop)["notice"] == "password_change_success"
    assert state_of(desktop)["election"] is None
    assert state_of(desktop)["connection"] == "connected"
    assert https_server.request_count("POST", "/api/auth/login") == 1
    assert https_server.request_count("POST", "/api/auth/password") == 1
    desktop.signOut()
    assert state_of(desktop)["phase"] == "signed_out"
    assert state_of(desktop)["account"] == {}
    assert state_of(desktop)["expires"] == "—"
    wait_for(qt_app, lambda: https_server.request_count("DELETE", "/api/auth/session") == 1)


def test_wrong_password_error_survives_a_successful_health_refresh(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    desktop.signIn(https_server.url, account["username"], "Wrong-Desktop-Password-42!")
    wait_for(qt_app, lambda: state_of(desktop)["error"] == "invalid_credentials")
    assert state_of(desktop)["phase"] == "signed_out"
    before = https_server.request_count("GET", "/api/health")
    desktop.refresh()
    wait_for(
        qt_app,
        lambda: (
            https_server.request_count("GET", "/api/health") > before
            and state_of(desktop)["connection"] == "connected"
        ),
    )
    assert state_of(desktop)["error"] == "invalid_credentials"
    assert state_of(desktop)["busy"] is False


@pytest.mark.parametrize(
    ("new_password", "confirmation", "error"),
    [
        (PERSONAL_PASSWORD, "Another-Desktop-Password-42!", "password_mismatch"),
        ("short", "short", "min_password"),
        ("x" * 129, "x" * 129, "min_password"),
    ],
)
def test_invalid_password_form_does_not_submit_a_password_change(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    new_password: str,
    confirmation: str,
    error: str,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(INITIAL_PASSWORD, new_password, confirmation)
    assert state_of(desktop)["error"] == error
    assert state_of(desktop)["busy"] is False
    assert state_of(desktop)["phase"] == "password_change"
    # A real round trip gives pending Qt network events a chance to reach the server.
    before = https_server.request_count("GET", "/api/health")
    desktop.refresh()
    wait_for(qt_app, lambda: https_server.request_count("GET", "/api/health") > before)
    assert https_server.request_count("POST", "/api/auth/password") == 0
    assert state_of(desktop)["account"]["must_change_password"] is True


def test_server_certificate_is_rejected_without_the_configured_ca(
    https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    controller = DesktopController(https_server.url)
    try:
        controller.refresh()
        wait_for(qt_app, lambda: state_of(controller)["connection"] == "certificate_error")
        assert state_of(controller)["phase"] == "signed_out"
    finally:
        controller.shutdown()
        controller.deleteLater()
        qt_app.processEvents()


def test_unavailable_local_server_is_reported_as_disconnected(qt_app: QCoreApplication) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        controller = DesktopController(f"https://127.0.0.1:{port}", str(TLS_DIRECTORY / "ca.pem"))
        try:
            controller.refresh()
            wait_for(
                qt_app, lambda: state_of(controller)["connection"] == "disconnected", timeout=10
            )
            assert state_of(controller)["phase"] == "signed_out"
        finally:
            controller.shutdown()
            controller.deleteLater()
            qt_app.processEvents()


def test_server_expiry_at_24_hours_clears_the_desktop_session(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(INITIAL_PASSWORD, PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    https_server.clock.value += timedelta(hours=24)
    desktop.refresh()
    wait_for(qt_app, lambda: state_of(desktop)["error"] == "session_expired")
    assert state_of(desktop)["phase"] == "signed_out"
    assert state_of(desktop)["account"] == {}
    assert state_of(desktop)["expires"] == "—"


def test_shutdown_clears_public_authenticated_state(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    sign_in(desktop, https_server, account, qt_app)
    desktop.shutdown()
    assert state_of(desktop)["phase"] == "signed_out"
    assert state_of(desktop)["account"] == {}
    assert state_of(desktop)["expires"] == "—"
    assert "token" not in state_of(desktop)
    wait_for(qt_app, lambda: https_server.request_count("DELETE", "/api/auth/session") == 1)


def test_incompatible_https_service_reports_failure_without_a_stuck_loading_state(
    qt_app: QCoreApplication,
) -> None:
    class IncompatibleService(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: object) -> None:
            pass

    service = ThreadingHTTPServer(("127.0.0.1", 0), IncompatibleService)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(TLS_DIRECTORY / "server.pem", TLS_DIRECTORY / "server-key.pem")
    service.socket = context.wrap_socket(service.socket, server_side=True)
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    url = f"https://localhost:{service.server_port}"
    controller = DesktopController(url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        controller.signIn(url, "synthetic.staff", "Synthetic-Password-42!")
        wait_for(qt_app, lambda: state_of(controller)["error"] == "request_failed")
        assert state_of(controller)["busy"] is False
        assert state_of(controller)["phase"] == "signed_out"
    finally:
        controller.shutdown()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        service.shutdown()
        service.server_close()
        worker.join(timeout=3)
