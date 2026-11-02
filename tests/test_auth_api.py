"""Ticket 01: exercise authentication through the public HTTPS API seam."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.manage import bootstrap_account
from election.server.app import create_app


class ControlledClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> ControlledClock:
    return ControlledClock()


@pytest.fixture
def account(database_url: str) -> dict[str, str]:
    username = "officer_" + uuid4().hex[:12]
    bootstrap_account(database_url, username, "測試職員", "Initial-Test-Password-42!")
    return {"username": username, "password": "Initial-Test-Password-42!"}


@pytest.fixture
def client(database_url: str, clock: ControlledClock) -> TestClient:
    with TestClient(create_app(database_url, now=clock), base_url="https://testserver") as client:
        yield client


def test_bootstrap_account_can_sign_in_without_exposing_credentials(
    client: TestClient, account: dict[str, str]
) -> None:
    response = client.post("/api/auth/login", json=account)
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["display_name"] == "測試職員"
    assert body["account"]["must_change_password"] is True
    assert body["expires_at"] == "2026-10-23T06:00:00Z"
    assert len(body["token"]) >= 40
    assert "password_hash" not in response.text
    assert account["password"] not in response.text


def test_first_password_change_unlocks_workspace_and_revokes_earlier_sessions(
    client: TestClient, account: dict[str, str]
) -> None:
    first = client.post("/api/auth/login", json=account).json()["token"]
    other = client.post("/api/auth/login", json=account).json()["token"]
    headers = {"Authorization": "Bearer " + first}
    assert client.get("/api/workspace", headers=headers).status_code == 403
    response = client.post(
        "/api/auth/password",
        headers=headers,
        json={
            "current_password": account["password"],
            "new_password": "Personal-Test-Password-84!",
        },
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["account"]["must_change_password"] is False
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert (
        client.get("/api/auth/me", headers={"Authorization": "Bearer " + other}).status_code == 401
    )
    assert (
        client.get(
            "/api/workspace", headers={"Authorization": "Bearer " + changed["token"]}
        ).json()["account"]["username"]
        == account["username"]
    )
    assert client.post("/api/auth/login", json=account).status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"username": account["username"], "password": "Personal-Test-Password-84!"},
        ).status_code
        == 200
    )


def test_logout_revokes_the_session_on_the_server(
    client: TestClient, account: dict[str, str]
) -> None:
    token = client.post("/api/auth/login", json=account).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.delete("/api/auth/session", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_session_has_no_idle_timeout_but_expires_at_exactly_24_hours(
    client: TestClient, account: dict[str, str], clock: ControlledClock
) -> None:
    token = client.post("/api/auth/login", json=account).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    clock.value += timedelta(hours=23, minutes=59, seconds=59)
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    clock.value += timedelta(seconds=1)
    assert client.get("/api/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize(
    "username,password", [("unknown_account", "Wrong-Password-42!"), (None, "Wrong-Password-42!")]
)
def test_wrong_password_and_unknown_account_have_the_same_public_error(
    client: TestClient, account: dict[str, str], username: str | None, password: str
) -> None:
    response = client.post(
        "/api/auth/login", json={"username": username or account["username"], "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}


@pytest.mark.parametrize("new_password", ["short", "x" * 129, "Initial-Test-Password-42!"])
def test_invalid_password_changes_keep_existing_credentials_usable_and_never_echo_secrets(
    client: TestClient, account: dict[str, str], new_password: str
) -> None:
    token = client.post("/api/auth/login", json=account).json()["token"]
    response = client.post(
        "/api/auth/password",
        headers={"Authorization": "Bearer " + token},
        json={"current_password": account["password"], "new_password": new_password},
    )
    assert response.status_code == 422
    assert new_password not in response.text
    assert account["password"] not in response.text
    assert client.post("/api/auth/login", json=account).status_code == 200


def test_password_change_requires_current_password(
    client: TestClient, account: dict[str, str]
) -> None:
    token = client.post("/api/auth/login", json=account).json()["token"]
    response = client.post(
        "/api/auth/password",
        headers={"Authorization": "Bearer " + token},
        json={
            "current_password": "Wrong-Password-42!",
            "new_password": "Personal-Test-Password-84!",
        },
    )
    assert response.status_code == 401
    assert client.post("/api/auth/login", json=account).status_code == 200


def test_account_and_session_survive_server_recreation(
    client: TestClient, account: dict[str, str], database_url: str, clock: ControlledClock
) -> None:
    token = client.post("/api/auth/login", json=account).json()["token"]
    with TestClient(create_app(database_url, now=clock)) as restarted:
        result = restarted.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
        assert result.json()["username"] == account["username"]


def test_anonymous_calls_cannot_read_account_or_workspace(client: TestClient) -> None:
    for path in ("/api/auth/me", "/api/workspace"):
        assert client.get(path).status_code == 401


def test_bootstrap_cannot_overwrite_an_existing_account(
    client: TestClient, account: dict[str, str], database_url: str
) -> None:
    with pytest.raises(ValueError, match="already exists"):
        bootstrap_account(
            database_url, account["username"], "Replacement", "Replacement-Password-24!"
        )
    assert client.post("/api/auth/login", json=account).status_code == 200


def test_health_exposes_server_time_and_database_availability(client: TestClient) -> None:
    result = client.get("/api/health")
    assert result.status_code == 200
    assert result.json() == {"status": "ok", "server_time": "2026-10-22T06:00:00Z"}


def test_database_outage_returns_a_safe_service_error() -> None:
    url = (
        "mysql+pymysql://fixture:Never-Expose-This@127.0.0.1:65531/election_test?connect_timeout=1"
    )
    with pytest.raises(RuntimeError, match="database_unavailable") as failed:
        with TestClient(create_app(url), base_url="https://testserver"):
            pytest.fail("An unavailable database must prevent API startup")
    assert "Never-Expose-This" not in str(failed.value)
