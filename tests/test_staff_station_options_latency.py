"""Check the complete public station-options response within five seconds on real MySQL."""

import socket
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from threading import Event, Lock, Thread, Timer
from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Constituency, Election
from election.server.db import make_engine
from election.server.station_models import PollingStation
from tests.backup_support import mysql_test_port
from tests.lifecycle_support import lifecycle_database_url

COHORT_SIZE = 1200
REQUEST_BUDGET_SECONDS = 5.0
CLIENT_TO_MYSQL_DELAY_SECONDS = 0.005
PROXY_CLEANUP_BUDGET_SECONDS = 10.0
TIMER_CLEANUP_BUDGET_SECONDS = 2.0
_QUERY_ROUTE_OVERRIDES = frozenset(
    {
        "unix_socket",
        "host",
        "port",
        "db",
        "database",
        "read_default_file",
        "read_default_group",
        "init_command",
    }
)


class _PrivateDatabaseUrl(str):
    def __repr__(self) -> str:
        return "<private lifecycle test database URL>"


@pytest.fixture
def database_url() -> Iterator[_PrivateDatabaseUrl]:
    # Keep the existing lifecycle-only fixture and hide expected failure argument repr.
    for value in lifecycle_database_url():
        yield _PrivateDatabaseUrl(value)


def _check_upstream(database_url: _PrivateDatabaseUrl) -> tuple[str, int]:
    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql", "Real MySQL is required"
    assert parsed.database and parsed.database.endswith("_lifecycle_test"), (
        "Refusing a seed outside the lifecycle test database"
    )
    assert not _QUERY_ROUTE_OVERRIDES.intersection(key.casefold() for key in parsed.query), (
        "Database query parameters must not override the approved route or schema"
    )
    host = parsed.host
    assert host is not None, "A loopback database host is required"
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    assert loopback and parsed.port == mysql_test_port(), (
        "Only the explicitly configured loopback fixture MySQL is allowed"
    )
    return host, parsed.port


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    if 0 < len(name) <= 64 and name.isascii() and name.replace("_", "").isalnum():
        return name
    return "Exception"


def _close_socket(connection: socket.socket) -> None:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


class _DelayedMysqlProxy:
    """Own the loopback listener and opaque, cancellable TCP forwarding threads."""

    def __init__(self, host: str, port: int) -> None:
        self._upstream = (host, port)
        self._stop = Event()
        self._lock = Lock()
        self._sockets: set[socket.socket] = set()
        self._threads: list[Thread] = []
        self._thread_error_types: list[str] = []
        self._accepted_connections = 0
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self._listener = socket.create_server((host, 0), family=family)
        try:
            self._listener.settimeout(0.1)
            self.port = int(self._listener.getsockname()[1])
            self._start(self._accept)
        except BaseException:
            self.close()
            raise

    @property
    def accepted_connections(self) -> int:
        with self._lock:
            return self._accepted_connections

    def _run(self, operation: Callable[[], None]) -> None:
        try:
            operation()
        except BaseException as error:
            with self._lock:
                self._thread_error_types.append(_safe_error_type(error))

    def _start(self, operation: Callable[[], None]) -> bool:
        with self._lock:
            if self._stop.is_set():
                return False
            thread = Thread(
                target=lambda: self._run(operation),
                name="station-options-latency-proxy",
                daemon=False,
            )
            self._threads.append(thread)
            try:
                thread.start()
            except BaseException:
                self._threads.remove(thread)
                raise
            return True

    def _own(self, connection: socket.socket) -> bool:
        with self._lock:
            if self._stop.is_set():
                accepted = False
            else:
                self._sockets.add(connection)
                accepted = True
        if not accepted:
            _close_socket(connection)
        return accepted

    def _release(self, *connections: socket.socket) -> None:
        for connection in connections:
            _close_socket(connection)
        with self._lock:
            self._sockets.difference_update(connections)

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                downstream, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self._own(downstream):
                continue
            try:
                # Own the accepted socket before configuration or thread startup.
                downstream.settimeout(REQUEST_BUDGET_SECONDS)
                with self._lock:
                    self._accepted_connections += 1
                if not self._start(lambda downstream=downstream: self._connect(downstream)):
                    self._release(downstream)
            except BaseException:
                self._release(downstream)
                raise

    def _connect(self, downstream: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            upstream = socket.create_connection(self._upstream, timeout=REQUEST_BUDGET_SECONDS)
            if not self._own(upstream):
                return
            if not self._start(lambda: self._relay(upstream, downstream, delayed=False)):
                return
            self._relay(downstream, upstream, delayed=True)
        except OSError:
            pass
        finally:
            self._release(downstream, *(() if upstream is None else (upstream,)))

    def _relay(self, source: socket.socket, destination: socket.socket, *, delayed: bool) -> None:
        try:
            while not self._stop.is_set():
                chunk = source.recv(65536)
                if not chunk:
                    return
                if delayed and self._stop.wait(CLIENT_TO_MYSQL_DELAY_SECONDS):
                    return
                destination.sendall(chunk)
        except OSError:
            pass
        finally:
            _close_socket(source)
            _close_socket(destination)

    def interrupt(self) -> None:
        """Interrupt owned DB transport only; this method never joins threads."""
        self._stop.set()
        _close_socket(self._listener)
        with self._lock:
            connections = tuple(self._sockets)
        for connection in connections:
            _close_socket(connection)

    def close(self) -> list[str]:
        self.interrupt()
        with self._lock:
            threads = tuple(self._threads)
        deadline = monotonic() + PROXY_CLEANUP_BUDGET_SECONDS
        for thread in threads:
            thread.join(max(0.0, deadline - monotonic()))
        problems: list[str] = []
        if any(thread.is_alive() for thread in threads):
            problems.append("Owned proxy threads exceeded their cleanup bound.")
        with self._lock:
            if self._thread_error_types:
                problems.append("An owned proxy thread failed before clean shutdown.")
        return problems


@dataclass(frozen=True)
class _StationOptionsCohort:
    baseline_station_ids: frozenset[int] = field(repr=False)
    expected: dict[int, dict[str, Any]] = field(repr=False)


@pytest.fixture
def station_options_cohort(
    database_url: _PrivateDatabaseUrl, admin: TestClient
) -> Iterator[_StationOptionsCohort]:
    _check_upstream(database_url)
    baseline = admin.get("/api/accounts/station-options")
    assert baseline.status_code == 200
    baseline_items = baseline.json()["items"]
    baseline_ids = frozenset(item["station"]["id"] for item in baseline_items)
    assert len(baseline_items) == len(baseline_ids)

    election_ids: list[int] = []
    constituency_ids: list[int] = []
    station_ids: list[int] = []
    expected: dict[int, dict[str, Any]] = {}
    prefix = "latency_" + uuid4().hex
    now = datetime.now(UTC).replace(tzinfo=None)
    common = {
        "revision": 1,
        "creation_digest": "0" * 64,
        "created_at": now,
        "updated_at": now,
    }
    failure: BaseException | None = None
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            elections = [
                Election(
                    name=f"{prefix} election {number:04d}",
                    status="draft",
                    request_id=str(uuid4()),
                    **common,
                )
                for number in range(COHORT_SIZE)
            ]
            db.add_all(elections)
            db.flush()
            election_ids = [election.id for election in elections]
            constituencies = [
                Constituency(
                    election_id=election.id,
                    name=f"{prefix} constituency {number:04d}",
                    code=f"C{number:04d}",
                    seats=1,
                    choices_per_ballot=1,
                    request_id=str(uuid4()),
                    **common,
                )
                for number, election in enumerate(elections)
            ]
            db.add_all(constituencies)
            db.flush()
            constituency_ids = [constituency.id for constituency in constituencies]
            stations = [
                PollingStation(
                    constituency_id=constituency.id,
                    name=f"{prefix} station {number:04d}",
                    code=f"P{number:04d}",
                    counting_mode="local",
                    destination_station_id=None,
                    request_id=str(uuid4()),
                    **common,
                )
                for number, constituency in enumerate(constituencies)
            ]
            db.add_all(stations)
            db.flush()
            station_ids = [station.id for station in stations]
            for election, constituency, station in zip(
                elections, constituencies, stations, strict=True
            ):
                expected[station.id] = {
                    "election": {
                        "id": election.id,
                        "name": election.name,
                        "status": "draft",
                        "revision": 1,
                    },
                    "constituency": {
                        "id": constituency.id,
                        "name": constituency.name,
                        "code": constituency.code,
                    },
                    "station": {
                        "id": station.id,
                        "name": station.name,
                        "code": station.code,
                        "counting_mode": "local",
                        "destination_station_id": None,
                    },
                }
            db.commit()
        yield _StationOptionsCohort(baseline_ids, expected)
    except BaseException as error:
        failure = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            with Session(engine) as db:
                if station_ids:
                    db.execute(delete(PollingStation).where(PollingStation.id.in_(station_ids)))
                if constituency_ids:
                    db.execute(delete(Constituency).where(Constituency.id.in_(constituency_ids)))
                if election_ids:
                    db.execute(delete(Election).where(Election.id.in_(election_ids)))
                db.commit()
        except BaseException as error:
            cleanup_error = error
        try:
            engine.dispose()
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
            else:
                cleanup_error.add_note(
                    "Fixture engine disposal also failed with " + _safe_error_type(error) + "."
                )
        if cleanup_error is not None:
            if failure is not None:
                failure.add_note("Owned cohort cleanup also failed.")
                raise cleanup_error from failure
            raise cleanup_error


def test_station_options_preserves_every_station_within_five_seconds(
    database_url: _PrivateDatabaseUrl,
    admin: TestClient,
    station_options_cohort: _StationOptionsCohort,
) -> None:
    host, port = _check_upstream(database_url)
    proxy: _DelayedMysqlProxy | None = None
    deadline_timer: Timer | None = None
    expired = Event()
    failure: BaseException | None = None
    cleanup_problems: list[str] = []
    try:
        proxy = _DelayedMysqlProxy(host, port)
        proxied_url = _PrivateDatabaseUrl(
            make_url(database_url).set(port=proxy.port).render_as_string(hide_password=False)
        )
        with TestClient(create_app(proxied_url), base_url="https://testserver") as client:
            try:
                client.headers["Authorization"] = admin.headers["Authorization"]
                identity = client.get("/api/auth/me")
                assert identity.status_code == 200
                assert identity.json()["role"] == "administrator"
                assert proxy.accepted_connections > 0, (
                    "The public identity probe did not use the proxy"
                )
                deadline = monotonic() + REQUEST_BUDGET_SECONDS

                def interrupt_expired_read() -> None:
                    expired.set()
                    proxy.interrupt()

                deadline_timer = Timer(max(0.0, deadline - monotonic()), interrupt_expired_read)
                deadline_timer.name = "station-options-latency-deadline"
                deadline_timer.daemon = False
                deadline_timer.start()
                try:
                    response = client.get("/api/accounts/station-options")
                except Exception:
                    if expired.is_set() or monotonic() > deadline:
                        raise TimeoutError(
                            "Public station-options GET exceeded the unchanged 5-second budget."
                        ) from None
                    raise
                if expired.is_set() or monotonic() > deadline:
                    raise TimeoutError(
                        "Public station-options GET exceeded the unchanged 5-second budget."
                    ) from None
                assert response.status_code == 200
                items = response.json()["items"]
                by_station_id = {item["station"]["id"]: item for item in items}
                assert len(items) == len(by_station_id)
                cohort = station_options_cohort
                assert set(by_station_id) == (cohort.baseline_station_ids | set(cohort.expected))
                owned_public_rows = [
                    item for item in items if item["station"]["id"] in cohort.expected
                ]
                assert len(owned_public_rows) == COHORT_SIZE
                for station_id, expected in cohort.expected.items():
                    actual = by_station_id[station_id]
                    assert {key: actual[key] for key in expected} == expected
                if expired.is_set() or monotonic() > deadline:
                    raise TimeoutError(
                        "Public station-options GET exceeded the unchanged 5-second budget."
                    ) from None
            except BaseException as error:
                failure = error
                raise
            finally:
                if deadline_timer is not None:
                    try:
                        deadline_timer.cancel()
                        if deadline_timer.ident is not None:
                            deadline_timer.join(timeout=TIMER_CLEANUP_BUDGET_SECONDS)
                            if deadline_timer.is_alive():
                                cleanup_problems.append(
                                    "The owned deadline Timer exceeded its cleanup bound."
                                )
                    except Exception as error:
                        cleanup_problems.append(
                            "Timer cleanup failed with " + _safe_error_type(error) + "."
                        )
    except BaseException as error:
        if failure is not None and error is not failure:
            failure.add_note(
                "TestClient context exit also failed with " + _safe_error_type(error) + "."
            )
            raise failure from None
        failure = error
        raise
    finally:
        if proxy is not None:
            try:
                cleanup_problems.extend(proxy.close())
            except Exception as error:
                cleanup_problems.append(
                    "Proxy cleanup failed with " + _safe_error_type(error) + "."
                )
        if cleanup_problems:
            if failure is not None:
                for problem in cleanup_problems:
                    failure.add_note(problem)
            else:
                raise AssertionError(" ".join(cleanup_problems))
