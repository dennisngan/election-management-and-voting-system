"""Queue observations and confirmations through the real MySQL-backed API."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state, prepared_election
from tests.queue_support import (
    QueueClock,
    active_queue_stations,
    arrange_retained_queue_election,
    observation,
    queue_account,
    queue_client,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_missing_queue_becomes_observed_and_due_at_thirty_minutes(
    admin: TestClient, database_url: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        assert client.get(path.removesuffix("queue") + "polling").json()["items"] == []
        response = client.get(path)
        assert response.status_code == 200
        missing = response.json()
        assert missing["missing"] is True
        assert missing["current"] is None
        assert missing["due_at"] is None
        assert missing["reminder_due"] is False
        assert missing["overdue_periods"] == 0
        assert missing["revision"] == 0
        assert missing["items"] == []

        created = client.post(path, json=observation(clock))
        assert created.status_code == 201
        row = created.json()
        assert set(row) == {
            "id",
            "station_id",
            "revision",
            "kind",
            "band",
            "event_at",
            "entered_at",
            "actor_id",
            "confirmed_event_id",
            "reason",
        }
        assert row["kind"] == "observation"
        assert row["band"] == "under_30"
        assert row["actor_id"] == account["id"]
        assert row["event_at"] == "2026-11-15T00:00:00Z"
        assert row["entered_at"] == "2026-11-15T00:00:00Z"
        assert row["revision"] == 1

        clock.value += timedelta(minutes=29, seconds=59)
        fresh = client.get(path).json()
        assert fresh["missing"] is False
        assert fresh["current"] == row
        assert fresh["due_at"] == "2026-11-15T00:30:00Z"
        assert fresh["reminder_due"] is False
        clock.value += timedelta(seconds=1)
        due = client.get(path).json()
        assert due["reminder_due"] is True
        assert due["overdue_periods"] == 1
        clock.value += timedelta(minutes=30)
        overdue = client.get(path).json()
        assert overdue["overdue_periods"] == 2
        assert overdue["current"]["band"] == "under_30"


@pytest.mark.parametrize(
    "event_at",
    ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"),
)
def test_unrepresentable_event_times_are_validation_errors_without_saved_history(
    admin: TestClient, database_url: str, event_at: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        rejected = client.post(path, json=observation(clock, event_at=event_at))
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] in ("queue_validation", "validation_error")
        assert client.get(path).json()["items"] == []


def test_all_four_bands_and_explicit_unchanged_confirmation_preserve_history(
    admin: TestClient, database_url: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    bands = ["under_30", "30_59", "60_90", "over_90"]
    with queue_client(database_url, account, clock) as client:
        saved = []
        for revision, band in enumerate(bands, start=1):
            response = client.post(
                path, json=observation(clock, expected_revision=revision - 1, band=band)
            )
            assert response.status_code == 201
            saved.append(response.json())
            assert saved[-1]["band"] == band
            assert saved[-1]["confirmed_event_id"] is None
            clock.value += timedelta(minutes=10)
        clock.value += timedelta(minutes=30)
        assert client.get(path).json()["reminder_due"] is True
        unchanged = client.post(
            path + "/confirm",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "current_event_id": saved[-1]["id"],
                "event_at": clock.value.isoformat(),
            },
        )
        assert unchanged.status_code == 201
        confirmation = unchanged.json()
        assert confirmation["kind"] == "unchanged_confirmation"
        assert confirmation["band"] == "over_90"
        assert confirmation["confirmed_event_id"] == saved[-1]["id"]
        assert confirmation["revision"] == 5
        assert confirmation["event_at"] == "2026-11-15T01:10:00Z"
        snapshot = client.get(path).json()
        assert snapshot["items"] == [*saved, confirmation]
        assert snapshot["current"] == confirmation
        assert snapshot["due_at"] == "2026-11-15T01:40:00Z"
        assert snapshot["reminder_due"] is False
        assert snapshot["overdue_periods"] == 0
        assert client.get(path.removesuffix("queue") + "polling").json()["items"] == []
        assert client.put(path, json={}).status_code == 405
        assert client.delete(path).status_code == 405


def test_backdated_observation_does_not_replace_current_or_postpone_its_reminder(
    admin: TestClient, database_url: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        first = client.post(path, json=observation(clock, band="30_59"))
        assert first.status_code == 201
        clock.value += timedelta(minutes=10)
        latest = client.post(path, json=observation(clock, expected_revision=1, band="60_90"))
        assert latest.status_code == 201
        current = latest.json()
        clock.value += timedelta(minutes=30)
        backdated = client.post(
            path,
            json=observation(
                clock,
                expected_revision=2,
                event_at="2026-11-15T00:05:00Z",
                reason="補錄較早的紙本觀察",
            ),
        )
        assert backdated.status_code == 201
        assert backdated.json()["revision"] == 3
        assert backdated.json()["event_at"] == "2026-11-15T00:05:00Z"
        assert backdated.json()["entered_at"] == "2026-11-15T00:40:00Z"
        snapshot = client.get(path).json()
        assert snapshot["revision"] == 3
        assert snapshot["current"] == current
        assert snapshot["due_at"] == "2026-11-15T00:40:00Z"
        assert snapshot["reminder_due"] is True
        assert snapshot["items"] == [first.json(), current, backdated.json()]

        body = {
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "current_event_id": current["id"],
            "event_at": clock.value.isoformat(),
        }
        stale = client.post(path + "/confirm", json=body)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"
        body.update(expected_revision=3, current_event_id=backdated.json()["id"])
        wrong_current = client.post(path + "/confirm", json=body)
        assert wrong_current.status_code == 409
        assert wrong_current.json()["detail"]["code"] == "queue_observation_conflict"
        body.update(current_event_id=current["id"], event_at="2026-11-15T00:09:00Z")
        too_early = client.post(path + "/confirm", json=body)
        assert too_early.status_code == 422
        body["event_at"] = clock.value.isoformat()
        confirmed = client.post(path + "/confirm", json=body)
        assert confirmed.status_code == 201
        assert confirmed.json()["revision"] == 4
        tied = client.post(path, json=observation(clock, expected_revision=4, band="over_90"))
        assert tied.status_code == 201
        final = client.get(path).json()
        assert final["current"] == tied.json()
        assert final["revision"] == 5
        assert final["due_at"] == "2026-11-15T01:10:00Z"
        assert final["reminder_due"] is False


def test_replayed_observation_and_confirmation_return_original_rows_after_later_updates(
    admin: TestClient, database_url: str
) -> None:
    stations = active_queue_stations(admin)
    station_ids = [context["station"]["id"] for context in stations]
    account = queue_account(admin, station_ids)
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_ids[0]}/queue"
    with queue_client(database_url, account, clock) as client:
        body = observation(clock)
        initial = client.post(path, json=body)
        assert initial.status_code == 201
        clock.value += timedelta(minutes=10)
        later = client.post(path, json=observation(clock, expected_revision=1, band="30_59"))
        assert later.status_code == 201
        replay = client.post(path, json=body)
        assert replay.status_code == 200
        assert replay.json() == initial.json()
        utc_equivalent = client.post(path, json={**body, "event_at": "2026-11-15T08:00:00+08:00"})
        assert utc_equivalent.status_code == 200
        assert utc_equivalent.json() == initial.json()
        changed = client.post(path, json={**body, "band": "over_90"})
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "request_conflict"
        wrong_station = client.post(f"/api/workspace/stations/{station_ids[1]}/queue", json=body)
        assert wrong_station.status_code == 409
        assert wrong_station.json()["detail"]["code"] == "request_conflict"
        confirm_body = {
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "current_event_id": later.json()["id"],
            "event_at": clock.value.isoformat(),
        }
        confirmed = client.post(path + "/confirm", json=confirm_body)
        assert confirmed.status_code == 201
        clock.value += timedelta(minutes=10)
        latest = client.post(path, json=observation(clock, expected_revision=3, band="60_90"))
        assert latest.status_code == 201
        confirm_replay = client.post(path + "/confirm", json=confirm_body)
        assert confirm_replay.status_code == 200
        assert confirm_replay.json() == confirmed.json()
        changed_confirmation = client.post(
            path + "/confirm", json={**confirm_body, "current_event_id": latest.json()["id"]}
        )
        assert changed_confirmation.status_code == 409
        assert changed_confirmation.json()["detail"]["code"] == "request_conflict"
        history = client.get(path).json()
        assert history["items"] == [initial.json(), later.json(), confirmed.json(), latest.json()]
        assert history["current"] == latest.json()
        assert client.get(f"/api/workspace/stations/{station_ids[1]}/queue").json()["items"] == []

        another = queue_account(admin, [station_ids[0]])
        with queue_client(database_url, another, clock) as second:
            actor_collision = second.post(path, json=body)
            assert actor_collision.status_code == 409
            assert actor_collision.json()["detail"]["code"] == "request_conflict"


@pytest.mark.parametrize(
    "changes",
    [
        {"band": "30_60"},
        {"band": ""},
        {"expected_revision": -1},
        {"expected_revision": True},
        {"expected_revision": "0"},
        {"event_at": "2026-11-15T00:00:01Z"},
        {"event_at": "2026-11-15T00:00:00"},
        {"reason": "字" * 1001},
        {"request_id": "not-a-uuid"},
        {"unexpected": "field"},
    ],
)
def test_invalid_observations_do_not_create_a_queue_record(
    admin: TestClient, database_url: str, changes: dict
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        rejected = client.post(path, json=observation(clock, **changes))
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] in ("queue_validation", "validation_error")
        snapshot = client.get(path).json()
        assert snapshot["items"] == []
        assert snapshot["current"] is None
        assert snapshot["revision"] == 0


@pytest.mark.parametrize("second_kind", ["observation", "unchanged_confirmation"])
def test_competing_clients_cannot_append_two_commands_at_the_same_revision(
    admin: TestClient, database_url: str, second_kind: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        original = client.post(path, json=observation(clock))
        assert original.status_code == 201
        clock.value += timedelta(minutes=1)
        first = (path, observation(clock, expected_revision=1, band="30_59"))
        second = (
            (
                path + "/confirm",
                {
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "current_event_id": original.json()["id"],
                    "event_at": clock.value.isoformat(),
                },
            )
            if second_kind == "unchanged_confirmation"
            else (path, observation(clock, expected_revision=1, band="over_90"))
        )
        barrier = Barrier(2)

        def submit(command: tuple[str, dict]) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=clock)) as peer:
                peer.headers.update(client.headers)
                barrier.wait(timeout=5)
                result = peer.post(command[0], json=command[1])
                return result.status_code, result.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, [first, second]))
        assert sorted(status for status, _ in outcomes) == [201, 409]
        loser = next(body for status, body in outcomes if status == 409)
        assert loser["detail"]["code"] == "revision_conflict"
        winner = next(body for status, body in outcomes if status == 201)
        snapshot = client.get(path).json()
        assert snapshot["revision"] == 2
        assert snapshot["items"] == [original.json(), winner]
        assert snapshot["current"] == winner


@pytest.mark.parametrize("kind", ["observation", "unchanged_confirmation"])
def test_concurrent_same_key_submission_has_exactly_one_history_effect(
    admin: TestClient, database_url: str, kind: str
) -> None:
    station = active_queue_stations(admin)[0]["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        prefix = []
        if kind == "unchanged_confirmation":
            initial = client.post(path, json=observation(clock))
            assert initial.status_code == 201
            prefix.append(initial.json())
            clock.value += timedelta(minutes=30)
            body = {
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "current_event_id": initial.json()["id"],
                "event_at": clock.value.isoformat(),
            }
            endpoint = path + "/confirm"
        else:
            body = observation(clock)
            endpoint = path
        barrier = Barrier(2)

        def submit(_: int) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=clock)) as peer:
                peer.headers.update(client.headers)
                barrier.wait(timeout=5)
                result = peer.post(endpoint, json=body)
                return result.status_code, result.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, [0, 1]))
        assert sorted(status for status, _ in outcomes) == [200, 201]
        assert outcomes[0][1] == outcomes[1][1]
        snapshot = client.get(path).json()
        assert snapshot["items"] == [*prefix, outcomes[0][1]]
        assert snapshot["revision"] == len(prefix) + 1


def test_concurrent_global_request_key_collision_cannot_write_two_stations(
    admin: TestClient, database_url: str
) -> None:
    stations = active_queue_stations(admin)
    ids = [context["station"]["id"] for context in stations]
    account = queue_account(admin, ids)
    clock = QueueClock()
    body = observation(clock)
    with queue_client(database_url, account, clock) as client:
        barrier = Barrier(2)

        def submit(station_id: int) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=clock)) as peer:
                peer.headers.update(client.headers)
                barrier.wait(timeout=5)
                result = peer.post(f"/api/workspace/stations/{station_id}/queue", json=body)
                return result.status_code, result.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, ids))
        assert sorted(status for status, _ in outcomes) == [201, 409]
        assert next(body for status, body in outcomes if status == 409)["detail"]["code"] == (
            "request_conflict"
        )
        histories = [
            client.get(f"/api/workspace/stations/{station_id}/queue").json()["items"]
            for station_id in ids
        ]
        assert sorted(len(items) for items in histories) == [0, 1]


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_assigned_operational_roles_read_but_only_polling_officers_write(
    admin: TestClient, database_url: str, role: str
) -> None:
    stations = active_queue_stations(admin)
    station_id, other_id = [context["station"]["id"] for context in stations]
    account = queue_account(admin, [station_id], role)
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    other = f"/api/workspace/stations/{other_id}/queue"
    with queue_client(database_url, account, clock) as client:
        allowed = client.get(path)
        assert allowed.status_code == 200
        assert allowed.json()["context"]["station"]["id"] == station_id
        forbidden = client.get(other)
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "station_access_denied"
        save = client.post(path, json=observation(clock))
        assert save.status_code == (201 if role == "polling_officer" else 403)
        confirm = client.post(
            path + "/confirm",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1 if role == "polling_officer" else 0,
                "current_event_id": save.json()["id"] if role == "polling_officer" else 1,
                "event_at": clock.value.isoformat(),
            },
        )
        assert confirm.status_code == (201 if role == "polling_officer" else 403)
        if role != "polling_officer":
            assert save.json()["detail"]["code"] == "polling_officer_required"
            assert confirm.json()["detail"]["code"] == "polling_officer_required"
        assert client.post(other, json=observation(clock)).status_code == 403
        assert (
            client.post(
                other + "/confirm",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "current_event_id": 1,
                    "event_at": clock.value.isoformat(),
                },
            ).status_code
            == 403
        )


def test_anonymous_temporary_password_and_administrator_have_no_queue_override(
    admin: TestClient, database_url: str
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    confirm_body = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "current_event_id": 1,
        "event_at": clock.value.isoformat(),
    }
    with TestClient(create_app(database_url, now=clock)) as anonymous:
        for response in (
            anonymous.get(path),
            anonymous.post(path, json=observation(clock)),
            anonymous.post(path + "/confirm", json=confirm_body),
        ):
            assert response.status_code == 401
    with queue_client(database_url, account, clock, ready=False) as temporary:
        for response in (
            temporary.get(path),
            temporary.post(path, json=observation(clock)),
            temporary.post(path + "/confirm", json=confirm_body),
        ):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "password_change_required"
    for response in (
        admin.get(path),
        admin.post(path, json=observation(clock)),
        admin.post(path + "/confirm", json=confirm_body),
    ):
        assert response.status_code == 403
    assert admin.get(path).json()["detail"]["code"] == "operational_role_required"


def test_queue_history_survives_application_restart_and_remains_readable_after_finalization(
    admin: TestClient, database_url: str
) -> None:
    context = active_queue_stations(admin)[0]
    station_id = context["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as client:
        record = client.post(path, json=observation(clock, band="60_90", reason="紙本觀察已核對"))
        assert record.status_code == 201
        clock.value += timedelta(minutes=30)
        confirmed = client.post(
            path + "/confirm",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "current_event_id": record.json()["id"],
                "event_at": clock.value.isoformat(),
            },
        )
        assert confirmed.status_code == 201
        history = client.get(path).json()
        with TestClient(create_app(database_url, now=clock)) as restarted:
            restarted.headers.update(client.headers)
            restored = restarted.get(path)
            assert restored.status_code == 200
            assert restored.json() == history
        arrange_retained_queue_election(database_url, context["election"]["id"])
        retained = client.get(path)
        assert retained.status_code == 200
        assert retained.json()["items"] == history["items"]
        assert retained.json()["current"] == confirmed.json()
        assert retained.json()["context"]["election"]["status"] == "finalized"
        for suffix, body in (
            ("", observation(clock, expected_revision=2)),
            (
                "/confirm",
                {
                    "request_id": str(uuid4()),
                    "expected_revision": 2,
                    "current_event_id": confirmed.json()["id"],
                    "event_at": clock.value.isoformat(),
                },
            ),
        ):
            blocked = client.post(path + suffix, json=body)
            assert blocked.status_code == 409
            assert blocked.json()["detail"]["code"] == "active_election_required"
        active_queue_stations(admin)
        assert client.get(path).json()["items"] == history["items"]
        blocked_by_new_active = client.post(path, json=observation(clock, expected_revision=2))
        assert blocked_by_new_active.status_code == 409
        assert blocked_by_new_active.json()["detail"]["code"] == "active_election_required"


def test_draft_election_queue_is_readable_but_cannot_record_observations(
    admin: TestClient, database_url: str
) -> None:
    election, _ = prepared_election(admin)
    options = admin.get("/api/accounts/station-options").json()["items"]
    station_id = next(
        row["station"]["id"] for row in options if row["election"]["id"] == election["id"]
    )
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as client:
        assert client.get(path).status_code == 200
        assert client.get(path).json()["missing"] is True
        blocked = client.post(path, json=observation(clock))
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "active_election_required"


def test_unknown_queue_cannot_be_confirmed_as_unchanged(
    admin: TestClient, database_url: str
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as client:
        rejected = client.post(
            path + "/confirm",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "current_event_id": 1,
                "event_at": clock.value.isoformat(),
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "queue_observation_conflict"
        snapshot = client.get(path).json()
        assert snapshot["missing"] is True
        assert snapshot["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"event_at": "2026-11-15T00:10:01Z"},
        {"event_at": "2026-11-15T00:10:00"},
        {"event_at": "0001-01-01T00:00:00+23:59"},
        {"current_event_id": 0},
        {"current_event_id": True},
        {"expected_revision": True},
        {"band": "over_90"},
    ],
)
def test_confirmation_rejects_future_times_invalid_shapes_and_supplied_band(
    admin: TestClient, database_url: str, changes: dict
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    account = queue_account(admin, [station_id])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station_id}/queue"
    with queue_client(database_url, account, clock) as client:
        original = client.post(path, json=observation(clock, band="30_59"))
        assert original.status_code == 201
        clock.value += timedelta(minutes=10)
        body = {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "current_event_id": original.json()["id"],
            "event_at": clock.value.isoformat(),
            **changes,
        }
        rejected = client.post(path + "/confirm", json=body)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] in ("queue_validation", "validation_error")
        snapshot = client.get(path).json()
        assert snapshot["items"] == [original.json()]
        assert snapshot["revision"] == 1
