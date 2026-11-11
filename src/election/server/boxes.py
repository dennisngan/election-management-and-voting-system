"""Frozen ballot boxes, revision-bound handovers and postpoll milestones."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from election.server.box_models import BallotBox, BoxEvent, BoxMilestone, BoxRequest
from election.server.box_state import (
    MILESTONE_KINDS,
    MilestoneKind,
    box_event_view,
    box_events,
    box_head,
    box_snapshot,
    milestone_rows,
    milestone_view,
)
from election.server.models import Account, AuditEvent
from election.server.station_access import station_scope
from election.server.station_models import PollingStation
from election.server.timestamps import utc_time


class BoxCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class BoxCreate(BoxCommand):
    box_reference: str = Field(min_length=1, max_length=64)
    seal_reference: str = Field(min_length=1, max_length=128)
    prepared_at: AwareDatetime

    @field_validator("box_reference", "seal_reference")
    @classmethod
    def meaningful_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonblank reference is required")
        return value

    @field_validator("prepared_at")
    @classmethod
    def normalized_preparation(cls, value: datetime) -> datetime:
        return utc_time(value)


class BoxEventInput(BoxCommand):
    expected_revision: int = Field(ge=1, strict=True)
    event_at: AwareDatetime
    reason: str = Field(default="", max_length=1000)

    @field_validator("event_at")
    @classmethod
    def normalized_event(cls, value: datetime) -> datetime:
        return utc_time(value)


class BoxCorrection(BoxEventInput):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value


class MilestoneInput(BoxEventInput):
    expected_revision: int = Field(ge=0, strict=True)
    box_id: Annotated[int, Field(gt=0, strict=True)] | None = None


def box_at(
    db: Session,
    station_id: int,
    box_id: int,
    *,
    side: Literal["origin", "destination"] | None = None,
) -> BallotBox:
    visible = or_(
        BallotBox.origin_station_id == station_id, BallotBox.destination_station_id == station_id
    )
    if side == "origin":
        visible = BallotBox.origin_station_id == station_id
    elif side == "destination":
        visible = BallotBox.destination_station_id == station_id
    box = db.scalar(
        select(BallotBox)
        .where(BallotBox.id == box_id, visible)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if box is None:
        raise HTTPException(404, detail={"code": "box_not_found"})
    return box


def box_timeline_snapshot(db: Session, actor: Account, station_id: int) -> dict[str, Any]:
    # Count context uses the physical-box snapshot, so enrich only at this outer
    # read boundary to avoid recursively asking a timeline for its own sources.
    from election.server.counting_round_events import round_events
    from election.server.turnout_basis import turnout_scope

    turnout_scope(db, actor, station_id)
    snapshot = box_snapshot(db, actor, station_id)
    return {**snapshot, "count_events": round_events(db, actor, station_id)}


def box_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/boxes", tags=["Ballot boxes"])
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def write(
        station_id: int,
        data: BoxCommand,
        db: Session,
        actor: Account,
        response: Response,
        operation: Callable[[PollingStation, datetime], dict[str, Any]],
        *,
        action: str,
        role: Literal["polling_officer", "counting_officer"],
        target_id: int | None = None,
    ) -> dict[str, Any]:
        if actor.role != role:
            raise HTTPException(403, detail={"code": role + "_required"})
        station, constituency, election = station_scope(db, actor, station_id, write=True)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "actor_id": actor.id,
                    "station_id": station_id,
                    "action": action,
                    "target_id": target_id,
                    "data": data.model_dump(mode="json", exclude={"request_id"}),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        previous = db.scalar(
            select(BoxRequest)
            .where(BoxRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if previous:
            if previous.payload_digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return previous.response
        now = timestamp()
        result = operation(station, now)
        db.add(
            BoxRequest(
                request_id=str(data.request_id),
                station_id=station_id,
                actor_id=actor.id,
                action=action,
                payload_digest=digest,
                response=result,
                entered_at=now,
            )
        )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="box_" + action,
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "constituency_id": constituency.id,
                    "election_id": election.id,
                    "record": result,
                },
            )
        )
        db.commit()
        return result

    @router.get("")
    def read_boxes(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        return box_timeline_snapshot(db, actor, station_id)

    @router.post("", status_code=201)
    def prepare_box(
        station_id: int, data: BoxCreate, db: Database, actor: Ready, response: Response
    ) -> dict[str, Any]:
        def prepare(station: PollingStation, now: datetime) -> dict[str, Any]:
            prepared_at = data.prepared_at.replace(tzinfo=None)
            if prepared_at > now:
                raise HTTPException(422, detail={"code": "box_validation"})
            destination_id = (
                station.id if station.counting_mode == "local" else station.destination_station_id
            )
            related = list(
                db.scalars(
                    select(PollingStation)
                    .where(PollingStation.id.in_([station.id, destination_id]))
                    .order_by(PollingStation.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            destination = next((row for row in related if row.id == destination_id), None)
            if (
                destination is None
                or destination.counting_mode != "local"
                or destination.constituency_id != station.constituency_id
                or (station.counting_mode == "send" and destination.id == station.id)
            ):
                raise HTTPException(422, detail={"code": "invalid_counting_destination"})
            # Receiver snapshots lock their station before box rows/ranges. Take
            # both related station locks before the unique-reference gap read too.
            existing = db.scalar(
                select(BallotBox.id)
                .where(
                    BallotBox.origin_station_id == station_id,
                    BallotBox.box_reference == data.box_reference,
                )
                .with_for_update()
            )
            if existing is not None:
                raise HTTPException(409, detail={"code": "box_reference_exists"})
            box = BallotBox(
                origin_station_id=station_id,
                destination_station_id=destination.id,
                mode=station.counting_mode,
                box_reference=data.box_reference,
                seal_reference=data.seal_reference,
                prepared_at=prepared_at,
                entered_at=now,
                actor_id=actor.id,
            )
            db.add(box)
            db.flush()
            event = BoxEvent(
                box_id=box.id,
                revision=1,
                kind="prepared",
                event_at=prepared_at,
                entered_at=now,
                actor_id=actor.id,
                reason="",
            )
            db.add(event)
            db.flush()
            return box_head(db, box, [event])

        return write(
            station_id,
            data,
            db,
            actor,
            response,
            prepare,
            action="prepared",
            role="polling_officer",
        )

    def record_handover(
        station_id: int,
        box_id: int,
        data: BoxEventInput,
        db: Session,
        actor: Account,
        response: Response,
        kind: Literal["departure", "receipt"],
        *,
        correction: bool = False,
    ) -> dict[str, Any]:
        def append(station: PollingStation, now: datetime) -> dict[str, Any]:
            box = box_at(
                db, station_id, box_id, side="origin" if kind == "departure" else "destination"
            )
            events = box_events(db, [box.id])
            if data.expected_revision != events[-1].revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            if kind == "departure" and box.mode == "local":
                raise HTTPException(422, detail={"code": "box_validation"})
            departure = next(
                (row for row in reversed(events) if row.kind.startswith("departure")), None
            )
            receipt = next(
                (row for row in reversed(events) if row.kind.startswith("receipt")), None
            )
            current = departure if kind == "departure" else receipt
            if (correction and current is None) or (not correction and current is not None):
                raise HTTPException(409, detail={"code": "box_state_conflict"})
            actual = data.event_at.replace(tzinfo=None)
            if actual > now or actual < box.prepared_at:
                raise HTTPException(422, detail={"code": "box_validation"})
            if kind == "receipt" and box.mode == "send":
                if departure is None:
                    raise HTTPException(409, detail={"code": "box_departure_required"})
                if actual < departure.event_at:
                    raise HTTPException(422, detail={"code": "box_validation"})
            if kind == "departure" and receipt is not None and actual > receipt.event_at:
                raise HTTPException(422, detail={"code": "box_validation"})
            if kind == "receipt":
                latest = {row.kind: row for row in milestone_rows(db, station_id)}
                opening = latest.get("first_box_opening")
                if opening and opening.box_id == box.id and actual > opening.event_at:
                    raise HTTPException(422, detail={"code": "box_validation"})
            event = BoxEvent(
                box_id=box.id,
                revision=events[-1].revision + 1,
                kind=kind + "_correction" if correction else kind,
                event_at=actual,
                entered_at=now,
                actor_id=actor.id,
                reason=data.reason,
            )
            db.add(event)
            db.flush()
            return box_head(db, box, [*events, event])

        return write(
            station_id,
            data,
            db,
            actor,
            response,
            append,
            action=kind + "_correction" if correction else kind,
            role="polling_officer" if kind == "departure" else "counting_officer",
            target_id=box_id,
        )

    @router.post("/{box_id}/departure", status_code=201)
    def departure(
        station_id: int,
        box_id: int,
        data: BoxEventInput,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return record_handover(station_id, box_id, data, db, actor, response, "departure")

    @router.post("/{box_id}/receipt", status_code=201)
    def receipt(
        station_id: int,
        box_id: int,
        data: BoxEventInput,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return record_handover(station_id, box_id, data, db, actor, response, "receipt")

    @router.put("/{box_id}/departure")
    def correct_departure(
        station_id: int,
        box_id: int,
        data: BoxCorrection,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return record_handover(
            station_id, box_id, data, db, actor, response, "departure", correction=True
        )

    @router.put("/{box_id}/receipt")
    def correct_receipt(
        station_id: int,
        box_id: int,
        data: BoxCorrection,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        return record_handover(
            station_id, box_id, data, db, actor, response, "receipt", correction=True
        )

    @router.put("/milestones/{kind}")
    def save_milestone(
        station_id: int,
        kind: MilestoneKind,
        data: MilestoneInput,
        db: Database,
        actor: Ready,
        response: Response,
    ) -> dict[str, Any]:
        def append(station: PollingStation, now: datetime) -> dict[str, Any]:
            if station.counting_mode != "local":
                raise HTTPException(403, detail={"code": "counting_station_required"})
            latest = {row.kind: row for row in milestone_rows(db, station_id)}
            current = latest.get(kind)
            revision = current.revision if current else 0
            if data.expected_revision != revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            if current is not None and not data.reason.strip():
                raise HTTPException(422, detail={"code": "box_correction_reason_required"})
            actual = data.event_at.replace(tzinfo=None)
            if actual > now or ((kind == "first_box_opening") != (data.box_id is not None)):
                raise HTTPException(422, detail={"code": "box_validation"})
            if kind == "first_box_opening":
                assert data.box_id is not None
                box = box_at(db, station_id, data.box_id, side="destination")
                receipt = next(
                    (
                        row
                        for row in reversed(box_events(db, [box.id]))
                        if row.kind.startswith("receipt")
                    ),
                    None,
                )
                if receipt is None:
                    raise HTTPException(409, detail={"code": "box_receipt_required"})
                if actual < receipt.event_at:
                    raise HTTPException(422, detail={"code": "box_validation"})
            known = {name: row.event_at for name, row in latest.items()}
            known[kind] = actual
            for index, earlier in enumerate(MILESTONE_KINDS):
                for later in MILESTONE_KINDS[index + 1 :]:
                    if earlier in known and later in known and known[earlier] > known[later]:
                        raise HTTPException(422, detail={"code": "box_validation"})
            row = BoxMilestone(
                station_id=station_id,
                kind=kind,
                revision=revision + 1,
                event_at=actual,
                entered_at=now,
                actor_id=actor.id,
                reason=data.reason,
                box_id=data.box_id,
            )
            db.add(row)
            db.flush()
            return milestone_view(row)

        return write(
            station_id,
            data,
            db,
            actor,
            response,
            append,
            action="milestone_" + kind,
            role="counting_officer",
        )

    @router.get("/{box_id}/history")
    def history(station_id: int, box_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        station_scope(db, actor, station_id)
        box = box_at(db, station_id, box_id)
        events = box_events(db, [box.id])
        return {"box": box_head(db, box, events), "items": [box_event_view(row) for row in events]}

    return router
