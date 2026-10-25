"""Explicit Supervisor tie decisions preserve the exact complete result reviewed."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.constituency_result_models import (
    ConstituencyResultRequest,
    ConstituencyTieResolution,
)
from election.server.constituency_results import constituency_result
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.security import verify_password
from election.server.turnout_basis import turnout_scope


class TieResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_resolution_revision: int = Field(strict=True, ge=0)
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: int = Field(strict=True, gt=0)
    reason: str = Field(max_length=2000)
    password: str = Field(min_length=1, max_length=128, repr=False)


def constituency_ties_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/constituencies", tags=["Constituency ties"])
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.post("/{constituency_id}/results/tie-resolutions")
    def resolve(
        constituency_id: int, data: TieResolution, db: Database, actor: Actor
    ) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        result = constituency_result(db, actor, constituency_id)
        password_hash = db.scalar(
            select(Account.password_hash).where(Account.id == actor.id).with_for_update()
        )
        if not verify_password(password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        if not data.reason.strip():
            raise HTTPException(422, detail={"code": "tie_resolution_reason_required"})
        # The result reader has already checked all constituency station assignments.
        election = result["context"]["election"]
        if election["status"] != "active":
            raise HTTPException(409, detail={"code": "active_election_required"})
        if result["contributions"]:
            turnout_scope(db, actor, result["contributions"][0]["station_id"], writable=True)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "constituency_id": constituency_id,
                    "actor_id": actor.id,
                    "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        receipt = db.scalar(
            select(ConstituencyResultRequest)
            .where(ConstituencyResultRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return receipt.response
        if result["basis_digest"] != data.basis_digest:
            raise HTTPException(409, detail={"code": "constituency_result_basis_stale"})
        if not result["complete"]:
            raise HTTPException(409, detail={"code": "constituency_result_incomplete"})
        if len(result["tie_candidate_ids"]) < 2:
            raise HTTPException(409, detail={"code": "constituency_tie_missing"})
        if data.candidate_id not in result["tie_candidate_ids"]:
            raise HTTPException(422, detail={"code": "tie_candidate_invalid"})
        current = result["tie_resolution"]
        if (current["revision"] if current else 0) != data.expected_resolution_revision:
            raise HTTPException(409, detail={"code": "tie_resolution_revision_conflict"})
        now = timestamp()
        row = ConstituencyTieResolution(
            constituency_id=constituency_id,
            revision=data.expected_resolution_revision + 1,
            candidate_id=data.candidate_id,
            actor_id=actor.id,
            accepted_at=now,
            reason=data.reason,
            basis_digest=data.basis_digest,
            data={
                key: result[key]
                for key in (
                    "context",
                    "candidate_totals",
                    "contributions",
                    "pending",
                    "complete",
                    "leader_candidate_ids",
                    "tie_candidate_ids",
                    "basis_digest",
                )
            },
        )
        db.add(row)
        db.flush()
        response = constituency_result(db, actor, constituency_id)
        db.add(
            ConstituencyResultRequest(
                request_id=str(data.request_id),
                constituency_id=constituency_id,
                actor_id=actor.id,
                digest=digest,
                response=response,
            )
        )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="constituency_tie_resolved",
                occurred_at=now,
                details={
                    "constituency_id": constituency_id,
                    "resolution_id": row.id,
                    "revision": row.revision,
                    "candidate_id": data.candidate_id,
                    "basis_digest": data.basis_digest,
                    "reason": data.reason,
                },
            )
        )
        db.commit()
        return response

    return router
