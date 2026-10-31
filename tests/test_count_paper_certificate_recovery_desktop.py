"""Count-paper provenance survives a real TLS trust failure and outcome recovery."""

import ipaddress
import socket
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture(autouse=True)
def isolated_client_command_journal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "desktop-commands"))


class RestartableHttpsServer:
    """Restart one test API origin with controlled server certificates."""

    def __init__(self, database_url: str, clock: ControlledClock, qt_app: QCoreApplication):
        self.database_url, self.clock, self.qt_app = database_url, clock, qt_app
        self.port = 0
        self.requests: list[tuple[str, str]] = []
        self.after_response: Callable[[str, str, int], None] | None = None
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"https://localhost:{self.port}"

    def request_count(self, method: str, path: str) -> int:
        with self._lock:
            return self.requests.count((method, path))

    def start(self, certificate: Path, private_key: Path) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()
        self.port = listener.getsockname()[1]
        application = create_app(self.database_url, now=self.clock)

        @application.middleware("http")
        async def observe_public_requests(request: Request, call_next) -> Response:
            with self._lock:
                self.requests.append((request.method, request.url.path))
            response = await call_next(request)
            if self.after_response is not None:
                self.after_response(request.method, request.url.path, response.status_code)
            response.headers["connection"] = "close"
            return response

        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=self.port,
                loop="asyncio",
                ws="none",
                ssl_certfile=str(certificate),
                ssl_keyfile=str(private_key),
                log_level="warning",
                access_log=False,
                timeout_keep_alive=1,
                timeout_graceful_shutdown=1,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        self._listener, self._server, self._thread = listener, server, thread
        thread.start()
        wait_for(self.qt_app, lambda: server.started)

    def stop(self) -> None:
        if self._server is None or self._thread is None or self._listener is None:
            return
        self._server.should_exit = True
        wait_for(self.qt_app, lambda: not self._thread.is_alive())
        self._thread.join(timeout=0)
        self._listener.close()
        self._listener = None
        self._server = None
        self._thread = None


def _untrusted_localhost_certificate(directory: Path) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = directory / "untrusted-localhost.pem"
    key_path = directory / "untrusted-localhost-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    certificate_path.chmod(0o600)
    key_path.chmod(0o600)
    return certificate_path, key_path


def test_count_paper_binding_stays_locked_through_certificate_error_until_committed_retry(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    tmp_path: Path,
) -> None:
    clock = ControlledClock()
    trusted_ca = tmp_path / "trusted-ca.pem"
    trusted_ca.write_bytes((TLS_DIRECTORY / "ca.pem").read_bytes())
    trusted_ca.chmod(0o600)
    untrusted_certificate, untrusted_key = _untrusted_localhost_certificate(tmp_path)
    server = RestartableHttpsServer(database_url, clock, qt_app)
    server.start(TLS_DIRECTORY / "server.pem", TLS_DIRECTORY / "server-key.pem")

    controller: DesktopController | None = None
    try:
        with tally_setup(admin, database_url) as setup:
            clock.value = setup["clock"].value
            officer = setup["counter"]
            station_id = setup["stations"]["N1"]["id"]
            rounds_path = setup["rounds_path"]
            options_response = officer.get(rounds_path)
            assert options_response.status_code == 200, options_response.text
            options = options_response.json()
            f1 = officer.post(rounds_path, json=complete_f1_command(options))
            assert f1.status_code == 201, f1.text
            round_id = f1.json()["id"]
            round_path = f"{rounds_path}/{round_id}"
            f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
            assert f2.status_code == 200, f2.text

            outage_path = f"/api/workspace/stations/{station_id}/outages"
            outage = officer.post(
                outage_path,
                json={
                    "request_id": str(uuid4()),
                    "reference": "T25 certificate recovery " + uuid4().hex[:8],
                    "kind": "network",
                    "started_at": "2026-11-15T23:10:00+08:00",
                    "ended_at": "2026-11-15T23:50:00+08:00",
                    "notes": "The signed paper tally is retained for re-entry.",
                },
            )
            assert outage.status_code == 201, outage.text
            outage_id = outage.json()["id"]
            paper_reference = "T25-PAPER-TLS-" + uuid4().hex[:8]
            paper = officer.post(
                f"{outage_path}/{outage_id}/paper-records",
                json={
                    "request_id": str(uuid4()),
                    "expected_outage_revision": 1,
                    "paper_reference": paper_reference,
                    "workflow": "count",
                    "action": "submit",
                    "original_event_at": "2026-11-15T23:35:12.345678+08:00",
                    "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                    "notes": "Retained paper count for certificate recovery test.",
                },
            )
            assert paper.status_code == 201, paper.text
            paper_id = paper.json()["id"]

            controller = DesktopController(server.url, str(trusted_ca))
            controller.signIn(
                server.url,
                setup["accounts"]["receiveronly"]["username"],
                READY_PASSWORD,
            )
            wait_for(qt_app, lambda: controller.property("state")["phase"] == "workspace")
            workspace = controller.property("workspace")
            wait_for_editor_idle(qt_app, workspace)
            workspace.selectStation(station_id)
            wait_for_editor_idle(qt_app, workspace)
            editor = controller.property("countingRounds")
            editor.open()
            wait_for_editor_idle(qt_app, editor)
            assert editor.selectScope(setup["scope"]["id"]) is True
            wait_for_editor_idle(qt_app, editor)
            assert editor.selectRound(round_id) is True
            wait_for_editor_idle(qt_app, editor)
            wait_for(qt_app, lambda: not editor.property("state")["paper_loading"])
            assert editor.selectPaperRecord(paper_id) is True

            submit_path = round_path + "/submit"
            before_submits = server.request_count("POST", submit_path)
            server.stop()
            server.start(untrusted_certificate, untrusted_key)
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            uncertain = editor.property("state")
            assert uncertain["error"] == "certificate_error"
            assert uncertain["uncertain_save"] is True
            assert uncertain["paper_binding_locked"] is True
            assert uncertain["paper_record"]["id"] == paper_id
            assert editor.selectPaperRecord(0) is False
            assert editor.selectPaperRecord(paper_id + 1) is False
            assert editor.property("state")["paper_record"]["id"] == paper_id
            assert server.request_count("POST", submit_path) == before_submits

            recovery = controller.property("recovery")
            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            command = next(
                row
                for row in recovery.property("state")["commands"]
                if row["workflow"] == "count" and row["path"] == submit_path
            )
            original_request_id = command["request_id"]
            original_payload = dict(command["payload"])
            assert original_payload["paper_record_id"] == paper_id

            server.stop()
            server.start(TLS_DIRECTORY / "server.pem", TLS_DIRECTORY / "server-key.pem")
            recovery.checkOutcome(original_request_id)
            wait_for_editor_idle(qt_app, recovery)
            checked = next(
                row
                for row in recovery.property("state")["commands"]
                if row["request_id"] == original_request_id
            )
            assert checked["error"] == "request_not_found"
            assert editor.property("state")["paper_binding_locked"] is True
            assert editor.selectPaperRecord(0) is False

            editor.submitCount()
            wait_for(qt_app, lambda: not editor.property("state")["busy"])
            wait_for(qt_app, lambda: editor.property("state")["notice"] == "count_submitted")
            committed = editor.property("state")
            assert committed["uncertain_save"] is False
            assert committed["paper_binding_locked"] is False
            assert committed["paper_record"] == {}
            assert committed["selected"]["status"] == "submitted"
            assert server.request_count("POST", submit_path) == before_submits + 1

            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            final_command = next(
                row
                for row in recovery.property("state")["commands"]
                if row["request_id"] == original_request_id
            )
            assert final_command["status"] == "committed"
            assert final_command["payload"] == original_payload
            assert final_command["request_id"] == original_request_id

            current_outage = officer.get(f"{outage_path}/{outage_id}")
            assert current_outage.status_code == 200, current_outage.text
            linked = current_outage.json()["record"]["paper_records"]
            assert len(linked) == 1
            assert linked[0]["id"] == paper_id
            assert linked[0]["status"] == "entered"
            assert linked[0]["reentry"]["request_id"] == original_request_id
            assert linked[0]["reentry"]["record"]["status"] == "submitted"
    finally:
        server.stop()
        if controller is not None:
            controller.shutdown()
            controller.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()
