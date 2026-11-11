"""Assigned station complaint case work, independent of formal period approval."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.complaint_categories import (
    ComplaintCommand,
    complaint_digest,
    complaint_replay,
    current_category_revision,
    save_complaint_response,
)
from election.server.complaint_models import (
    ComplaintCase,
    ComplaintCategory,
    ComplaintCategoryRevision,
    ComplaintReference,
    ComplaintRevision,
)
from election.server.complaint_period_models import ComplaintPeriodRecord
from election.server.configuration_models import Constituency, Election
from election.server.lifecycle_models import ElectionSchedule
from election.server.models import Account
from election.server.station_access import station_scope
from election.server.station_models import PollingStation
from election.server.timestamps import as_utc


class ComplaintInput(ComplaintCommand):
    case_reference: str = Field(min_length=1, max_length=64)
    received_at: AwareDatetime
    category_id: int = Field(gt=0, strict=True)
    expected_category_revision: int = Field(ge=1, strict=True)
    description: str = Field(max_length=4000)
    work_status: Literal["in_progress", "completed"]
    completed_at: AwareDatetime | None = None
    reason: str = Field(default="", max_length=1000)

    @field_validator("case_reference", mode="before")
    @classmethod
    def meaningful_reference(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("A nonblank reference is required")
        return value

    @field_validator("received_at", "completed_at")
    @classmethod
    def actual_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        try:
            normalized = value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Time is outside the supported UTC range") from None
        if normalized.year < 1000:
            raise ValueError("Time is outside the supported UTC range")
        return normalized

    @model_validator(mode="after")
    def consistent_completion(self) -> Self:
        if self.work_status == "in_progress" and self.completed_at is not None:
            raise ValueError("An in-progress case has no completion time")
        if self.work_status == "completed" and (
            self.completed_at is None or self.completed_at < self.received_at
        ):
            raise ValueError("Completion must be at or after receipt")
        return self


class ComplaintEdit(ComplaintInput):
    expected_revision: int = Field(ge=1, strict=True)


class ComplaintAmendment(ComplaintEdit):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An amendment reason is required")
        return value


def complaint_schedule(db: Session, election_id: int) -> ElectionSchedule | None:
    return db.scalar(
        select(ElectionSchedule)
        .where(ElectionSchedule.election_id == election_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def complaint_read_scope(
    db: Session, actor: Account, station_id: int
) -> tuple[PollingStation, Constituency, Election]:
    station, constituency, election = station_scope(db, actor, station_id)
    # Activation holds Election before Schedule and Station. Readers share that
    # election boundary before locking Schedule/cases, including draft scopes.
    current = db.scalar(
        select(Election)
        .where(Election.id == election.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert current is not None
    return station, constituency, current


def complaint_case_at(db: Session, station_id: int, case_id: int) -> ComplaintCase:
    case = db.scalar(
        select(ComplaintCase)
        .where(
            ComplaintCase.id == case_id,
            ComplaintCase.station_id == station_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(404, detail={"code": "complaint_not_found"})
    return case


def complaint_history(db: Session, case_id: int) -> list[ComplaintRevision]:
    return list(
        db.scalars(
            select(ComplaintRevision)
            .where(ComplaintRevision.case_id == case_id)
            .order_by(ComplaintRevision.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def protected_complaint_ranges(db: Session, station_id: int) -> list[tuple[datetime, datetime]]:
    rows = db.execute(
        select(ComplaintPeriodRecord.start_at, ComplaintPeriodRecord.end_at)
        .where(
            ComplaintPeriodRecord.station_id == station_id,
            ComplaintPeriodRecord.status.in_(("submitted", "approved")),
        )
        .with_for_update()
    )
    return [(start, end) for start, end in rows]


def in_submitted_period(actual: datetime, ranges: list[tuple[datetime, datetime]]) -> bool:
    return any(start <= actual < end for start, end in ranges)


def complaint_revision_view(
    case: ComplaintCase,
    row: ComplaintRevision,
    schedule: ElectionSchedule | None,
    *,
    protected_ranges: list[tuple[datetime, datetime]] | None = None,
) -> dict[str, Any]:
    period_index = None
    coverage = "schedule_unavailable"
    if schedule:
        coverage = "outside_configured_periods"
        if schedule.planned_opening_at <= row.received_at < schedule.planned_closing_at:
            period_index = 1 + (
                (row.received_at - schedule.planned_opening_at)
                // timedelta(minutes=schedule.reporting_interval_minutes)
            )
            coverage = "within_configured_periods"
    return {
        "id": case.id,
        "station_id": case.station_id,
        "ever_submitted": case.ever_submitted,
        "requires_amendment": case.ever_submitted
        or in_submitted_period(
            row.received_at,
            protected_ranges or [],
        ),
        "revision_id": row.id,
        "revision": row.revision,
        "case_reference": row.case_reference,
        "received_at": as_utc(row.received_at),
        "category_id": row.category_id,
        "category_revision": row.category_revision,
        "category_code": row.category_code,
        "category_label_en": row.category_label_en,
        "category_label_tc": row.category_label_tc,
        "category_label_sc": row.category_label_sc,
        "category_verified_source": row.category_verified_source,
        "category_source_english": row.category_source_english,
        "category_reference_page": row.category_reference_page,
        "category_source": (
            "verified_reference" if row.category_verified_source else "project_configured"
        ),
        "translation_provenance": "project_translation",
        "is_other": row.is_other,
        "description": row.description,
        "work_status": row.work_status,
        "completed_at": as_utc(row.completed_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "amendment_reason": row.amendment_reason,
        "period_index": period_index,
        "coverage_status": coverage,
        "schedule_revision": schedule.revision if schedule else None,
    }


def complaint_snapshot(
    db: Session, actor: Account, station_id: int, now: datetime
) -> dict[str, Any]:
    station, constituency, election = complaint_read_scope(db, actor, station_id)
    schedule = complaint_schedule(db, election.id)
    cases = list(
        db.scalars(
            select(ComplaintCase)
            .where(ComplaintCase.station_id == station_id)
            .order_by(ComplaintCase.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    revisions = list(
        db.scalars(
            select(ComplaintRevision)
            .join(ComplaintCase, ComplaintCase.id == ComplaintRevision.case_id)
            .where(ComplaintCase.station_id == station_id)
            .order_by(ComplaintRevision.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    latest = {row.case_id: row for row in revisions}
    protected_ranges = protected_complaint_ranges(db, station_id)
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
        "items": [
            complaint_revision_view(
                case,
                latest[case.id],
                schedule,
                protected_ranges=protected_ranges,
            )
            for case in cases
        ],
        "schedule_state": "configured" if schedule else "unavailable",
        "schedule": {
            "revision": schedule.revision,
            "planned_opening_at": as_utc(schedule.planned_opening_at),
            "planned_closing_at": as_utc(schedule.planned_closing_at),
            "reporting_interval_minutes": schedule.reporting_interval_minutes,
        }
        if schedule
        else None,
        "generated_at": as_utc(now),
    }


def complaints_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/complaints", tags=["Complaints"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read_cases(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        return complaint_snapshot(db, actor, station_id, timestamp())

    def write_case(
        station_id: int,
        data: ComplaintInput,
        db: Session,
        actor: Account,
        response: Response,
        *,
        case_id: int | None = None,
        amendment: bool = False,
    ) -> dict[str, Any]:
        if actor.role != "polling_officer":
            raise HTTPException(403, detail={"code": "polling_officer_required"})
        _, _, election = station_scope(db, actor, station_id, write=True)
        action = (
            "case_created" if case_id is None else "case_amended" if amendment else "case_edited"
        )
        digest = complaint_digest(
            data, actor.id, action, election.id, station_id=station_id, target_id=case_id
        )
        previous = complaint_replay(db, data.request_id, digest, response)
        if previous is not None:
            return previous
        schedule = complaint_schedule(db, election.id)
        if schedule is None:
            raise HTTPException(409, detail={"code": "schedule_required"})
        case = complaint_case_at(db, station_id, case_id) if case_id is not None else None
        current = complaint_history(db, case.id)[-1] if case else None
        if case is not None:
            assert isinstance(data, ComplaintEdit) and current is not None
            if current.revision != data.expected_revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        received_at = data.received_at.replace(tzinfo=None)
        completed_at = data.completed_at.replace(tzinfo=None) if data.completed_at else None
        if received_at > now or (completed_at and completed_at > now):
            raise HTTPException(422, detail={"code": "complaint_validation"})
        protected_ranges = protected_complaint_ranges(db, station_id)
        if case is not None and current is not None:
            required = case.ever_submitted or any(
                in_submitted_period(actual, protected_ranges)
                for actual in (current.received_at, received_at)
            )
            if required and not amendment:
                raise HTTPException(409, detail={"code": "complaint_amendment_required"})
        elif in_submitted_period(received_at, protected_ranges) and not data.reason.strip():
            raise HTTPException(422, detail={"code": "complaint_late_reason_required"})
        category = db.scalar(
            select(ComplaintCategory)
            .where(
                ComplaintCategory.id == data.category_id,
                ComplaintCategory.election_id == election.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if category is None:
            raise HTTPException(404, detail={"code": "complaint_category_not_found"})
        if current and current.category_id == category.id:
            labels = db.scalar(
                select(ComplaintCategoryRevision)
                .where(ComplaintCategoryRevision.id == current.category_revision_id)
                .with_for_update()
            )
            assert labels is not None
        else:
            labels = current_category_revision(db, category.id)
            if labels.revision != data.expected_category_revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            if not labels.enabled:
                raise HTTPException(422, detail={"code": "complaint_category_disabled"})
        if labels.description_required and not data.description.strip():
            raise HTTPException(422, detail={"code": "complaint_description_required"})
        alias = db.scalar(
            select(ComplaintReference)
            .where(
                ComplaintReference.station_id == station_id,
                ComplaintReference.reference == data.case_reference,
            )
            .with_for_update()
        )
        if alias is not None and (case is None or alias.case_id != case.id):
            raise HTTPException(409, detail={"code": "complaint_reference_exists"})
        if case is None:
            case = ComplaintCase(station_id=station_id, ever_submitted=False)
            db.add(case)
            db.flush()
        if alias is None:
            db.add(
                ComplaintReference(
                    station_id=station_id,
                    reference=data.case_reference,
                    case_id=case.id,
                )
            )
        row = ComplaintRevision(
            case_id=case.id,
            revision=current.revision + 1 if current else 1,
            case_reference=data.case_reference,
            received_at=received_at,
            category_id=category.id,
            category_revision_id=labels.id,
            category_revision=labels.revision,
            category_code=category.code,
            category_label_en=labels.label_en,
            category_label_tc=labels.label_tc,
            category_label_sc=labels.label_sc,
            category_verified_source=category.verified_source,
            category_source_english=category.source_english,
            category_reference_page=category.reference_page,
            is_other=category.is_other,
            description=data.description,
            work_status=data.work_status,
            completed_at=completed_at,
            entered_at=now,
            actor_id=actor.id,
            amendment_reason=data.reason,
        )
        db.add(row)
        db.flush()
        result = complaint_revision_view(case, row, schedule, protected_ranges=protected_ranges)
        save_complaint_response(
            db,
            data,
            digest,
            actor.id,
            action,
            election.id,
            station_id,
            result,
            now,
        )
        db.commit()
        return result

    @router.post("", status_code=201)
    def create_case(
        station_id: int, data: ComplaintInput, db: Database, actor: Ready, response: Response
    ) -> dict[str, Any]:
        return write_case(station_id, data, db, actor, response)

    @router.put("/{case_id}")
    def edit_case(
        station_id: int,
        case_id: int,
        data: ComplaintEdit,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return write_case(station_id, data, db, actor, response, case_id=case_id)

    @router.post("/{case_id}/amend")
    def amend_case(
        station_id: int,
        case_id: int,
        data: ComplaintAmendment,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return write_case(station_id, data, db, actor, response, case_id=case_id, amendment=True)

    def read_case_rows(
        station_id: int, case_id: int, db: Session, actor: Account
    ) -> tuple[ComplaintCase, list[ComplaintRevision], ElectionSchedule | None]:
        _, _, election = complaint_read_scope(db, actor, station_id)
        schedule = complaint_schedule(db, election.id)
        case = complaint_case_at(db, station_id, case_id)
        return case, complaint_history(db, case_id), schedule

    @router.get("/{case_id}/history")
    def read_history(station_id: int, case_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        case, rows, schedule = read_case_rows(station_id, case_id, db, actor)
        protected_ranges = protected_complaint_ranges(db, station_id)
        return {
            "items": [
                complaint_revision_view(
                    case,
                    row,
                    schedule,
                    protected_ranges=protected_ranges,
                )
                for row in rows
            ]
        }

    @router.get("/{case_id}")
    def read_case(
        station_id: int,
        case_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        case, rows, schedule = read_case_rows(station_id, case_id, db, actor)
        row = (
            rows[-1]
            if revision is None
            else next((candidate for candidate in rows if candidate.revision == revision), None)
        )
        if row is None:
            raise HTTPException(404, detail={"code": "complaint_revision_not_found"})
        return complaint_revision_view(
            case, row, schedule, protected_ranges=protected_complaint_ranges(db, station_id)
        )

    return router
