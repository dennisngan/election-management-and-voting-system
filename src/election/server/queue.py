"""Station-scoped queue observations, history and clock-based reminders."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.models import Account, AuditEvent
from election.server.queue_models import QueueEvent
from election.server.station_access import station_scope
from election.server.station_models import PollingStation
from election.server.timestamps import as_utc

QueueBand = Literal["under_30", "30_59", "60_90", "over_90"]


class QueueCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    event_at: AwareDatetime

    @field_validator("event_at")
    @classmethod
    def supported_utc_time(cls, value: datetime) -> datetime:
        try:
            normalized = value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Event time is outside the supported UTC range") from None
        if normalized.year < 1000:
            raise ValueError("Event time is outside the supported UTC range")
        return normalized


class ObservationInput(QueueCommand):
    band: QueueBand
    reason: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        return value.strip()


class ConfirmationInput(QueueCommand):
    current_event_id: int = Field(gt=0, strict=True)


def queue_event_view(event: QueueEvent) -> dict[str, Any]:
    """Safe immutable projection shared with queue statements."""
    return {
        "id": event.id,
        "station_id": event.station_id,
        "revision": event.revision,
        "kind": event.kind,
        "band": event.band,
        "event_at": as_utc(event.event_at),
        "entered_at": as_utc(event.entered_at),
        "actor_id": event.actor_id,
        "confirmed_event_id": event.confirmed_event_id,
        "reason": event.reason,
    }


def station_events(db: Session, station_id: int) -> list[QueueEvent]:
    # Locking reads see committed rows even after authentication opened a MySQL
    # repeatable-read snapshot. The station lock serializes this command history.
    return list(
        db.scalars(
            select(QueueEvent)
            .where(QueueEvent.station_id == station_id)
            .order_by(QueueEvent.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def current_event(events: list[QueueEvent]) -> QueueEvent | None:
    return max(events, key=lambda event: (event.event_at, event.revision), default=None)


def queue_freshness(event_at: datetime | None, now: datetime) -> dict[str, Any]:
    """One event-time reminder calculation for live views and historical reports."""
    timestamp = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    observed = event_at
    if observed is not None and observed.tzinfo:
        observed = observed.astimezone(UTC).replace(tzinfo=None)
    due_at = observed + timedelta(minutes=30) if observed else None
    elapsed = (timestamp - observed).total_seconds() if observed else 0
    return {
        "missing": observed is None,
        "due_at": as_utc(due_at),
        "reminder_due": due_at is not None and timestamp >= due_at,
        "overdue_periods": max(0, int(elapsed // (30 * 60))),
    }


def queue_snapshot(db: Session, actor: Account, station_id: int, now: datetime) -> dict[str, Any]:
    """Authorized station history and freshness; missing never implies zero queue."""
    station, constituency, election = station_scope(db, actor, station_id)
    db.scalar(
        select(PollingStation)
        .where(PollingStation.id == station.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    events = station_events(db, station_id)
    current = current_event(events)
    timestamp = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
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
        "current": queue_event_view(current) if current else None,
        "items": [queue_event_view(event) for event in events],
        "revision": events[-1].revision if events else 0,
        "server_time": as_utc(timestamp),
        **queue_freshness(current.event_at if current else None, timestamp),
    }


def command_digest(actor: Account, station_id: int, action: str, data: QueueCommand) -> str:
    payload = data.model_dump(mode="json", exclude={"request_id"})
    payload["event_at"] = as_utc(data.event_at.astimezone(UTC).replace(tzinfo=None))
    content = {"actor_id": actor.id, "station_id": station_id, "action": action, "data": payload}
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def queue_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/queue", tags=["queue"])
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read_queue(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        return queue_snapshot(db, actor, station_id, timestamp())

    def append_event(
        station_id: int,
        data: ObservationInput | ConfirmationInput,
        db: Session,
        actor: Account,
        response: Response,
    ) -> dict[str, Any]:
        if actor.role != "polling_officer":
            raise HTTPException(403, detail={"code": "polling_officer_required"})
        station_scope(db, actor, station_id, write=True)
        action = "observation" if isinstance(data, ObservationInput) else "unchanged_confirmation"
        digest = command_digest(actor, station_id, action, data)
        replay = db.scalar(
            select(QueueEvent)
            .where(QueueEvent.request_id == str(data.request_id))
            .with_for_update()
        )
        if replay:
            if replay.payload_digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return queue_event_view(replay)
        events = station_events(db, station_id)
        revision = events[-1].revision if events else 0
        if data.expected_revision != revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
        if event_at > now:
            raise HTTPException(422, detail={"code": "queue_validation"})
        confirmed = None
        band: str = data.band if isinstance(data, ObservationInput) else ""
        if isinstance(data, ConfirmationInput):
            confirmed = current_event(events)
            if not confirmed or confirmed.id != data.current_event_id:
                raise HTTPException(409, detail={"code": "queue_observation_conflict"})
            if event_at < confirmed.event_at:
                raise HTTPException(422, detail={"code": "queue_validation"})
            band = confirmed.band
        event = QueueEvent(
            station_id=station_id,
            revision=revision + 1,
            kind=action,
            band=band,
            event_at=event_at,
            entered_at=now,
            actor_id=actor.id,
            confirmed_event_id=confirmed.id if confirmed else None,
            request_id=str(data.request_id),
            payload_digest=digest,
            reason=data.reason if isinstance(data, ObservationInput) else "",
        )
        db.add(event)
        db.flush()
        view = queue_event_view(event)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="queue_" + action,
                occurred_at=now,
                details=view,
            )
        )
        db.commit()
        return view

    @router.post("", status_code=201)
    def record_observation(
        station_id: int, data: ObservationInput, db: Database, actor: Actor, response: Response
    ) -> dict[str, Any]:
        return append_event(station_id, data, db, actor, response)

    @router.post("/confirm", status_code=201)
    def confirm_unchanged(
        station_id: int, data: ConfirmationInput, db: Database, actor: Actor, response: Response
    ) -> dict[str, Any]:
        return append_event(station_id, data, db, actor, response)

    return router
