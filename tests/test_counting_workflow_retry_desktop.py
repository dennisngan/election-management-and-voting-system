"""Count selection retry behavior after a committed TLS response is dropped."""

import socket
import struct
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.desktop_support import (
    TLS_DIRECTORY,
    ControlledClock,
    HttpsServer,
    wait_for,
    wait_for_editor_idle,
)
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer


@dataclass
class LostSelectionResponse(HttpsServer):
    drop_path: str = ""
    drop_peer: tuple[str, int] | None = None
    response_tagged: threading.Event = field(default_factory=threading.Event)
    response_dropped: threading.Event = field(default_factory=threading.Event)


class TransparentTlsProxy:
    """Forward opaque TLS bytes and reset only the tagged selection response."""

    def __init__(
        self,
        listener: socket.socket,
        backend_port: int,
        endpoint: LostSelectionResponse,
    ) -> None:
        self._listener, self._backend_port, self._endpoint = listener, backend_port, endpoint
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._connections: set[socket.socket] = set()
        self._thread = threading.Thread(target=self._accept, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._listener.close()
        except OSError:
            pass
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            self._close(connection)
        self._thread.join(timeout=2)

    @staticmethod
    def _close(connection: socket.socket) -> None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass

    def _accept(self) -> None:
        self._listener.settimeout(0.2)
        while not self._stopping.is_set():
            try:
                client, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stopping.is_set():
                    return
                continue
            try:
                backend = socket.create_connection(("127.0.0.1", self._backend_port), timeout=3)
            except OSError:
                self._close(client)
                continue
            with self._lock:
                self._connections.update((client, backend))
            worker = threading.Thread(
                target=self._relay,
                args=(client, backend),
                daemon=True,
            )
            worker.start()

    def _relay(self, client: socket.socket, backend: socket.socket) -> None:
        closed = threading.Event()
        close_lock = threading.Lock()

        def close_pair(*, reset_client: bool = False) -> None:
            with close_lock:
                if closed.is_set():
                    return
                closed.set()
                if reset_client:
                    try:
                        client.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_LINGER,
                            struct.pack("ii", 1, 0),
                        )
                    except OSError:
                        pass
                    client.close()
                    backend.close()
                else:
                    self._close(client)
                    self._close(backend)
            with self._lock:
                self._connections.discard(client)
                self._connections.discard(backend)

        def copy(source: socket.socket, destination: socket.socket, *, from_backend: bool) -> None:
            try:
                while not closed.is_set():
                    data = source.recv(65536)
                    if not data:
                        close_pair()
                        return
                    if from_backend:
                        peer = backend.getsockname()
                        with self._endpoint.lock:
                            should_drop = self._endpoint.drop_peer == peer
                            if should_drop:
                                self._endpoint.drop_peer = None
                        if should_drop:
                            self._endpoint.response_dropped.set()
                            close_pair(reset_client=True)
                            return
                    destination.sendall(data)
            except OSError:
                close_pair()

        client_to_backend = threading.Thread(
            target=copy,
            args=(client, backend),
            kwargs={"from_backend": False},
            daemon=True,
        )
        backend_to_client = threading.Thread(
            target=copy,
            args=(backend, client),
            kwargs={"from_backend": True},
            daemon=True,
        )
        client_to_backend.start()
        backend_to_client.start()
        client_to_backend.join()
        backend_to_client.join()


@pytest.fixture
def lost_selection_response(
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[LostSelectionResponse]:
    backend_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    backend_listener.bind(("127.0.0.1", 0))
    backend_listener.listen()
    backend_port = backend_listener.getsockname()[1]

    client_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_listener.bind(("127.0.0.1", 0))
    client_listener.listen()
    client_port = client_listener.getsockname()[1]
    endpoint = LostSelectionResponse(
        url=f"https://localhost:{client_port}",
        clock=ControlledClock(),
    )
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def tag_committed_selection(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with endpoint.lock:
            endpoint.requests.append((request.method, request.url.path))
        response = await call_next(request)
        peer = request.client
        if (
            request.method == "POST"
            and request.url.path == endpoint.drop_path
            and response.status_code == 200
            and peer is not None
        ):
            with endpoint.lock:
                endpoint.drop_peer = (peer.host, peer.port)
                endpoint.drop_path = ""
            endpoint.response_tagged.set()
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=backend_port,
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
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [backend_listener]},
        daemon=True,
    )
    proxy = TransparentTlsProxy(client_listener, backend_port, endpoint)
    server_thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        proxy.start()
        yield endpoint
    finally:
        proxy.stop()
        server.should_exit = True
        wait_for(qt_app, lambda: not server_thread.is_alive())
        server_thread.join(timeout=0)
        backend_listener.close()


def test_uncertain_selection_retains_command_after_wrong_password_retry(
    admin: TestClient,
    database_url: str,
    lost_selection_response: LostSelectionResponse,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        endpoint = lost_selection_response
        endpoint.clock.value = setup["clock"].value
        counter, supervisor, path = (
            setup["counter"],
            setup["clients"]["supervisor"],
            setup["rounds_path"],
        )
        options = counter.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        f2 = counter.put(target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        approved = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        with f1_editor(
            endpoint,
            qt_app,
            setup["accounts"]["supervisor"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            endpoint.drop_path = target + "/select"
            editor.selectApproved(READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)
            assert endpoint.response_tagged.is_set()
            assert endpoint.response_dropped.is_set()
            uncertain = editor.property("state")
            assert uncertain["error"] == "disconnected"
            assert uncertain["uncertain_save"] is True
            assert uncertain["notice"] != "count_selected"
            assert endpoint.request_count("POST", target + "/select") == 1
            assert len(supervisor.get(path).json()["selection_history"]) == 1

            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            selected = editor.property("state")["selected"]
            assert selected["selection"]["revision"] == 1
            assert editor.property("state")["uncertain_save"] is True

            editor.selectApproved("Incorrect-Password-42!")
            wait_for_editor_idle(qt_app, editor)
            denied = editor.property("state")
            assert denied["error"] == "invalid_credentials"
            assert endpoint.request_count("POST", target + "/select") == 2
            assert denied["uncertain_save"] is True
