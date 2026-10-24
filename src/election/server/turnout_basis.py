"""Current reporting scope, schedule and exact ordinary-stock source checks."""

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.lifecycle_models import ActiveElection, ElectionSchedule
from election.server.models import Account
from election.server.stock import stock_scope
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_snapshots import snapshot_basis_current, snapshot_view


def locked_schedule(db: Session, election_id: int) -> ElectionSchedule:
    schedule = db.scalar(
        select(ElectionSchedule)
        .where(ElectionSchedule.election_id == election_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if schedule is None:
        raise HTTPException(409, detail={"code": "schedule_not_configured"})
    return schedule


def turnout_scope(
    db: Session, actor: Account, station_id: int, *, writable: bool = False,
) -> dict[str, Any]:
    scope = stock_scope(db, actor, station_id)
    # Match activation/configuration first, then the physical-stock write locks.
    active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
    election = db.scalar(select(Election).where(
        Election.id == scope["election"]["id"],
    ).with_for_update().execution_options(populate_existing=True))
    assert election is not None
    db.scalar(select(Constituency).where(
        Constituency.id == scope["constituency"]["id"],
    ).with_for_update().execution_options(populate_existing=True))
    if writable and (
        active is None or active.election_id != election.id or election.status != "active"
    ):
        raise HTTPException(409, detail={"code": "active_election_required"})
    return stock_scope(db, actor, station_id)


def stock_snapshot_basis(
    db: Session, station_id: int, snapshot_id: int, revision: int, event_at: datetime,
) -> dict[str, Any]:
    head = db.scalar(select(StockSnapshot).where(
        StockSnapshot.id == snapshot_id, StockSnapshot.station_id == station_id,
    ).with_for_update().execution_options(populate_existing=True))
    if head is None:
        raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
    if head.revision != revision:
        raise HTTPException(409, detail={"code": "stock_snapshot_basis_stale"})
    row = db.scalar(select(StockSnapshotRevision).where(
        StockSnapshotRevision.snapshot_id == snapshot_id,
        StockSnapshotRevision.revision == revision,
    ).with_for_update().execution_options(populate_existing=True))
    assert row is not None
    if not row.data["complete"]:
        raise HTTPException(409, detail={"code": "stock_snapshot_incomplete"})
    if row.event_at != event_at:
        raise HTTPException(409, detail={"code": "fallback_balance_time_required"})
    if not snapshot_basis_current(db, station_id, row, lock=True):
        raise HTTPException(409, detail={"code": "stock_snapshot_basis_stale"})
    frozen: dict[str, Any] = jsonable_encoder(
        snapshot_view(row, station_id),
        custom_encoder={datetime: lambda value: value.isoformat().replace("+00:00", "Z")},
    )
    return frozen

