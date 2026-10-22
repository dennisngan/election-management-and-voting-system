"""Normal external turnout, exact period review and dependent approval validity."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.lifecycle_models import ElectionSchedule
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc, station_scope
from election.server.security import verify_password
from election.server.turnout_models import TurnoutRecord, TurnoutRequest

MAX_TOTAL = 9223372036854775807


class TurnoutCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    expected_schedule_revision: int = Field(strict=True, ge=1)


class TurnoutDraft(TurnoutCommand):
    supplied_hourly: int | None = Field(default=None, strict=True, ge=0, le=MAX_TOTAL)
    supplied_cumulative: int | None = Field(default=None, strict=True, ge=0, le=MAX_TOTAL)
    source_context: str = Field(default="", max_length=2000)
    event_at: AwareDatetime | None = None

    @field_validator("event_at")
    @classmethod
    def supported_utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        try:
            normalized = value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Unsupported UTC event time") from None
        if normalized.year < 1000:
            raise ValueError("Unsupported UTC event time")
        return normalized


class TurnoutAmendment(TurnoutDraft):
    amendment_reason: str = Field(min_length=1, max_length=2000)


class TurnoutApproval(TurnoutCommand):
    password: str = Field(min_length=1, max_length=128, repr=False)


def invalid() -> NoReturn:
    raise HTTPException(422, detail={"code": "turnout_validation"})


def period_count(schedule: ElectionSchedule) -> int:
    span = schedule.planned_closing_at - schedule.planned_opening_at
    microseconds = (span.days * 86400 + span.seconds) * 1_000_000 + span.microseconds
    interval = schedule.reporting_interval_minutes * 60 * 1_000_000
    return (microseconds + interval - 1) // interval


def period_bounds(schedule: ElectionSchedule, index: int) -> tuple[datetime, datetime]:
    if index < 1 or index > period_count(schedule):
        raise HTTPException(404, detail={"code": "turnout_period_not_found"})
    step = timedelta(minutes=schedule.reporting_interval_minutes)
    start = schedule.planned_opening_at + (index - 1) * step
    # Add only the remaining duration at the last partial period, so even a
    # closing date at datetime's upper bound never overflows during pagination.
    return start, start + min(step, schedule.planned_closing_at - start)


def turnout_record_view(row: TurnoutRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "station_id": row.station_id,
        "period_index": row.period_index,
        "revision": row.revision,
        "schedule_revision": row.schedule_revision,
        "start_at": as_utc(row.start_at),
        "end_at": as_utc(row.end_at),
        "provenance": "external_manual",
        "supplied_hourly": row.supplied_hourly,
        "supplied_cumulative": row.supplied_cumulative,
        "source_context": row.source_context,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "status": row.status,
        "amendment_reason": row.amendment_reason,
        "submitted_at": as_utc(row.submitted_at),
        "submitted_by": row.submitted_by,
        "approved_at": as_utc(row.approved_at),
        "approved_by": row.approved_by,
        "derived_hourly": row.derived_hourly,
        "derived_cumulative_start": row.derived_cumulative_start,
        "derived_cumulative_end": row.derived_cumulative_end,
        "basis_predecessor_record_id": row.basis_predecessor_record_id,
        "basis_predecessor_revision": row.basis_predecessor_revision,
    }


def current_records(db: Session, station_id: int) -> dict[int, TurnoutRecord]:
    rows = db.scalars(
        select(TurnoutRecord)
        .where(TurnoutRecord.station_id == station_id)
        .order_by(TurnoutRecord.period_index, TurnoutRecord.revision)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {row.period_index: row for row in rows}


def approved_prefix(
    records: dict[int, TurnoutRecord], schedule: ElectionSchedule
) -> tuple[dict[str, Any], set[int]]:
    prefix: dict[str, Any] = {
        "periods": 0,
        "hourly_total": None,
        "cumulative_end": None,
        "covered_until": None,
    }
    valid: set[int] = set()
    predecessor: TurnoutRecord | None = None
    cumulative = 0
    for index in sorted(records):
        row = records[index]
        if index != prefix["periods"] + 1 or index > period_count(schedule):
            break
        start, end = period_bounds(schedule, index)
        if (
            row.status != "approved"
            or row.schedule_revision != schedule.revision
            or (row.start_at, row.end_at) != (start, end)
            or row.basis_predecessor_record_id != (predecessor.id if predecessor else None)
            or row.basis_predecessor_revision != (predecessor.revision if predecessor else None)
            or row.derived_cumulative_start != cumulative
            or row.derived_hourly is None
            or row.derived_cumulative_end is None
            or row.derived_cumulative_end != cumulative + row.derived_hourly
        ):
            break
        valid.add(row.id)
        cumulative = row.derived_cumulative_end
        prefix.update(
            periods=index,
            hourly_total=cumulative,
            cumulative_end=cumulative,
            covered_until=as_utc(end),
        )
        predecessor = row
    return prefix, valid


def locked_schedule(db: Session, election_id: int) -> ElectionSchedule:
    schedule = db.scalar(
        select(ElectionSchedule)
        .where(ElectionSchedule.election_id == election_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if schedule is None:
        raise HTTPException(409, detail={"code": "schedule_not_configured"})
    return schedule


def turnout_snapshot(
    db: Session,
    actor: Account,
    station_id: int,
    now: datetime,
    *,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= 1000:
        invalid()
    station, constituency, election = station_scope(db, actor, station_id)
    # Every turnout write takes the schedule lock before touching record history.
    # Using it for reads also avoids a Station→Schedule inversion with activation.
    schedule = locked_schedule(db, election.id)
    records = current_records(db, station_id)
    prefix, valid = approved_prefix(records, schedule)
    count = period_count(schedule)
    items = []
    for index in range(offset + 1, min(offset + limit, count) + 1):
        start, end = period_bounds(schedule, index)
        row = records.get(index)
        items.append(
            {
                "period_index": index,
                "start_at": as_utc(start),
                "end_at": as_utc(end),
                "status": row.status if row else "missing",
                "record": turnout_record_view(row) if row else None,
                "approval_valid": bool(row and row.id in valid),
                "review_required": bool(row and row.status == "approved" and row.id not in valid),
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
        "schedule": {
            "revision": schedule.revision,
            "planned_opening_at": as_utc(schedule.planned_opening_at),
            "planned_closing_at": as_utc(schedule.planned_closing_at),
            "reporting_interval_minutes": schedule.reporting_interval_minutes,
        },
        "period_count": count,
        "offset": offset,
        "limit": limit,
        "items": items,
        "approved_prefix": prefix,
        "server_time": as_utc(now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now),
    }


def validate_content(row: TurnoutRecord, now: datetime, *, complete: bool) -> None:
    if row.event_at is not None and row.event_at > now:
        invalid()
    if complete and (
        (row.supplied_hourly is None and row.supplied_cumulative is None)
        or not row.source_context.strip()
        or row.event_at is None
        or row.event_at < row.end_at
        or row.end_at > now
    ):
        invalid()


def turnout_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/turnout", tags=["turnout"])
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(
        station_id: int,
        db: Database,
        actor: Actor,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> dict[str, Any]:
        return turnout_snapshot(db, actor, station_id, timestamp(), offset=offset, limit=limit)

    @router.get("/{period_index}/history")
    def history(station_id: int, period_index: int, db: Database, actor: Actor) -> dict[str, Any]:
        _, _, election = station_scope(db, actor, station_id)
        period_bounds(locked_schedule(db, election.id), period_index)
        rows = db.scalars(
            select(TurnoutRecord)
            .where(
                TurnoutRecord.station_id == station_id, TurnoutRecord.period_index == period_index
            )
            .order_by(TurnoutRecord.revision)
            .with_for_update()
        )
        return {"items": [turnout_record_view(row) for row in rows]}

    @router.get("/{period_index}")
    def record(
        station_id: int, period_index: int, db: Database, actor: Actor, revision: int | None = None
    ) -> dict[str, Any]:
        _, _, election = station_scope(db, actor, station_id)
        period_bounds(locked_schedule(db, election.id), period_index)
        query = select(TurnoutRecord).where(
            TurnoutRecord.station_id == station_id, TurnoutRecord.period_index == period_index
        )
        if revision is not None:
            query = query.where(TurnoutRecord.revision == revision)
        row = db.scalar(query.order_by(TurnoutRecord.revision.desc()).limit(1).with_for_update())
        if row is None:
            raise HTTPException(404, detail={"code": "turnout_record_not_found"})
        return turnout_record_view(row)

    def execute(
        station_id: int,
        index: int,
        action: str,
        data: TurnoutCommand,
        db: Session,
        actor: Account,
    ) -> dict[str, Any]:
        role = "supervisor" if action == "approve" else "polling_officer"
        if actor.role != role:
            raise HTTPException(403, detail={"code": role + "_required"})
        _, constituency, election = station_scope(db, actor, station_id, write=True)
        if isinstance(data, TurnoutApproval):
            # Reconfirm the current credential even for a cached approval outcome.
            password_hash = db.scalar(
                select(Account.password_hash).where(Account.id == actor.id).with_for_update()
            )
            if not verify_password(password_hash, data.password):
                raise HTTPException(401, detail={"code": "invalid_credentials"})
        digest = hashlib.sha256(
            json.dumps(
                {
                    "station_id": station_id,
                    "period_index": index,
                    "actor_id": actor.id,
                    "action": action,
                    "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        replay = db.scalar(
            select(TurnoutRequest)
            .where(TurnoutRequest.request_id == str(data.request_id))
            .with_for_update()
        )
        if replay:
            if replay.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return replay.response
        schedule = locked_schedule(db, election.id)
        start, end = period_bounds(schedule, index)
        if data.expected_schedule_revision != schedule.revision:
            raise HTTPException(409, detail={"code": "turnout_schedule_conflict"})
        records = current_records(db, station_id)
        current = records.get(index)
        if data.expected_revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        if isinstance(data, TurnoutDraft):
            amendment = action == "amend"
            if amendment:
                if not current or current.status not in ("submitted", "approved"):
                    raise HTTPException(409, detail={"code": "turnout_state_conflict"})
                assert isinstance(data, TurnoutAmendment)
                if not data.amendment_reason.strip():
                    invalid()
            elif current and current.status != "draft":
                raise HTTPException(409, detail={"code": "turnout_state_conflict"})
            row = TurnoutRecord(
                station_id=station_id,
                period_index=index,
                revision=data.expected_revision + 1,
                schedule_revision=schedule.revision,
                start_at=start,
                end_at=end,
                supplied_hourly=data.supplied_hourly,
                supplied_cumulative=data.supplied_cumulative,
                source_context=data.source_context,
                event_at=data.event_at.replace(tzinfo=None) if data.event_at else None,
                entered_at=now,
                actor_id=actor.id,
                status="draft",
                amendment_reason=data.amendment_reason
                if isinstance(data, TurnoutAmendment)
                else current.amendment_reason
                if current
                else "",
                submitted_at=None,
                submitted_by=None,
                approved_at=None,
                approved_by=None,
                derived_hourly=None,
                derived_cumulative_start=None,
                derived_cumulative_end=None,
                basis_predecessor_record_id=None,
                basis_predecessor_revision=None,
            )
            validate_content(row, now, complete=False)
            db.add(row)
            db.flush()
        else:
            if not current:
                raise HTTPException(409, detail={"code": "turnout_state_conflict"})
            if current.status == "approved" and action == "approve":
                _, valid = approved_prefix(records, schedule)
                if current.id not in valid:
                    raise HTTPException(409, detail={"code": "turnout_review_required"})
            if current.status != ("submitted" if action == "approve" else "draft"):
                raise HTTPException(409, detail={"code": "turnout_state_conflict"})
            row = current
            validate_content(row, now, complete=True)
            if action == "approve":
                if row.schedule_revision != schedule.revision or (row.start_at, row.end_at) != (
                    start,
                    end,
                ):
                    raise HTTPException(409, detail={"code": "turnout_review_required"})
                _, valid = approved_prefix(records, schedule)
                predecessor = records.get(index - 1) if index > 1 else None
                if index > 1 and (not predecessor or predecessor.id not in valid):
                    raise HTTPException(409, detail={"code": "turnout_previous_period_required"})
                baseline = predecessor.derived_cumulative_end if predecessor else 0
                assert baseline is not None
                hourly = row.supplied_hourly
                if hourly is None:
                    assert row.supplied_cumulative is not None
                    hourly = row.supplied_cumulative - baseline
                cumulative = baseline + hourly
                if (
                    hourly < 0
                    or cumulative > MAX_TOTAL
                    or (
                        row.supplied_cumulative is not None
                        and row.supplied_cumulative != cumulative
                    )
                ):
                    invalid()
                row.derived_hourly = hourly
                row.derived_cumulative_start = baseline
                row.derived_cumulative_end = cumulative
                row.basis_predecessor_record_id = predecessor.id if predecessor else None
                row.basis_predecessor_revision = predecessor.revision if predecessor else None
                row.status, row.approved_at, row.approved_by = "approved", now, actor.id
            else:
                row.status, row.submitted_at, row.submitted_by = "submitted", now, actor.id
        result = turnout_record_view(row)
        db.add(
            TurnoutRequest(
                request_id=str(data.request_id),
                station_id=station_id,
                actor_id=actor.id,
                digest=digest,
                response=result,
            )
        )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="turnout_" + action,
                occurred_at=now,
                details={
                    "election_id": election.id,
                    "constituency_id": constituency.id,
                    "station_id": station_id,
                    "record": result,
                },
            )
        )
        db.commit()
        return result

    @router.put("/{period_index}")
    def save(
        station_id: int, period_index: int, data: TurnoutDraft, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "save", data, db, actor)

    @router.post("/{period_index}/submit")
    def submit(
        station_id: int, period_index: int, data: TurnoutCommand, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "submit", data, db, actor)

    @router.post("/{period_index}/approve")
    def approve(
        station_id: int, period_index: int, data: TurnoutApproval, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "approve", data, db, actor)

    @router.post("/{period_index}/amend")
    def amend(
        station_id: int, period_index: int, data: TurnoutAmendment, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, period_index, "amend", data, db, actor)

    return router
