"""Station polling-event drafts, exact-revision review and preserved amendments."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.lifecycle_models import ActiveElection, ElectionSchedule
from election.server.models import Account, AuditEvent
from election.server.polling_models import PollingRecord, PollingRequest
from election.server.security import verify_password
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation

type PollingKind = Literal[
    "opening", "admission_closure", "queue_clear_estimate", "service_completion"
]
KINDS = ("opening", "admission_closure", "queue_clear_estimate", "service_completion")


class PollingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    request_id: UUID


class PollingDraft(PollingCommand):
    event_at: AwareDatetime | None = None
    estimated_clear_at: AwareDatetime | None = None
    reason: str = Field(default="", max_length=2000)


class PollingAmendment(PollingDraft):
    reason: str = Field(min_length=1, max_length=2000)
    event_reason: str | None = Field(default=None, max_length=2000)


class PollingApproval(PollingCommand):
    password: str = Field(min_length=1, max_length=128, repr=False)


def as_utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


def stored_time(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC).replace(tzinfo=None) if value else None


def record_view(row: PollingRecord) -> dict[str, Any]:
    opening_status = None
    if row.kind == "opening":
        opening_status = (
            "missing"
            if row.event_at is None
            else "delayed"
            if row.event_at > row.planned_at
            else "on_time"
        )
    return {
        "station_id": row.station_id,
        "kind": row.kind,
        "revision": row.revision,
        "status": row.status,
        "event_at": as_utc(row.event_at),
        "estimated_clear_at": as_utc(row.estimated_clear_at),
        "reason": row.reason,
        "amendment_reason": row.amendment_reason,
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "submitted_at": as_utc(row.submitted_at),
        "submitted_by": row.submitted_by,
        "approved_at": as_utc(row.approved_at),
        "approved_by": row.approved_by,
        "schedule_revision": row.schedule_revision,
        "planned_at": as_utc(row.planned_at),
        "opening_status": opening_status,
    }


def station_scope(
    db: Session, actor: Account, station_id: int, *, write: bool = False
) -> tuple[PollingStation, Constituency, Election]:
    if actor.role not in ("polling_officer", "counting_officer", "supervisor"):
        raise HTTPException(403, detail={"code": "operational_role_required"})
    if db.get(StationAssignment, (actor.id, station_id)) is None:
        raise HTTPException(403, detail={"code": "station_access_denied"})
    station = db.get(PollingStation, station_id)
    if station is None:
        raise HTTPException(404, detail={"code": "configuration_not_found"})
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    election = db.get(Election, constituency.election_id)
    assert election is not None
    if write:
        # Current reads avoid the authentication dependency's older MySQL snapshot.
        active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        election = db.scalar(
            select(Election)
            .where(Election.id == election.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert election is not None
        if not active or active.election_id != election.id or election.status != "active":
            raise HTTPException(409, detail={"code": "active_election_required"})
        station = db.scalar(
            select(PollingStation)
            .where(PollingStation.id == station_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert station is not None
    return station, constituency, election


def latest_records(db: Session, station_id: int, *, lock: bool = False) -> dict[str, PollingRecord]:
    query = (
        select(PollingRecord)
        .where(PollingRecord.station_id == station_id)
        .order_by(PollingRecord.revision)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return {row.kind: row for row in db.scalars(query)}


def invalid() -> None:
    raise HTTPException(422, detail={"code": "polling_validation"})


def validate_record(
    row: PollingRecord, latest: dict[str, PollingRecord], now: datetime, *, complete: bool
) -> None:
    if complete and row.event_at is None:
        invalid()
    if row.event_at and row.event_at > now:
        invalid()
    if row.kind != "queue_clear_estimate" and row.estimated_clear_at is not None:
        invalid()
    if row.kind == "queue_clear_estimate":
        if complete and row.estimated_clear_at is None:
            invalid()
        if row.estimated_clear_at and row.event_at and row.estimated_clear_at < row.event_at:
            invalid()
    if complete and row.kind == "opening" and row.event_at and row.event_at > row.planned_at:
        if not row.reason.strip():
            invalid()
    records = {**latest, row.kind: row}
    opening = records.get("opening")
    closure = records.get("admission_closure")
    completion = records.get("service_completion")
    estimate = records.get("queue_clear_estimate")
    # Missing events stay missing; known actual events must remain chronologically consistent.
    for before, after in ((opening, closure), (closure, completion), (opening, completion)):
        if before and after and before.event_at and after.event_at:
            if before.event_at > after.event_at:
                invalid()
    if closure and estimate and closure.event_at and estimate.estimated_clear_at:
        if estimate.estimated_clear_at < closure.event_at:
            invalid()


def polling_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/polling", tags=["polling"])
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        station, constituency, election = station_scope(db, actor, station_id)
        schedule = db.get(ElectionSchedule, election.id)
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
            }
            if schedule
            else None,
            "items": [record_view(row) for row in latest_records(db, station_id).values()],
        }

    @router.get("/audit")
    def audit(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        station_scope(db, actor, station_id)
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action.like("polling_%")).order_by(AuditEvent.id)
        )
        return {
            "items": [
                {
                    "actor_id": row.actor_id,
                    "action": row.action,
                    "occurred_at": as_utc(row.occurred_at),
                    "details": row.details,
                }
                for row in events
                if row.details.get("station_id") == station_id
            ]
        }

    @router.get("/{kind}/history")
    def history(station_id: int, kind: PollingKind, db: Database, actor: Actor) -> dict[str, Any]:
        station_scope(db, actor, station_id)
        rows = db.scalars(
            select(PollingRecord)
            .where(PollingRecord.station_id == station_id, PollingRecord.kind == kind)
            .order_by(PollingRecord.revision)
        )
        return {"items": [record_view(row) for row in rows]}

    def execute(
        station_id: int,
        kind: PollingKind,
        action: str,
        data: PollingCommand,
        db: Session,
        actor: Account,
    ) -> dict[str, Any]:
        required_role = "supervisor" if action == "approve" else "polling_officer"
        if actor.role != required_role:
            raise HTTPException(
                403,
                detail={
                    "code": "supervisor_required"
                    if action == "approve"
                    else "polling_officer_required"
                },
            )
        if isinstance(data, PollingApproval) and not verify_password(
            actor.password_hash, data.password
        ):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        _, constituency, election = station_scope(db, actor, station_id, write=True)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "station_id": station_id,
                    "kind": kind,
                    "action": action,
                    "actor_id": actor.id,
                    "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        previous = db.scalar(
            select(PollingRequest)
            .where(PollingRequest.request_id == str(data.request_id))
            .with_for_update()
        )
        if previous:
            if previous.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return previous.response
        records = latest_records(db, station_id, lock=True)
        current = records.get(kind)
        if data.revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        if isinstance(data, PollingDraft):
            amendment = action == "amend"
            if amendment:
                if not current or current.status not in ("submitted", "approved"):
                    raise HTTPException(409, detail={"code": "polling_state_conflict"})
                if not data.reason.strip():
                    invalid()
            elif current and current.status != "draft":
                raise HTTPException(409, detail={"code": "polling_state_conflict"})
            schedule = db.get(ElectionSchedule, election.id)
            if not schedule:
                raise HTTPException(409, detail={"code": "schedule_not_configured"})
            row = PollingRecord(
                station_id=station_id,
                kind=kind,
                revision=data.revision + 1,
                status="draft",
                event_at=stored_time(data.event_at),
                estimated_clear_at=stored_time(data.estimated_clear_at),
                reason=(
                    data.event_reason
                    if isinstance(data, PollingAmendment) and data.event_reason is not None
                    else current.reason
                    if amendment and current
                    else data.reason
                ),
                amendment_reason=(
                    data.reason if amendment else current.amendment_reason if current else ""
                ),
                entered_at=now,
                actor_id=actor.id,
                schedule_revision=schedule.revision,
                planned_at=schedule.planned_opening_at
                if kind == "opening"
                else schedule.planned_closing_at,
            )
            validate_record(row, records, now, complete=False)
            db.add(row)
        else:
            if not current or current.status != ("submitted" if action == "approve" else "draft"):
                raise HTTPException(409, detail={"code": "polling_state_conflict"})
            validate_record(current, records, now, complete=True)
            row = current
            if action == "approve":
                row.status, row.approved_at, row.approved_by = "approved", now, actor.id
            else:
                row.status, row.submitted_at, row.submitted_by = "submitted", now, actor.id
        result = record_view(row)
        db.add(
            PollingRequest(
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
                action="polling_" + action,
                occurred_at=now,
                details={
                    "election_id": election.id,
                    "constituency_id": constituency.id,
                    "station_id": station_id,
                    "record": result,
                },
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "request_conflict"}) from None
        return result

    @router.put("/{kind}")
    def save(
        station_id: int, kind: PollingKind, data: PollingDraft, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, kind, "save", data, db, actor)

    @router.post("/{kind}/submit")
    def submit(
        station_id: int, kind: PollingKind, data: PollingCommand, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, kind, "submit", data, db, actor)

    @router.post("/{kind}/approve")
    def approve(
        station_id: int, kind: PollingKind, data: PollingApproval, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, kind, "approve", data, db, actor)

    @router.post("/{kind}/amend")
    def amend(
        station_id: int, kind: PollingKind, data: PollingAmendment, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, kind, "amend", data, db, actor)

    return router
