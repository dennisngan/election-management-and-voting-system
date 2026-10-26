"""Revision-bound completion and review of preserved physical count observations."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_round_models import (
    CountRoundRequest,
    CountRoundRevision,
    CountRoundSelection,
)
from election.server.counting_rounds import (
    latest_round_revision,
    round_at,
    round_context,
    round_view,
)
from election.server.counting_totals import physical_approval_blockers
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.paper_reentry import finish_paper_entry, guard_paper_entry
from election.server.polling import as_utc
from election.server.security import verify_password
from election.server.turnout_basis import turnout_scope


class CountBaseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    scope_revision: int = Field(strict=True, ge=1)


class CountCommand(CountBaseCommand):
    paper_record_id: int | None = Field(default=None, strict=True, gt=0)


class CountApproval(CountBaseCommand):
    password: str = Field(min_length=1, max_length=128, repr=False)


class CountSelection(CountApproval):
    expected_selection_revision: int = Field(strict=True, ge=0)


def command_digest(
    action: str,
    station_id: int,
    scope_id: int,
    round_id: int,
    actor_id: int,
    data: CountBaseCommand,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": action,
                "station_id": station_id,
                "scope_id": scope_id,
                "round_id": round_id,
                "actor_id": actor_id,
                "data": data.model_dump(
                    mode="json", exclude={"request_id", "password", "paper_record_id"}
                ),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def counting_workflow_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/rounds",
        tags=["count completion and review"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.post("/{round_id}/submit")
    def submit(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: CountCommand,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        if actor.role != "counting_officer":
            raise HTTPException(403, detail={"code": "counting_officer_required"})
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        turnout_scope(db, actor, station_id, writable=True)
        options = round_context(db, actor, station_id, scope_id)
        digest = command_digest("submit", station_id, scope_id, round_id, actor.id, data)
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(CountRoundRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            paper_entry = guard_paper_entry(
                db,
                actor,
                station_id,
                data.paper_record_id,
                "count",
                "submit",
                {"scope_id": scope_id, "round_id": round_id},
                data.request_id,
            )
            finish_paper_entry(
                db, actor, paper_entry, data.request_id, receipt.response, timestamp()
            )
            if paper_entry is not None:
                db.commit()
            return receipt.response
        paper_entry = guard_paper_entry(
            db,
            actor,
            station_id,
            data.paper_record_id,
            "count",
            "submit",
            {"scope_id": scope_id, "round_id": round_id},
            data.request_id,
        )
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        round = round_at(db, scope_id, round_id)
        current = latest_round_revision(db, round.id)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        view = round_view(db, round, current, options)
        if current.status != "draft":
            raise HTTPException(409, detail={"code": "count_round_state_conflict"})
        if not view["source_current"]:
            raise HTTPException(409, detail={"code": "count_round_basis_stale"})
        if not current.data.get("count_inputs_complete"):
            raise HTTPException(409, detail={"code": "count_inputs_incomplete"})
        now = timestamp()
        frozen = deepcopy(current.data)
        frozen.update(
            count_complete=True,
            submitted_at=as_utc(now),
            submitted_by=actor.id,
            completed_at=as_utc(now),
            completion_event={
                "origin_revision": current.revision + 1,
                "event_at": as_utc(now),
                "entered_at": as_utc(now),
                "actor_id": actor.id,
                "amendment_reason": "",
            },
        )
        row = CountRoundRevision(
            round_id=round.id,
            revision=current.revision + 1,
            status="submitted",
            event_at=now,
            entered_at=now,
            actor_id=actor.id,
            notes="",
            amendment_reason="",
            data=frozen,
        )
        db.add(row)
        db.flush()
        result = round_view(db, round, row, options)
        db.add(
            CountRoundRequest(
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
                action="count_round_submitted",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "revision": row.revision,
                },
            )
        )
        finish_paper_entry(db, actor, paper_entry, data.request_id, result, now)
        db.commit()
        return result

    @router.post("/{round_id}/approve")
    def approve(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: CountApproval,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        turnout_scope(db, actor, station_id, writable=True)
        password_hash = db.scalar(
            select(Account.password_hash).where(Account.id == actor.id).with_for_update()
        )
        if not verify_password(password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        options = round_context(db, actor, station_id, scope_id)
        digest = command_digest("approve", station_id, scope_id, round_id, actor.id, data)
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(CountRoundRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return receipt.response
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        round = round_at(db, scope_id, round_id)
        current = latest_round_revision(db, round.id)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        view = round_view(db, round, current, options)
        if current.status != "submitted":
            raise HTTPException(409, detail={"code": "count_round_state_conflict"})
        if not view["source_current"]:
            raise HTTPException(409, detail={"code": "count_round_basis_stale"})
        if not current.data.get("count_inputs_complete"):
            raise HTTPException(409, detail={"code": "count_inputs_incomplete"})
        now = timestamp()
        frozen = deepcopy(current.data)
        if physical_approval_blockers(frozen, comparisons=view["physical_comparisons"]):
            raise HTTPException(409, detail={"code": "count_physical_difference_unaccepted"})
        frozen.update(
            physical_comparisons=view["physical_comparisons"],
            approved_physical_decisions=[
                decision for decision in view["physical_decisions"] if decision["valid"]
            ],
            approved_at=as_utc(now),
            approved_by=actor.id,
            reviewed_revision=current.revision,
            reviewed_revision_id=current.id,
        )
        row = CountRoundRevision(
            round_id=round.id,
            revision=current.revision + 1,
            status="approved",
            event_at=now,
            entered_at=now,
            actor_id=actor.id,
            notes="",
            amendment_reason="",
            data=frozen,
        )
        db.add(row)
        db.flush()
        result = round_view(db, round, row, options)
        db.add(
            CountRoundRequest(
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
                action="count_round_approved",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "revision": row.revision,
                },
            )
        )
        db.commit()
        return result

    @router.post("/{round_id}/select")
    def select_round(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: CountSelection,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        turnout_scope(db, actor, station_id, writable=True)
        password_hash = db.scalar(
            select(Account.password_hash).where(Account.id == actor.id).with_for_update()
        )
        if not verify_password(password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        options = round_context(db, actor, station_id, scope_id)
        digest = command_digest("select", station_id, scope_id, round_id, actor.id, data)
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(CountRoundRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return receipt.response
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        round = round_at(db, scope_id, round_id)
        current = latest_round_revision(db, round.id)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        view = round_view(db, round, current, options)
        if current.status != "approved":
            raise HTTPException(409, detail={"code": "count_round_state_conflict"})
        if not view["source_current"]:
            raise HTTPException(409, detail={"code": "count_round_basis_stale"})
        if not view["approval_valid"]:
            raise HTTPException(409, detail={"code": "count_approval_invalid"})
        prior = options["selection"]
        revision = prior["revision"] if prior else 0
        if data.expected_selection_revision != revision:
            raise HTTPException(409, detail={"code": "selection_revision_conflict"})
        now = timestamp()
        pointer = CountRoundSelection(
            scope_id=scope_id,
            revision=revision + 1,
            round_revision_id=current.id,
            selected_at=now,
            actor_id=actor.id,
        )
        db.add(pointer)
        db.flush()
        refreshed = round_context(db, actor, station_id, scope_id)
        result = round_view(db, round, current, refreshed)
        db.add(
            CountRoundRequest(
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
                action="count_round_selected",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "revision": current.revision,
                    "selection_revision": pointer.revision,
                },
            )
        )
        db.commit()
        return result

    return router
