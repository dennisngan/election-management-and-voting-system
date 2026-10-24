"""EPR fallback activation retains a confirmed turnout and ordinary-stock basis."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.fallback_models import FallbackRecord, FallbackRequest, FallbackRevision
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc
from election.server.security import verify_password
from election.server.stock import stock_write
from election.server.stock_serials import MAX_STOCK_QUANTITY
from election.server.stock_time import StockEventTime
from election.server.turnout_basis import (
    FallbackSelection,
    active_fallback_at,
    confirmed_mode_events,
    locked_schedule,
    recovery_reconciliation,
    stock_snapshot_basis,
    turnout_scope,
)


class FallbackCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_schedule_revision: int = Field(strict=True, ge=1)


class FallbackDraft(FallbackCommand):
    kind: Literal["activation", "recovery"]
    event_at: StockEventTime
    cumulative_quantity: int = Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)
    stock_snapshot_id: int = Field(strict=True, gt=0)
    stock_snapshot_revision: int = Field(strict=True, ge=1)
    source_context: str = Field(min_length=1, max_length=2000)

    activation_id: int | None = Field(default=None, strict=True, gt=0)
    activation_revision: int | None = Field(default=None, strict=True, ge=1)
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def recovery_source(self) -> FallbackDraft:
        if self.kind == "recovery":
            if (self.activation_id is None or self.activation_revision is None
                    or not self.reason.strip()):
                raise ValueError("Select the confirmed activation and explain the recovery")
        elif self.activation_id is not None or self.activation_revision is not None:
            raise ValueError("Activation does not select a preceding activation")
        return self

    @field_validator("source_context")
    @classmethod
    def meaningful_context(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A supplied source context is required")
        return value


class FallbackAmendment(FallbackDraft):
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Explain the source correction")
        return value


class FallbackReview(FallbackCommand):
    expected_revision: int = Field(strict=True, ge=1)


class FallbackApproval(FallbackReview):
    password: str = Field(min_length=1, max_length=128, repr=False)


def fallback_view(head: FallbackRecord, row: FallbackRevision) -> dict[str, Any]:
    return {
        **row.data,
        "id": head.id, "station_id": head.station_id, "kind": head.kind,
        "revision": row.revision, "schedule_revision": row.schedule_revision,
        "status": row.status, "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at), "actor_id": row.actor_id,
        "stock_snapshot_id": row.stock_snapshot_id,
        "stock_snapshot_revision": row.stock_snapshot_revision, "reason": row.reason,
        "submitted_at": as_utc(row.submitted_at), "submitted_by": row.submitted_by,
        "approved_at": as_utc(row.approved_at), "approved_by": row.approved_by,
    }


def fallback_rows(db: Session, station_id: int) -> list[tuple[FallbackRecord, FallbackRevision]]:
    query = select(FallbackRecord, FallbackRevision).join(FallbackRevision, and_(
        FallbackRevision.record_id == FallbackRecord.id,
        FallbackRevision.revision == FallbackRecord.revision,
    )).where(FallbackRecord.station_id == station_id).order_by(FallbackRecord.id)
    return [(head, row) for head, row in db.execute(
        query.with_for_update().execution_options(populate_existing=True),
    )]



def validate_mode_timeline(
    db: Session, station_id: int, kind: str, event_at: datetime,
    activation_id: int | None, record_id: int | None,
) -> None:
    events = confirmed_mode_events(
        db, station_id, datetime.max, exclude_record_id=record_id,
    )
    candidate_id = record_id if record_id is not None else 2**63 - 1
    timeline = [(row.event_at, head.id, head.kind, head.activation_id) for head, row in events]
    timeline.append((event_at, candidate_id, kind, activation_id))
    active_id = None
    for _, identity, event_kind, parent_id in sorted(timeline):
        if event_kind == "activation":
            if active_id is not None:
                raise HTTPException(409, detail={"code": "fallback_source_conflict"})
            active_id = identity
        else:
            if active_id is None or parent_id != active_id:
                raise HTTPException(409, detail={"code": "fallback_source_conflict"})
            active_id = None

def fallback_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/fallback", tags=["EPR fallback"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def record(db: Session, station_id: int, record_id: int) -> FallbackRecord:
        row = db.scalar(select(FallbackRecord).where(
            FallbackRecord.id == record_id, FallbackRecord.station_id == station_id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise HTTPException(404, detail={"code": "fallback_record_not_found"})
        return row

    def revision(db: Session, head: FallbackRecord, number: int) -> FallbackRevision:
        row = db.scalar(select(FallbackRevision).where(
            FallbackRevision.record_id == head.id, FallbackRevision.revision == number,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise HTTPException(404, detail={"code": "fallback_revision_not_found"})
        return row

    @router.get("")
    def collection(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = turnout_scope(db, actor, station_id)
        rows = fallback_rows(db, station_id)
        selected = active_fallback_at(db, station_id, timestamp())
        active = selected[0].id if selected is not None else None
        return {
            "scope": scope, "items": [fallback_view(head, row) for head, row in rows],
            "mode": "fallback" if active is not None else "normal", "active_activation_id": active,
        }

    @router.get("/{record_id}/history")
    def history(station_id: int, record_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        turnout_scope(db, actor, station_id)
        head = record(db, station_id, record_id)
        rows = db.scalars(select(FallbackRevision).where(
            FallbackRevision.record_id == head.id,
        ).order_by(FallbackRevision.revision).with_for_update())
        return {"items": [fallback_view(head, row) for row in rows]}

    @router.get("/{record_id}")
    def current(
        station_id: int, record_id: int, db: Database, actor: Ready,
        revision_number: int | None = Query(default=None, alias="revision", ge=1),
    ) -> dict[str, Any]:
        turnout_scope(db, actor, station_id)
        head = record(db, station_id, record_id)
        return fallback_view(head, revision(db, head, revision_number or head.revision))

    def execute(
        station_id: int, record_id: int | None, action: str,
        data: FallbackDraft | FallbackReview, db: Session, actor: Account,
    ) -> dict[str, Any]:
        required = "supervisor" if action == "approve" else "polling_officer"
        if actor.role != required:
            raise HTTPException(403, detail={"code": required + "_required"})
        scope = turnout_scope(db, actor, station_id, writable=True)
        schedule = locked_schedule(db, scope["election"]["id"])
        if isinstance(data, FallbackApproval):
            password_hash = db.scalar(select(Account.password_hash).where(
                Account.id == actor.id,
            ).with_for_update())
            if not verify_password(password_hash, data.password):
                raise HTTPException(401, detail={"code": "invalid_credentials"})
        command_data = data.model_dump(mode="json", exclude={"request_id", "password"})
        if isinstance(data, FallbackDraft) and data.kind == "activation":
            for key in ("activation_id", "activation_revision"):
                command_data.pop(key, None)
            if not data.reason:
                command_data.pop("reason", None)
        digest = hashlib.sha256(json.dumps({
            "station_id": station_id, "record_id": record_id,
            "actor_id": actor.id, "action": action,
            "data": command_data,
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        replay = db.scalar(select(FallbackRequest).where(
            FallbackRequest.request_id == str(data.request_id),
        ).with_for_update())
        if replay is not None:
            if replay.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return replay.response
        if data.expected_schedule_revision != schedule.revision:
            raise HTTPException(409, detail={"code": "turnout_schedule_conflict"})
        now = timestamp()
        if isinstance(data, FallbackDraft):
            event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
            if event_at > now:
                raise HTTPException(422, detail={"code": "fallback_validation"})
            head = None
            if action == "amend":
                assert record_id is not None and isinstance(data, FallbackAmendment)
                head = record(db, station_id, record_id)
                if head.revision != data.expected_revision:
                    raise HTTPException(409, detail={"code": "revision_conflict"})
                previous = revision(db, head, head.revision)
                if previous.status not in ("submitted", "approved"):
                    raise HTTPException(409, detail={"code": "fallback_state_conflict"})
                if head.kind != data.kind or head.activation_id != data.activation_id:
                    raise HTTPException(409, detail={"code": "fallback_source_conflict"})
            validate_mode_timeline(
                db, station_id, data.kind, event_at, data.activation_id, head.id if head else None,
            )
            source = stock_snapshot_basis(
                db, station_id, data.stock_snapshot_id, data.stock_snapshot_revision, event_at,
            )
            content: dict[str, Any] = {
                "cumulative_quantity": data.cumulative_quantity,
                "source_context": data.source_context, "stock_snapshot": source, "scope": scope,
            }
            if data.kind == "recovery":
                assert data.activation_id is not None and data.activation_revision is not None
                content.update({
                    "activation_id": data.activation_id,
                    "activation_revision": data.activation_revision,
                    "reconciliation": recovery_reconciliation(
                        db, station_id, schedule,
                        FallbackSelection(data.activation_id, data.activation_revision,
                                          data.stock_snapshot_id, data.stock_snapshot_revision),
                        event_at, data.cumulative_quantity,
                        exclude_record_id=head.id if head else None,
                    ),
                })
            if head is None:
                head = FallbackRecord(
                    station_id=station_id, kind=data.kind, revision=1, approved_revision=None,
                    activation_id=data.activation_id, created_at=now,
                )
                db.add(head)
                db.flush()
            else:
                head.revision += 1
            row = FallbackRevision(
                record_id=head.id, revision=head.revision, schedule_revision=schedule.revision,
                event_at=event_at, entered_at=now, actor_id=actor.id, status="draft",
                stock_snapshot_id=data.stock_snapshot_id,
                stock_snapshot_revision=data.stock_snapshot_revision, reason=data.reason,
                submitted_at=None, submitted_by=None, approved_at=None, approved_by=None,
                data=content,
            )
            db.add(row)
        else:
            assert record_id is not None
            head = record(db, station_id, record_id)
            if head.revision != data.expected_revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            row = revision(db, head, head.revision)
            validate_mode_timeline(
                db, station_id, head.kind, row.event_at, head.activation_id, head.id,
            )
            expected = "submitted" if action == "approve" else "draft"
            if row.status != expected:
                raise HTTPException(409, detail={"code": "fallback_state_conflict"})
            if row.schedule_revision != schedule.revision:
                raise HTTPException(409, detail={"code": "turnout_review_required"})
            stock_snapshot_basis(
                db, station_id, row.stock_snapshot_id, row.stock_snapshot_revision, row.event_at,
            )
            if head.kind == "recovery":
                assert head.activation_id is not None
                comparison = recovery_reconciliation(
                    db, station_id, schedule,
                    FallbackSelection(head.activation_id, row.data["activation_revision"],
                                      row.stock_snapshot_id, row.stock_snapshot_revision),
                    row.event_at, row.data["cumulative_quantity"], exclude_record_id=head.id,
                )
                if comparison != row.data["reconciliation"]:
                    raise HTTPException(409, detail={"code": "fallback_review_required"})
            if action == "approve":
                row.status, row.approved_at, row.approved_by = "approved", now, actor.id
                head.approved_revision = row.revision
            else:
                row.status, row.submitted_at, row.submitted_by = "submitted", now, actor.id
        db.flush()
        result = fallback_view(head, row)
        db.add(FallbackRequest(
            request_id=str(data.request_id), station_id=station_id, actor_id=actor.id,
            digest=digest, response=result,
        ))
        db.add(AuditEvent(
            actor_id=actor.id, action="fallback_" + action, occurred_at=now,
            details={"station_id": station_id, "record_id": head.id,
                     "revision": row.revision, "kind": head.kind, "status": row.status,
                     "stock_snapshot_id": row.stock_snapshot_id,
                     "stock_snapshot_revision": row.stock_snapshot_revision},
        ))
        db.commit()
        return result

    @router.post("", status_code=201)
    def create(station_id: int, data: FallbackDraft, db: Database, actor: Ready) -> dict[str, Any]:
        return stock_write(db, lambda: execute(station_id, None, "save", data, db, actor))

    @router.post("/{record_id}/amend", status_code=201)
    def amend(
        station_id: int, record_id: int, data: FallbackAmendment, db: Database, actor: Ready,
    ) -> dict[str, Any]:
        return stock_write(db, lambda: execute(station_id, record_id, "amend", data, db, actor))

    @router.post("/{record_id}/submit")
    def submit(
        station_id: int, record_id: int, data: FallbackReview, db: Database, actor: Ready,
    ) -> dict[str, Any]:
        return stock_write(db, lambda: execute(station_id, record_id, "submit", data, db, actor))

    @router.post("/{record_id}/approve")
    def approve(
        station_id: int, record_id: int, data: FallbackApproval, db: Database, actor: Ready,
    ) -> dict[str, Any]:
        return stock_write(db, lambda: execute(station_id, record_id, "approve", data, db, actor))

    return router
