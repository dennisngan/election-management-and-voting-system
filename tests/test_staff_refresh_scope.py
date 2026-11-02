"""Profile polling loads staff directories only after their workspace is opened."""

import ssl
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.desktop_support import (
    TLS_DIRECTORY,
    HttpsServer,
    state_of,
    wait_for,
    wait_for_editor_idle,
)
from tests.lifecycle_support import lifecycle_database_url


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_profile_polling_defers_staff_directories_until_open_and_keeps_manual_refresh(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    admin: TestClient,
) -> None:
    staff, configuration = desktop.property("staff"), desktop.property("configuration")
    profile_cycles: list[bool] = []

    def configuration_changed() -> None:
        # The administrator profile callback starts this public refresh before
        # refreshing staff. Qt dispatch returns after that complete callback.
        if configuration.property("state")["refreshing"]:
            profile_cycles.append(True)

    configuration.stateChanged.connect(configuration_changed)
    ready_setup(desktop, https_server, account, qt_app)
    wait_for(qt_app, lambda: bool(profile_cycles))
    wait_for(qt_app, lambda: setup_idle(configuration) and setup_idle(staff))
    before_profile = https_server.request_count("GET", "/api/auth/me")
    before_cycles = len(profile_cycles)
    desktop.refresh()
    wait_for(
        qt_app,
        lambda: (
            https_server.request_count("GET", "/api/auth/me") > before_profile
            and len(profile_cycles) > before_cycles
        ),
    )
    wait_for(qt_app, lambda: setup_idle(configuration) and setup_idle(staff))
    paths = ("/api/accounts", "/api/accounts/station-options")
    assert all(https_server.request_count("GET", path) == 0 for path in paths)
    assert staff.property("state")["accounts"] == []
    assert staff.property("state")["station_options"] == []

    staff.open()
    wait_for_editor_idle(qt_app, staff)
    opened = staff.property("state")
    assert opened["error"] == ""
    assert all(https_server.request_count("GET", path) > 0 for path in paths)
    current = state_of(desktop)["account"]
    assert any(
        row["id"] == current["id"] and row["username"] == current["username"]
        for row in opened["accounts"]
    )
    assert isinstance(opened["station_options"], list)
    expected_accounts = {row["id"] for row in opened["accounts"]}
    expected_stations = {row["station"]["id"] for row in opened["station_options"]}

    read_start = Barrier(5)

    def read_directory(client: httpx.Client, path: str) -> set[int]:
        read_start.wait(timeout=5)
        response = client.get(path)
        assert response.status_code == 200
        items = response.json()["items"]
        return {row["id"] if path == "/api/accounts" else row["station"]["id"] for row in items}

    # Keep peer transports alive across all cycles against the same HTTPS backend.
    # Close them after every submitted directory read has settled, including failures.
    with ExitStack() as peers:
        clients = [
            peers.enter_context(
                httpx.Client(
                    base_url=https_server.url,
                    verify=ssl.create_default_context(cafile=TLS_DIRECTORY / "ca.pem"),
                    headers=admin.headers,
                    timeout=8,
                )
            )
            for _ in range(4)
        ]
        with ThreadPoolExecutor(max_workers=4) as readers:
            for _ in range(5):
                cycle_profiles = len(profile_cycles)
                before_refresh = {path: https_server.request_count("GET", path) for path in paths}
                other_reads = [
                    readers.submit(read_directory, client, path)
                    for client, path in zip(clients, paths * 2, strict=True)
                ]
                read_start.wait(timeout=5)
                refresh_started = time.monotonic()
                desktop.refresh()
                staff.refresh()
                wait_for_editor_idle(qt_app, staff)
                elapsed = time.monotonic() - refresh_started
                assert elapsed < 5, f"Staff refresh took {elapsed:.3f} seconds"
                refreshed = staff.property("state")
                assert refreshed["error"] == ""
                assert len(refreshed["accounts"]) == len(opened["accounts"])
                assert len(refreshed["station_options"]) == len(opened["station_options"])
                assert {row["id"] for row in refreshed["accounts"]} == expected_accounts
                assert {
                    row["station"]["id"] for row in refreshed["station_options"]
                } == expected_stations
                assert next(
                    row for row in refreshed["accounts"] if row["id"] == current["id"]
                ) == next(row for row in opened["accounts"] if row["id"] == current["id"])
                assert other_reads[0].result() == expected_accounts
                assert other_reads[1].result() == expected_stations
                assert other_reads[2].result() == expected_accounts
                assert other_reads[3].result() == expected_stations
                assert all(
                    https_server.request_count("GET", path) >= before_refresh[path] + 3
                    for path in paths
                )
                # The profile callback can start a background staff refresh after
                # the manual batch settles. Finish that public cycle before the
                # next baseline includes some of its already-issued requests.
                wait_for(qt_app, lambda: len(profile_cycles) > cycle_profiles)
                wait_for(qt_app, lambda: setup_idle(configuration) and setup_idle(staff))
    desktop.signOut()
    assert staff.property("state")["accounts"] == []
    assert staff.property("state")["station_options"] == []
