"""Current reporting scope, schedule and exact ordinary-stock source checks."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.fallback_models import FallbackRecord, FallbackRevision
from election.server.lifecycle_models import ActiveElection, ElectionSchedule
from election.server.models import Account
from election.server.reporting_periods import period_bounds
from election.server.stock import stock_scope
from election.server.stock_serials import MAX_STOCK_QUANTITY
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_snapshots import snapshot_basis_current, snapshot_view
from election.server.timestamps import as_utc
from election.server.turnout_models import TurnoutRecord


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
    db: Session,
    actor: Account,
    station_id: int,
    *,
    writable: bool = False,
) -> dict[str, Any]:
    scope = stock_scope(db, actor, station_id)
    # Match activation/configuration first, then the physical-stock write locks.
    active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
    election = db.scalar(
        select(Election)
        .where(
            Election.id == scope["election"]["id"],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert election is not None
    db.scalar(
        select(Constituency)
        .where(
            Constituency.id == scope["constituency"]["id"],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if writable and (
        active is None or active.election_id != election.id or election.status != "active"
    ):
        raise HTTPException(409, detail={"code": "active_election_required"})
    return stock_scope(db, actor, station_id)


def stock_snapshot_basis(
    db: Session,
    station_id: int,
    snapshot_id: int,
    revision: int,
    event_at: datetime,
) -> dict[str, Any]:
    head = db.scalar(
        select(StockSnapshot)
        .where(
            StockSnapshot.id == snapshot_id,
            StockSnapshot.station_id == station_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if head is None:
        raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
    if head.revision != revision:
        raise HTTPException(409, detail={"code": "stock_snapshot_basis_stale"})
    row = db.scalar(
        select(StockSnapshotRevision)
        .where(
            StockSnapshotRevision.snapshot_id == snapshot_id,
            StockSnapshotRevision.revision == revision,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
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


@dataclass(frozen=True)
class FallbackSelection:
    activation_id: int
    activation_revision: int
    stock_snapshot_id: int
    stock_snapshot_revision: int


def confirmed_mode_events(
    db: Session,
    station_id: int,
    end_at: datetime,
    *,
    exclude_record_id: int | None = None,
) -> list[tuple[FallbackRecord, FallbackRevision]]:
    query = (
        select(FallbackRecord, FallbackRevision)
        .join(
            FallbackRevision,
            and_(
                FallbackRevision.record_id == FallbackRecord.id,
                FallbackRevision.revision == FallbackRecord.approved_revision,
            ),
        )
        .where(
            FallbackRecord.station_id == station_id,
            FallbackRevision.event_at <= end_at,
            FallbackRevision.status == "approved",
        )
        .order_by(FallbackRevision.event_at, FallbackRecord.id)
    )
    if exclude_record_id is not None:
        query = query.where(FallbackRecord.id != exclude_record_id)
    return [
        (head, row)
        for head, row in db.execute(
            query.with_for_update().execution_options(populate_existing=True),
        )
    ]


def active_fallback_at(
    db: Session,
    station_id: int,
    at: datetime,
    *,
    exclude_record_id: int | None = None,
) -> tuple[FallbackRecord, FallbackRevision] | None:
    events = confirmed_mode_events(db, station_id, at, exclude_record_id=exclude_record_id)
    return events[-1] if events and events[-1][0].kind == "activation" else None


def mode_basis_required(
    db: Session,
    station_id: int,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    events = confirmed_mode_events(db, station_id, end_at)
    before = [item for item in events if item[1].event_at <= start_at]
    return bool(
        (before and before[-1][0].kind == "activation")
        or any(start_at < row.event_at <= end_at for _, row in events)
    )


@dataclass(frozen=True)
class _ConfirmedStockBasis:
    head: FallbackRecord
    activation: FallbackRevision
    original: dict[str, Any]
    endpoint: dict[str, Any]
    ordinary_delta: int
    cumulative: int


def _confirmed_stock_basis(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    end_at: datetime,
    selection: FallbackSelection,
    *,
    exclude_record_id: int | None = None,
) -> _ConfirmedStockBasis:
    active = active_fallback_at(db, station_id, end_at, exclude_record_id=exclude_record_id)
    if active is None or active[0].id != selection.activation_id:
        raise HTTPException(409, detail={"code": "fallback_source_conflict"})
    head, activation = active
    if (
        head.revision != selection.activation_revision
        or head.approved_revision != selection.activation_revision
        or activation.revision != selection.activation_revision
        or activation.schedule_revision != schedule.revision
    ):
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    original = stock_snapshot_basis(
        db,
        station_id,
        activation.stock_snapshot_id,
        activation.stock_snapshot_revision,
        activation.event_at,
    )
    if original != activation.data["stock_snapshot"]:
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    endpoint = stock_snapshot_basis(
        db,
        station_id,
        selection.stock_snapshot_id,
        selection.stock_snapshot_revision,
        end_at,
    )
    ordinary_delta = endpoint["ordinary_issued_quantity"] - original["ordinary_issued_quantity"]
    if ordinary_delta < 0:
        raise HTTPException(409, detail={"code": "fallback_stock_regression"})
    cumulative = activation.data["cumulative_quantity"] + ordinary_delta
    if cumulative > MAX_STOCK_QUANTITY:
        raise HTTPException(422, detail={"code": "turnout_validation"})
    return _ConfirmedStockBasis(head, activation, original, endpoint, ordinary_delta, cumulative)


def _mode_source(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    head: FallbackRecord,
    row: FallbackRevision,
) -> dict[str, Any]:
    if (
        head.revision != row.revision
        or head.approved_revision != row.revision
        or row.schedule_revision != schedule.revision
    ):
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    source = stock_snapshot_basis(
        db,
        station_id,
        row.stock_snapshot_id,
        row.stock_snapshot_revision,
        row.event_at,
    )
    if source != row.data["stock_snapshot"]:
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    result: dict[str, Any] = {
        "id": head.id,
        "revision": row.revision,
        "kind": head.kind,
        "event_at": as_utc(row.event_at),
        "cumulative_quantity": row.data["cumulative_quantity"],
        "source_context": row.data["source_context"],
        "reason": row.reason,
        "approved_at": as_utc(row.approved_at),
        "approved_by": row.approved_by,
        "stock_snapshot_id": row.stock_snapshot_id,
        "stock_snapshot_revision": row.stock_snapshot_revision,
        "stock_snapshot": source,
    }
    if head.kind == "recovery":
        assert head.activation_id is not None
        comparison = recovery_reconciliation(
            db,
            station_id,
            schedule,
            FallbackSelection(
                head.activation_id,
                row.data["activation_revision"],
                row.stock_snapshot_id,
                row.stock_snapshot_revision,
            ),
            row.event_at,
            row.data["cumulative_quantity"],
            exclude_record_id=head.id,
        )
        if comparison != row.data["reconciliation"]:
            raise HTTPException(409, detail={"code": "fallback_review_required"})
        result.update(
            activation_id=head.activation_id,
            activation_revision=row.data["activation_revision"],
            reconciliation=comparison,
        )
    return result


def _period_mode_coverage(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    start_at: datetime,
    end_at: datetime,
    baseline: int,
    cumulative: int,
    *,
    exclude_record_id: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = confirmed_mode_events(db, station_id, end_at, exclude_record_id=exclude_record_id)
    before = [item for item in events if item[1].event_at <= start_at]
    active = before[-1] if before and before[-1][0].kind == "activation" else None
    sources = [_mode_source(db, station_id, schedule, *active)] if active else []
    coverage: list[dict[str, Any]] = []
    cursor, quantity = start_at, baseline

    def segment(mode: str, end: datetime, total: int) -> None:
        nonlocal cursor, quantity
        if total < quantity or (end == cursor and total != quantity):
            raise HTTPException(422, detail={"code": "turnout_validation"})
        if end > cursor:
            coverage.append(
                {
                    "mode": mode,
                    "start_at": as_utc(cursor),
                    "end_at": as_utc(end),
                    "cumulative_start_quantity": quantity,
                    "cumulative_end_quantity": total,
                    "hourly_quantity": total - quantity,
                }
            )
        cursor, quantity = end, total

    for head, row in events:
        if row.event_at <= start_at:
            continue
        frozen = _mode_source(db, station_id, schedule, head, row)
        if head.kind == "activation":
            if active is not None:
                raise HTTPException(409, detail={"code": "fallback_source_conflict"})
            segment("normal", row.event_at, row.data["cumulative_quantity"])
            active = head, row
        else:
            if active is None or head.activation_id != active[0].id:
                raise HTTPException(409, detail={"code": "fallback_source_conflict"})
            segment("reconciled", row.event_at, row.data["cumulative_quantity"])
            active = None
        sources.append(frozen)
    segment("fallback" if active else "normal", end_at, cumulative)
    return coverage, sources


def fallback_period_basis(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    period_index: int,
    selection: FallbackSelection,
    predecessor: TurnoutRecord | None,
    *,
    exclude_record_id: int | None = None,
    coverage_end_at: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    start_at, end_at = period_bounds(schedule, period_index)
    if coverage_end_at is not None:
        if not start_at < coverage_end_at <= end_at:
            raise HTTPException(409, detail={"code": "fallback_source_conflict"})
        end_at = coverage_end_at
    source = _confirmed_stock_basis(
        db,
        station_id,
        schedule,
        end_at,
        selection,
        exclude_record_id=exclude_record_id,
    )
    head, activation = source.head, source.activation
    original, endpoint = source.original, source.endpoint
    ordinary_delta, cumulative = source.ordinary_delta, source.cumulative
    baseline = predecessor.derived_cumulative_end if predecessor else 0
    assert baseline is not None
    confirmed = activation.data["cumulative_quantity"]
    if cumulative < baseline:
        raise HTTPException(422, detail={"code": "turnout_validation"})
    coverage, sources = _period_mode_coverage(
        db,
        station_id,
        schedule,
        start_at,
        end_at,
        baseline,
        cumulative,
        exclude_record_id=exclude_record_id,
    )
    basis = {
        "activation_id": head.id,
        "activation_revision": activation.revision,
        "stock_snapshot_id": selection.stock_snapshot_id,
        "stock_snapshot_revision": selection.stock_snapshot_revision,
        "predecessor_record_id": predecessor.id if predecessor else None,
        "predecessor_revision": predecessor.revision if predecessor else None,
        "ordinary_issued_since_activation_quantity": ordinary_delta,
        "stock_derived_cumulative_quantity": cumulative,
        "activation": {
            "id": head.id,
            "revision": activation.revision,
            "event_at": as_utc(activation.event_at),
            "cumulative_quantity": confirmed,
            "source_context": activation.data["source_context"],
            "approved_at": as_utc(activation.approved_at),
            "approved_by": activation.approved_by,
        },
        "activation_stock_snapshot": original,
        "stock_snapshot": endpoint,
        "coverage": coverage,
        "source_events": sources,
    }
    return (
        "mixed" if any(row["mode"] != "fallback" for row in coverage) else "fallback_stock"
    ), basis


def recovery_reconciliation(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    selection: FallbackSelection,
    event_at: datetime,
    recovered: int,
    *,
    exclude_record_id: int | None = None,
) -> dict[str, Any]:
    source = _confirmed_stock_basis(
        db,
        station_id,
        schedule,
        event_at,
        selection,
        exclude_record_id=exclude_record_id,
    )
    return {
        "stock_derived_cumulative_quantity": source.cumulative,
        "recovered_cumulative_quantity": recovered,
        "difference": recovered - source.cumulative,
    }


def recovery_period_basis(
    db: Session,
    station_id: int,
    schedule: ElectionSchedule,
    period_index: int,
    recovery_id: int,
    recovery_revision: int,
    predecessor: TurnoutRecord | None,
    supplied_hourly: int | None = None,
    supplied_cumulative: int | None = None,
) -> tuple[str, dict[str, Any]]:
    start_at, end_at = period_bounds(schedule, period_index)
    events = confirmed_mode_events(db, station_id, end_at)
    if not events or events[-1][0].id != recovery_id or events[-1][0].kind != "recovery":
        raise HTTPException(409, detail={"code": "fallback_source_conflict"})
    head, recovery = events[-1]
    if (
        head.revision != recovery_revision
        or head.approved_revision != recovery_revision
        or recovery.revision != recovery_revision
        or recovery.schedule_revision != schedule.revision
        or not start_at < recovery.event_at <= end_at
    ):
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    assert head.activation_id is not None
    reconciliation = recovery_reconciliation(
        db,
        station_id,
        schedule,
        FallbackSelection(
            head.activation_id,
            recovery.data["activation_revision"],
            recovery.stock_snapshot_id,
            recovery.stock_snapshot_revision,
        ),
        recovery.event_at,
        recovery.data["cumulative_quantity"],
        exclude_record_id=head.id,
    )
    if reconciliation != recovery.data["reconciliation"]:
        raise HTTPException(409, detail={"code": "fallback_review_required"})
    _, basis = fallback_period_basis(
        db,
        station_id,
        schedule,
        period_index,
        FallbackSelection(
            head.activation_id,
            recovery.data["activation_revision"],
            recovery.stock_snapshot_id,
            recovery.stock_snapshot_revision,
        ),
        predecessor,
        exclude_record_id=head.id,
        coverage_end_at=recovery.event_at,
    )
    recovered = reconciliation["recovered_cumulative_quantity"]
    baseline = predecessor.derived_cumulative_end if predecessor else 0
    assert baseline is not None
    selected = recovered
    if recovery.event_at < end_at:
        if supplied_cumulative is not None:
            selected = supplied_cumulative
        elif supplied_hourly is not None:
            selected = baseline + supplied_hourly
        else:
            raise HTTPException(422, detail={"code": "turnout_validation"})
    if (
        selected < recovered
        or selected > MAX_STOCK_QUANTITY
        or (supplied_cumulative is not None and supplied_cumulative != selected)
        or (supplied_hourly is not None and supplied_hourly != selected - baseline)
    ):
        raise HTTPException(422, detail={"code": "turnout_validation"})
    coverage, sources = _period_mode_coverage(
        db,
        station_id,
        schedule,
        start_at,
        end_at,
        baseline,
        selected,
    )
    basis["coverage"], basis["source_events"] = coverage, sources
    basis.update(
        {
            "selected_cumulative_quantity": selected,
            "recovery_id": head.id,
            "recovery_revision": recovery.revision,
            "recovered_cumulative_quantity": recovered,
            "reconciliation_difference": reconciliation["difference"],
            "recovery": {
                "event_at": as_utc(recovery.event_at),
                "source_context": recovery.data["source_context"],
                "reason": recovery.reason,
                "approved_at": as_utc(recovery.approved_at),
                "approved_by": recovery.approved_by,
            },
        }
    )
    return "external_reconciled", basis


def turnout_basis_current(
    db: Session,
    row: TurnoutRecord,
    schedule: ElectionSchedule,
    predecessor: TurnoutRecord | None,
) -> bool:
    if row.source_basis is None:
        return row.provenance == "external_manual" and not mode_basis_required(
            db,
            row.station_id,
            row.start_at,
            row.end_at,
        )
    try:
        if "recovery_id" in row.source_basis:
            provenance, basis = recovery_period_basis(
                db,
                row.station_id,
                schedule,
                row.period_index,
                row.source_basis["recovery_id"],
                row.source_basis["recovery_revision"],
                predecessor,
                row.supplied_hourly,
                row.supplied_cumulative,
            )
            return provenance == row.provenance and basis == row.source_basis
        selection = FallbackSelection(
            row.source_basis["activation_id"],
            row.source_basis["activation_revision"],
            row.source_basis["stock_snapshot_id"],
            row.source_basis["stock_snapshot_revision"],
        )
        provenance, basis = fallback_period_basis(
            db,
            row.station_id,
            schedule,
            row.period_index,
            selection,
            predecessor,
        )
        return provenance == row.provenance and basis == row.source_basis
    except HTTPException, KeyError, TypeError, ValueError:
        return False
