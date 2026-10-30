"""Election completion changes reach public Qt lifecycle state through real HTTPS."""

import ssl
from collections.abc import Iterator
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, wait_for
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_completion_desktop_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_lifecycle_refresh_propagates_no_active_election_after_real_finalization(
    desktop: DesktopController,
    admin: TestClient,
    account: dict[str, str],
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        configuration = ready_setup(desktop, https_server, account, qt_app)
        lifecycle = desktop.property("lifecycle")
        assert lifecycle is not None
        election_id = setup["election"]["id"]
        wait_for(qt_app, lambda: (
            setup_idle(configuration) and setup_idle(lifecycle)
            and (lifecycle.property("state")["active_election"] or {}).get("id") == election_id
            and (desktop.property("state")["active_election"] or {}).get("id") == election_id
        ))
        assert desktop.property("state")["account"]["role"] == "administrator"
        assert desktop.property("workspace").property("state")["selected"] == {}
        context = ssl.create_default_context(cafile=str(TLS_DIRECTORY / "ca.pem"))
        with httpx.Client(base_url=https_server.url, verify=context) as supervisor:
            login = supervisor.post("/api/auth/login", json={
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
            })
            assert login.status_code == 200, login.text
            supervisor.headers["Authorization"] = "Bearer " + login.json()["token"]
            try:
                response = supervisor.get(setup["completion_path"])
                assert response.status_code == 200, response.text
                reviewed = response.json()
                assert reviewed["can_finalize"] is True
                finalized = supervisor.post(
                    f"/api/workspace/elections/{election_id}/finalizations", json={
                        "request_id": str(uuid4()),
                        "expected_election_revision": reviewed["election"]["revision"],
                        "basis_digest": reviewed["basis_digest"],
                        "password": BOX_READY_PASSWORD,
                    },
                )
                assert finalized.status_code == 201, finalized.text
                assert finalized.json()["election"]["status"] == "finalized"
                assert finalized.json()["active_election_id"] is None
                active = supervisor.get("/api/active-election")
                assert active.status_code == 200, active.text
                assert active.json()["election"] is None
                assert desktop.property("state")["active_election"]["id"] == election_id
                before = https_server.request_count("GET", "/api/active-election")
                lifecycle.refresh()
                wait_for(qt_app, lambda: setup_idle(lifecycle))
                observed_lifecycle = lifecycle.property("state")
                observed_root = desktop.property("state")
                after = https_server.request_count("GET", "/api/active-election")
            finally:
                logout = supervisor.delete("/api/auth/session")
                assert logout.status_code == 204, logout.text
        assert after == before + 1, "An independent active-election refresh overlapped this seam"
        assert observed_lifecycle["error"] == ""
        assert observed_lifecycle["active_election"] is None
        assert observed_root["active_election"] is None
