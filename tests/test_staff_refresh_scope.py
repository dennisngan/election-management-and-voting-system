"""Profile polling loads staff directories only after their workspace is opened."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.desktop_support import HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_profile_polling_defers_staff_directories_until_open_and_keeps_manual_refresh(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
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
        lambda: https_server.request_count("GET", "/api/auth/me") > before_profile
        and len(profile_cycles) > before_cycles,
    )
    wait_for(qt_app, lambda: setup_idle(configuration) and setup_idle(staff))
    paths = ("/api/accounts", "/api/accounts/station-options")
    assert all(https_server.request_count("GET", path) == 0 for path in paths)
    assert staff.property("state")["accounts"] == []
    assert staff.property("state")["station_options"] == []

    staff.open()
    wait_for(qt_app, lambda: setup_idle(staff))
    opened = staff.property("state")
    assert opened["error"] == ""
    assert all(https_server.request_count("GET", path) > 0 for path in paths)
    current = state_of(desktop)["account"]
    assert any(
        row["id"] == current["id"] and row["username"] == current["username"]
        for row in opened["accounts"]
    )
    assert isinstance(opened["station_options"], list)

    before_refresh = {path: https_server.request_count("GET", path) for path in paths}
    staff.refresh()
    wait_for(qt_app, lambda: setup_idle(staff))
    assert staff.property("state")["error"] == ""
    assert all(
        https_server.request_count("GET", path) > before_refresh[path] for path in paths
    )
    desktop.signOut()
    assert staff.property("state")["accounts"] == []
    assert staff.property("state")["station_options"] == []
