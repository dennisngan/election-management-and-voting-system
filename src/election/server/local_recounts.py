"""Authorize one new blank physical-count round without replacing its reviewed source."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from election.server.boxes import utc_time
from election.server.counting_round_models import CountRound, CountRoundRequest, CountRoundRevision
from election.server.counting_rounds import (
    F1Draft,
    f1_basis,
    latest_round_revision,
    round_context,
    round_view,
)
from election.server.lifecycle_models import ActiveElection
from election.server.local_recount_models import LocalRecountInstruction
from election.server.models import Account, AuditEvent
from election.server.recount_state import scope_recount_state
from election.server.security import verify_password
from election.server.turnout_basis import turnout_scope


class LocalRecountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    scope_revision: int = Field(strict=True, ge=1)
    expected_selection_revision: int = Field(strict=True, ge=0)
    source_round_id: int = Field(strict=True, ge=1)
    source_round_revision: int = Field(strict=True, ge=1)
    event_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=2000)
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("event_at")
    @classmethod
    def supported_time(cls, value: datetime) -> datetime:
        return utc_time(value)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A local recount reason is required")
        return value


@dataclass(frozen=True)
class CreatedRecount:
    instruction: LocalRecountInstruction
    round: CountRound
    revision: CountRoundRevision


def local_recount_digest(
    actor_id: int, station_id: int, scope_id: int, data: LocalRecountInput,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": "local-recount", "station_id": station_id,
                "scope_id": scope_id, "actor_id": actor_id,
                "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
            }, sort_keys=True, ensure_ascii=False,
        ).encode()
    ).hexdigest()


def create_local_recount_round(
    db: Session, actor_id: int, options: dict[str, Any], source: CountRoundRevision,
    data: LocalRecountInput, now: datetime,
) -> CreatedRecount:
    """Append one blank replacement inside the caller's authorized transaction."""
    scope_id = options["scope"]["id"]
    number = db.scalar(
        select(func.max(CountRound.round_number)).where(CountRound.scope_id == scope_id)
    )
    replacement = CountRound(scope_id=scope_id, round_number=(number or 0) + 1)
    db.add(replacement)
    db.flush()
    blank = f1_basis(
        options,
        F1Draft(
            request_id=data.request_id, expected_revision=0,
            scope_revision=data.scope_revision, event_at=data.event_at,
        ),
    )
    blank["scope_basis"] = deepcopy(source.data["scope_basis"])
    blank["instruction_only"] = True
    event_at = data.event_at.replace(tzinfo=None)
    revision = CountRoundRevision(
        round_id=replacement.id, revision=1, status="draft",
        event_at=event_at, entered_at=now, actor_id=actor_id,
        notes="", amendment_reason="", data=blank,
    )
    db.add(revision)
    instruction = LocalRecountInstruction(
        request_id=str(data.request_id), scope_id=scope_id,
        scope_revision_id=options["scope"]["revision_id"],
        source_round_revision_id=source.id, new_round_id=replacement.id,
        actor_id=actor_id, reason=data.reason, event_at=event_at, entered_at=now,
    )
    db.add(instruction)
    db.flush()
    return CreatedRecount(instruction, replacement, revision)


def preserve_local_recount_receipt(
    db: Session, actor_id: int, created: CreatedRecount,
    options: dict[str, Any], data: LocalRecountInput,
) -> dict[str, Any]:
    """Keep the original acknowledgement and audit without committing the transaction."""
    station_id, scope_id = options["context"]["station"]["id"], options["scope"]["id"]
    projected = scope_recount_state(db, scope_id, options["selection"])["latest_instruction"]
    result = {
        "instruction": projected,
        "round": round_view(db, created.round, created.revision, options),
    }
    db.add(
        CountRoundRequest(
            request_id=str(data.request_id), station_id=station_id, actor_id=actor_id,
            digest=local_recount_digest(actor_id, station_id, scope_id, data),
            response=deepcopy(result),
        )
    )
    db.add(
        AuditEvent(
            actor_id=actor_id, action="local_recount_instructed",
            occurred_at=created.instruction.entered_at,
            details={
                "station_id": station_id, "scope_id": scope_id,
                "instruction_id": created.instruction.id, "request_id": str(data.request_id),
                "source_round_id": data.source_round_id,
                "source_round_revision": data.source_round_revision,
                "new_round_id": created.round.id, "reason": data.reason,
            },
        )
    )
    return result


def local_recounts_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts",
        tags=["local recount instructions"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(station_id: int, scope_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        options = round_context(db, actor, station_id, scope_id)
        state = scope_recount_state(db, scope_id, options["selection"])
        selection = options["selection"]
        return {
            "context": options["context"],
            "scope": options["scope"],
            "selection": selection,
            **state,
            "can_instruct": bool(
                actor.role == "supervisor"
                and options["context"]["election"]["status"] == "active"
                and options["scope"]["count_ready"]
                and selection and selection.get("valid")
                and not state["pending"]
            ),
        }

    @router.post("", status_code=201)
    def instruct(
        station_id: int, scope_id: int, data: LocalRecountInput,
        response: Response, db: Database, actor: Actor,
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
        digest = local_recount_digest(actor.id, station_id, scope_id, data)
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(CountRoundRequest.request_id == str(data.request_id))
            .with_for_update().execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return receipt.response
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        if not options["scope"]["count_ready"]:
            raise HTTPException(409, detail={"code": "count_scope_not_ready"})
        selection = options["selection"]
        if not selection or (
            not selection["valid"]
            or selection["revision"] != data.expected_selection_revision
            or selection["round_id"] != data.source_round_id
            or selection["round_revision"] != data.source_round_revision
        ):
            raise HTTPException(409, detail={"code": "local_recount_selection_stale"})
        if scope_recount_state(db, scope_id, selection)["pending"]:
            raise HTTPException(409, detail={"code": "local_recount_pending"})
        source = latest_round_revision(db, data.source_round_id)
        if source is None or source.id != selection["round_revision_id"]:
            raise HTTPException(409, detail={"code": "local_recount_source_stale"})
        now = timestamp()
        event_at = data.event_at.replace(tzinfo=None)
        if event_at > now:
            raise HTTPException(422, detail={"code": "event_time_in_future"})
        created = create_local_recount_round(db, actor.id, options, source, data, now)
        result = preserve_local_recount_receipt(db, actor.id, created, options, data)
        db.commit()
        return result

    return router
