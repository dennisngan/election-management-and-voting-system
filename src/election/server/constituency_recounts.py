"""Create every required local replacement in one constituency transaction."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.boxes import utc_time
from election.server.constituency_recount_models import (
    ConstituencyRecountInstruction,
    ConstituencyRecountMember,
)
from election.server.constituency_result_models import ConstituencyResultRequest
from election.server.constituency_results import constituency_result
from election.server.counting_round_models import CountRoundRevision
from election.server.counting_rounds import latest_round_revision, round_context
from election.server.lifecycle_models import ActiveElection
from election.server.local_recount_models import LocalRecountInstruction
from election.server.local_recounts import (
    LocalRecountInput,
    create_local_recount_round,
    preserve_local_recount_receipt,
)
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc
from election.server.recount_state import scope_recount_state
from election.server.security import verify_password


class RecountScopeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: int = Field(strict=True, ge=1)
    scope_id: int = Field(strict=True, ge=1)
    scope_revision: int = Field(strict=True, ge=1)
    source_round_id: int = Field(strict=True, ge=1)
    source_round_revision: int = Field(strict=True, ge=1)
    expected_selection_revision: int = Field(strict=True, ge=1)


class ConstituencyRecountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_sources: list[RecountScopeSource] = Field(min_length=1)
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
            raise ValueError("A constituency recount reason is required")
        return value


def _scope_sources(result: dict[str, Any]) -> list[dict[str, int]]:
    return [
        {
            "station_id": row["station_id"], "scope_id": row["scope_id"],
            "scope_revision": row["scope_revision"],
            "source_round_id": row["round_id"],
            "source_round_revision": row["round_revision"],
            "expected_selection_revision": row["selection_revision"],
        }
        for row in sorted(result["contributions"], key=lambda row: (
            row["station_id"], row["scope_id"],
        ))
    ]


def _instruction_view(
    db: Session, instruction: ConstituencyRecountInstruction, *, is_latest: bool,
) -> dict[str, Any]:
    rows = db.execute(
        select(ConstituencyRecountMember, LocalRecountInstruction)
        .join(LocalRecountInstruction, LocalRecountInstruction.id == (
            ConstituencyRecountMember.local_instruction_id
        ))
        .where(ConstituencyRecountMember.instruction_id == instruction.id)
        .order_by(ConstituencyRecountMember.position)
        .with_for_update()
    )
    members = []
    for member, local in rows:
        state = scope_recount_state(db, member.scope_id, None)
        original = next(row for row in state["instructions"] if row["id"] == local.id)
        revision = latest_round_revision(db, local.new_round_id)
        assert revision is not None
        progress = (
            "completed" if original["completed_at"] is not None
            else "approved" if revision.status == "approved"
            else "submitted" if revision.status == "submitted" else "incomplete"
        )
        members.append({
            "station_id": member.station_id, "scope_id": member.scope_id,
            "local_instruction_id": local.id, "progress": progress,
            "new_round_id": local.new_round_id,
            "new_round_number": original["new_round_number"],
            "round_revision": revision.revision,
            "scope_source": deepcopy(instruction.data["scope_sources"][member.position]),
            "source_context": deepcopy(instruction.data["source_contexts"][member.position]),
            "completed_at": original["completed_at"],
            "completion_selection_id": original["completion_selection_id"],
            "completion_selection_revision": original["completion_selection_revision"],
            "completion_round_revision_id": original["completion_round_revision_id"],
            "current_required_round_id": state["latest_instruction"]["new_round_id"],
        })
    completed = [row["completed_at"] for row in members if row["completed_at"] is not None]
    complete = bool(members) and len(completed) == len(members)
    return {
        "id": instruction.id, "request_id": instruction.request_id,
        "constituency_id": instruction.constituency_id, "actor_id": instruction.actor_id,
        "reason": instruction.reason, "event_at": as_utc(instruction.event_at),
        "entered_at": as_utc(instruction.entered_at), "basis_digest": instruction.basis_digest,
        "context": deepcopy(instruction.data["context"]),
        "scope_sources": deepcopy(instruction.data["scope_sources"]),
        "members": members, "member_count": len(members),
        "completed_member_count": len(completed), "historical_complete": complete,
        "completed_at": max(completed, key=datetime.fromisoformat) if complete else None,
        "is_latest": is_latest,
    }


def _source_contexts(
    db: Session, actor: Account, sources: list[dict[str, int]],
) -> list[tuple[dict[str, Any], CountRoundRevision]]:
    contexts = []
    for row in sources:
        options = round_context(db, actor, row["station_id"], row["scope_id"])
        selection = options["selection"]
        source = latest_round_revision(db, row["source_round_id"])
        if not (
            options["scope"]["count_ready"]
            and options["scope"]["revision"] == row["scope_revision"]
            and selection and selection["valid"]
            and selection["revision"] == row["expected_selection_revision"]
            and selection["round_id"] == row["source_round_id"]
            and selection["round_revision"] == row["source_round_revision"]
            and source is not None and source.id == selection["round_revision_id"]
            and not scope_recount_state(db, row["scope_id"], selection)["pending"]
        ):
            raise HTTPException(409, detail={"code": "constituency_recount_sources_stale"})
        assert source is not None
        contexts.append((options, source))
    return contexts


def constituency_recounts_router(
    database: Callable[..., Any], ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/constituencies/{constituency_id}/recounts",
        tags=["constituency recount instructions"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(constituency_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        result = constituency_result(db, actor, constituency_id)
        rows = list(db.scalars(
            select(ConstituencyRecountInstruction)
            .where(ConstituencyRecountInstruction.constituency_id == constituency_id)
            .order_by(ConstituencyRecountInstruction.id.desc()).with_for_update()
        ))
        return {
            "context": result["context"], "basis_digest": result["basis_digest"],
            "scope_sources": _scope_sources(result) if result["complete"] else [],
            "can_instruct": result["context"]["election"]["status"] == "active"
            and result["complete"],
            "blockers": result["pending"],
            "instructions": [_instruction_view(db, row, is_latest=index == 0)
                             for index, row in enumerate(rows)],
        }

    @router.post("", status_code=201)
    def instruct(
        constituency_id: int, data: ConstituencyRecountInput,
        response: Response, db: Database, actor: Actor,
    ) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        result = constituency_result(db, actor, constituency_id)
        current_actor = db.scalar(
            select(Account).where(Account.id == actor.id).with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_actor is None or current_actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        if not verify_password(current_actor.password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        election = result["context"]["election"]
        if election["status"] != "active" or active is None or active.election_id != election["id"]:
            raise HTTPException(409, detail={"code": "active_election_required"})
        digest = hashlib.sha256(json.dumps({
            "action": "constituency-recount", "constituency_id": constituency_id,
            "actor_id": actor.id,
            "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = db.scalar(
            select(ConstituencyResultRequest)
            .where(ConstituencyResultRequest.request_id == str(data.request_id))
            .with_for_update().execution_options(populate_existing=True)
        )
        if cached is not None:
            if cached.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return cached.response
        if result["basis_digest"] != data.basis_digest:
            raise HTTPException(409, detail={"code": "constituency_result_basis_stale"})
        if not result["complete"]:
            raise HTTPException(409, detail={"code": "constituency_result_incomplete"})
        sources = _scope_sources(result)
        if [row.model_dump() for row in data.scope_sources] != sources:
            raise HTTPException(409, detail={"code": "constituency_recount_sources_stale"})
        contexts = _source_contexts(db, actor, sources)
        now = timestamp()
        event_at = data.event_at.replace(tzinfo=None)
        if event_at > now:
            raise HTTPException(422, detail={"code": "event_time_in_future"})
        parent = ConstituencyRecountInstruction(
            request_id=str(data.request_id), constituency_id=constituency_id,
            actor_id=actor.id, reason=data.reason, basis_digest=data.basis_digest,
            event_at=event_at, entered_at=now,
            data={
                "context": deepcopy(result["context"]), "scope_sources": deepcopy(sources),
                "source_contexts": [
                    {"context": deepcopy(options["context"]),
                     "scope_reference": options["scope"]["reference"]}
                    for options, _ in contexts
                ],
            },
        )
        db.add(parent)
        db.flush()
        created_members = []
        for position, (options, source) in enumerate(contexts):
            local_data = LocalRecountInput(
                **{key: value for key, value in sources[position].items()
                   if key not in {"station_id", "scope_id"}},
                request_id=uuid5(data.request_id, f"scope:{options['scope']['id']}"),
                event_at=data.event_at, reason=data.reason, password=data.password,
            )
            created = create_local_recount_round(db, actor.id, options, source, local_data, now)
            db.add(ConstituencyRecountMember(
                instruction_id=parent.id, scope_id=options["scope"]["id"],
                station_id=sources[position]["station_id"],
                local_instruction_id=created.instruction.id, position=position,
            ))
            created_members.append((created, options, local_data))
        db.flush()
        members = [preserve_local_recount_receipt(db, actor.id, created, options, local_data)
                   for created, options, local_data in created_members]
        receipt = {"instruction": _instruction_view(db, parent, is_latest=True), "members": members}
        db.add(ConstituencyResultRequest(
            request_id=str(data.request_id), constituency_id=constituency_id,
            actor_id=actor.id, digest=digest, response=deepcopy(receipt),
        ))
        db.add(AuditEvent(
            actor_id=actor.id, action="constituency_recount_instructed", occurred_at=now,
            details={
                "constituency_id": constituency_id, "instruction_id": parent.id,
                "request_id": str(data.request_id), "scope_sources": deepcopy(sources),
                "local_instruction_ids": [row.instruction.id for row, _, _ in created_members],
                "reason": data.reason,
            },
        ))
        db.commit()
        return receipt

    return router
