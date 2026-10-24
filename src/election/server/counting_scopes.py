"""Received-box provenance at the assigned counting station."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.accounting import accounting_record, record_view
from election.server.box_models import BallotBox
from election.server.boxes import box_snapshot, utc_time
from election.server.counting_scope_models import (
    CountingScope,
    CountingScopeBox,
    CountingScopeRequest,
    CountingScopeRevision,
)
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc
from election.server.turnout_basis import turnout_scope


class ScopeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0)


class BoxSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    box_id: int = Field(strict=True, gt=0)
    revision: int = Field(strict=True, ge=1)


class AccountingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: int = Field(strict=True, gt=0)
    revision: int = Field(strict=True, ge=1)


class ScopeDraft(ScopeCommand):
    reference: str = Field(min_length=1, max_length=80)
    event_at: AwareDatetime
    box_revisions: list[BoxSelection]
    accounting_revisions: list[AccountingSelection]
    notes: str = Field(default="", max_length=2000)
    amendment_reason: str = Field(default="", max_length=2000)

    @field_validator("reference")
    @classmethod
    def meaningful_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonblank scope reference is required")
        return value

    @field_validator("event_at")
    @classmethod
    def supported_time(cls, value: datetime) -> datetime:
        return utc_time(value)

    @model_validator(mode="after")
    def distinct_selections(self) -> ScopeDraft:
        if len({row.box_id for row in self.box_revisions}) != len(self.box_revisions):
            raise ValueError("Select each physical box once")
        if len({row.station_id for row in self.accounting_revisions}) != len(
            self.accounting_revisions
        ):
            raise ValueError("Select each source station once")
        return self


def latest_revision(db: Session, scope_id: int) -> CountingScopeRevision | None:
    return db.scalar(
        select(CountingScopeRevision)
        .where(CountingScopeRevision.scope_id == scope_id)
        .order_by(CountingScopeRevision.revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def source_box_ids(db: Session, origin_id: int) -> list[int]:
    return list(db.scalars(
        select(BallotBox.id).where(BallotBox.origin_station_id == origin_id)
        .order_by(BallotBox.id).with_for_update()
    ))


def scope_at(db: Session, station_id: int, scope_id: int) -> CountingScope:
    scope = db.scalar(
        select(CountingScope).where(
            CountingScope.id == scope_id, CountingScope.station_id == station_id
        ).with_for_update().execution_options(populate_existing=True)
    )
    if scope is None:
        raise HTTPException(404, detail={"code": "counting_scope_not_found"})
    return scope


def scope_view(
    db: Session, scope: CountingScope, row: CountingScopeRevision,
    boxes: list[dict[str, Any]],
) -> dict[str, Any]:
    current = latest_revision(db, scope.id)
    available = {box["id"]: box for box in boxes}
    source_current = all(
        box["id"] in available
        and available[box["id"]]["revision"] == box["revision"]
        and available[box["id"]]["scope_id"] == scope.id
        for box in row.data["box_basis"]
    )
    for frozen in row.data["accounting_basis"]:
        latest = accounting_record(db, frozen["station_id"])
        if latest is None or latest.id != frozen["id"]:
            source_current = False
            continue
        view = record_view(db, latest)
        if not view["source_current"] or (
            frozen["approval_valid"] and not view["approval_valid"]
        ):
            source_current = False
    for coverage in row.data["coverage"]:
        if source_box_ids(db, coverage["station"]["id"]) != coverage["source_box_ids"]:
            source_current = False
    is_current = current is not None and current.id == row.id
    blockers = list(row.data["blockers"])
    if not source_current:
        blockers.append({"code": "scope_basis_stale"})
    return {
        **row.data,
        "id": scope.id,
        "revision_id": row.id,
        "station_id": scope.station_id,
        "reference": scope.reference,
        "revision": row.revision,
        "status": row.status,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "notes": row.notes,
        "amendment_reason": row.amendment_reason,
        "submitted_at": as_utc(row.submitted_at),
        "submitted_by": row.submitted_by,
        "source_current": source_current,
        "is_current": is_current,
        "blockers": blockers,
        "count_ready": bool(is_current and row.status == "submitted" and not blockers),
    }


def scope_options(db: Session, actor: Account, station_id: int) -> dict[str, Any]:
    # Match accounting's ActiveElection → Election → Constituency lock order
    # before destination station, physical boxes, schedule and stock sources.
    turnout_scope(db, actor, station_id)
    snapshot = box_snapshot(db, actor, station_id)
    visible_ids = [box["id"] for box in snapshot["items"]]
    members = dict(db.execute(select(CountingScopeBox.box_id, CountingScopeBox.scope_id)
                             .where(CountingScopeBox.box_id.in_(visible_ids))
                             .with_for_update()).all())
    boxes = [
        {**box, "scope_id": members.get(box["id"])}
        for box in snapshot["items"]
        if box["destination_station_id"] == station_id
    ]
    # A receiver's station assignment is not a source-station permission. Only
    # actual received-box links permit these scoped accounting snapshots.
    origins = {box["origin_station_id"] for box in boxes if box["receipt"]}
    sources = []
    for origin_id in sorted(origins):
        box = next(item for item in boxes if item["origin_station_id"] == origin_id)
        row = accounting_record(db, origin_id)
        sources.append({
            "station": box["origin"],
            "record": record_view(db, row) if row else None,
        })
    scopes = list(db.scalars(
        select(CountingScope).where(CountingScope.station_id == station_id)
        .order_by(CountingScope.id).with_for_update()
    ))
    views = []
    for scope in scopes:
        row = latest_revision(db, scope.id)
        assert row is not None
        views.append(scope_view(db, scope, row, boxes))
    return {
        "context": snapshot["context"],
        "counting_applicable": snapshot["counting_applicable"],
        "boxes": boxes,
        "source_accounting": sources,
        "scopes": views,
    }


def draft_basis(
    db: Session, options: dict[str, Any], data: ScopeDraft, scope_id: int,
) -> dict[str, Any]:
    available = {box["id"]: box for box in options["boxes"]}
    selected = []
    blockers: list[dict[str, Any]] = []
    for selection in sorted(data.box_revisions, key=lambda item: item.box_id):
        box = available.get(selection.box_id)
        if box is None:
            raise HTTPException(404, detail={"code": "box_not_found"})
        if box["revision"] != selection.revision:
            raise HTTPException(409, detail={"code": "box_revision_conflict"})
        if box["scope_id"] is not None and box["scope_id"] != scope_id:
            raise HTTPException(409, detail={"code": "box_already_in_scope", "box_id": box["id"]})
        if box["receipt"] is None:
            blockers.append({"code": "box_receipt_missing", "box_id": box["id"]})
        selected.append({key: value for key, value in box.items() if key != "scope_id"})
    if not selected:
        blockers.append({"code": "scope_boxes_missing"})
    origins = {box["origin_station_id"] for box in selected}
    selections = {row.station_id: row.revision for row in data.accounting_revisions}
    if selections.keys() - origins:
        raise HTTPException(422, detail={"code": "scope_accounting_origin_mismatch"})
    sources = {source["station"]["id"]: source["record"]
               for source in options["source_accounting"]}
    accounting = []
    coverage = []
    for origin_id in sorted(origins):
        origin_boxes = [box for box in selected if box["origin_station_id"] == origin_id]
        box_ids = [box["id"] for box in origin_boxes]
        all_box_ids = source_box_ids(db, origin_id)
        coverage.append({
            "station": origin_boxes[0]["origin"],
            "scope_box_ids": box_ids,
            "source_box_ids": all_box_ids,
            "all_source_boxes_in_scope": box_ids == all_box_ids,
        })
        if origin_id not in selections:
            blockers.append({"code": "source_accounting_missing", "station_id": origin_id})
            continue
        if not any(box["receipt"] for box in origin_boxes):
            raise HTTPException(409, detail={"code": "accounting_receipt_required"})
        source = sources.get(origin_id)
        if source is None:
            raise HTTPException(404, detail={"code": "accounting_not_found"})
        if source["revision"] != selections[origin_id] or not source["source_current"]:
            raise HTTPException(409, detail={"code": "accounting_source_stale"})
        if not source["approval_valid"]:
            blockers.append({"code": "source_accounting_unapproved", "station_id": origin_id})
        accounting.append(source)
    complete_coverage = bool(coverage) and all(
        row["all_source_boxes_in_scope"] for row in coverage
    ) and len(accounting) == len(origins)
    estimates = {}
    for name in ("estimated_box_from_stock_quantity", "estimated_box_from_turnout_quantity"):
        values = [row["summary"][name] for row in accounting]
        estimates[name] = sum(values) if complete_coverage and all(
            value is not None for value in values
        ) else None
    return jsonable_encoder({
        "context": options["context"],
        "box_basis": selected,
        "accounting_basis": accounting,
        "blockers": blockers,
        "coverage": coverage,
        **estimates,
    })


def counting_scopes_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes", tags=["counting scopes"]
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        return scope_options(db, actor, station_id)

    @router.get("/{scope_id}/revisions/{revision}")
    def revision(
        station_id: int, scope_id: int, revision: int, db: Database, actor: Actor,
    ) -> dict[str, Any]:
        options = scope_options(db, actor, station_id)
        scope = scope_at(db, station_id, scope_id)
        row = db.scalar(select(CountingScopeRevision).where(
            CountingScopeRevision.scope_id == scope_id, CountingScopeRevision.revision == revision
        ).with_for_update())
        if row is None:
            raise HTTPException(404, detail={"code": "counting_scope_not_found"})
        return scope_view(db, scope, row, options["boxes"])

    def execute(
        station_id: int, scope_id: int | None, action: str, data: ScopeCommand,
        db: Session, actor: Account, response: Response,
    ) -> dict[str, Any]:
        if actor.role != "counting_officer":
            raise HTTPException(403, detail={"code": "counting_officer_required"})
        turnout_scope(db, actor, station_id, writable=True)
        options = scope_options(db, actor, station_id)
        if not options["counting_applicable"]:
            raise HTTPException(409, detail={"code": "counting_station_required"})
        digest = hashlib.sha256(json.dumps({
            "station_id": station_id, "scope_id": scope_id, "actor_id": actor.id, "action": action,
            "data": data.model_dump(mode="json", exclude={"request_id"}),
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        replay = db.scalar(select(CountingScopeRequest).where(
            CountingScopeRequest.request_id == str(data.request_id)
        ).with_for_update().execution_options(populate_existing=True))
        if replay:
            if replay.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return replay.response
        scope = scope_at(db, station_id, scope_id) if scope_id is not None else None
        current = latest_revision(db, scope.id) if scope else None
        if data.expected_revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        if isinstance(data, ScopeDraft):
            event_at = data.event_at.replace(tzinfo=None)
            if event_at > now:
                raise HTTPException(422, detail={"code": "event_time_in_future"})
            if current and current.status != "draft" and not data.amendment_reason.strip():
                raise HTTPException(422, detail={"code": "scope_reason_required"})
            if scope is None:
                duplicate = db.scalar(select(CountingScope).where(
                    CountingScope.station_id == station_id,
                    CountingScope.reference == data.reference,
                ).with_for_update())
                if duplicate:
                    raise HTTPException(409, detail={"code": "scope_reference_conflict"})
                scope = CountingScope(station_id=station_id, reference=data.reference)
                db.add(scope)
                db.flush()
            elif scope.reference != data.reference:
                raise HTTPException(422, detail={"code": "scope_reference_immutable"})
            frozen = draft_basis(db, options, data, scope.id)
            current = CountingScopeRevision(
                scope_id=scope.id, revision=data.expected_revision + 1, status="draft",
                event_at=event_at, entered_at=now, actor_id=actor.id,
                notes=data.notes, amendment_reason=data.amendment_reason, data=frozen,
            )
            db.add(current)
            db.execute(delete(CountingScopeBox).where(CountingScopeBox.scope_id == scope.id))
            db.add_all(CountingScopeBox(box_id=row["id"], scope_id=scope.id)
                       for row in frozen["box_basis"])
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, detail={"code": "scope_membership_conflict"}) from None
        else:
            if current is None or scope is None or current.status != "draft":
                raise HTTPException(409, detail={"code": "scope_state_conflict"})
            view = scope_view(db, scope, current, options["boxes"])
            if view["blockers"]:
                raise HTTPException(409, detail={
                    "code": "scope_incomplete", "blockers": view["blockers"]
                })
            current.status, current.submitted_at, current.submitted_by = "submitted", now, actor.id
        assert scope is not None
        # Refresh only membership in the already-locked destination box snapshot.
        member_ids = {box.box_id for box in db.scalars(select(CountingScopeBox).where(
            CountingScopeBox.scope_id == scope.id
        ).with_for_update())}
        boxes = [{**box, "scope_id": scope.id if box["id"] in member_ids else box["scope_id"]}
                 for box in options["boxes"]]
        result = scope_view(db, scope, current, boxes)
        db.add(CountingScopeRequest(
            request_id=str(data.request_id), station_id=station_id, actor_id=actor.id,
            digest=digest, response=result,
        ))
        db.add(AuditEvent(actor_id=actor.id, action="counting_scope_" + action, occurred_at=now,
                          details={"station_id": station_id, "scope_id": scope.id,
                                   "revision": current.revision,
                                   "reason": current.amendment_reason}))
        db.commit()
        return result

    @router.post("", status_code=201)
    def create(
        station_id: int, data: ScopeDraft, db: Database, actor: Actor, response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, None, "save", data, db, actor, response)

    @router.put("/{scope_id}")
    def save(
        station_id: int, scope_id: int, data: ScopeDraft,
        db: Database, actor: Actor, response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, scope_id, "save", data, db, actor, response)

    @router.post("/{scope_id}/submit")
    def submit(
        station_id: int, scope_id: int, data: ScopeCommand,
        db: Database, actor: Actor, response: Response,
    ) -> dict[str, Any]:
        return execute(station_id, scope_id, "submit", data, db, actor, response)

    return router
