"""Exercise public desktop slots over real HTTPS/MySQL; native controls use Computer."""

import socket
import ssl
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from election.desktop.controller import DesktopController
from tests.desktop_support import (
    INITIAL_PASSWORD,
    PERSONAL_PASSWORD,
    TLS_DIRECTORY,
    HttpsServer,
    sign_in,
    state_of,
    texts_of,
    wait_for,
)


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


@pytest.mark.parametrize("old_profile_arrives_first", [True, False])
def test_password_rotation_ignores_a_delayed_old_session_refresh(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    old_profile_arrives_first: bool,
) -> None:
    https_server.hold_profile = True
    https_server.hold_password_response = old_profile_arrives_first
    sign_in(desktop, https_server, account, qt_app)
    wait_for(qt_app, https_server.profile_entered.is_set)
    desktop.changePassword(INITIAL_PASSWORD, PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, https_server.password_committed.is_set)
    if not old_profile_arrives_first:
        wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    https_server.release_profile.set()
    wait_for(qt_app, https_server.profile_finished.is_set)
    assert https_server.delayed_profile_status == 401
    # Keep processing Qt's event queue after the server releases the old response.
    # This is an asynchronous transport barrier, not a block of the GUI thread.
    settled = threading.Event()
    QTimer.singleShot(300, settled.set)
    wait_for(qt_app, settled.is_set)
    https_server.release_password_response.set()
    wait_for(qt_app, lambda: not state_of(desktop)["busy"])
    assert state_of(desktop)["phase"] == "workspace"
    assert state_of(desktop)["account"]["must_change_password"] is False
    assert state_of(desktop)["notice"] == "password_change_success"
    assert state_of(desktop)["error"] == ""
