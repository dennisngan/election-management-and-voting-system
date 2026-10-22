"""Staff account management and assigned-station access through the public API."""

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.configuration_support import create_constituency, create_election


def test_administrator_manages_officer_access_first_password_reset_and_disabling(
    admin: TestClient, database_url: str
) -> None:
    election = create_election(admin)
    constituency = create_constituency(admin, election["id"])
    stations_path = f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations"
    stations = []
    for code in ("ASSIGNED", "UNASSIGNED"):
        response = admin.post(
            stations_path,
            json={
                "name": "權限測試投票站 " + code,
                "code": code,
                "counting_mode": "local",
                "destination_station_id": None,
                "request_id": str(uuid4()),
            },
        )
        assert response.status_code == 201
        stations.append(response.json())
    assigned, unassigned = stations
    username = "staff_" + uuid4().hex[:12]
    account_payload = {
        "username": username,
        "display_name": "  票站職員測試  ",
        "role": "polling_officer",
        "temporary_password": "Staff-Initial-Test-42!",
        "station_ids": [assigned["id"]],
        "enabled": True,
    }
    created = admin.post("/api/accounts", json=account_payload)
    assert created.status_code == 201
    account = created.json()
    safe_fields = {
        "id",
        "username",
        "display_name",
        "role",
        "must_change_password",
        "enabled",
        "revision",
        "station_ids",
    }
    assert set(account) == safe_fields
    assert account["username"] == username
    assert account["display_name"] == account_payload["display_name"]
    assert account["role"] == "polling_officer"
    assert account["must_change_password"] is True
    assert account["enabled"] is True
    assert account["revision"] == 1
    assert account["station_ids"] == [assigned["id"]]
    account_path = f"/api/accounts/{account['id']}"
    assert admin.get(account_path).json() == account
    duplicate = admin.post("/api/accounts", json=account_payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": {"code": "username_exists"}}
    assert admin.get(account_path).json() == account
    admin_operational = admin.get(f"/api/workspace/stations/{assigned['id']}")
    assert admin_operational.status_code == 403
    assert admin_operational.json() == {"detail": {"code": "operational_role_required"}}

    with TestClient(create_app(database_url)) as officer:
        login = officer.post(
            "/api/auth/login",
            json={"username": username, "password": account_payload["temporary_password"]},
        )
        assert login.status_code == 200
        assert login.json()["account"]["must_change_password"] is True
        officer.headers["Authorization"] = "Bearer " + login.json()["token"]
        blocked = officer.get("/api/workspace/stations")
        assert blocked.status_code == 403
        assert blocked.json() == {"detail": {"code": "password_change_required"}}
        changed = officer.post(
            "/api/auth/password",
            json={
                "current_password": account_payload["temporary_password"],
                "new_password": "Staff-Ready-Test-84!",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["account"]["must_change_password"] is False
        officer.headers["Authorization"] = "Bearer " + changed.json()["token"]
        listed = officer.get("/api/workspace/stations")
        assert listed.status_code == 200
        contexts = listed.json()["items"]
        assert len(contexts) == 1
        context = contexts[0]
        assert set(context) == {"election", "constituency", "station", "account", "capabilities"}
        assert context["election"] == {
            "id": election["id"],
            "name": election["name"],
            "status": election["status"],
        }
        assert context["constituency"] == {
            "id": constituency["id"],
            "name": constituency["name"],
            "code": constituency["code"],
        }
        assert context["station"] == {
            key: assigned[key]
            for key in ("id", "name", "code", "counting_mode", "destination_station_id")
        }
        assert set(context["account"]) == safe_fields
        assert context["account"]["id"] == account["id"]
        assert context["account"]["must_change_password"] is False
        assert context["capabilities"] == {
            "prepare_polling": True,
            "prepare_counting": False,
            "approve": False,
        }
        assert officer.get(f"/api/workspace/stations/{assigned['id']}").json() == context
        forbidden = officer.get(f"/api/workspace/stations/{unassigned['id']}")
        assert forbidden.status_code == 403
        assert forbidden.json() == {"detail": {"code": "station_access_denied"}}

        current = admin.get(account_path).json()
        reset = admin.post(
            account_path + "/password-reset",
            json={"temporary_password": "Staff-Reset-Test-126!", "revision": current["revision"]},
        )
        assert reset.status_code == 200
        assert set(reset.json()) == safe_fields
        assert reset.json()["revision"] == current["revision"] + 1
        assert reset.json()["must_change_password"] is True
        assert reset.json()["station_ids"] == [assigned["id"]]
        revoked = officer.get("/api/auth/me")
        assert revoked.status_code == 401
        assert revoked.json() == {"detail": {"code": "session_expired"}}

        reset_login = officer.post(
            "/api/auth/login", json={"username": username, "password": "Staff-Reset-Test-126!"}
        )
        assert reset_login.status_code == 200
        assert reset_login.json()["account"]["must_change_password"] is True
        officer.headers["Authorization"] = "Bearer " + reset_login.json()["token"]
        assert officer.get("/api/workspace/stations").status_code == 403
        reset_changed = officer.post(
            "/api/auth/password",
            json={
                "current_password": "Staff-Reset-Test-126!",
                "new_password": "Staff-Reset-Ready-Test-168!",
            },
        )
        assert reset_changed.status_code == 200
        officer.headers["Authorization"] = "Bearer " + reset_changed.json()["token"]
        assert officer.get(f"/api/workspace/stations/{assigned['id']}").status_code == 200
        current = admin.get(account_path).json()
        disabled = admin.put(
            account_path,
            json={
                "display_name": "停用測試職員",
                "role": current["role"],
                "enabled": False,
                "station_ids": current["station_ids"],
                "revision": current["revision"],
            },
        )
        assert disabled.status_code == 200
        assert set(disabled.json()) == safe_fields
        assert disabled.json()["enabled"] is False
        assert disabled.json()["revision"] == current["revision"] + 1
        assert admin.get(account_path).json() == disabled.json()
        revoked = officer.get(f"/api/workspace/stations/{assigned['id']}")
        assert revoked.status_code == 401
        assert revoked.json() == {"detail": {"code": "session_expired"}}


def test_administrator_reads_staff_audit_without_passwords_hashes_or_session_secrets(
    admin: TestClient,
) -> None:
    initial_password = "Audit-Initial-Synthetic-42!"
    reset_password = "Audit-Reset-Synthetic-84!"
    created = admin.post(
        "/api/accounts",
        json={
            "username": "audit_staff_" + uuid4().hex[:12],
            "display_name": "審計測試職員",
            "role": "polling_officer",
            "temporary_password": initial_password,
            "station_ids": [],
            "enabled": True,
        },
    )
    assert created.status_code == 201
    account_path = f"/api/accounts/{created.json()['id']}"
    updated = admin.put(
        account_path,
        json={
            "display_name": "修訂審計測試職員",
            "role": "counting_officer",
            "station_ids": [],
            "enabled": True,
            "revision": created.json()["revision"],
        },
    )
    assert updated.status_code == 200
    reset = admin.post(
        account_path + "/password-reset",
        json={"temporary_password": reset_password, "revision": updated.json()["revision"]},
    )
    assert reset.status_code == 200
    response = admin.get(account_path + "/audit")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items"}
    events = body["items"]
    assert [event["action"] for event in events] == [
        "staff_created",
        "staff_updated",
        "staff_password_reset",
    ]
    actor_id = admin.get("/api/auth/me").json()["id"]
    for index, event in enumerate(events, start=1):
        assert set(event) == {"id", "actor_id", "action", "occurred_at", "details"}
        assert event["actor_id"] == actor_id
        occurred_at = datetime.fromisoformat(event["occurred_at"])
        assert occurred_at.tzinfo is not None
        assert occurred_at.utcoffset() == UTC.utcoffset(occurred_at)
        assert event["details"]["account_id"] == created.json()["id"]
        assert event["details"]["revision"] == index
    assert events[0]["details"]["before"] == {}
    assert events[0]["details"]["after"] == created.json()
    assert events[1]["details"]["before"] == created.json()
    assert events[1]["details"]["after"] == updated.json()
    assert events[2]["details"]["before"] == updated.json()
    assert events[2]["details"]["after"] == reset.json()
    serialized = json.dumps(body)
    for secret in (initial_password, reset_password, admin.headers["Authorization"].split()[1]):
        assert secret not in serialized
    for field in (
        "temporary_password",
        "current_password",
        "new_password",
        "password_hash",
        "token_hash",
        '"token"',
        "$argon2",
    ):
        assert field not in serialized


STAFF_INITIAL_PASSWORD = "Staff-Edge-Initial-42!"
STAFF_READY_PASSWORD = "Staff-Edge-Ready-84!"


@pytest.fixture
def staff_stations(admin: TestClient) -> list[dict]:
    election = create_election(admin)
    constituency = create_constituency(admin, election["id"])
    path = f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations"
    rows = []
    for code in ("ALLOWED", "OTHER"):
        created = admin.post(
            path,
            json={"name": "職員測試票站 " + code, "code": code, "request_id": str(uuid4())},
        )
        assert created.status_code == 201
        rows.append(created.json())
    return rows


def new_staff(
    admin: TestClient,
    *,
    role: str = "polling_officer",
    station_ids: list[int] | None = None,
    enabled: bool = True,
) -> dict:
    created = admin.post(
        "/api/accounts",
        json={
            "username": "edge_staff_" + uuid4().hex[:12],
            "display_name": "職員權限測試",
            "role": role,
            "station_ids": station_ids or [],
            "enabled": enabled,
            "temporary_password": STAFF_INITIAL_PASSWORD,
        },
    )
    assert created.status_code == 201
    return created.json()


def sign_in_staff(client: TestClient, account: dict, *, first_change: bool = True) -> None:
    login = client.post(
        "/api/auth/login",
        json={"username": account["username"], "password": STAFF_INITIAL_PASSWORD},
    )
    assert login.status_code == 200
    client.headers["Authorization"] = "Bearer " + login.json()["token"]
    if first_change:
        changed = client.post(
            "/api/auth/password",
            json={"current_password": STAFF_INITIAL_PASSWORD, "new_password": STAFF_READY_PASSWORD},
        )
        assert changed.status_code == 200
        client.headers["Authorization"] = "Bearer " + changed.json()["token"]


def staff_settings(account: dict, **changes: object) -> dict:
    return {
        key: changes.get(key, account[key])
        for key in ("display_name", "role", "enabled", "station_ids", "revision")
    }


def account_calls(account: dict) -> list[tuple[str, str, dict | None]]:
    path = f"/api/accounts/{account['id']}"
    return [
        ("GET", "/api/accounts", None),
        ("GET", "/api/accounts/station-options", None),
        (
            "POST",
            "/api/accounts",
            {
                "username": "denied_" + uuid4().hex[:12],
                "display_name": "Denied",
                "role": "polling_officer",
                "station_ids": [],
                "enabled": True,
                "temporary_password": STAFF_INITIAL_PASSWORD,
            },
        ),
        ("GET", path, None),
        ("PUT", path, staff_settings(account, display_name="Denied")),
        (
            "POST",
            path + "/password-reset",
            {"temporary_password": "Denied-Reset-Password-42!", "revision": account["revision"]},
        ),
        ("GET", path + "/audit", None),
    ]


@pytest.mark.parametrize(
    "access", ["anonymous", "temporary", "polling_officer", "counting_officer", "supervisor"]
)
def test_account_routes_require_a_ready_administrator(
    admin: TestClient, database_url: str, access: str
) -> None:
    target = new_staff(admin)
    with TestClient(create_app(database_url)) as restricted:
        if access != "anonymous":
            account = new_staff(admin, role="polling_officer" if access == "temporary" else access)
            sign_in_staff(restricted, account, first_change=access != "temporary")
        expected_status = 401 if access == "anonymous" else 403
        expected_code = (
            "session_expired"
            if access == "anonymous"
            else "password_change_required"
            if access == "temporary"
            else "administrator_required"
        )
        for method, path, payload in account_calls(target):
            denied = restricted.request(method, path, json=payload)
            assert denied.status_code == expected_status, (method, path)
            assert denied.json() == {"detail": {"code": expected_code}}
    assert admin.get(f"/api/accounts/{target['id']}").json() == target
    events = admin.get(f"/api/accounts/{target['id']}/audit").json()["items"]
    assert [event["action"] for event in events] == ["staff_created"]


@pytest.mark.parametrize(
    ("role", "capabilities"),
    [
        ("polling_officer", {"prepare_polling": True, "prepare_counting": False, "approve": False}),
        (
            "counting_officer",
            {"prepare_polling": False, "prepare_counting": True, "approve": False},
        ),
        ("supervisor", {"prepare_polling": False, "prepare_counting": False, "approve": True}),
    ],
)
def test_operational_roles_receive_only_assigned_context_and_their_capabilities(
    admin: TestClient, database_url: str, staff_stations: list[dict], role: str, capabilities: dict
) -> None:
    assigned, forbidden_station = staff_stations
    account = new_staff(admin, role=role, station_ids=[assigned["id"]])
    with TestClient(create_app(database_url)) as staff:
        sign_in_staff(staff, account)
        listed = staff.get("/api/workspace/stations")
        assert listed.status_code == 200
        contexts = listed.json()["items"]
        assert len(contexts) == 1
        assert contexts[0]["station"]["id"] == assigned["id"]
        assert contexts[0]["account"]["role"] == role
        assert contexts[0]["capabilities"] == capabilities
        assert staff.get(f"/api/workspace/stations/{assigned['id']}").json() == contexts[0]
        for station_id in (forbidden_station["id"], 2147483647):
            denied = staff.get(f"/api/workspace/stations/{station_id}")
            assert denied.status_code == 403
            assert denied.json() == {"detail": {"code": "station_access_denied"}}


@pytest.mark.parametrize("change", ["role", "assignments"])
def test_role_or_station_assignment_changes_revoke_every_existing_staff_session(
    admin: TestClient, database_url: str, staff_stations: list[dict], change: str
) -> None:
    assigned, other = staff_stations
    account = new_staff(admin, station_ids=[assigned["id"]])
    path = f"/api/accounts/{account['id']}"
    with (
        TestClient(create_app(database_url)) as first,
        TestClient(create_app(database_url)) as second,
    ):
        sign_in_staff(first, account)
        login = second.post(
            "/api/auth/login",
            json={"username": account["username"], "password": STAFF_READY_PASSWORD},
        )
        assert login.status_code == 200
        second.headers["Authorization"] = "Bearer " + login.json()["token"]
        for client in (first, second):
            assert client.get(f"/api/workspace/stations/{assigned['id']}").status_code == 200
        current = admin.get(path).json()
        changes = (
            {"role": "counting_officer"} if change == "role" else {"station_ids": [other["id"]]}
        )
        changed = admin.put(path, json=staff_settings(current, **changes))
        assert changed.status_code == 200
        for client in (first, second):
            for endpoint in ("/api/auth/me", f"/api/workspace/stations/{assigned['id']}"):
                revoked = client.get(endpoint)
                assert revoked.status_code == 401
                assert revoked.json() == {"detail": {"code": "session_expired"}}
        renewed = first.post(
            "/api/auth/login",
            json={"username": account["username"], "password": STAFF_READY_PASSWORD},
        )
        assert renewed.status_code == 200
        first.headers["Authorization"] = "Bearer " + renewed.json()["token"]
        context = first.get("/api/workspace/stations").json()["items"]
        assert len(context) == 1
        assert context[0]["account"]["role"] == changed.json()["role"]
        assert context[0]["station"]["id"] == (assigned["id"] if change == "role" else other["id"])
        assert context[0]["capabilities"]["prepare_counting"] is (change == "role")


@pytest.mark.parametrize("disabled_at_creation", [False, True])
def test_disabled_staff_cannot_sign_in(
    admin: TestClient, database_url: str, disabled_at_creation: bool
) -> None:
    account = new_staff(admin, enabled=not disabled_at_creation)
    if not disabled_at_creation:
        response = admin.put(
            f"/api/accounts/{account['id']}", json=staff_settings(account, enabled=False)
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    with TestClient(create_app(database_url)) as disabled:
        login = disabled.post(
            "/api/auth/login",
            json={"username": account["username"], "password": STAFF_INITIAL_PASSWORD},
        )
        assert login.status_code == 401
        assert login.json() == {"detail": {"code": "invalid_credentials"}}


def test_stale_password_reset_does_not_change_credentials_or_revoke_a_current_session(
    admin: TestClient, database_url: str
) -> None:
    account = new_staff(admin)
    path = f"/api/accounts/{account['id']}"
    with TestClient(create_app(database_url)) as staff:
        sign_in_staff(staff, account)
        stale = admin.get(path).json()
        updated = admin.put(path, json=staff_settings(stale, display_name="新版本職員"))
        assert updated.status_code == 200
        renewed = staff.post(
            "/api/auth/login",
            json={"username": account["username"], "password": STAFF_READY_PASSWORD},
        )
        assert renewed.status_code == 200
        staff.headers["Authorization"] = "Bearer " + renewed.json()["token"]
        reset = admin.post(
            path + "/password-reset",
            json={
                "temporary_password": "Stale-Reset-Should-Not-Work-42!",
                "revision": stale["revision"],
            },
        )
        assert reset.status_code == 409
        assert reset.json() == {"detail": {"code": "revision_conflict"}}
        assert staff.get("/api/auth/me").status_code == 200
        assert admin.get(path).json() == updated.json()
        events = admin.get(path + "/audit").json()["items"]
        assert all(event["action"] != "staff_password_reset" for event in events)


@pytest.mark.parametrize(
    "invalid", ["duplicate", "unknown", "zero", "bool", "string", "float", "admin"]
)
def test_invalid_station_assignments_reject_creation_and_edit_without_mutation(
    admin: TestClient, staff_stations: list[dict], invalid: str
) -> None:
    station_id = staff_stations[0]["id"]
    station_ids = {
        "duplicate": [station_id, station_id],
        "unknown": [2147483647],
        "zero": [0],
        "bool": [True],
        "string": [str(station_id)],
        "float": [float(station_id)],
        "admin": [station_id],
    }[invalid]
    role = "administrator" if invalid == "admin" else "polling_officer"
    username = "invalid_staff_" + uuid4().hex[:12]
    created = admin.post(
        "/api/accounts",
        json={
            "username": username,
            "display_name": "Invalid assignment",
            "role": role,
            "station_ids": station_ids,
            "temporary_password": STAFF_INITIAL_PASSWORD,
        },
    )
    account = new_staff(admin)
    path = f"/api/accounts/{account['id']}"
    edited = admin.put(path, json=staff_settings(account, role=role, station_ids=station_ids))
    expected_code = (
        "invalid_station_assignment" if invalid in ("unknown", "admin") else "validation_error"
    )
    for response in (created, edited):
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == expected_code
    assert admin.get(path).json() == account
    assert all(row["username"] != username for row in admin.get("/api/accounts").json()["items"])


def test_stale_account_edits_preserve_another_clients_saved_settings(
    admin: TestClient, database_url: str
) -> None:
    account = new_staff(admin)
    path = f"/api/accounts/{account['id']}"
    with TestClient(create_app(database_url)) as another:
        another.headers.update(admin.headers)
        stale = another.get(path).json()
        winning = admin.put(path, json=staff_settings(account, display_name="Winning edit"))
        assert winning.status_code == 200
        denied = another.put(path, json=staff_settings(stale, display_name="Stale edit"))
        assert denied.status_code == 409
        assert denied.json() == {"detail": {"code": "revision_conflict"}}
        assert another.get(path).json() == winning.json()


def test_concurrent_account_edits_accept_only_one_same_revision_writer(
    admin: TestClient, database_url: str
) -> None:
    account = new_staff(admin)
    path = f"/api/accounts/{account['id']}"
    start = Barrier(2)

    def submit(name: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.put(path, json=staff_settings(account, display_name=name))
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ("First writer", "Second writer")))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    assert next(body for status, body in outcomes if status == 409) == {
        "detail": {"code": "revision_conflict"}
    }
    assert winner["revision"] == account["revision"] + 1
    assert admin.get(path).json() == winner


def test_concurrent_duplicate_username_creates_one_account_and_never_overwrites_it(
    admin: TestClient, database_url: str
) -> None:
    username = "duplicate_staff_" + uuid4().hex[:12]
    payload = {
        "username": username,
        "display_name": "Original account",
        "role": "polling_officer",
        "station_ids": [],
        "temporary_password": STAFF_INITIAL_PASSWORD,
    }
    start = Barrier(2)

    def submit(_: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.post("/api/accounts", json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (1, 2)))
    assert sorted(status for status, _ in outcomes) == [201, 409]
    winner = next(body for status, body in outcomes if status == 201)
    assert next(body for status, body in outcomes if status == 409) == {
        "detail": {"code": "username_exists"}
    }
    retry = admin.post(
        "/api/accounts",
        json={
            **payload,
            "display_name": "Changed retry",
            "temporary_password": "Changed-Retry-Password-42!",
        },
    )
    assert retry.status_code == 409
    assert retry.json() == {"detail": {"code": "username_exists"}}
    assert [
        row for row in admin.get("/api/accounts").json()["items"] if row["username"] == username
    ] == [winner]
    assert admin.get(f"/api/accounts/{winner['id']}").json() == winner


@pytest.fixture
def isolated_last_administrator(admin: TestClient, database_url: str) -> Iterator[TestClient]:
    from sqlalchemy import select
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from election.server.db import make_engine
    from election.server.models import Account

    parsed = make_url(database_url)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.database and parsed.database.endswith("_test"), "Refusing non-test database"
    own_id = admin.get("/api/auth/me").json()["id"]
    # This fixture is run in a coordinated quiet window against the named synthetic test DB.
    original = {
        row["id"]: {"enabled": row["enabled"], "role": row["role"]}
        for row in admin.get("/api/accounts").json()["items"]
        if row["role"] == "administrator" and row["enabled"]
    }
    assert own_id in original
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            for row in db.scalars(select(Account).where(Account.id.in_(original))):
                if row.id != own_id:
                    row.enabled = False
            db.commit()
        yield admin
    finally:
        # Restore only exact pre-existing accounts, including our own if a regression changed it.
        try:
            with Session(engine) as db:
                for row in db.scalars(select(Account).where(Account.id.in_(original))):
                    row.enabled = original[row.id]["enabled"]
                    row.role = original[row.id]["role"]
                db.commit()
        finally:
            engine.dispose()


def test_last_enabled_administrator_survives_disable_demotion_and_concurrent_self_disables(
    isolated_last_administrator: TestClient, database_url: str
) -> None:
    admin = isolated_last_administrator
    own_id = admin.get("/api/auth/me").json()["id"]
    own_path = f"/api/accounts/{own_id}"
    own = admin.get(own_path).json()
    enabled_admins = [
        row
        for row in admin.get("/api/accounts").json()["items"]
        if row["enabled"] and row["role"] == "administrator"
    ]
    assert enabled_admins == [own]
    for change in ({"enabled": False}, {"role": "polling_officer"}):
        denied = admin.put(own_path, json=staff_settings(own, **change))
        assert denied.status_code == 409
        assert denied.json() == {"detail": {"code": "last_administrator_required"}}
        assert admin.get(own_path).json() == own
    second = new_staff(admin, role="administrator")
    with TestClient(create_app(database_url)) as other:
        sign_in_staff(other, second)
        second = admin.get(f"/api/accounts/{second['id']}").json()
        headers = {own["id"]: dict(admin.headers), second["id"]: dict(other.headers)}
        start = Barrier(2)

        def disable_self(account: dict) -> tuple[int, int, dict]:
            with TestClient(create_app(database_url)) as client:
                client.headers.update(headers[account["id"]])
                start.wait(timeout=5)
                response = client.put(
                    f"/api/accounts/{account['id']}", json=staff_settings(account, enabled=False)
                )
                return account["id"], response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(disable_self, (own, second)))
        assert sorted(status for _, status, _ in outcomes) == [200, 409]
        survivor_id = next(account_id for account_id, status, _ in outcomes if status == 409)
        disabled_id = next(account_id for account_id, status, _ in outcomes if status == 200)
        assert next(body for _, status, body in outcomes if status == 409) == {
            "detail": {"code": "last_administrator_required"}
        }
        with TestClient(create_app(database_url)) as survivor:
            survivor.headers.update(headers[survivor_id])
            assert survivor.get(f"/api/accounts/{survivor_id}").json()["enabled"] is True
            assert survivor.get(f"/api/accounts/{disabled_id}").json()["enabled"] is False
            enabled_admin_ids = {
                row["id"]
                for row in survivor.get("/api/accounts").json()["items"]
                if row["enabled"] and row["role"] == "administrator"
            }
            assert enabled_admin_ids == {survivor_id}
