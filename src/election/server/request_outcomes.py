"""Read the durable result of an uncertain count command."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.allocations import allocation_view
from election.server.counting_round_models import CountRoundRequest
from election.server.models import Account
from election.server.stock import stock_scope
from election.server.turnout_models import TurnoutRequest

RequestWorkflow = Literal["count", "turnout", "allocation"]


def read_request_outcome(
    db: Session,
    actor: Account,
    station_id: int,
    request_id: UUID,
    workflow: RequestWorkflow,
) -> dict[str, Any]:
    """Return an immutable actor-scoped receipt for a supported workflow."""
    allowed_roles = (
        ("counting_officer", "supervisor")
        if workflow == "count"
        else ("polling_officer", "supervisor")
    )
    if actor.role not in allowed_roles:
        raise HTTPException(403, detail={"code": "request_outcome_role_required"})
    scope = stock_scope(db, actor, station_id)
    receipt: dict[str, Any] | None = None
    if workflow == "count":
        count_row = db.scalar(
            select(CountRoundRequest)
            .where(
                CountRoundRequest.request_id == str(request_id),
                CountRoundRequest.station_id == station_id,
                CountRoundRequest.actor_id == actor.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if count_row is not None:
            receipt = count_row.response
    elif workflow == "turnout":
        turnout_row = db.scalar(
            select(TurnoutRequest).where(
                TurnoutRequest.request_id == str(request_id),
                TurnoutRequest.station_id == station_id,
                TurnoutRequest.actor_id == actor.id,
            )
        )
        if turnout_row is not None:
            receipt = turnout_row.response
    else:
        allocation_row = db.scalar(
            select(StockAllocationRevision)
            .join(StockAllocation, StockAllocation.id == StockAllocationRevision.allocation_id)
            .where(
                StockAllocationRevision.request_id == str(request_id),
                StockAllocationRevision.actor_id == actor.id,
                StockAllocation.station_id == station_id,
            )
        )
        if allocation_row is not None:
            receipt = allocation_view(allocation_row, scope)
    if receipt is None:
        return {"request_id": str(request_id), "workflow": workflow, "status": "not_found"}
    return {
        "request_id": str(request_id),
        "workflow": workflow,
        "status": "committed",
        "record": receipt,
    }


def request_outcomes_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    """Expose actor-scoped read-only request receipts for supported workflows."""
    _ = timestamp
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/request-outcomes",
        tags=["request outcomes"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("/{request_id}")
    def read(
        station_id: int,
        request_id: UUID,
        workflow: RequestWorkflow,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        return read_request_outcome(db, actor, station_id, request_id, workflow)

    return router
