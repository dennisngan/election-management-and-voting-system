"""Read the durable result of an uncertain count command."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_round_models import CountRoundRequest
from election.server.models import Account
from election.server.stock import stock_scope


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
        workflow: Literal["count"],
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        if actor.role not in ("counting_officer", "supervisor"):
            raise HTTPException(403, detail={"code": "request_outcome_role_required"})
        stock_scope(db, actor, station_id)
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(
                CountRoundRequest.request_id == str(request_id),
                CountRoundRequest.station_id == station_id,
                CountRoundRequest.actor_id == actor.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt is None:
            return {
                "request_id": str(request_id),
                "workflow": workflow,
                "status": "not_found",
            }
        return {
            "request_id": str(request_id),
            "workflow": workflow,
            "status": "committed",
            "record": receipt.response,
        }

    return router
