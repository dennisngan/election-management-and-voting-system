"""Normal turnout is entered and approved through real MySQL-backed public APIs."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    approve_period,
    arrange_finalized_turnout_election,
    submit_period,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_configured_periods_and_explicit_zero_are_approved_while_opening_is_missing(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, officer_account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, sv),
    ):
        missing = officer.get(path)
        assert missing.status_code == 200
        snapshot = missing.json()
        assert snapshot["period_count"] == 3
        assert [(row["start_at"], row["end_at"]) for row in snapshot["items"]] == [
            ("2026-11-15T00:30:00Z", "2026-11-15T01:30:00Z"),
            ("2026-11-15T01:30:00Z", "2026-11-15T02:30:00Z"),
            ("2026-11-15T02:30:00Z", "2026-11-15T03:10:00Z"),
        ]
        assert [row["period_index"] for row in snapshot["items"]] == [1, 2, 3]
        assert all(
            row["status"] == "missing" and row["record"] is None for row in snapshot["items"]
        )
        assert snapshot["approved_prefix"] == {
            "periods": 0,
            "hourly_total": None,
            "cumulative_end": None,
            "covered_until": None,
        }
        assert officer.get(path.removesuffix("turnout") + "polling").json()["items"] == []
        saved = officer.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=0,
                supplied_cumulative=0,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="外部每小時報表，尚未開站，明確零人",
            ),
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "draft"
        assert saved.json()["actor_id"] == officer_account["id"]
        submitted = officer.post(path + "/1/submit", json=turnout_command(1))
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        approved = supervisor.post(
            path + "/1/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["derived_hourly"] == 0
        assert approved.json()["derived_cumulative_start"] == 0
        assert approved.json()["derived_cumulative_end"] == 0
        assert approved.json()["approved_by"] == sv["id"]
        latest = officer.get(path).json()
        assert latest["items"][0]["approval_valid"] is True
        assert latest["approved_prefix"] == {
            "periods": 1,
            "hourly_total": 0,
            "cumulative_end": 0,
            "covered_until": "2026-11-15T01:30:00Z",
        }


@pytest.mark.parametrize(
    "hourly,cumulative,first_total,second_total,final_total",
    [
        (10, None, 10, 15, 18),
        (None, 20, 20, 25, 28),
        (7, 7, 7, 12, 15),
        (9007199254740993, None, 9007199254740993, 9007199254740998, 9007199254741001),
    ],
)
def test_hourly_cumulative_and_combined_inputs_use_adjacent_approved_endpoints_once(
    admin: TestClient,
    database_url: str,
    hourly: int | None,
    cumulative: int | None,
    first_total: int,
    second_total: int,
    final_total: int,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=hourly,
            supplied_cumulative=cumulative,
            event_at="2026-11-15T01:30:00Z",
            source_context="外部首時段報表",
        )
        first = supervisor.post(
            path + "/1/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert first.status_code == 200
        assert first.json()["derived_hourly"] == first_total
        assert first.json()["derived_cumulative_start"] == 0
        assert first.json()["derived_cumulative_end"] == first_total
        assert first.json()["supplied_hourly"] == hourly
        assert first.json()["supplied_cumulative"] == cumulative
        assert first.json()["basis_predecessor_record_id"] is None
        submit_period(
            officer,
            path,
            2,
            supplied_cumulative=second_total,
            event_at="2026-11-15T02:30:00Z",
            source_context="外部第二時段累計報表",
        )
        second = supervisor.post(
            path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert second.status_code == 200
        assert second.json()["derived_hourly"] == 5
        assert second.json()["derived_cumulative_start"] == first_total
        assert second.json()["derived_cumulative_end"] == second_total
        assert second.json()["basis_predecessor_record_id"] == first.json()["id"]
        assert second.json()["basis_predecessor_revision"] == 1
        submit_period(
            officer,
            path,
            3,
            supplied_hourly=3,
            event_at="2026-11-15T03:10:00Z",
            source_context="外部最後不足一小時報表",
        )
        third = supervisor.post(
            path + "/3/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert third.status_code == 200
        assert third.json()["derived_cumulative_end"] == final_total
        assert third.json()["derived_hourly"] == 3
        snapshot = officer.get(path).json()
        assert snapshot["approved_prefix"] == {
            "periods": 3,
            "hourly_total": final_total,
            "cumulative_end": final_total,
            "covered_until": "2026-11-15T03:10:00Z",
        }
        assert all(row["approval_valid"] for row in snapshot["items"])
        assert all(not row["review_required"] for row in snapshot["items"])


def test_reasoned_upstream_amendment_invalidates_later_approvals_until_each_basis_is_reviewed(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        first_content = {
            "supplied_hourly": 100,
            "event_at": "2026-11-15T01:30:00Z",
            "source_context": "首時段外部報表",
        }
        second_content = {
            "supplied_cumulative": 115,
            "event_at": "2026-11-15T02:30:00Z",
            "source_context": "第二時段外部累計",
        }
        third_content = {
            "supplied_hourly": 20,
            "supplied_cumulative": 135,
            "event_at": "2026-11-15T03:10:00Z",
            "source_context": "末時段外部報表",
        }
        submit_period(officer, path, 1, **first_content)
        original_first = approve_period(supervisor, path, 1)
        submit_period(officer, path, 2, **second_content)
        second_approval = turnout_command(1, password=READY_PASSWORD)
        second = supervisor.post(path + "/2/approve", json=second_approval)
        assert second.status_code == 200
        original_second = second.json()
        submit_period(officer, path, 3, **third_content)
        original_third = approve_period(supervisor, path, 3)
        assert officer.get(path).json()["approved_prefix"]["hourly_total"] == 135

        amended_first = {**first_content, "supplied_hourly": 110}
        amended = officer.post(
            path + "/1/amend",
            json=turnout_draft(1, **amended_first, amendment_reason="核對外部紙本，首時段應為110"),
        )
        assert amended.status_code == 200
        assert amended.json()["revision"] == 2
        affected = officer.get(path).json()
        assert affected["approved_prefix"]["periods"] == 0
        assert affected["approved_prefix"]["hourly_total"] is None
        assert [row["status"] for row in affected["items"]] == ["draft", "approved", "approved"]
        assert [row["review_required"] for row in affected["items"]] == [False, True, True]
        assert affected["items"][1]["record"] == original_second
        assert affected["items"][2]["record"] == original_third
        forbidden_rebind = supervisor.post(
            path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert forbidden_rebind.status_code == 409
        assert forbidden_rebind.json()["detail"]["code"] == "turnout_review_required"
        replay = supervisor.post(path + "/2/approve", json=second_approval)
        assert replay.status_code == 200
        assert replay.json() == original_second
        assert officer.get(path).json()["items"][1]["approval_valid"] is False

        edited = officer.put(path + "/1", json=turnout_draft(2, **amended_first))
        assert edited.status_code == 200
        assert edited.json()["revision"] == 3
        assert edited.json()["amendment_reason"] == "核對外部紙本，首時段應為110"
        assert officer.post(path + "/1/submit", json=turnout_command(3)).status_code == 200
        current_first = approve_period(supervisor, path, 1, 3)
        assert current_first["derived_cumulative_end"] == 110
        assert officer.get(path).json()["approved_prefix"]["periods"] == 1

        for index, content in ((2, second_content), (3, third_content)):
            amended = officer.post(
                f"{path}/{index}/amend",
                json=turnout_draft(
                    1, **content, amendment_reason="首時段修正後重新核對相鄰累計基礎"
                ),
            )
            assert amended.status_code == 200
            assert (
                officer.post(f"{path}/{index}/submit", json=turnout_command(2)).status_code == 200
            )
            reviewed = approve_period(supervisor, path, index, 2)
            assert reviewed["derived_hourly"] == (5 if index == 2 else 20)
        complete = officer.get(path).json()
        assert complete["approved_prefix"]["hourly_total"] == 135
        assert complete["approved_prefix"]["periods"] == 3
        assert all(row["approval_valid"] for row in complete["items"])
        assert complete["items"][1]["record"]["basis_predecessor_record_id"] == current_first["id"]
        assert complete["items"][1]["record"]["basis_predecessor_revision"] == 3
        first_history = officer.get(path + "/1/history").json()["items"]
        assert [row["revision"] for row in first_history] == [1, 2, 3]
        assert first_history[0] == original_first
        assert officer.get(path + "/2/history").json()["items"][0] == original_second
        assert officer.get(path + "/1?revision=1").json() == original_first


def test_period_can_be_submitted_out_of_order_but_cannot_assume_a_missing_zero_baseline(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            2,
            supplied_cumulative=15,
            event_at="2026-11-15T02:30:00Z",
            source_context="先收到第二時段外部累計",
        )
        rejected = supervisor.post(
            path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "turnout_previous_period_required"
        incomplete = officer.get(path).json()
        assert incomplete["items"][0]["status"] == "missing"
        assert incomplete["items"][1]["status"] == "submitted"
        assert incomplete["items"][1]["record"]["derived_hourly"] is None
        assert incomplete["approved_prefix"]["cumulative_end"] is None
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=10,
            event_at="2026-11-15T01:30:00Z",
            source_context="稍後收到首時段紙本",
        )
        approve_period(supervisor, path, 1)
        second = approve_period(supervisor, path, 2)
        assert second["derived_hourly"] == 5
        assert officer.get(path).json()["approved_prefix"]["hourly_total"] == 15


@pytest.mark.parametrize(
    "hourly,cumulative",
    [(None, 99), (10, 115), (9223372036854775807, None)],
)
def test_approval_rejects_negative_deltas_inconsistent_figures_and_signed64_overflow(
    admin: TestClient, database_url: str, hourly: int | None, cumulative: int | None
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=100,
            event_at="2026-11-15T01:30:00Z",
            source_context="首時段紙本100人",
        )
        approve_period(supervisor, path, 1)
        submit_period(
            officer,
            path,
            2,
            supplied_hourly=hourly,
            supplied_cumulative=cumulative,
            event_at="2026-11-15T02:30:00Z",
            source_context="需要覆核的外部第二時段數字",
        )
        rejected = supervisor.post(
            path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "turnout_validation"
        snapshot = officer.get(path).json()
        assert snapshot["items"][1]["status"] == "submitted"
        assert snapshot["items"][1]["record"]["approved_by"] is None
        assert snapshot["items"][1]["record"]["derived_hourly"] is None
        assert snapshot["approved_prefix"]["cumulative_end"] == 100


@pytest.mark.parametrize(
    "changes",
    [
        {"supplied_hourly": -1},
        {"supplied_cumulative": -1},
        {"supplied_hourly": True},
        {"supplied_cumulative": "0"},
        {"supplied_hourly": 0.5},
        {"supplied_cumulative": 9223372036854775808},
        {"expected_revision": True},
        {"expected_schedule_revision": "1"},
        {"source_context": "字" * 2001},
        {"request_id": "invalid"},
        {"event_at": "2026-11-15T04:00:01Z"},
        {"event_at": "2026-11-15T01:30:00"},
        {"event_at": "0001-01-01T00:00:00Z"},
        {"event_at": "0001-01-01T00:00:00+23:59"},
        {"event_at": "9999-12-31T23:59:59-23:59"},
        {"provenance": "fallback"},
    ],
)
def test_invalid_draft_values_do_not_create_normal_turnout_history(
    admin: TestClient, database_url: str, changes: dict
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        rejected = officer.put(path + "/1", json=turnout_draft(**changes))
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] in ("validation_error", "turnout_validation")
        assert officer.get(path + "/1/history").json()["items"] == []
        assert officer.get(path).json()["items"][0]["status"] == "missing"


@pytest.mark.parametrize(
    "content",
    [
        {},
        {"event_at": "2026-11-15T01:30:00Z", "source_context": "沒有數字"},
        {"supplied_hourly": 0, "event_at": "2026-11-15T01:30:00Z", "source_context": "  "},
        {"supplied_hourly": 0, "source_context": "缺原始事件時間"},
        {
            "supplied_hourly": 0,
            "event_at": "2026-11-15T01:29:59Z",
            "source_context": "時段尚未完結",
        },
    ],
)
def test_partial_drafts_persist_but_cannot_be_submitted_as_complete_reports(
    admin: TestClient, database_url: str, content: dict
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        saved = officer.put(path + "/1", json=turnout_draft(**content))
        assert saved.status_code == 200
        assert saved.json()["status"] == "draft"
        rejected = officer.post(path + "/1/submit", json=turnout_command(1))
        assert rejected.status_code == 422
        assert officer.get(path + "/1").json() == saved.json()
        assert officer.get(path).json()["approved_prefix"]["hourly_total"] is None


def test_future_period_drafts_and_explicit_zero_submission_at_the_exact_period_end(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path = scope["stations"][0]["id"], scope["path"]
    clock = TurnoutClock(datetime(2026, 11, 15, 1, 29, 59, tzinfo=UTC))
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        future = officer.put(path + "/3", json=turnout_draft(supplied_hourly=0))
        assert future.status_code == 200
        assert future.json()["status"] == "draft"
        assert officer.post(path + "/3/submit", json=turnout_command(1)).status_code == 422
        content = {
            "supplied_hourly": 0,
            "source_context": "明確零報表",
            "event_at": "2026-11-15T01:30:00Z",
        }
        too_early = officer.put(path + "/1", json=turnout_draft(**content))
        assert too_early.status_code == 422
        assert officer.get(path).json()["items"][0]["status"] == "missing"
        clock.value = datetime(2026, 11, 15, 1, 30, tzinfo=UTC)
        submit_period(officer, path, 1, **content)
        approved = approve_period(supervisor, path, 1)
        assert approved["derived_hourly"] == 0
        assert officer.get(path).json()["approved_prefix"]["hourly_total"] == 0


def test_overnight_schedule_keeps_last_partial_period_and_schedule_changes_are_rejected_when_active(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(
        admin,
        planned_opening_at="2026-11-15T23:30:00+08:00",
        planned_closing_at="2026-11-16T00:10:00+08:00",
        reporting_interval_minutes=30,
    )
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        page = officer.get(path).json()
        assert page["period_count"] == 2
        assert [(row["start_at"], row["end_at"]) for row in page["items"]] == [
            ("2026-11-15T15:30:00Z", "2026-11-15T16:00:00Z"),
            ("2026-11-15T16:00:00Z", "2026-11-15T16:10:00Z"),
        ]
        changed = admin.put(
            f"/api/elections/{scope['election']['id']}/schedule",
            json={
                "election_date": "2026-11-15",
                "planned_opening_at": "2026-11-15T23:30:00+08:00",
                "planned_closing_at": "2026-11-16T00:20:00+08:00",
                "reporting_interval_minutes": 10,
                "revision": 1,
            },
        )
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "draft_required"
        assert officer.get(path).json()["items"] == page["items"]
        stale_schedule = officer.put(path + "/1", json=turnout_draft(expected_schedule_revision=2))
        assert stale_schedule.status_code == 409
        assert stale_schedule.json()["detail"]["code"] == "turnout_schedule_conflict"


def test_extreme_configured_schedule_is_paginated_without_allocating_billions_of_periods(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        first = officer.get(path + "?offset=0&limit=2")
        assert first.status_code == 200
        assert first.json()["period_count"] == 4733542080
        assert [row["period_index"] for row in first.json()["items"]] == [1, 2]
        last = officer.get(path + "?offset=4733542079&limit=1000")
        assert last.status_code == 200
        assert len(last.json()["items"]) == 1
        assert last.json()["items"][0]["period_index"] == 4733542080
        assert last.json()["items"][0]["start_at"] == "9999-12-31T23:59:00Z"
        assert last.json()["items"][0]["end_at"] == "9999-12-31T23:59:59.999999Z"
        saved = officer.put(path + "/4733542080", json=turnout_draft())
        assert saved.status_code == 200
        assert saved.json()["period_index"] == 4733542080
        assert officer.get(path + "?offset=4733542080").json()["items"] == []
        assert officer.get(path + "?offset=-1").status_code == 422
        assert officer.get(path + "?limit=0").status_code == 422
        assert officer.get(path + "?limit=1001").status_code == 422
        assert officer.put(path + "/4733542081", json=turnout_draft()).status_code == 404
        assert officer.put(path + "/0", json=turnout_draft()).status_code == 404


def test_approval_replays_reconfirm_the_current_supervisor_password_and_never_expose_it(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=10,
            event_at="2026-11-15T01:30:00Z",
            source_context="已核對外部紙本報表",
        )
        command = turnout_command(1, password=READY_PASSWORD)
        approved = supervisor.post(path + "/1/approve", json=command)
        assert approved.status_code == 200
        wrong = supervisor.post(
            path + "/1/approve", json={**command, "password": "wrong-existing-password"}
        )
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["code"] == "invalid_credentials"
        new_password = "Turnout-New-Supervisor-96!"
        changed = supervisor.post(
            "/api/auth/password",
            json={"current_password": READY_PASSWORD, "new_password": new_password},
        )
        assert changed.status_code == 200
        supervisor.headers["Authorization"] = "Bearer " + changed.json()["token"]
        assert supervisor.post(path + "/1/approve", json=command).status_code == 401
        replay = supervisor.post(path + "/1/approve", json={**command, "password": new_password})
        assert replay.status_code == 200
        assert replay.json() == approved.json()
        changed_payload = supervisor.post(
            path + "/1/approve", json={**command, "password": new_password, "expected_revision": 2}
        )
        assert changed_payload.status_code == 409
        assert changed_payload.json()["detail"]["code"] == "request_conflict"
        outputs = [
            approved.json(),
            officer.get(path).json(),
            officer.get(path + "/1/history").json(),
        ]
        for output in outputs:
            assert READY_PASSWORD not in repr(output)
            assert new_password not in repr(output)
            assert "password_hash" not in repr(output)
            assert "digest" not in repr(output)
        assert len(officer.get(path + "/1/history").json()["items"]) == 1


@pytest.mark.parametrize("action", ["save", "submit", "approve", "amend"])
@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_turnout_commands_are_revision_safe_and_same_key_has_one_effect(
    admin: TestClient, database_url: str, action: str, same_key: bool
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    content = {
        "supplied_hourly": 10,
        "event_at": "2026-11-15T01:30:00Z",
        "source_context": "並行紙本報表",
    }
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        if action in ("submit", "approve", "amend"):
            if action == "submit":
                assert officer.put(path + "/1", json=turnout_draft(**content)).status_code == 200
            else:
                submit_period(officer, path, 1, **content)
        if action == "amend":
            approve_period(supervisor, path, 1)
        if action == "save":
            client, method, endpoint = officer, "put", path + "/1"
            first = turnout_draft(**content)
            second = turnout_draft(**content)
        elif action == "amend":
            client, method, endpoint = officer, "post", path + "/1/amend"
            first = turnout_draft(1, **content, amendment_reason="重新核對紙本")
            second = turnout_draft(1, **content, amendment_reason="重新核對紙本")
        else:
            client = supervisor if action == "approve" else officer
            method, endpoint = "post", path + "/1/" + action
            first = turnout_command(
                1, **({"password": READY_PASSWORD} if action == "approve" else {})
            )
            second = turnout_command(
                1, **({"password": READY_PASSWORD} if action == "approve" else {})
            )
        if same_key:
            second = first.copy()
        barrier = Barrier(2)

        def send(payload: dict) -> tuple[int, dict]:
            barrier.wait(timeout=5)
            response = getattr(client, method)(endpoint, json=payload)
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, [first, second]))
        assert sorted(status for status, _ in outcomes) == ([200, 200] if same_key else [200, 409])
        if same_key:
            assert outcomes[0][1] == outcomes[1][1]
        else:
            error = next(body for status, body in outcomes if status == 409)
            assert error["detail"]["code"] in ("revision_conflict", "turnout_state_conflict")
        history = officer.get(path + "/1/history").json()["items"]
        assert len(history) == (2 if action == "amend" else 1)
        assert history[-1] == next(body for status, body in outcomes if status == 200)


def test_upstream_amendment_racing_with_downstream_approval_never_leaves_a_valid_stale_total(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=100,
            event_at="2026-11-15T01:30:00Z",
            source_context="首段",
        )
        approve_period(supervisor, path, 1)
        submit_period(
            officer,
            path,
            2,
            supplied_cumulative=115,
            event_at="2026-11-15T02:30:00Z",
            source_context="次段",
        )
        barrier = Barrier(2)

        def amend() -> int:
            barrier.wait(timeout=5)
            return officer.post(
                path + "/1/amend",
                json=turnout_draft(
                    1,
                    supplied_hourly=110,
                    event_at="2026-11-15T01:30:00Z",
                    source_context="首段更正",
                    amendment_reason="核對後首段110人",
                ),
            ).status_code

        def approve() -> int:
            barrier.wait(timeout=5)
            return supervisor.post(
                path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD)
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            amended, approved = pool.submit(amend), pool.submit(approve)
            assert amended.result() == 200
            assert approved.result() in (200, 409)
        snapshot = officer.get(path).json()
        assert snapshot["approved_prefix"]["periods"] == 0
        assert snapshot["approved_prefix"]["hourly_total"] is None
        assert snapshot["items"][1]["approval_valid"] is False
        if snapshot["items"][1]["status"] == "approved":
            assert snapshot["items"][1]["review_required"] is True


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_all_turnout_routes_enforce_operational_roles_and_station_assignments(
    admin: TestClient, database_url: str, role: str
) -> None:
    scope = turnout_scope(admin)
    station_id, other_id = [station["id"] for station in scope["stations"]]
    path, clock = scope["path"], TurnoutClock()
    other = f"/api/workspace/stations/{other_id}/turnout"
    content = {
        "supplied_hourly": 10,
        "event_at": "2026-11-15T01:30:00Z",
        "source_context": "權限測試外部報表",
    }
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (writer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
        turnout_staff(admin, database_url, clock, [station_id], role) as (reader, _),
    ):
        submit_period(writer, path, 1, **content)
        approve_period(supervisor, path, 1)
        for suffix in ("", "/1", "/1/history"):
            assert reader.get(path + suffix).status_code == 200
            denied = reader.get(other + suffix)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "station_access_denied"
        for method, suffix, body, allowed_role in (
            ("put", "/1", turnout_draft(1, **content), "polling_officer"),
            ("post", "/1/submit", turnout_command(1), "polling_officer"),
            ("post", "/1/approve", turnout_command(1, password=READY_PASSWORD), "supervisor"),
            (
                "post",
                "/1/amend",
                turnout_draft(1, **content, amendment_reason="權限核對"),
                "polling_officer",
            ),
        ):
            response = getattr(reader, method)(path + suffix, json=body)
            if role == allowed_role:
                assert response.status_code == (200 if suffix.endswith("/amend") else 409)
            else:
                assert response.status_code == 403
                assert response.json()["detail"]["code"] == allowed_role + "_required"
            assert getattr(reader, method)(other + suffix, json=body).status_code == 403


def test_anonymous_unready_and_administrator_cannot_bypass_any_turnout_route(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    routes = [
        ("get", "", None),
        ("get", "/1", None),
        ("get", "/1/history", None),
        ("put", "/1", turnout_draft()),
        ("post", "/1/submit", turnout_command(0)),
        ("post", "/1/approve", turnout_command(0, password=READY_PASSWORD)),
        ("post", "/1/amend", turnout_draft(amendment_reason="權限核對")),
    ]
    with (
        TestClient(create_app(database_url, now=clock)) as anonymous,
        turnout_staff(admin, database_url, clock, [station_id], ready=False) as (temporary, _),
    ):
        for client, expected, code in (
            (anonymous, 401, "session_expired"),
            (temporary, 403, "password_change_required"),
            (admin, 403, None),
        ):
            for method, suffix, body in routes:
                response = getattr(client, method)(
                    path + suffix, **({"json": body} if body else {})
                )
                assert response.status_code == expected
                if code:
                    assert response.json()["detail"]["code"] == code


def test_same_request_key_changed_payload_actor_and_station_cannot_create_another_revision(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_ids = [station["id"] for station in scope["stations"]]
    path, clock = scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, station_ids) as (officer, _),
        turnout_staff(admin, database_url, clock, station_ids) as (other, _),
    ):
        payload = turnout_draft(
            supplied_hourly=10, event_at="2026-11-15T09:30:00+08:00", source_context="同一紙本報表"
        )
        saved = officer.put(path + "/1", json=payload)
        assert saved.status_code == 200
        later = officer.put(path + "/1", json=turnout_draft(1, supplied_hourly=11))
        assert later.status_code == 200
        replay = officer.put(path + "/1", json={**payload, "event_at": "2026-11-15T01:30:00Z"})
        assert replay.status_code == 200
        assert replay.json() == saved.json()
        for client, endpoint, body in (
            (officer, path + "/1", {**payload, "supplied_hourly": 12}),
            (other, path + "/1", payload),
            (officer, f"/api/workspace/stations/{station_ids[1]}/turnout/1", payload),
        ):
            response = client.put(endpoint, json=body)
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "request_conflict"
        assert officer.get(path + "/1/history").json()["items"] == [saved.json(), later.json()]
        assert officer.get(path + "/1").json() == later.json()


def test_concurrent_global_turnout_key_collision_across_stations_has_one_effect(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    ids = [station["id"] for station in scope["stations"]]
    clock = TurnoutClock()
    with turnout_staff(admin, database_url, clock, ids) as (officer, _):
        body = turnout_draft(supplied_hourly=0)
        barrier = Barrier(2)

        def save(station_id: int) -> tuple[int, dict]:
            barrier.wait(timeout=5)
            response = officer.put(f"/api/workspace/stations/{station_id}/turnout/1", json=body)
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, ids))
        assert sorted(status for status, _ in outcomes) == [200, 409]
        assert (
            next(body for status, body in outcomes if status == 409)["detail"]["code"]
            == "request_conflict"
        )
        lengths = [
            len(
                officer.get(f"/api/workspace/stations/{station_id}/turnout/1/history").json()[
                    "items"
                ]
            )
            for station_id in ids
        ]
        assert sorted(lengths) == [0, 1]


def test_stale_revisions_and_workflow_states_require_reasoned_amendments(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    content = {
        "supplied_hourly": 10,
        "event_at": "2026-11-15T01:30:00Z",
        "source_context": "完整紙本記錄",
    }
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        first = officer.put(path + "/1", json=turnout_draft())
        assert first.status_code == 200
        second = officer.put(path + "/1", json=turnout_draft(1, **content))
        assert second.status_code == 200
        assert second.json()["revision"] == 2
        for method, suffix, body in (
            ("put", "/1", turnout_draft(1, **content)),
            ("post", "/1/submit", turnout_command(1)),
        ):
            stale = getattr(officer, method)(path + suffix, json=body)
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "revision_conflict"
        not_submitted = supervisor.post(
            path + "/1/approve", json=turnout_command(2, password=READY_PASSWORD)
        )
        assert not_submitted.status_code == 409
        assert not_submitted.json()["detail"]["code"] == "turnout_state_conflict"
        assert officer.post(path + "/1/submit", json=turnout_command(2)).status_code == 200
        silent_edit = officer.put(path + "/1", json=turnout_draft(2, **content))
        assert silent_edit.status_code == 409
        assert silent_edit.json()["detail"]["code"] == "turnout_state_conflict"
        blank_amendment = officer.post(
            path + "/1/amend", json=turnout_draft(2, **content, amendment_reason="   ")
        )
        assert blank_amendment.status_code == 422
        stale_approval = supervisor.post(
            path + "/1/approve", json=turnout_command(1, password=READY_PASSWORD)
        )
        assert stale_approval.status_code == 409
        assert stale_approval.json()["detail"]["code"] == "revision_conflict"
        approved = approve_period(supervisor, path, 1, 2)
        assert officer.put(path + "/1", json=turnout_draft(2, **content)).status_code == 409
        amended = officer.post(
            path + "/1/amend", json=turnout_draft(2, **content, amendment_reason="核對後提出修訂")
        )
        assert amended.status_code == 200
        assert amended.json()["revision"] == 3
        assert amended.json()["status"] == "draft"
        assert amended.json()["approved_at"] is None
        assert officer.get(path + "/1/history").json()["items"] == [
            first.json(),
            approved,
            amended.json(),
        ]


def test_turnout_history_survives_restart_finalization_and_another_active_election(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    content = {
        "supplied_hourly": 10,
        "event_at": "2026-11-15T01:30:00Z",
        "source_context": "外部紙本報表甲",
    }
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(officer, path, 1, **content)
        approved = approve_period(supervisor, path, 1)
        snapshot = officer.get(path).json()
        with TestClient(create_app(database_url, now=clock)) as restarted:
            restarted.headers.update(officer.headers)
            assert restarted.get(path).json() == snapshot
            assert restarted.get(path + "/1/history").json()["items"] == [approved]
        arrange_finalized_turnout_election(database_url, scope["election"]["id"])
        retained = officer.get(path)
        assert retained.status_code == 200
        assert retained.json()["context"]["election"]["status"] == "finalized"
        assert retained.json()["items"] == snapshot["items"]
        assert retained.json()["approved_prefix"] == snapshot["approved_prefix"]
        for client, method, suffix, body in (
            (officer, "put", "/1", turnout_draft(1, **content)),
            (officer, "post", "/1/submit", turnout_command(1)),
            (supervisor, "post", "/1/approve", turnout_command(1, password=READY_PASSWORD)),
            (
                officer,
                "post",
                "/1/amend",
                turnout_draft(1, **content, amendment_reason="禁止歷史更改"),
            ),
        ):
            blocked = getattr(client, method)(path + suffix, json=body)
            assert blocked.status_code == 409
            assert blocked.json()["detail"]["code"] == "active_election_required"
        turnout_scope(admin)
        assert officer.get(path).json()["items"] == snapshot["items"]
        assert officer.get(path + "/1?revision=1").json() == approved
        assert officer.put(path + "/1", json=turnout_draft(1, **content)).status_code == 409


def test_draft_turnout_schedule_can_be_viewed_but_not_operated_until_activation(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin, activate=False)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        assert officer.get(path).status_code == 200
        blocked = officer.put(path + "/1", json=turnout_draft())
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "active_election_required"
