"""Received-box provenance at the assigned counting station."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from election.server.accounting import accounting_record, record_view
from election.server.boxes import box_snapshot
from election.server.models import Account


def scope_options(db: Session, actor: Account, station_id: int) -> dict[str, Any]:
    snapshot = box_snapshot(db, actor, station_id)
    boxes = [
        {**box, "scope_id": None}
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
    return {
        "context": snapshot["context"],
        "counting_applicable": snapshot["counting_applicable"],
        "boxes": boxes,
        "source_accounting": sources,
        "scopes": [],
    }


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

    return router
