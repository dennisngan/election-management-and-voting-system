"""P19 received-cohort snapshots with explicit zero and revision-bound review."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from election.server.complaint_categories import (
    ComplaintCommand,
    complaint_digest,
    complaint_replay,
    save_complaint_response,
)
from election.server.complaint_models import ComplaintCase, ComplaintRevision
from election.server.complaint_period_models import ComplaintPeriodCase, ComplaintPeriodRecord
from election.server.complaints import complaint_read_scope, complaint_schedule
from election.server.lifecycle_models import ElectionSchedule
from election.server.models import Account
from election.server.polling import as_utc, station_scope
from election.server.reporting_periods import period_bounds, period_count
from election.server.security import verify_password


class ComplaintPeriodCommand(ComplaintCommand):
    expected_revision: int = Field(ge=0, strict=True)
    expected_schedule_revision: int = Field(ge=1, strict=True)


class ComplaintPeriodAmendment(ComplaintPeriodCommand):
    expected_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An amendment reason is required")
        return value


class ComplaintPeriodApproval(ComplaintPeriodCommand):
    expected_revision: int = Field(ge=1, strict=True)
    password: str = Field(min_length=1, max_length=128, repr=False)


def required_bounds(schedule: ElectionSchedule, index: int) -> tuple[datetime, datetime]:
    try:
        return period_bounds(schedule, index)
    except IndexError:
        raise HTTPException(404, detail={"code": "complaint_period_not_found"}) from None


def cohort_groups(cases: list[ComplaintRevision]) -> list[dict[str, Any]]:
    groups: dict[int, dict[str, Any]] = {}
    for case in cases:
        group = groups.setdefault(
            case.category_revision_id,
            {
                "category_id": case.category_id,
                "category_revision_id": case.category_revision_id,
                "category_revision": case.category_revision,
                "code": case.category_code,
                "label_en": case.category_label_en,
                "label_tc": case.category_label_tc,
                "label_sc": case.category_label_sc,
                "verified_source": case.category_verified_source,
                "source": "verified_reference"
                if case.category_verified_source
                else "project_configured",
                "source_english": case.category_source_english,
                "reference_page": case.category_reference_page,
                "is_other": case.is_other,
                "translation_provenance": "project_translation",
                "total_received": 0,
                "total_completed": 0,
                "total_in_progress": 0,
            },
        )
        group["total_received"] += 1
        group["total_completed" if case.work_status == "completed" else "total_in_progress"] += 1
    return [groups[key] for key in sorted(groups)]


def current_complaint_cases(db: Session, station_id: int) -> list[ComplaintRevision]:
    rows = db.scalars(
        select(ComplaintRevision)
        .join(ComplaintCase, ComplaintCase.id == ComplaintRevision.case_id)
        .where(ComplaintCase.station_id == station_id)
        .order_by(
            ComplaintRevision.case_id,
            ComplaintRevision.revision,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list({row.case_id: row for row in rows}.values())


def case_cohorts(
    rows: list[ComplaintRevision], schedule: ElectionSchedule
) -> tuple[dict[int, list[ComplaintRevision]], int]:
    cohorts: dict[int, list[ComplaintRevision]] = {}
    outside = 0
    step = timedelta(minutes=schedule.reporting_interval_minutes)
    for row in rows:
        if not schedule.planned_opening_at <= row.received_at < schedule.planned_closing_at:
            outside += 1
            continue
        index = 1 + (row.received_at - schedule.planned_opening_at) // step
        cohorts.setdefault(index, []).append(row)
    return cohorts, outside


def cohort_hash(
    station_id: int, index: int, schedule: ElectionSchedule, rows: list[ComplaintRevision]
) -> str:
    start, end = period_bounds(schedule, index)
    return hashlib.sha256(
        json.dumps(
            {
                "station_id": station_id,
                "period_index": index,
                "schedule_revision": schedule.revision,
                "start_at": as_utc(start),
                "end_at": as_utc(end),
                "members": sorted((row.case_id, row.id) for row in rows),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def period_records(db: Session, station_id: int) -> list[ComplaintPeriodRecord]:
    return list(
        db.scalars(
            select(ComplaintPeriodRecord)
            .where(ComplaintPeriodRecord.station_id == station_id)
            .order_by(ComplaintPeriodRecord.period_index, ComplaintPeriodRecord.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def period_members(db: Session, record_ids: list[int]) -> dict[int, list[ComplaintRevision]]:
    result: dict[int, list[ComplaintRevision]] = {}
    if record_ids:
        rows = db.execute(
            select(ComplaintPeriodCase.record_id, ComplaintRevision)
            .join(ComplaintRevision, ComplaintRevision.id == ComplaintPeriodCase.case_revision_id)
            .where(ComplaintPeriodCase.record_id.in_(record_ids))
            .order_by(
                ComplaintPeriodCase.record_id,
                ComplaintPeriodCase.case_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for record_id, row in rows:
            result.setdefault(record_id, []).append(row)
    return result


def complaint_period_view(
    row: ComplaintPeriodRecord,
    members: list[ComplaintRevision],
    *,
    basis_current: bool,
    is_latest_revision: bool = True,
) -> dict[str, Any]:
    approval_valid = row.status == "approved" and basis_current and is_latest_revision
    return {
        "id": row.id,
        "station_id": row.station_id,
        "period_index": row.period_index,
        "revision": row.revision,
        "schedule_revision": row.schedule_revision,
        "start_at": as_utc(row.start_at),
        "end_at": as_utc(row.end_at),
        "status": row.status,
        "basis_at": as_utc(row.basis_at),
        "basis_current": basis_current,
        "is_latest_revision": is_latest_revision,
        "approval_valid": approval_valid,
        "review_required": row.status == "submitted"
        or (row.status == "approved" and not basis_current),
        "total_received": row.total_received,
        "total_completed": row.total_completed,
        "total_in_progress": row.total_in_progress,
        "group_counts": row.group_counts,
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "amendment_reason": row.amendment_reason,
        "submitted_at": as_utc(row.submitted_at),
        "submitted_by": row.submitted_by,
        "approved_at": as_utc(row.approved_at),
        "approved_by": row.approved_by,
        "members": [
            {
                "case_id": member.case_id,
                "case_revision_id": member.id,
                "revision": member.revision,
                "case_reference": member.case_reference,
                "received_at": as_utc(member.received_at),
                "work_status": member.work_status,
                "completed_at": as_utc(member.completed_at),
                "entered_at": as_utc(member.entered_at),
                "actor_id": member.actor_id,
                "category_id": member.category_id,
                "category_revision": member.category_revision,
                "category_code": member.category_code,
                "category_label_en": member.category_label_en,
                "category_label_tc": member.category_label_tc,
                "category_label_sc": member.category_label_sc,
            }
            for member in members
        ],
    }


def current_basis(
    row: ComplaintPeriodRecord, schedule: ElectionSchedule, cases: list[ComplaintRevision]
) -> bool:
    try:
        return (
            row.schedule_revision == schedule.revision
            and (row.start_at, row.end_at) == period_bounds(schedule, row.period_index)
            and row.basis_hash == cohort_hash(row.station_id, row.period_index, schedule, cases)
        )
    except IndexError:
        return False


def complaint_period_snapshot(
    db: Session,
    actor: Account,
    station_id: int,
    now: datetime,
    *,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    station, constituency, election = complaint_read_scope(db, actor, station_id)
    schedule = complaint_schedule(db, election.id)
    records = period_records(db, station_id)
    latest = {row.period_index: row for row in records}
    count = period_count(schedule) if schedule else 0
    cohorts, outside = (
        case_cohorts(current_complaint_cases(db, station_id), schedule) if schedule else ({}, 0)
    )
    hashes = {
        index: current_basis(row, schedule, cohorts.get(index, [])) if schedule else False
        for index, row in latest.items()
    }
    indexes = range(offset + 1, min(count, offset + limit) + 1)
    selected = [latest[index] for index in indexes if index in latest]
    members = period_members(db, [row.id for row in selected])
    items = []
    for index in indexes:
        assert schedule is not None
        start, end = period_bounds(schedule, index)
        row = latest.get(index)
        record = (
            complaint_period_view(row, members.get(row.id, []), basis_current=hashes[index])
            if row
            else None
        )
        items.append(
            {
                "period_index": index,
                "start_at": as_utc(start),
                "end_at": as_utc(end),
                "record": record,
                "status": row.status if row else "missing",
                "basis_current": hashes[index] if row else False,
                "approval_valid": record["approval_valid"] if record else False,
                "review_required": record["review_required"] if record else False,
            }
        )
    return {
        "context": {
            "election": {"id": election.id, "name": election.name, "status": election.status},
            "constituency": {
                "id": constituency.id,
                "name": constituency.name,
                "code": constituency.code,
            },
            "station": {"id": station.id, "name": station.name, "code": station.code},
        },
        "schedule_state": "configured" if schedule else "unavailable",
        "schedule": {
            "revision": schedule.revision,
            "planned_opening_at": as_utc(schedule.planned_opening_at),
            "planned_closing_at": as_utc(schedule.planned_closing_at),
            "reporting_interval_minutes": schedule.reporting_interval_minutes,
        }
        if schedule
        else None,
        "period_count": count,
        "offset": offset,
        "limit": limit,
        "items": items,
        "summary": {
            "required": count,
            "approved_current": sum(
                row.status == "approved" and hashes[index]
                for index, row in latest.items()
                if 1 <= index <= count
            ),
            "missing": count - sum(1 <= index <= count for index in latest),
        },
        "outside_coverage_case_count": outside,
        "generated_at": as_utc(now),
    }


def complaint_periods_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/complaint-periods", tags=["Complaint periods"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read_periods(
        station_id: int,
        db: Database,
        actor: Ready,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> dict[str, Any]:
        return complaint_period_snapshot(
            db, actor, station_id, timestamp(), offset=offset, limit=limit
        )

    def execute(
        station_id: int,
        index: int,
        action: str,
        data: ComplaintPeriodCommand,
        db: Session,
        actor: Account,
        response: Response,
    ) -> dict[str, Any]:
        role = "supervisor" if action == "approve" else "polling_officer"
        if actor.role != role:
            raise HTTPException(403, detail={"code": role + "_required"})
        _, _, election = station_scope(db, actor, station_id, write=True)
        if isinstance(data, ComplaintPeriodApproval):
            password_hash = db.scalar(
                select(Account.password_hash).where(Account.id == actor.id).with_for_update()
            )
            assert password_hash is not None
            if not verify_password(password_hash, data.password):
                raise HTTPException(401, detail={"code": "invalid_credentials"})
        command_action = "period_" + action
        digest = complaint_digest(
            data, actor.id, command_action, election.id, station_id=station_id, target_id=index
        )
        previous = complaint_replay(db, data.request_id, digest, response)
        if previous is not None:
            return previous
        schedule = complaint_schedule(db, election.id)
        if schedule is None:
            raise HTTPException(409, detail={"code": "schedule_required"})
        start, end = required_bounds(schedule, index)
        if data.expected_schedule_revision != schedule.revision:
            raise HTTPException(409, detail={"code": "complaint_schedule_conflict"})
        heads = current_complaint_cases(db, station_id)
        cohorts, _ = case_cohorts(heads, schedule)
        cases = cohorts.get(index, [])
        current = next(
            (row for row in reversed(period_records(db, station_id)) if row.period_index == index),
            None,
        )
        if data.expected_revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        if action in ("save", "amend"):
            if action == "amend":
                if current is None or current.status not in ("submitted", "approved"):
                    raise HTTPException(409, detail={"code": "complaint_period_state_conflict"})
                assert isinstance(data, ComplaintPeriodAmendment)
                reason = data.reason
            else:
                if current and current.status != "draft":
                    raise HTTPException(409, detail={"code": "complaint_period_state_conflict"})
                reason = current.amendment_reason if current else ""
            completed = sum(case.work_status == "completed" for case in cases)
            row = ComplaintPeriodRecord(
                station_id=station_id,
                period_index=index,
                revision=data.expected_revision + 1,
                schedule_revision=schedule.revision,
                start_at=start,
                end_at=end,
                status="draft",
                basis_at=now,
                basis_hash=cohort_hash(station_id, index, schedule, cases),
                total_received=len(cases),
                total_completed=completed,
                total_in_progress=len(cases) - completed,
                group_counts=cohort_groups(cases),
                entered_at=now,
                actor_id=actor.id,
                amendment_reason=reason,
                submitted_at=None,
                submitted_by=None,
                approved_at=None,
                approved_by=None,
            )
            db.add(row)
            db.flush()
            db.add_all(
                [
                    ComplaintPeriodCase(
                        record_id=row.id, case_id=case.case_id, case_revision_id=case.id
                    )
                    for case in cases
                ]
            )
            members = cases
        else:
            if current is None:
                raise HTTPException(409, detail={"code": "complaint_period_state_conflict"})
            if not current_basis(current, schedule, cases):
                raise HTTPException(409, detail={"code": "complaint_period_review_required"})
            if current.status != ("submitted" if action == "approve" else "draft"):
                raise HTTPException(409, detail={"code": "complaint_period_state_conflict"})
            if end > now:
                raise HTTPException(422, detail={"code": "complaint_period_not_ended"})
            row = current
            members = period_members(db, [row.id]).get(row.id, [])
            if action == "approve":
                row.status, row.approved_at, row.approved_by = "approved", now, actor.id
            else:
                row.status, row.submitted_at, row.submitted_by = "submitted", now, actor.id
                if members:
                    db.execute(
                        update(ComplaintCase)
                        .where(ComplaintCase.id.in_([case.case_id for case in members]))
                        .values(ever_submitted=True)
                    )
        result = complaint_period_view(row, members, basis_current=True)
        save_complaint_response(
            db,
            data,
            digest,
            actor.id,
            command_action,
            election.id,
            station_id,
            result,
            now,
        )
        db.commit()
        return result

    @router.put("/{period_index}")
    def save(
        station_id: int,
        period_index: int,
        data: ComplaintPeriodCommand,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "save", data, db, actor, response)

    @router.post("/{period_index}/submit")
    def submit(
        station_id: int,
        period_index: int,
        data: ComplaintPeriodCommand,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "submit", data, db, actor, response)

    @router.post("/{period_index}/approve")
    def approve(
        station_id: int,
        period_index: int,
        data: ComplaintPeriodApproval,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "approve", data, db, actor, response)

    @router.post("/{period_index}/amend")
    def amend(
        station_id: int,
        period_index: int,
        data: ComplaintPeriodAmendment,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "amend", data, db, actor, response)

    def read_records(
        station_id: int,
        period_index: int,
        db: Session,
        actor: Account,
    ) -> list[dict[str, Any]]:
        _, _, election = complaint_read_scope(db, actor, station_id)
        schedule = complaint_schedule(db, election.id)
        if schedule is None:
            raise HTTPException(404, detail={"code": "complaint_period_not_found"})
        cases = case_cohorts(current_complaint_cases(db, station_id), schedule)[0].get(
            period_index, []
        )
        rows = [row for row in period_records(db, station_id) if row.period_index == period_index]
        if not rows:
            required_bounds(schedule, period_index)
        members = period_members(db, [row.id for row in rows])
        return [
            complaint_period_view(
                row,
                members.get(row.id, []),
                basis_current=current_basis(row, schedule, cases),
                is_latest_revision=row.id == rows[-1].id,
            )
            for row in rows
        ]

    @router.get("/{period_index}/history")
    def history(
        station_id: int,
        period_index: int,
        db: Database,
        actor: Ready,
    ) -> dict[str, Any]:
        return {"items": read_records(station_id, period_index, db, actor)}

    @router.get("/{period_index}")
    def read_record(
        station_id: int,
        period_index: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        records = read_records(station_id, period_index, db, actor)
        row: dict[str, Any] | None = next(
            (
                record
                for record in reversed(records)
                if revision is None or record["revision"] == revision
            ),
            None,
        )
        if row is None:
            raise HTTPException(404, detail={"code": "complaint_period_record_not_found"})
        return row

    return router
