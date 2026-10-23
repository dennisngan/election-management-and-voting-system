"""Real MySQL P19 received-cohort snapshots, review and dependency protection."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Election
from election.server.db import make_engine
from tests.complaint_period_support import READY_PASSWORD, complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    category_edit,
    complaint_payload,
    complaint_staff,
    station_categories,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_missing_complaint_periods_are_not_explicit_zero_reports(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [scope["station"]["id"]]
    ) as (client, _):
        response = client.get(scope["path"])
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["period_count"] == 3
        assert [row["period_index"] for row in snapshot["items"]] == [1, 2, 3]
        assert [(row["start_at"], row["end_at"]) for row in snapshot["items"]] == [
            ("2026-11-14T23:30:00Z", "2026-11-15T00:30:00Z"),
            ("2026-11-15T00:30:00Z", "2026-11-15T01:30:00Z"),
            ("2026-11-15T01:30:00Z", "2026-11-15T02:10:00Z"),
        ]
        assert all(
            row["record"] is None and row["status"] == "missing" for row in snapshot["items"]
        )
        assert snapshot["summary"] == {"required": 3, "approved_current": 0, "missing": 3}


def test_explicit_zero_period_is_submitted_and_approved_without_opening_record(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    clock = ComplaintClock()
    station_id = scope["station"]["id"]
    path = scope["path"]
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
            po,
            officer,
        ),
        complaint_staff(admin, database_url, clock, "supervisor", [station_id]) as (sv, reviewer),
    ):
        assert po.get(path.removesuffix("complaint-periods") + "polling").json()["items"] == []
        prepared = po.put(path + "/1", json=period_command())
        assert prepared.status_code == 200
        row = prepared.json()
        assert row["status"] == "draft" and row["revision"] == 1
        assert row["total_received"] == row["total_completed"] == row["total_in_progress"] == 0
        assert row["members"] == row["group_counts"] == []
        assert row["basis_at"] == "2026-11-15T16:00:00Z" and row["actor_id"] == officer["id"]
        assert row["basis_current"] and not row["approval_valid"]
        submitted = po.post(path + "/1/submit", json=period_command(1))
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["submitted_by"] == officer["id"]
        approved = sv.post(path + "/1/approve", json=period_command(1, password=READY_PASSWORD))
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved" and approved.json()["approval_valid"]
        assert approved.json()["approved_by"] == reviewer["id"]
        snapshot = po.get(path).json()
        assert snapshot["summary"] == {"required": 3, "approved_current": 1, "missing": 2}
        assert po.get(path + "/1").json() == approved.json()
        assert po.get(path + "/1/history").json()["items"] == [approved.json()]


def test_period_counts_use_received_cohort_and_freeze_work_status_at_preparation(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    station_id = scope["station"]["id"]
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station_id]
    ) as (po, actor):
        categories = station_categories(po, station_id)
        case_path, path = scope["case_path"], scope["path"]
        first = po.post(
            case_path,
            json=complaint_payload(
                categories[0],
                case_reference="0001",
                work_status="completed",
                completed_at="2026-11-15T11:00:00+08:00",
            ),
        ).json()
        second = po.post(
            case_path,
            json=complaint_payload(
                categories[0],
                case_reference="0002",
                received_at="2026-11-15T07:30:00+08:00",
            ),
        ).json()
        boundary = po.post(
            case_path,
            json=complaint_payload(
                categories[-1],
                case_reference="0003",
                received_at="2026-11-15T08:30:00+08:00",
            ),
        ).json()
        assert (
            po.post(
                case_path,
                json=complaint_payload(
                    categories[0],
                    case_reference="outside",
                    received_at="2026-11-15T07:29:59+08:00",
                ),
            ).status_code
            == 201
        )
        prepared = po.put(path + "/1", json=period_command())
        assert prepared.status_code == 200
        row = prepared.json()
        assert (row["total_received"], row["total_completed"], row["total_in_progress"]) == (
            2,
            1,
            1,
        )
        assert [member["case_id"] for member in row["members"]] == [first["id"], second["id"]]
        assert row["members"][0]["completed_at"] == "2026-11-15T03:00:00Z"
        (group,) = row["group_counts"]
        assert (group["code"], group["label_tc"], group["total_received"]) == ("9", "投票安排", 2)
        assert (group["total_completed"], group["total_in_progress"]) == (1, 1)
        assert group["source_english"] == "Polling arrangements" and group["reference_page"] == 61
        assert all(member["actor_id"] == actor["id"] for member in row["members"])
        second_period = po.put(path + "/2", json=period_command()).json()
        assert second_period["total_received"] == 1
        assert second_period["members"][0]["case_id"] == boundary["id"]
        assert second_period["group_counts"][0]["code"] == "30"
        assert po.get(path).json()["outside_coverage_case_count"] == 1


def test_late_case_invalidates_approved_zero_basis_and_requires_reasoned_renewal(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    path, case_path, sid = scope["path"], scope["case_path"], scope["station"]["id"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, reviewer),
    ):
        category = station_categories(po, sid)[0]
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        approved = sv.post(
            path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
        ).json()
        body = complaint_payload(category)
        missing_reason = po.post(case_path, json=body)
        assert missing_reason.status_code == 422
        assert missing_reason.json()["detail"]["code"] == "complaint_late_reason_required"
        late = po.post(case_path, json={**body, "reason": "恢復後補錄紙本投訴"})
        assert late.status_code == 201
        case = late.json()
        assert case["requires_amendment"] and not case["ever_submitted"]
        historical = po.get(path + "/1").json()
        assert historical["status"] == "approved" and not historical["approval_valid"]
        assert historical["review_required"] and not historical["basis_current"]
        assert historical["approved_by"] == reviewer["id"] == approved["approved_by"]
        assert historical["total_received"] == 0 and historical["members"] == []
        assert (
            sv.post(
                path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
            ).status_code
            == 409
        )
        edit = complaint_payload(
            category,
            expected_revision=1,
            work_status="completed",
            completed_at="2026-11-15T08:45:00+08:00",
        )
        assert po.put(f"{case_path}/{case['id']}", json=edit).status_code == 409
        amended_case = po.post(
            f"{case_path}/{case['id']}/amend",
            json={
                **edit,
                "request_id": str(uuid4()),
                "reason": "核對紙本後記錄完成時間",
            },
        )
        assert amended_case.status_code == 200
        refreshed = po.post(path + "/1/amend", json=period_command(1, reason="補錄投訴後重編統計"))
        assert refreshed.status_code == 200
        assert refreshed.json()["revision"] == 2 and refreshed.json()["status"] == "draft"
        assert refreshed.json()["total_received"] == refreshed.json()["total_completed"] == 1
        assert (
            refreshed.json()["members"][0]["case_revision_id"] == amended_case.json()["revision_id"]
        )
        assert refreshed.json()["approved_by"] is None
        assert po.post(path + "/1/submit", json=period_command(2)).status_code == 200
        assert po.get(f"{case_path}/{case['id']}").json()["ever_submitted"]
        renewed = sv.post(path + "/1/approve", json=period_command(2, password=READY_PASSWORD))
        assert renewed.status_code == 200 and renewed.json()["approval_valid"]
        history = po.get(path + "/1/history").json()["items"]
        assert [row["revision"] for row in history] == [1, 2]
        assert history[0]["total_received"] == 0 and history[0]["approved_by"] == reviewer["id"]
        assert history[1] == renewed.json()


def test_public_submission_sticks_case_protection_even_after_received_time_leaves_period(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        category = station_categories(po, sid)[0]
        creation = complaint_payload(category)
        original = po.post(case_path, json=creation).json()
        assert po.put(path + "/1", json=period_command()).status_code == 200
        submitted = po.post(path + "/1/submit", json=period_command(1))
        assert submitted.status_code == 200 and submitted.json()["basis_current"]
        saved_case = po.get(f"{case_path}/{original['id']}").json()
        assert saved_case["ever_submitted"] and saved_case["requires_amendment"]
        replay = po.post(case_path, json=creation)
        assert replay.status_code == 200 and replay.json() == original
        body = complaint_payload(
            category, expected_revision=1, received_at="2026-11-15T07:29:59+08:00"
        )
        assert po.put(f"{case_path}/{original['id']}", json=body).status_code == 409
        moved = po.post(
            f"{case_path}/{original['id']}/amend",
            json={
                **body,
                "reason": "核對接收時間，原記錄早一分鐘",
            },
        )
        assert moved.status_code == 200
        assert moved.json()["ever_submitted"] and moved.json()["requires_amendment"]
        assert moved.json()["period_index"] is None
        assert (
            po.put(
                f"{case_path}/{original['id']}",
                json={
                    **body,
                    "request_id": str(uuid4()),
                    "expected_revision": 2,
                },
            ).status_code
            == 409
        )
        assert not po.get(path + "/1").json()["basis_current"]
        assert submitted.json()["members"][0]["received_at"] == "2026-11-15T00:15:00Z"


def test_catalog_rename_does_not_change_frozen_period_labels_or_basis(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        category = station_categories(po, sid)[0]
        assert po.post(scope["case_path"], json=complaint_payload(category)).status_code == 201
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        original = sv.post(
            path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
        ).json()
        catalog = f"/api/elections/{scope['election']['id']}/complaint-categories/{category['id']}"
        renamed = admin.put(
            catalog, json=category_edit(category, label_tc="全新項目顯示", enabled=False)
        )
        assert renamed.status_code == 200
        retained = po.get(path + "/1").json()
        assert retained == original
        assert retained["group_counts"][0]["label_tc"] == "投票安排"
        assert retained["members"][0]["category_label_tc"] == "投票安排"
        assert retained["approval_valid"] and retained["basis_current"]


def test_submission_and_approval_require_the_configured_period_end_to_have_elapsed(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock(datetime(2026, 11, 15, 0, 29, 59, tzinfo=UTC))
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        assert po.put(path + "/1", json=period_command()).status_code == 200
        early = po.post(path + "/1/submit", json=period_command(1))
        assert early.status_code == 422
        assert early.json()["detail"]["code"] == "complaint_period_not_ended"
        assert po.get(path + "/1").json()["status"] == "draft"
        clock.value = datetime(2026, 11, 15, 0, 30, tzinfo=UTC)
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        clock.value = datetime(2026, 11, 15, 0, 29, 59, tzinfo=UTC)
        approval = period_command(1, password=READY_PASSWORD)
        assert sv.post(path + "/1/approve", json=approval).status_code == 422
        clock.value = datetime(2026, 11, 15, 0, 30, tzinfo=UTC)
        assert sv.post(path + "/1/approve", json=approval).status_code == 200


def test_draft_basis_changes_require_a_fresh_prepared_revision_before_submission(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        category = station_categories(po, sid)[0]
        case = po.post(case_path, json=complaint_payload(category)).json()
        first = po.put(path + "/1", json=period_command()).json()
        changed = po.put(
            f"{case_path}/{case['id']}",
            json=complaint_payload(
                category,
                expected_revision=1,
                description="修正草稿描述但個案數目不變",
            ),
        )
        assert changed.status_code == 200
        assert not po.get(path + "/1").json()["basis_current"]
        stale = po.post(path + "/1/submit", json=period_command(1))
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "complaint_period_review_required"
        refreshed = po.put(path + "/1", json=period_command(1)).json()
        assert refreshed["revision"] == 2 and refreshed["basis_current"]
        assert first["members"][0]["case_revision_id"] == case["revision_id"]
        assert refreshed["members"][0]["case_revision_id"] == changed.json()["revision_id"]
        assert po.post(path + "/1/submit", json=period_command(2)).status_code == 200
        assert po.get(f"{case_path}/{case['id']}").json()["ever_submitted"]


def test_approval_replay_reconfirms_current_password_and_returns_original_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        command = period_command(1, password=READY_PASSWORD)
        approved = sv.post(path + "/1/approve", json=command)
        assert approved.status_code == 200
        assert (
            sv.post(path + "/1/approve", json={**command, "password": "wrong"}).status_code == 401
        )
        new_password = "Complaint-Changed-Test-96!"
        changed = sv.post(
            "/api/auth/password",
            json={
                "current_password": READY_PASSWORD,
                "new_password": new_password,
            },
        )
        assert changed.status_code == 200
        sv.headers["Authorization"] = "Bearer " + changed.json()["token"]
        assert sv.post(path + "/1/approve", json=command).status_code == 401
        replay = sv.post(path + "/1/approve", json={**command, "password": new_password})
        assert replay.status_code == 200 and replay.json() == approved.json()
        assert len(po.get(path + "/1/history").json()["items"]) == 1


def test_period_request_replays_are_one_effect_and_share_global_case_uuid_scope(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        command = period_command()
        first = po.put(path + "/1", json=command)
        assert first.status_code == 200
        assert po.put(path + "/1", json=command).json() == first.json()
        assert po.put(path + "/2", json=command).status_code == 409
        assert po.put(path + "/1", json={**command, "expected_revision": 1}).status_code == 409
        category = station_categories(po, sid)[0]
        crossed = po.post(
            case_path, json=complaint_payload(category, request_id=command["request_id"])
        )
        assert crossed.status_code == 409
        assert crossed.json()["detail"]["code"] == "request_conflict"
        assert po.get(case_path).json()["items"] == []


def test_status_correction_preserves_approved_members_and_requires_new_review(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        category = station_categories(po, sid)[0]
        case = po.post(case_path, json=complaint_payload(category)).json()
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        approved = sv.post(
            path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
        ).json()
        correction = po.post(
            f"{case_path}/{case['id']}/amend",
            json=complaint_payload(
                category,
                expected_revision=1,
                work_status="completed",
                completed_at="2026-11-15T09:00:00+08:00",
                reason="核對處理情況後記錄完成時間",
            ),
        )
        assert correction.status_code == 200
        old = po.get(path + "/1?revision=1").json()
        assert old["total_in_progress"] == 1 and old["total_completed"] == 0
        assert old["members"][0]["work_status"] == "in_progress"
        assert old["members"][0]["case_revision_id"] == case["revision_id"]
        assert (
            old["approved_by"] == approved["approved_by"]
            and old["approved_at"] == approved["approved_at"]
        )
        assert not old["basis_current"] and old["review_required"]
        reason = "個案處理狀態更正後重編統計"
        amended = po.post(path + "/1/amend", json=period_command(1, reason=reason)).json()
        assert amended["revision"] == 2 and amended["total_completed"] == 1
        saved = po.put(path + "/1", json=period_command(2)).json()
        assert saved["revision"] == 3 and saved["amendment_reason"] == reason
        assert po.post(path + "/1/submit", json=period_command(3)).status_code == 200
        renewed = sv.post(path + "/1/approve", json=period_command(3, password=READY_PASSWORD))
        assert renewed.status_code == 200 and renewed.json()["approval_valid"]
        assert [row["revision"] for row in po.get(path + "/1/history").json()["items"]] == [1, 2, 3]


def test_sparse_period_pagination_handles_large_ordinals_without_materializing_all_periods(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    sid, path = scope["station"]["id"], scope["path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        first = po.get(path + "?offset=0&limit=2")
        assert first.status_code == 200 and first.json()["period_count"] == 4733542080
        assert [row["period_index"] for row in first.json()["items"]] == [1, 2]
        last = po.get(path + "?offset=4733542079&limit=1000")
        assert last.status_code == 200 and len(last.json()["items"]) == 1
        assert last.json()["items"][0]["start_at"] == "9999-12-31T23:59:00Z"
        assert last.json()["items"][0]["end_at"] == "9999-12-31T23:59:59.999999Z"
        saved = po.put(path + "/4733542080", json=period_command())
        assert saved.status_code == 200 and saved.json()["period_index"] == 4733542080
        assert po.get(path + "?offset=4733542080").json()["items"] == []
        assert po.get(path).json()["summary"] == {
            "required": 4733542080,
            "approved_current": 0,
            "missing": 4733542079,
        }
        assert po.post(path + "/4733542080/submit", json=period_command(1)).status_code == 422
        for query in ("offset=-1", "limit=0", "limit=1001"):
            assert po.get(path + "?" + query).status_code == 422
        assert po.put(path + "/4733542081", json=period_command()).status_code == 404
        assert po.put(path + "/0", json=period_command()).status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        {"expected_revision": True},
        {"expected_schedule_revision": True},
        {"total_received": 0},
        {"members": []},
        {"group_counts": []},
        {"basis_at": "2026-11-15T00:00:00Z"},
    ],
)
def test_period_counts_and_membership_are_not_client_supplied(
    admin: TestClient,
    database_url: str,
    extra: dict,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        assert po.put(path + "/1", json=period_command(**extra)).status_code == 422
        assert po.get(path).json()["items"][0]["record"] is None


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_period_readers_have_no_polling_write_override(
    admin: TestClient,
    database_url: str,
    role: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _):
        prepared = po.put(path + "/1", json=period_command()).json()
        assert (
            po.post(
                path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
            ).status_code
            == 403
        )
    with complaint_staff(admin, database_url, clock, role, [sid]) as (reader, _):
        assert reader.get(path).json()["items"][0]["record"] == prepared
        assert reader.get(path + "/1").json() == prepared
        assert reader.get(path + "/1/history").json()["items"] == [prepared]
        assert reader.put(path + "/1", json=period_command(1)).status_code == 403
        assert reader.post(path + "/1/submit", json=period_command(1)).status_code == 403
        assert (
            reader.post(path + "/1/amend", json=period_command(1, reason="更正")).status_code == 403
        )
        if role == "counting_officer":
            assert (
                reader.post(
                    path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
                ).status_code
                == 403
            )


def test_period_station_authentication_and_retained_finalized_scope_are_enforced(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _):
        prepared = po.put(path + "/1", json=period_command()).json()
        assert admin.get(path).status_code == 403
        assert admin.put(path + "/1", json=period_command(1)).status_code == 403
        denied = f"/api/workspace/stations/{scope['N2']['id']}/complaint-periods"
        assert po.get(denied).status_code == 403
        assert po.get(denied + "/1/history").status_code == 403
        assert po.put(denied + "/1", json=period_command()).status_code == 403
        engine = make_engine(database_url)
        try:
            with Session(engine) as db:
                db.execute(
                    update(Election)
                    .where(Election.id == scope["election"]["id"])
                    .values(status="finalized")
                )
                db.commit()
        finally:
            engine.dispose()
        assert po.get(path + "/1").json() == prepared
        assert po.get(path).json()["context"]["election"]["status"] == "finalized"
        assert po.put(path + "/1", json=period_command(1)).status_code == 409
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 409
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid], ready=False) as (
        unready,
        _,
    ):
        assert unready.get(path).status_code == 403
    with TestClient(
        create_app(database_url, now=clock), base_url="https://testserver"
    ) as anonymous:
        assert anonymous.get(path).status_code == 401


def test_concurrent_period_prepare_replay_and_stale_save_have_one_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _):
        authorization = po.headers["Authorization"]
        barrier = Barrier(2)
        first = period_command()

        def prepare(command: dict) -> tuple[int, dict]:
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                barrier.wait(timeout=10)
                response = peer.put(path + "/1", json=command)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            replay = list(pool.map(prepare, (first, first)))
        assert [status for status, _ in replay] == [200, 200] and replay[0][1] == replay[1][1]
        assert len(po.get(path + "/1/history").json()["items"]) == 1
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            edits = list(pool.map(prepare, (period_command(1), period_command(1))))
        assert sorted(status for status, _ in edits) == [200, 409]
        assert [row["revision"] for row in po.get(path + "/1/history").json()["items"]] == [1, 2]


def test_concurrent_submission_and_new_case_cannot_submit_an_unreviewed_basis(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    clock = ComplaintClock()
    with complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _):
        category = station_categories(po, sid)[0]
        assert po.put(path + "/1", json=period_command()).status_code == 200
        authorization = po.headers["Authorization"]
        barrier = Barrier(2)

        def send(target: str, command: dict) -> tuple[int, dict]:
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                barrier.wait(timeout=10)
                response = peer.post(target, json=command)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            submission = pool.submit(send, path + "/1/submit", period_command(1))
            creation = pool.submit(send, case_path, complaint_payload(category))
            submitted, created = submission.result(timeout=30), creation.result(timeout=30)
        assert (submitted[0], created[0]) in ((200, 422), (409, 201))
        latest = po.get(path + "/1").json()
        if submitted[0] == 200:
            assert latest["status"] == "submitted" and latest["basis_current"]
            assert created[1]["detail"]["code"] == "complaint_late_reason_required"
            assert po.get(case_path).json()["items"] == []
        else:
            assert latest["status"] == "draft" and not latest["basis_current"]
            assert submitted[1]["detail"]["code"] == "complaint_period_review_required"
            assert len(po.get(case_path).json()["items"]) == 1


def test_period_state_schedule_and_revision_conflicts_do_not_replace_formal_records(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, _),
    ):
        assert po.get(path + "/1").status_code == 404
        assert po.get(path + "/1/history").json()["items"] == []
        assert po.get(path + "/0/history").status_code == 404
        assert po.put(path + "/1", json=period_command(1)).status_code == 409
        mismatch = po.put(path + "/1", json=period_command(expected_schedule_revision=1))
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "complaint_schedule_conflict"
        assert po.post(path + "/1/submit", json=period_command()).status_code == 409
        first = po.put(path + "/1", json=period_command()).json()
        assert po.post(path + "/1/amend", json=period_command(1, reason="更正")).status_code == 409
        assert (
            sv.post(
                path + "/1/approve", json=period_command(1, password=READY_PASSWORD)
            ).status_code
            == 409
        )
        submit = period_command(1)
        submitted = po.post(path + "/1/submit", json=submit)
        assert submitted.status_code == 200
        assert po.post(path + "/1/submit", json=submit).json() == submitted.json()
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 409
        assert po.put(path + "/1", json=period_command(1)).status_code == 409
        assert po.post(path + "/1/amend", json=period_command(1)).status_code == 422
        assert po.post(path + "/1/amend", json=period_command(1, reason=" \n")).status_code == 422
        approved = sv.post(path + "/1/approve", json=period_command(1, password=READY_PASSWORD))
        assert approved.status_code == 200
        assert po.put(path + "/1", json=period_command(1)).status_code == 409
        assert po.get(path + "/1?revision=99").status_code == 404
        assert po.get(path + "/1?revision=0").status_code == 422
        assert len(po.get(path + "/1/history").json()["items"]) == 1
        assert po.get(path + "/1").json()["id"] == first["id"]


def test_case_receipt_cannot_move_into_a_submitted_period_through_ordinary_edit(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        category = station_categories(po, sid)[0]
        outside = po.post(
            case_path,
            json=complaint_payload(
                category,
                received_at="2026-11-15T07:29:59+08:00",
            ),
        ).json()
        assert not outside["requires_amendment"]
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        command = complaint_payload(category, expected_revision=1)
        assert po.put(f"{case_path}/{outside['id']}", json=command).status_code == 409
        reasoned = po.post(
            f"{case_path}/{outside['id']}/amend",
            json={
                **command,
                "reason": "核對紙本接收時間後移入已匯報時段",
            },
        )
        assert reasoned.status_code == 200 and reasoned.json()["requires_amendment"]
        assert not reasoned.json()["ever_submitted"]
        assert not po.get(path + "/1").json()["basis_current"]


def test_concurrent_approval_and_case_correction_preserve_approval_and_stale_basis_truth(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    sid, path, case_path = scope["station"]["id"], scope["path"], scope["case_path"]
    clock = ComplaintClock()
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, _),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, reviewer),
    ):
        category = station_categories(po, sid)[0]
        original = po.post(case_path, json=complaint_payload(category)).json()
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        barrier = Barrier(2)

        def send(token: str, target: str, command: dict) -> tuple[int, dict]:
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = token
                barrier.wait(timeout=10)
                response = peer.post(target, json=command)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(
                send,
                sv.headers["Authorization"],
                path + "/1/approve",
                period_command(1, password=READY_PASSWORD),
            )
            correction = pool.submit(
                send,
                po.headers["Authorization"],
                f"{case_path}/{original['id']}/amend",
                complaint_payload(
                    category,
                    expected_revision=1,
                    description="核對後修正描述",
                    reason="紙本資料核對更正",
                ),
            )
            approved, corrected = approval.result(timeout=30), correction.result(timeout=30)
        assert corrected[0] == 200 and approved[0] in (200, 409)
        current = po.get(path + "/1").json()
        assert not current["basis_current"] and not current["approval_valid"]
        assert (
            current["review_required"]
            and current["members"][0]["case_revision_id"] == original["revision_id"]
        )
        if approved[0] == 200:
            assert current["status"] == "approved" and current["approved_by"] == reviewer["id"]
        else:
            assert current["status"] == "submitted" and current["approved_by"] is None
            assert approved[1]["detail"]["code"] == "complaint_period_review_required"
