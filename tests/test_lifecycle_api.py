"""Election lifecycle checks use an isolated MySQL database and public API actions."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.db import make_engine
from tests.configuration_support import create_constituency, create_election
from tests.lifecycle_support import (
    complete_configuration,
    lifecycle_database_url,
    lifecycle_test_state,
    prepared_election,
    schedule_payload,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_admin_saves_schedule_and_activates_one_persisted_election(
    admin: TestClient, database_url: str
) -> None:
    assert admin.get("/api/active-election").json() == {"election": None}
    election = create_election(admin)
    path = f"/api/elections/{election['id']}"
    missing = admin.get(path + "/schedule")
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "schedule_not_configured"}}
    saved = admin.put(path + "/schedule", json=schedule_payload())
    assert saved.status_code == 200
    schedule = saved.json()
    assert schedule["election_id"] == election["id"]
    assert schedule["election_date"] == "2026-11-15"
    assert schedule["reporting_interval_minutes"] == 60
    assert schedule["revision"] == 1
    assert datetime.fromisoformat(schedule["planned_opening_at"]) == datetime(
        2026, 11, 14, 23, 30, tzinfo=UTC
    )
    assert datetime.fromisoformat(schedule["planned_closing_at"]) == datetime(
        2026, 11, 15, 14, 30, tzinfo=UTC
    )
    assert admin.get(path + "/schedule").json() == schedule
    complete_configuration(admin, election["id"])
    changed = admin.put(
        path + "/schedule", json=schedule_payload(revision=1, reporting_interval_minutes=30)
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    activated = admin.post(
        path + "/activate", json={"election_revision": 1, "schedule_revision": 2}
    )
    assert activated.status_code == 200
    current = activated.json()
    assert current["election"]["id"] == election["id"]
    assert current["election"]["status"] == "active"
    assert current["election"]["revision"] == 2
    assert current["election"]["schedule"] == changed.json()
    assert admin.get("/api/active-election").json() == current
    with TestClient(create_app(database_url)) as restarted:
        restarted.headers.update(admin.headers)
        assert restarted.get("/api/active-election").json() == current
        assert restarted.get(path + "/schedule").json() == changed.json()


def test_concurrent_retries_activate_the_same_election_once_and_return_the_same_resource(
    admin: TestClient, database_url: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    election, planned = prepared_election(admin)
    start = Barrier(2)

    def activate(_: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.post(
                f"/api/elections/{election['id']}/activate",
                json={
                    "election_revision": election["revision"],
                    "schedule_revision": planned["revision"],
                },
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(activate, (1, 2)))
    assert [status for status, _ in outcomes] == [200, 200]
    assert outcomes[0][1] == outcomes[1][1]
    assert outcomes[0][1]["election"]["status"] == "active"
    assert outcomes[0][1]["election"]["revision"] == 2
    assert admin.get("/api/active-election").json() == outcomes[0][1]


def test_competing_clients_cannot_activate_different_elections(
    admin: TestClient, database_url: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    elections = [prepared_election(admin), prepared_election(admin)]
    start = Barrier(2)

    def activate(item: tuple[dict, dict]) -> tuple[int, int, dict]:
        election, planned = item
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.post(
                f"/api/elections/{election['id']}/activate",
                json={"election_revision": 1, "schedule_revision": planned["revision"]},
            )
            return election["id"], response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(activate, elections))
    assert sorted(status for _, status, _ in outcomes) == [200, 409]
    winner = next(body for _, status, body in outcomes if status == 200)
    loser_id, _, conflict = next(outcome for outcome in outcomes if outcome[1] == 409)
    assert conflict == {"detail": {"code": "active_election_conflict"}}
    assert admin.get("/api/active-election").json() == winner
    assert admin.get(f"/api/elections/{loser_id}").json()["status"] == "draft"
    assert len(admin.get(f"/api/elections/{loser_id}/constituencies").json()["items"]) == 2
    assert any(row["id"] == loser_id for row in admin.get("/api/elections").json()["items"])


@pytest.mark.parametrize(
    "changes",
    [
        {"planned_opening_at": "2026-11-15T07:30:00"},
        {"planned_closing_at": "2026-11-15T22:30:00"},
        {"election_date": "2026-11-14"},
        {"planned_closing_at": "2026-11-15T07:30:00+08:00"},
        {"planned_closing_at": "2026-11-15T07:29:59+08:00"},
        {"reporting_interval_minutes": 0},
        {"reporting_interval_minutes": 1441},
        {"reporting_interval_minutes": True},
        {"reporting_interval_minutes": "60"},
    ],
)
def test_invalid_schedules_never_replace_the_saved_schedule(
    admin: TestClient, changes: dict
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/schedule"
    original = admin.put(path, json=schedule_payload())
    assert original.status_code == 200
    rejected = admin.put(path, json=schedule_payload(revision=1, **changes))
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "validation_error"
    assert admin.get(path).json() == original.json()


@pytest.mark.parametrize("existing", [False, True])
def test_overlapping_schedule_saves_only_accept_one_expected_revision(
    admin: TestClient, database_url: str, existing: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    election = create_election(admin)
    path = f"/api/elections/{election['id']}/schedule"
    revision = 0
    if existing:
        first = admin.put(path, json=schedule_payload())
        assert first.status_code == 200
        revision = 1
    start = Barrier(2)

    def save(interval: int) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            start.wait(timeout=5)
            response = client.put(
                path, json=schedule_payload(revision=revision, reporting_interval_minutes=interval)
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, (30, 60)))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    assert next(body for status, body in outcomes if status == 409) == {
        "detail": {"code": "revision_conflict"}
    }
    assert winner["revision"] == revision + 1
    assert admin.get(path).json() == winner


def test_activation_requires_schedule_and_complete_configuration_for_every_scope(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    base = f"/api/elections/{election['id']}"

    def attempt(code: str) -> None:
        response = admin.post(
            base + "/activate", json={"election_revision": 1, "schedule_revision": 1}
        )
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": code}}
        assert admin.get(base).json()["status"] == "draft"
        assert admin.get("/api/active-election").json() == {"election": None}

    attempt("schedule_required")
    assert admin.put(base + "/schedule", json=schedule_payload()).status_code == 200
    attempt("election_configuration_incomplete")
    north = create_constituency(admin, election["id"], "N")
    attempt("election_configuration_incomplete")

    def candidate_and_station(constituency_id: int) -> str:
        path = f"{base}/constituencies/{constituency_id}"
        assert (
            admin.post(
                path + "/candidates",
                json={"name": "候選人", "ballot_number": 1, "request_id": str(uuid4())},
            ).status_code
            == 201
        )
        attempt("election_configuration_incomplete")
        station = admin.post(
            path + "/stations", json={"name": "票站", "code": "P1", "request_id": str(uuid4())}
        )
        assert station.status_code == 201
        attempt("election_configuration_incomplete")
        return f"{path}/stations/{station.json()['id']}"

    def counter(station_path: str) -> None:
        assert (
            admin.post(
                station_path + "/counters",
                json={"name": "發票櫃台", "code": "C1", "request_id": str(uuid4())},
            ).status_code
            == 201
        )

    north_station = candidate_and_station(north["id"])
    counter(north_station)
    south = create_constituency(admin, election["id"], "S")
    attempt("election_configuration_incomplete")
    south_station = candidate_and_station(south["id"])
    counter(south_station)
    extra_station = admin.post(
        f"{base}/constituencies/{north['id']}/stations",
        json={"name": "另一票站", "code": "P2", "request_id": str(uuid4())},
    )
    assert extra_station.status_code == 201
    attempt("election_configuration_incomplete")
    counter(f"{base}/constituencies/{north['id']}/stations/{extra_station.json()['id']}")
    assert (
        admin.post(
            base + "/activate", json={"election_revision": 1, "schedule_revision": 1}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("changed", ["election", "schedule"])
def test_activation_rejects_stale_configuration_revisions_until_reviewed(
    admin: TestClient, changed: str
) -> None:
    election, planned = prepared_election(admin)
    path = f"/api/elections/{election['id']}"
    election_revision, schedule_revision = election["revision"], planned["revision"]
    if changed == "election":
        saved = admin.put(path, json={"name": "更新後的選舉", "revision": election_revision})
        assert saved.status_code == 200
        election_revision = saved.json()["revision"]
    else:
        saved = admin.put(path + "/schedule", json=schedule_payload(revision=schedule_revision))
        assert saved.status_code == 200
        schedule_revision = saved.json()["revision"]
    stale = admin.post(path + "/activate", json={"election_revision": 1, "schedule_revision": 1})
    assert stale.status_code == 409
    assert stale.json() == {"detail": {"code": "revision_conflict"}}
    assert admin.get("/api/active-election").json() == {"election": None}
    assert admin.get(path).json()["status"] == "draft"
    activated = admin.post(
        path + "/activate",
        json={"election_revision": election_revision, "schedule_revision": schedule_revision},
    )
    assert activated.status_code == 200
    retried = admin.post(path + "/activate", json={"election_revision": 1, "schedule_revision": 1})
    assert retried.status_code == 200
    assert retried.json() == activated.json()


def test_active_schedule_and_configuration_cannot_be_silently_replaced(admin: TestClient) -> None:
    election, planned = prepared_election(admin)
    path = f"/api/elections/{election['id']}"
    activated = admin.post(
        path + "/activate", json={"election_revision": 1, "schedule_revision": 1}
    )
    assert activated.status_code == 200
    constituency = admin.get(path + "/constituencies").json()["items"][0]
    constituency_path = f"{path}/constituencies/{constituency['id']}"
    candidate = admin.get(constituency_path + "/candidates").json()["items"][0]
    station = admin.get(constituency_path + "/stations").json()["items"][0]
    station_path = f"{constituency_path}/stations/{station['id']}"
    counter = admin.get(station_path + "/counters").json()["items"][0]
    saved_paths = [
        path,
        path + "/schedule",
        path + "/constituencies",
        constituency_path,
        constituency_path + "/candidates",
        constituency_path + "/stations",
        f"{constituency_path}/candidates/{candidate['id']}",
        station_path,
        station_path + "/counters",
        f"{station_path}/counters/{counter['id']}",
    ]
    before = {saved_path: admin.get(saved_path).json() for saved_path in saved_paths}
    changes = [
        ("PUT", path, {"name": "Replace active", "revision": 2}),
        (
            "PUT",
            path + "/schedule",
            schedule_payload(revision=planned["revision"], reporting_interval_minutes=30),
        ),
        (
            "POST",
            path + "/constituencies",
            {"name": "Replace active", "code": "X", "request_id": str(uuid4())},
        ),
        ("PUT", constituency_path, {"name": "Replace active", "code": "X", "revision": 1}),
        (
            "POST",
            constituency_path + "/candidates",
            {"name": "Replace active", "ballot_number": 2, "request_id": str(uuid4())},
        ),
        (
            "PUT",
            f"{constituency_path}/candidates/{candidate['id']}",
            {"name": "Replace active", "ballot_number": 1, "revision": 1},
        ),
        (
            "POST",
            constituency_path + "/stations",
            {"name": "Replace active", "code": "P2", "request_id": str(uuid4())},
        ),
        ("PUT", station_path, {"name": "Replace active", "code": "P1", "revision": 1}),
        (
            "POST",
            station_path + "/counters",
            {"name": "Replace active", "code": "C2", "request_id": str(uuid4())},
        ),
        (
            "PUT",
            f"{station_path}/counters/{counter['id']}",
            {"name": "Replace active", "code": "C1", "revision": 1},
        ),
    ]
    for method, changed_path, payload in changes:
        rejected = admin.request(method, changed_path, json=payload)
        assert rejected.status_code == 409, (method, changed_path)
        assert rejected.json() == {"detail": {"code": "draft_required"}}
    assert {saved_path: admin.get(saved_path).json() for saved_path in saved_paths} == before
    assert admin.get("/api/active-election").json() == activated.json()
    another = create_election(admin)
    assert (
        admin.put(
            f"/api/elections/{another['id']}", json={"name": "另一草稿仍可修改", "revision": 1}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_ready_staff_can_view_active_context_but_cannot_configure_or_activate(
    admin: TestClient, database_url: str, role: str
) -> None:
    from sqlalchemy import select

    from election.manage import bootstrap_account
    from election.server.models import Account

    election, _ = prepared_election(admin)
    path = f"/api/elections/{election['id']}"
    active = admin.post(path + "/activate", json={"election_revision": 1, "schedule_revision": 1})
    assert active.status_code == 200
    username, password = "lifecycle_" + uuid4().hex[:12], "Lifecycle-Initial-42!"
    bootstrap_account(database_url, username, "生命週期權限測試", password)
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            account = db.scalar(select(Account).where(Account.username == username))
            assert account is not None
            account.role = role
            db.commit()
    finally:
        engine.dispose()
    with TestClient(create_app(database_url)) as staff:
        login = staff.post("/api/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200
        staff.headers["Authorization"] = "Bearer " + login.json()["token"]
        ready = staff.post(
            "/api/auth/password",
            json={"current_password": password, "new_password": "Lifecycle-Ready-84!"},
        )
        assert ready.status_code == 200
        staff.headers["Authorization"] = "Bearer " + ready.json()["token"]
        current = staff.get("/api/active-election")
        assert current.status_code == 200
        assert current.json() == active.json()
        assert "password" not in current.text
        assert "token" not in current.text
        for response in (
            staff.get(path + "/schedule"),
            staff.put(path + "/schedule", json=schedule_payload(revision=1)),
            staff.post(path + "/activate", json={"election_revision": 2, "schedule_revision": 1}),
        ):
            assert response.status_code == 403
            assert response.json() == {"detail": {"code": "administrator_required"}}


@pytest.mark.parametrize("temporary", [False, True])
def test_anonymous_and_temporary_password_sessions_cannot_access_lifecycle_routes(
    admin: TestClient, database_url: str, temporary: bool
) -> None:
    from election.manage import bootstrap_account

    election = create_election(admin)
    path = f"/api/elections/{election['id']}"
    with TestClient(create_app(database_url)) as restricted:
        if temporary:
            username, password = "lifecycle_temp_" + uuid4().hex[:12], "Lifecycle-Temporary-42!"
            bootstrap_account(database_url, username, "臨時密碼測試", password)
            login = restricted.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200
            restricted.headers["Authorization"] = "Bearer " + login.json()["token"]
        for response in (
            restricted.get("/api/active-election"),
            restricted.get(path + "/schedule"),
            restricted.put(path + "/schedule", json=schedule_payload()),
            restricted.post(
                path + "/activate", json={"election_revision": 1, "schedule_revision": 1}
            ),
        ):
            assert response.status_code == (403 if temporary else 401)
            assert response.json() == {
                "detail": {"code": "password_change_required" if temporary else "session_expired"}
            }


def test_planned_time_passage_does_not_implicitly_activate_or_close_an_election(
    admin: TestClient, database_url: str
) -> None:
    clock = [datetime(2026, 11, 14, 20, tzinfo=UTC)]
    username = admin.get("/api/auth/me").json()["username"]
    with TestClient(create_app(database_url, now=lambda: clock[0])) as client:
        login = client.post(
            "/api/auth/login", json={"username": username, "password": "Configuration-Ready-84!"}
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        election, _ = prepared_election(client)
        path = f"/api/elections/{election['id']}"
        clock[0] = datetime(2026, 11, 15, 16, tzinfo=UTC)
        assert client.get(path).json()["status"] == "draft"
        assert client.get("/api/active-election").json() == {"election": None}
        active = client.post(
            path + "/activate", json={"election_revision": 1, "schedule_revision": 1}
        )
        assert active.status_code == 200
        clock[0] = datetime(2026, 11, 15, 18, tzinfo=UTC)
        assert client.get(path).json()["status"] == "active"
        assert client.get("/api/active-election").json() == active.json()


def test_active_election_filters_operational_assignments_without_deleting_draft_station_options(
    admin: TestClient, database_url: str
) -> None:
    first, first_schedule = prepared_election(admin)
    second, _ = prepared_election(admin)
    station_ids: dict[int, list[int]] = {}
    for election in (first, second):
        station_ids[election["id"]] = []
        constituencies = admin.get(f"/api/elections/{election['id']}/constituencies").json()[
            "items"
        ]
        for constituency in constituencies:
            path = f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations"
            station_ids[election["id"]].extend(row["id"] for row in admin.get(path).json()["items"])
    assigned = station_ids[first["id"]] + station_ids[second["id"]]
    username = "lifecycle_assigned_" + uuid4().hex[:12]
    initial_password = "Lifecycle-Assigned-Initial-42!"
    created = admin.post(
        "/api/accounts",
        json={
            "username": username,
            "display_name": "跨草稿選舉指派的投票站職員",
            "role": "polling_officer",
            "enabled": True,
            "temporary_password": initial_password,
            "station_ids": assigned,
        },
    )
    assert created.status_code == 201
    with TestClient(create_app(database_url)) as officer:
        login = officer.post(
            "/api/auth/login", json={"username": username, "password": initial_password}
        )
        assert login.status_code == 200
        officer.headers["Authorization"] = "Bearer " + login.json()["token"]
        ready = officer.post(
            "/api/auth/password",
            json={
                "current_password": initial_password,
                "new_password": "Lifecycle-Assigned-Ready-84!",
            },
        )
        assert ready.status_code == 200
        officer.headers["Authorization"] = "Bearer " + ready.json()["token"]
        before = officer.get("/api/workspace/stations")
        assert before.status_code == 200
        assert {item["station"]["id"] for item in before.json()["items"]} == set(assigned)
        active = admin.post(
            f"/api/elections/{first['id']}/activate",
            json={
                "election_revision": first["revision"],
                "schedule_revision": first_schedule["revision"],
            },
        )
        assert active.status_code == 200
        after = officer.get("/api/workspace/stations")
        assert after.status_code == 200
        assert {item["station"]["id"] for item in after.json()["items"]} == set(
            station_ids[first["id"]]
        )
        assert all(item["election"]["id"] == first["id"] for item in after.json()["items"])
        wrong_election = officer.get(f"/api/workspace/stations/{station_ids[second['id']][0]}")
        assert wrong_election.status_code == 409
        assert wrong_election.json() == {"detail": {"code": "wrong_active_election"}}
    options = admin.get("/api/accounts/station-options")
    assert options.status_code == 200
    assert set(assigned).issubset(item["station"]["id"] for item in options.json()["items"])
    assert {first["id"], second["id"]}.issubset(
        item["election"]["id"] for item in options.json()["items"]
    )
    saved_account = admin.get(f"/api/accounts/{created.json()['id']}")
    assert set(saved_account.json()["station_ids"]) == set(assigned)
    assert admin.get(f"/api/elections/{first['id']}").json()["status"] == "active"
    assert admin.get(f"/api/elections/{second['id']}").json()["status"] == "draft"
    for election in (first, second):
        assert (
            len(admin.get(f"/api/elections/{election['id']}/constituencies").json()["items"]) == 2
        )
