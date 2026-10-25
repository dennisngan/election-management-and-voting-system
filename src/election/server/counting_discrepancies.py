"""Supervisor dispositions of exact physical-paper comparisons through public HTTP."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_discrepancy_models import CountPhysicalDecision
from election.server.counting_round_models import CountRoundRequest
from election.server.counting_rounds import (
    latest_round_revision,
    round_at,
    round_context,
    round_view,
)
from election.server.counting_totals import physical_comparisons
from election.server.counting_workflow import CountApproval, command_digest
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.physical_decisions import comparison_fingerprint
from election.server.security import verify_password
from election.server.turnout_basis import turnout_scope


class PhysicalAcceptance(CountApproval):
    expected_decision_revision: int = Field(strict=True, ge=0)
    reason: str = Field(max_length=2000)


def counting_discrepancies_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/rounds",
        tags=["physical discrepancy review"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.post("/{round_id}/physical-differences/{source}/accept")
    def accept(
        station_id: int,
        scope_id: int,
        round_id: int,
        source: Literal["stock", "turnout"],
        data: PhysicalAcceptance,
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
        if not data.reason.strip():
            raise HTTPException(422, detail={"code": "physical_difference_reason_required"})
        options = round_context(db, actor, station_id, scope_id)
        digest = command_digest(
            "accept_physical_" + source, station_id, scope_id, round_id, actor.id, data
        )
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
        if not view["count_inputs_complete"]:
            raise HTTPException(409, detail={"code": "count_inputs_incomplete"})
        comparison = next(
            row for row in physical_comparisons(current.data) if row["source"] == source
        )
        if not comparison["available"]:
            raise HTTPException(409, detail={"code": "physical_difference_unavailable"})
        if comparison["difference_quantity"] == 0:
            raise HTTPException(409, detail={"code": "physical_difference_not_pending"})
        previous = db.scalar(
            select(CountPhysicalDecision)
            .where(
                CountPhysicalDecision.round_id == round.id, CountPhysicalDecision.source == source
            )
            .order_by(CountPhysicalDecision.revision.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (previous.revision if previous else 0) != data.expected_decision_revision:
            raise HTTPException(409, detail={"code": "physical_decision_revision_conflict"})
        now = timestamp()
        snapshot = {
            "reviewed_revision": current.revision,
            "scope_revision": data.scope_revision,
            **{
                key: comparison[key]
                for key in ("expected_quantity", "actual_quantity", "difference_quantity")
            },
        }
        row = CountPhysicalDecision(
            round_id=round.id,
            source=source,
            revision=data.expected_decision_revision + 1,
            round_revision_id=current.id,
            actor_id=actor.id,
            accepted_at=now,
            reason=data.reason,
            fingerprint=comparison_fingerprint(current.data, comparison),
            data=snapshot,
        )
        db.add(row)
        db.flush()
        result = round_view(db, round, current, options)
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
                action="count_physical_difference_accepted",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "source": source,
                    "reviewed_revision_id": current.id,
                    "decision_revision": row.revision,
                    "reason": data.reason,
                    "fingerprint": row.fingerprint,
                    **snapshot,
                },
            )
        )
        db.commit()
        return result

    return router
