"""Polling Officers prepare events; assigned Supervisors approve exact revisions."""

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import (
    INITIAL_PASSWORD,
    READY_PASSWORD,
    arrange_retained_polling_election,
    draft_payload,
    polling_scope,
    ready_polling_staff,
    transition_payload,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_late_opening_draft_is_reviewed_amended_and_preserved_after_restart(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, officer_account = officer_info
        supervisor, supervisor_account = supervisor_info
        initial = officer.get(scope.path)
        assert initial.status_code == 200
        assert initial.json()["items"] == []
        assert initial.json()["context"]["station"]["id"] == station_id
        assert initial.json()["schedule"]["revision"] == 1
        opening = scope.path + "/opening"
        partial = officer.put(opening, json=draft_payload())
        assert partial.status_code == 200
        assert partial.json()["status"] == "draft"
        assert partial.json()["revision"] == 1
        assert partial.json()["event_at"] is None
        incomplete = officer.post(opening + "/submit", json=transition_payload(1))
        assert incomplete.status_code == 422
        assert incomplete.json() == {"detail": {"code": "polling_validation"}}
        late = officer.put(opening, json=draft_payload(1, event_at="2025-11-15T07:35:00+08:00"))
        assert late.status_code == 200
        assert late.json()["revision"] == 2
        assert late.json()["opening_status"] == "delayed"
        unexplained = officer.post(opening + "/submit", json=transition_payload(2))
        assert unexplained.status_code == 422
        explained = officer.put(
            opening,
            json=draft_payload(2, event_at="2025-11-15T07:35:00+08:00", reason="投票設備檢查延誤"),
        )
        assert explained.status_code == 200
        assert explained.json()["revision"] == 3
        submitted = officer.post(opening + "/submit", json=transition_payload(3))
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["submitted_by"] == officer_account["id"]
        approved = supervisor.post(
            opening + "/approve", json=transition_payload(3, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        approved_record = approved.json()
        assert approved_record["status"] == "approved"
        assert approved_record["approved_by"] == supervisor_account["id"]
        assert approved_record["revision"] == 3
        assert approved_record["reason"] == "投票設備檢查延誤"
        assert datetime.fromisoformat(approved_record["planned_at"]) == datetime(
            2025, 11, 14, 23, 30, tzinfo=UTC
        )
        amended = officer.post(
            opening + "/amend",
            json=transition_payload(
                3,
                reason="核對紙本紀錄後更正開站時間",
                event_at="2025-11-15T07:36:00+08:00",
                estimated_clear_at=None,
            ),
        )
        assert amended.status_code == 200
        correction = amended.json()
        assert correction["revision"] == 4
        assert correction["status"] == "draft"
        assert correction["approved_at"] is None
        assert correction["approved_by"] is None
        assert correction["amendment_reason"] == "核對紙本紀錄後更正開站時間"
        history = officer.get(opening + "/history")
        assert history.status_code == 200
        records = history.json()["items"]
        assert [row["revision"] for row in records] == [1, 2, 3, 4]
        assert records[2] == approved_record
        assert records[3] == correction
        with TestClient(create_app(database_url)) as restarted:
            restarted.headers.update(officer.headers)
            assert restarted.get(opening + "/history").json() == history.json()
            assert restarted.get(scope.path).json()["items"] == [correction]


def test_editing_an_amendment_draft_retains_its_required_correction_reason(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        opening = scope.path + "/opening"
        saved = officer.put(opening, json=draft_payload(event_at="2025-11-15T07:30:00+08:00"))
        assert saved.status_code == 200
        assert officer.post(opening + "/submit", json=transition_payload(1)).status_code == 200
        approved = supervisor.post(
            opening + "/approve", json=transition_payload(1, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        amendment_reason = "核對紙本值勤紀錄後更正"
        amended = officer.post(
            opening + "/amend",
            json=transition_payload(
                1,
                reason=amendment_reason,
                event_at="2025-11-15T07:29:00+08:00",
                estimated_clear_at=None,
            ),
        )
        assert amended.status_code == 200
        revised = officer.put(opening, json=draft_payload(2, event_at="2025-11-15T07:28:00+08:00"))
        assert revised.status_code == 200
        assert revised.json()["revision"] == 3
        assert revised.json()["amendment_reason"] == amendment_reason
        resubmitted = officer.post(opening + "/submit", json=transition_payload(3))
        assert resubmitted.status_code == 200
        assert resubmitted.json()["amendment_reason"] == amendment_reason
        history = officer.get(opening + "/history").json()["items"]
        assert history[0] == approved.json()
        assert history[1]["amendment_reason"] == history[2]["amendment_reason"] == amendment_reason


def test_admission_closure_queue_forecast_and_actual_completion_remain_distinct(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        # Every scheduled time has already passed, but no actual event is invented.
        assert officer.get(scope.path).json()["items"] == []
        for kind, event_at, estimate in (
            ("opening", "2025-11-15T07:30:00+08:00", None),
            ("admission_closure", "2025-11-15T22:30:00+08:00", None),
            (
                "queue_clear_estimate",
                "2025-11-15T22:40:00+08:00",
                "2025-11-15T23:15:00+08:00",
            ),
        ):
            path = scope.path + "/" + kind
            saved = officer.put(
                path, json=draft_payload(event_at=event_at, estimated_clear_at=estimate)
            )
            assert saved.status_code == 200
            assert saved.json()["opening_status"] == ("on_time" if kind == "opening" else None)
            submitted = officer.post(path + "/submit", json=transition_payload(1))
            assert submitted.status_code == 200
            approved = supervisor.post(
                path + "/approve", json=transition_payload(1, password=READY_PASSWORD)
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"
        before_completion = officer.get(scope.path).json()["items"]
        assert {row["kind"] for row in before_completion} == {
            "opening",
            "admission_closure",
            "queue_clear_estimate",
        }
        forecast = next(row for row in before_completion if row["kind"] == "queue_clear_estimate")
        assert datetime.fromisoformat(forecast["estimated_clear_at"]) == datetime(
            2025, 11, 15, 15, 15, tzinfo=UTC
        )
        completion = scope.path + "/service_completion"
        saved_completion = officer.put(
            completion, json=draft_payload(event_at="2025-11-15T23:25:00+08:00")
        )
        assert saved_completion.status_code == 200
        submitted_completion = officer.post(completion + "/submit", json=transition_payload(1))
        assert submitted_completion.status_code == 200
        completed = supervisor.post(
            completion + "/approve", json=transition_payload(1, password=READY_PASSWORD)
        )
        assert completed.status_code == 200
        assert datetime.fromisoformat(completed.json()["event_at"]) == datetime(
            2025, 11, 15, 15, 25, tzinfo=UTC
        )
        final_records = officer.get(scope.path).json()["items"]
        assert len(final_records) == 4
        assert (
            next(row for row in final_records if row["kind"] == "queue_clear_estimate") == forecast
        )


@pytest.mark.parametrize(
    "identity",
    [
        "counting_officer",
        "supervisor",
        "administrator",
        "unassigned_polling",
        "unassigned_supervisor",
        "anonymous",
        "first_password",
    ],
)
def test_direct_polling_api_rejects_wrong_role_station_and_unready_sessions(
    admin: TestClient, database_url: str, identity: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with ExitStack() as clients:
        officer, _ = clients.enter_context(
            ready_polling_staff(admin, database_url, "polling_officer", [station_id])
        )
        opening = scope.path + "/opening"
        assert (
            officer.put(
                opening, json=draft_payload(event_at="2025-11-15T07:30:00+08:00")
            ).status_code
            == 200
        )
        assert officer.post(opening + "/submit", json=transition_payload(1)).status_code == 200
        if identity == "administrator":
            client = admin
        elif identity in ("anonymous", "first_password"):
            client = clients.enter_context(TestClient(create_app(database_url)))
            if identity == "first_password":
                username = "unready_polling_" + uuid4().hex[:12]
                created = admin.post(
                    "/api/accounts",
                    json={
                        "username": username,
                        "display_name": "尚未修改密碼測試",
                        "role": "polling_officer",
                        "station_ids": [station_id],
                        "temporary_password": INITIAL_PASSWORD,
                    },
                )
                assert created.status_code == 201
                login = client.post(
                    "/api/auth/login",
                    json={"username": username, "password": INITIAL_PASSWORD},
                )
                assert login.status_code == 200
                client.headers["Authorization"] = "Bearer " + login.json()["token"]
        else:
            role = (
                "supervisor"
                if identity == "unassigned_supervisor"
                else ("polling_officer" if identity == "unassigned_polling" else identity)
            )
            stations = (
                [scope.stations[1]["id"]] if identity.startswith("unassigned") else [station_id]
            )
            client, _ = clients.enter_context(
                ready_polling_staff(admin, database_url, role, stations)
            )
        common_status = 401 if identity == "anonymous" else 403
        common_code = {
            "anonymous": "session_expired",
            "first_password": "password_change_required",
            "administrator": "operational_role_required",
            "unassigned_polling": "station_access_denied",
            "unassigned_supervisor": "station_access_denied",
        }.get(identity)
        for path in (scope.path, opening + "/history", scope.path + "/audit"):
            response = client.get(path)
            assert response.status_code == (200 if common_code is None else common_status)
            if common_code:
                assert response.json() == {"detail": {"code": common_code}}
        for suffix, method, payload in (
            ("", "PUT", draft_payload(1, event_at="2025-11-15T07:30:00+08:00")),
            ("/submit", "POST", transition_payload(1)),
            ("/amend", "POST", transition_payload(1, reason="更正", event_at=None)),
        ):
            if identity == "unassigned_polling":
                code = "station_access_denied"
            elif identity in ("anonymous", "first_password"):
                code = common_code
            else:
                code = "polling_officer_required"
            rejected = client.request(method, opening + suffix, json=payload)
            assert rejected.status_code == common_status
            assert rejected.json() == {"detail": {"code": code}}
        if identity != "supervisor":
            rejected = client.post(
                opening + "/approve", json=transition_payload(1, password=READY_PASSWORD)
            )
            if identity == "unassigned_supervisor":
                code = "station_access_denied"
            elif identity in ("anonymous", "first_password"):
                code = common_code
            else:
                code = "supervisor_required"
            assert rejected.status_code == common_status
            assert rejected.json() == {"detail": {"code": code}}
        assert officer.get(opening + "/history").json()["items"][0]["status"] == "submitted"


def test_supervisor_approval_requires_own_password_and_exact_submitted_revision_even_on_replay(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    supervisor_password = "Supervisor-Own-Approval-126!"
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(
            admin, database_url, "supervisor", [station_id], password=supervisor_password
        ) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, supervisor_account = supervisor_info
        opening = scope.path + "/opening"
        assert (
            officer.put(
                opening, json=draft_payload(event_at="2025-11-15T07:30:00+08:00")
            ).status_code
            == 200
        )
        # A Supervisor cannot approve a draft before the Officer submits it.
        unsubmitted = supervisor.post(
            opening + "/approve", json=transition_payload(1, password=supervisor_password)
        )
        assert unsubmitted.status_code == 409
        assert unsubmitted.json() == {"detail": {"code": "polling_state_conflict"}}
        assert (
            officer.put(
                opening, json=draft_payload(1, event_at="2025-11-15T07:29:00+08:00")
            ).status_code
            == 200
        )
        assert officer.post(opening + "/submit", json=transition_payload(2)).status_code == 200
        stale = supervisor.post(
            opening + "/approve", json=transition_payload(1, password=supervisor_password)
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"code": "revision_conflict"}}
        command = transition_payload(2, password=supervisor_password)
        wrong_password = {**command, "password": READY_PASSWORD}
        rejected = supervisor.post(opening + "/approve", json=wrong_password)
        assert rejected.status_code == 401
        assert rejected.json() == {"detail": {"code": "invalid_credentials"}}
        assert supervisor.get("/api/auth/me").status_code == 200
        unapproved = officer.get(opening + "/history").json()["items"][-1]
        assert unapproved["status"] == "submitted"
        assert unapproved["approved_by"] is None
        approved = supervisor.post(opening + "/approve", json=command)
        assert approved.status_code == 200
        assert approved.json()["approved_by"] == supervisor_account["id"]
        assert approved.json()["revision"] == 2
        assert supervisor.post(opening + "/approve", json=command).json() == approved.json()
        replay_without_own_password = supervisor.post(opening + "/approve", json=wrong_password)
        assert replay_without_own_password.status_code == 401
        assert replay_without_own_password.json() == {"detail": {"code": "invalid_credentials"}}
        assert len(officer.get(opening + "/history").json()["items"]) == 2
        assert officer.get(opening + "/history").json()["items"][-1] == approved.json()


def test_correcting_on_time_opening_to_delayed_keeps_delay_and_amendment_reasons_separate(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        opening = scope.path + "/opening"
        assert (
            officer.put(
                opening, json=draft_payload(event_at="2025-11-15T07:30:00+08:00")
            ).status_code
            == 200
        )
        assert officer.post(opening + "/submit", json=transition_payload(1)).status_code == 200
        approved = supervisor.post(
            opening + "/approve", json=transition_payload(1, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        assert approved.json()["opening_status"] == "on_time"
        assert approved.json()["reason"] == ""
        correction = officer.post(
            opening + "/amend",
            json=transition_payload(
                1,
                reason="核對紙本開站時間後更正",
                event_reason="設備檢查延誤十分鐘",
                event_at="2025-11-15T07:40:00+08:00",
                estimated_clear_at=None,
            ),
        )
        assert correction.status_code == 200
        corrected = correction.json()
        assert corrected["opening_status"] == "delayed"
        assert corrected["reason"] == "設備檢查延誤十分鐘"
        assert corrected["amendment_reason"] == "核對紙本開站時間後更正"
        submitted = officer.post(opening + "/submit", json=transition_payload(2))
        assert submitted.status_code == 200
        assert submitted.json()["reason"] == corrected["reason"]
        assert submitted.json()["amendment_reason"] == corrected["amendment_reason"]
        history = supervisor.get(opening + "/history").json()["items"]
        assert history[0] == approved.json()
        assert history[1]["status"] == "submitted"
        assert history[1]["approved_by"] is None


@pytest.mark.parametrize("same_request", [False, True])
def test_two_clients_cannot_duplicate_or_overwrite_the_same_opening_revision(
    admin: TestClient, database_url: str, same_request: bool
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as (officer, _):
        opening = scope.path + "/opening"
        first = draft_payload(event_at="2025-11-15T07:30:00+08:00")
        commands = [
            first,
            first if same_request else draft_payload(event_at="2025-11-15T07:29:00+08:00"),
        ]
        start = Barrier(2)

        def save(command: dict[str, object]) -> tuple[int, dict]:
            with TestClient(create_app(database_url)) as client:
                client.headers.update(officer.headers)
                start.wait(timeout=5)
                result = client.put(opening, json=command)
                return result.status_code, result.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, commands))
        if same_request:
            assert [status for status, _ in outcomes] == [200, 200]
            assert outcomes[0][1] == outcomes[1][1]
        else:
            assert sorted(status for status, _ in outcomes) == [200, 409]
            assert next(body for status, body in outcomes if status == 409) == {
                "detail": {"code": "revision_conflict"}
            }
        winner = next(body for status, body in outcomes if status == 200)
        history = officer.get(opening + "/history")
        assert history.status_code == 200
        assert history.json()["items"] == [winner]
        assert winner["revision"] == 1


def test_command_replays_return_the_original_outcome_without_duplicate_history_or_audit(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        opening = scope.path + "/opening"
        save_command = draft_payload(event_at="2025-11-15T07:30:00+08:00")
        saved = officer.put(opening, json=save_command)
        assert saved.status_code == 200
        assert officer.put(opening, json=save_command).json() == saved.json()
        different_save = officer.put(opening, json={**save_command, "reason": "不同內容"})
        assert different_save.status_code == 409
        assert different_save.json() == {"detail": {"code": "request_conflict"}}
        submit_command = transition_payload(1)
        submitted = officer.post(opening + "/submit", json=submit_command)
        assert submitted.status_code == 200
        assert officer.post(opening + "/submit", json=submit_command).json() == submitted.json()
        # A later state transition must not rewrite the stored earlier command response.
        assert officer.put(opening, json=save_command).json() == saved.json()
        fresh_edit_of_submitted = officer.put(
            opening, json=draft_payload(1, event_at="2025-11-15T07:29:00+08:00")
        )
        assert fresh_edit_of_submitted.status_code == 409
        assert fresh_edit_of_submitted.json() == {"detail": {"code": "polling_state_conflict"}}
        approval_command = transition_payload(1, password=READY_PASSWORD)
        approved = supervisor.post(opening + "/approve", json=approval_command)
        assert approved.status_code == 200
        assert officer.post(opening + "/submit", json=submit_command).json() == submitted.json()
        changed_password = "Supervisor-Changed-Password-168!"
        changed = supervisor.post(
            "/api/auth/password",
            json={"current_password": READY_PASSWORD, "new_password": changed_password},
        )
        assert changed.status_code == 200
        supervisor.headers["Authorization"] = "Bearer " + changed.json()["token"]
        # Replay fingerprints exclude credentials: a valid new password still replays.
        with TestClient(create_app(database_url)) as restarted:
            restarted.headers.update(supervisor.headers)
            replay = restarted.post(
                opening + "/approve", json={**approval_command, "password": changed_password}
            )
            assert replay.status_code == 200
            assert replay.json() == approved.json()
        amendment_command = transition_payload(
            1,
            reason="核對紀錄更正",
            event_at="2025-11-15T07:29:00+08:00",
            estimated_clear_at=None,
        )
        amended = officer.post(opening + "/amend", json=amendment_command)
        assert amended.status_code == 200
        assert officer.post(opening + "/amend", json=amendment_command).json() == amended.json()
        revised = officer.put(opening, json=draft_payload(2, event_at="2025-11-15T07:28:00+08:00"))
        assert revised.status_code == 200
        assert officer.post(opening + "/amend", json=amendment_command).json() == amended.json()
        conflicting_amendment = officer.post(
            opening + "/amend", json={**amendment_command, "reason": "另一更正原因"}
        )
        assert conflicting_amendment.status_code == 409
        assert conflicting_amendment.json() == {"detail": {"code": "request_conflict"}}
        history = officer.get(opening + "/history").json()["items"]
        assert [row["revision"] for row in history] == [1, 2, 3]
        assert history[0] == approved.json()
        assert history[1] == amended.json()
        assert history[2] == revised.json()
        audit = officer.get(scope.path + "/audit")
        assert audit.status_code == 200
        assert [row["action"] for row in audit.json()["items"]] == [
            "polling_save",
            "polling_submit",
            "polling_approve",
            "polling_amend",
            "polling_save",
        ]


@pytest.mark.parametrize(
    ("kind", "changes", "code"),
    [
        ("opening", {"event_at": "2025-11-15T23:30:00+08:00"}, "polling_validation"),
        ("admission_closure", {"event_at": "2025-11-15T07:29:00+08:00"}, "polling_validation"),
        ("admission_closure", {"event_at": "2025-11-15T23:30:00+08:00"}, "polling_validation"),
        ("service_completion", {"event_at": "2025-11-15T22:29:00+08:00"}, "polling_validation"),
        ("service_completion", {"event_at": "2025-11-15T07:29:00+08:00"}, "polling_validation"),
        (
            "queue_clear_estimate",
            {
                "event_at": "2025-11-15T22:40:00+08:00",
                "estimated_clear_at": "2025-11-15T22:39:00+08:00",
            },
            "polling_validation",
        ),
        (
            "queue_clear_estimate",
            {
                "event_at": "2025-11-15T22:20:00+08:00",
                "estimated_clear_at": "2025-11-15T22:29:00+08:00",
            },
            "polling_validation",
        ),
        ("opening", {"estimated_clear_at": "2025-11-15T23:15:00+08:00"}, "polling_validation"),
        ("service_completion", {"event_at": "FUTURE"}, "polling_validation"),
        ("queue_clear_estimate", {"event_at": "FUTURE"}, "polling_validation"),
        ("opening", {"event_at": "2025-11-15T07:30:00"}, "validation_error"),
        ("opening", {"event_at": "not-a-time"}, "validation_error"),
        ("opening", {"revision": True}, "validation_error"),
        ("opening", {"revision": "1"}, "validation_error"),
        ("opening", {"revision": -1}, "validation_error"),
        ("opening", {"request_id": "not-a-uuid"}, "validation_error"),
    ],
)
def test_invalid_polling_time_order_or_inputs_never_replace_saved_events(
    admin: TestClient, database_url: str, kind: str, changes: dict, code: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as (officer, _):
        for saved_kind, event_at in (
            ("opening", "2025-11-15T07:30:00+08:00"),
            ("admission_closure", "2025-11-15T22:30:00+08:00"),
            ("service_completion", "2025-11-15T23:25:00+08:00"),
        ):
            assert (
                officer.put(
                    scope.path + "/" + saved_kind, json=draft_payload(event_at=event_at)
                ).status_code
                == 200
            )
        before = officer.get(scope.path).json()
        command = {**draft_payload(0 if kind == "queue_clear_estimate" else 1), **changes}
        if command.get("event_at") == "FUTURE":
            command["event_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        rejected = officer.put(scope.path + "/" + kind, json=command)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == code
        assert officer.get(scope.path).json() == before


def test_only_the_active_election_accepts_writes_while_assigned_history_remains_readable(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin, activate=False)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        opening = scope.path + "/opening"
        assert officer.get(scope.path).json()["items"] == []
        for active in (False, True):
            if active:
                activated = admin.post(
                    f"/api/elections/{scope.election['id']}/activate",
                    json={"election_revision": scope.election["revision"], "schedule_revision": 1},
                )
                assert activated.status_code == 200
                saved = officer.put(
                    opening, json=draft_payload(event_at="2025-11-15T07:30:00+08:00")
                )
                assert saved.status_code == 200
                # Arrange retained history only; actual finalization belongs to Ticket 24.
                arrange_retained_polling_election(database_url, scope.election["id"])
                other = polling_scope(admin)
                assert (
                    admin.get("/api/active-election").json()["election"]["id"]
                    == other.election["id"]
                )
                assert officer.get(opening + "/history").json()["items"] == [saved.json()]
                retained = officer.get(scope.path)
                assert retained.status_code == 200
                assert retained.json()["context"]["election"]["status"] == "finalized"
                assert retained.json()["items"] == [saved.json()]
            revision = 1 if active else 0
            for client, method, suffix, command in (
                (officer, "PUT", "", draft_payload(revision)),
                (officer, "POST", "/submit", transition_payload(revision)),
                (officer, "POST", "/amend", transition_payload(revision, reason="更正")),
                (
                    supervisor,
                    "POST",
                    "/approve",
                    transition_payload(revision, password=READY_PASSWORD),
                ),
            ):
                rejected = client.request(method, opening + suffix, json=command)
                assert rejected.status_code == 409
                assert rejected.json() == {"detail": {"code": "active_election_required"}}
            history = officer.get(opening + "/history")
            assert history.status_code == 200
            assert history.json()["items"] == ([saved.json()] if active else [])


def test_a_future_queue_forecast_is_not_an_actual_completion_and_requires_a_complete_observation(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, _ = officer_info
        supervisor, _ = supervisor_info
        estimate = scope.path + "/queue_clear_estimate"
        partial = officer.put(estimate, json=draft_payload(event_at="2025-11-15T22:40:00+08:00"))
        assert partial.status_code == 200
        assert partial.json()["estimated_clear_at"] is None
        rejected = officer.post(estimate + "/submit", json=transition_payload(1))
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": {"code": "polling_validation"}}
        forecast_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        saved = officer.put(
            estimate,
            json=draft_payload(
                1,
                event_at="2025-11-15T22:40:00+08:00",
                estimated_clear_at=forecast_at.isoformat(),
            ),
        )
        assert saved.status_code == 200
        assert datetime.fromisoformat(saved.json()["estimated_clear_at"]) == forecast_at
        submitted = officer.post(estimate + "/submit", json=transition_payload(2))
        assert submitted.status_code == 200
        approved = supervisor.post(
            estimate + "/approve", json=transition_payload(2, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        records = officer.get(scope.path).json()["items"]
        assert records == [approved.json()]
        assert {row["kind"] for row in records} == {"queue_clear_estimate"}


def test_polling_audit_preserves_scope_actors_occurrence_entry_approval_and_reasons_without_secrets(
    admin: TestClient, database_url: str
) -> None:
    scope = polling_scope(admin)
    station_id = scope.stations[0]["id"]
    with (
        ready_polling_staff(admin, database_url, "polling_officer", [station_id]) as officer_info,
        ready_polling_staff(admin, database_url, "supervisor", [station_id]) as supervisor_info,
    ):
        officer, officer_account = officer_info
        supervisor, supervisor_account = supervisor_info
        opening = scope.path + "/opening"
        before = datetime.now(UTC)
        saved = officer.put(
            opening,
            json=draft_payload(event_at="2025-11-15T07:35:00+08:00", reason="設備啟動延誤"),
        )
        assert saved.status_code == 200
        submitted = officer.post(opening + "/submit", json=transition_payload(1))
        assert submitted.status_code == 200
        approved = supervisor.post(
            opening + "/approve", json=transition_payload(1, password=READY_PASSWORD)
        )
        assert approved.status_code == 200
        corrected = officer.post(
            opening + "/amend",
            json=transition_payload(
                1,
                reason="核對值勤紀錄更正一分鐘",
                event_at="2025-11-15T07:36:00+08:00",
                estimated_clear_at=None,
            ),
        )
        assert corrected.status_code == 200
        response = supervisor.get(scope.path + "/audit")
        after = datetime.now(UTC)
        assert response.status_code == 200
        events = response.json()["items"]
        assert len(events) == 4
        expected = (
            ("polling_save", officer_account["id"], saved.json()),
            ("polling_submit", officer_account["id"], submitted.json()),
            ("polling_approve", supervisor_account["id"], approved.json()),
            ("polling_amend", officer_account["id"], corrected.json()),
        )
        for event, (action, actor_id, record) in zip(events, expected, strict=True):
            assert event["action"] == action
            assert event["actor_id"] == actor_id
            assert before <= datetime.fromisoformat(event["occurred_at"]) <= after
            assert event["details"] == {
                "election_id": scope.election["id"],
                "constituency_id": scope.constituency["id"],
                "station_id": station_id,
                "record": record,
            }
            assert before <= datetime.fromisoformat(record["entered_at"]) <= after
            assert record["actor_id"] == officer_account["id"]
            assert record["schedule_revision"] == 1
        approval = events[2]["details"]["record"]
        assert approval["revision"] == 1
        assert approval["approved_by"] == supervisor_account["id"]
        assert approval["submitted_by"] == officer_account["id"]
        assert before <= datetime.fromisoformat(approval["submitted_at"]) <= after
        assert before <= datetime.fromisoformat(approval["approved_at"]) <= after
        assert datetime.fromisoformat(approval["event_at"]) == datetime(
            2025, 11, 14, 23, 35, tzinfo=UTC
        )
        assert approval["reason"] == "設備啟動延誤"
        assert events[3]["details"]["record"]["amendment_reason"] == "核對值勤紀錄更正一分鐘"
        serialized = json.dumps(response.json(), ensure_ascii=False)
        for secret in (
            INITIAL_PASSWORD,
            READY_PASSWORD,
            officer.headers["Authorization"].removeprefix("Bearer "),
            supervisor.headers["Authorization"].removeprefix("Bearer "),
            '"password"',
            '"password_hash"',
            '"token"',
        ):
            assert secret not in serialized
        # Another station's audit requires its own station assignment.
        other_station = f"/api/workspace/stations/{scope.stations[1]['id']}/polling/audit"
        assert supervisor.get(other_station).status_code == 403
