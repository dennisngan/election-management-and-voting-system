"""Frozen, event-time remaining-stock observations and ordinary issuance."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.models import Account, AuditEvent
from election.server.station_models import IssuanceCounter
from election.server.stock import stock_scope, stock_write
from election.server.stock_inventory import (
    allocation_fragments,
    covering_fragments,
    current_allocations,
    current_returns,
    preserve_later_remaining,
    receipt_basis,
    received_ranges,
    reject_known_issued,
    subtract_intervals,
)
from election.server.stock_models import StockReceipt, StockReceiptRevision
from election.server.stock_serials import MAX_STOCK_QUANTITY, serial_number
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_time import StockEventTime


class RemainingRangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series: str = Field(min_length=1, max_length=64)
    serial_from: str = Field(min_length=1, max_length=18)
    serial_to: str = Field(min_length=1, max_length=18)

    @field_validator("series")
    @classmethod
    def meaningful_series(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A ballot series is required")
        return value

    @model_validator(mode="after")
    def ordered_serials(self) -> RemainingRangeInput:
        if serial_number(self.serial_to) < serial_number(self.serial_from):
            raise ValueError("Serial end must not precede its start")
        return self

    @property
    def quantity(self) -> int:
        return serial_number(self.serial_to) - serial_number(self.serial_from) + 1


class CounterRemainingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter_id: int = Field(strict=True, gt=0)
    ranges: list[RemainingRangeInput]

    @model_validator(mode="after")
    def nonoverlapping(self) -> CounterRemainingInput:
        previous: dict[str, int] = {}
        for row in sorted(
            self.ranges, key=lambda item: (item.series, serial_number(item.serial_from))
        ):
            if serial_number(row.serial_from) <= previous.get(row.series, -1):
                raise ValueError("Remaining ranges must not overlap")
            previous[row.series] = serial_number(row.serial_to)
        if sum(row.quantity for row in self.ranges) > MAX_STOCK_QUANTITY:
            raise ValueError("Remaining quantity exceeds the supported bound")
        return self


class StockSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    event_at: StockEventTime
    counters: list[CounterRemainingInput]

    @model_validator(mode="after")
    def unique_counters(self) -> StockSnapshotInput:
        if len({row.counter_id for row in self.counters}) != len(self.counters):
            raise ValueError("Report each counter at most once")
        return self


class StockSnapshotCorrection(StockSnapshotInput):
    revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value


def snapshot_view(row: StockSnapshotRevision, station_id: int) -> dict[str, Any]:
    return {
        **row.data,
        "id": row.snapshot_id,
        "station_id": station_id,
        "status": "recorded",
        "revision": row.revision,
        "event_at": row.event_at.replace(tzinfo=UTC),
        "entered_at": row.entered_at.replace(tzinfo=UTC),
        "actor_id": row.actor_id,
        "reason": row.reason,
    }


def snapshot_accounting(
    db: Session,
    station_id: int,
    data: StockSnapshotInput,
    *,
    exclude_snapshot_id: int | None = None,
) -> dict[str, Any]:
    event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
    counters = list(
        db.scalars(
            select(IssuanceCounter)
            .where(IssuanceCounter.station_id == station_id)
            .order_by(IssuanceCounter.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    reports = {row.counter_id: row for row in data.counters}
    if reports.keys() - {row.id for row in counters}:
        raise HTTPException(404, detail={"code": "counter_not_found"})
    allocations = [
        row for row in current_allocations(db, station_id, lock=True) if row.event_at <= event_at
    ]
    returns = [
        row for row in current_returns(db, station_id, lock=True) if row.event_at <= event_at
    ]
    fragments = allocation_fragments(allocations, returns)
    current_lines = received_ranges(db, station_id, lock=True)
    receipt_versions = list(
        db.scalars(
            select(StockReceiptRevision)
            .where(
                StockReceiptRevision.receipt_id.in_({line.receipt_id for line in current_lines}),
                StockReceiptRevision.event_at <= event_at,
            )
            .with_for_update()
        )
    )
    eligible_receipts = {(row.receipt_id, row.revision) for row in receipt_versions}
    lines = [
        row for row in current_lines if (row.receipt_id, row.receipt_revision) in eligible_receipts
    ]
    basis: set[tuple[int, int]] = set()
    for row in allocations:
        for source in receipt_basis(lines, row.series, row.serial_from_value, row.serial_to_value):
            basis.add((source["receipt_id"], source["revision"]))
    result: list[dict[str, Any]] = []
    for counter in counters:
        owned = [row for row in fragments if row.counter_id == counter.id]
        allocated = sum(row.quantity for row in allocations if row.counter_id == counter.id)
        returned = sum(row.quantity for row in returns if row.counter_id == counter.id)
        net_allocated = allocated - returned
        report = reports.get(counter.id)
        for remaining in report.ranges if report else []:
            first, last = serial_number(remaining.serial_from), serial_number(remaining.serial_to)
            reject_known_issued(
                db,
                station_id,
                remaining.series,
                first,
                last,
                event_at,
                exclude_snapshot_id=exclude_snapshot_id,
            )
            if covering_fragments(fragments, counter.id, remaining.series, first, last) is None:
                raise HTTPException(409, detail={"code": "remaining_outside_owned_stock"})
        remaining_quantity = sum(row.quantity for row in report.ranges) if report else None
        if remaining_quantity is not None and remaining_quantity > net_allocated:
            raise HTTPException(409, detail={"code": "negative_issuance"})
        issued_ranges = []
        if report is not None:
            for owned_part in owned:
                remaining_parts = [
                    (serial_number(row.serial_from), serial_number(row.serial_to))
                    for row in report.ranges
                    if row.series == owned_part.series
                ]
                for first, last in subtract_intervals(
                    owned_part.serial_from_value, owned_part.serial_to_value, remaining_parts
                ):
                    issued_ranges.append(
                        {
                            "series": owned_part.series,
                            "serial_from": str(first).zfill(len(owned_part.allocation.serial_from)),
                            "serial_to": str(last).zfill(len(owned_part.allocation.serial_to)),
                            "quantity": last - first + 1,
                        }
                    )
        result.append(
            {
                "counter": {"id": counter.id, "code": counter.code, "name": counter.name},
                "reported": report is not None,
                "ranges": [{**row.model_dump(), "quantity": row.quantity} for row in report.ranges]
                if report
                else None,
                "ordinary_allocated_quantity": allocated,
                "ordinary_returned_quantity": returned,
                "ordinary_net_allocated_quantity": net_allocated,
                "issued_ranges": issued_ranges,
                "ordinary_remaining_quantity": remaining_quantity,
                "ordinary_issued_quantity": net_allocated - remaining_quantity
                if remaining_quantity is not None
                else None,
            }
        )
    complete = bool(counters) and all(row["reported"] for row in result)
    allocated_total = sum(row.quantity for row in allocations)
    returned_total = sum(row.quantity for row in returns)
    remaining_total = (
        sum(row["ordinary_remaining_quantity"] for row in result) if complete else None
    )
    return {
        "complete": complete,
        "provenance": "stock_derived",
        "counters": result,
        "ordinary_allocated_quantity": allocated_total,
        "ordinary_returned_quantity": returned_total,
        "ordinary_net_allocated_quantity": allocated_total - returned_total,
        "ordinary_remaining_quantity": remaining_total,
        "ordinary_issued_quantity": allocated_total - returned_total - remaining_total
        if remaining_total is not None
        else None,
        "receipt_basis": [{"receipt_id": rid, "revision": rev} for rid, rev in sorted(basis)],
        "allocation_basis": [
            {"allocation_id": row.allocation_id, "revision": row.revision} for row in allocations
        ],
        "return_basis": [{"return_id": row.return_id, "revision": row.revision} for row in returns],
    }


def snapshot_basis_current(
    db: Session,
    station_id: int,
    row: StockSnapshotRevision,
    *,
    lock: bool = False,
) -> bool:
    allocations = {
        (item.allocation_id, item.revision)
        for item in current_allocations(db, station_id, lock=lock)
        if item.event_at <= row.event_at
    }
    expected_allocations = {
        (item["allocation_id"], item["revision"]) for item in row.data["allocation_basis"]
    }
    returns = {
        (item.return_id, item.revision)
        for item in current_returns(db, station_id, lock=lock)
        if item.event_at <= row.event_at
    }
    expected_returns = {(item["return_id"], item["revision"]) for item in row.data["return_basis"]}
    expected_receipts = {
        (item["receipt_id"], item["revision"]) for item in row.data["receipt_basis"]
    }
    receipt_query = select(StockReceipt).where(
        StockReceipt.station_id == station_id,
        StockReceipt.id.in_({item[0] for item in expected_receipts}),
    )
    counter_query = select(IssuanceCounter.id).where(IssuanceCounter.station_id == station_id)
    if lock:
        # Authentication can predate a competing writer's commit under MySQL RR.
        # A write validator must inspect current source heads under its scope lock.
        receipt_query = receipt_query.with_for_update().execution_options(populate_existing=True)
        counter_query = counter_query.with_for_update()
    receipts = {(item.id, item.revision) for item in db.scalars(receipt_query)}
    counters = set(db.scalars(counter_query))
    expected_counters = {item["counter"]["id"] for item in row.data["counters"]}
    return (
        allocations == expected_allocations
        and returns == expected_returns
        and receipts == expected_receipts
        and counters == expected_counters
    )


def stock_snapshot_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/stock-snapshots",
        tags=["Remaining stock snapshots"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def save_snapshot(
        station_id: int,
        data: StockSnapshotInput,
        response: Response,
        db: Session,
        actor: Account,
        snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            scope = stock_scope(db, actor, station_id, write=True)
            head = None
            if snapshot_id is not None:
                head = db.scalar(
                    select(StockSnapshot)
                    .where(StockSnapshot.id == snapshot_id, StockSnapshot.station_id == station_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if head is None:
                    raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
            values = data.model_dump(mode="json", exclude={"request_id"})
            values["event_at"] = data.event_at.astimezone(UTC).isoformat()
            digest = hashlib.sha256(
                json.dumps(
                    {"station_id": station_id, "snapshot_id": snapshot_id, **values},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            saved = db.scalar(
                select(StockSnapshotRevision)
                .where(StockSnapshotRevision.request_id == str(data.request_id))
                .with_for_update()
            )
            if saved is not None:
                if saved.payload_digest != digest:
                    raise HTTPException(409, detail={"code": "request_conflict"})
                response.status_code = 200
                return snapshot_view(saved, station_id)
            if isinstance(data, StockSnapshotCorrection):
                assert head is not None
                if head.revision != data.revision:
                    raise HTTPException(409, detail={"code": "revision_conflict"})
                head.revision += 1
            now = timestamp()
            if data.event_at.astimezone(UTC).replace(tzinfo=None) > now:
                raise HTTPException(422, detail={"code": "event_time_in_future"})
            accounting = snapshot_accounting(db, station_id, data, exclude_snapshot_id=snapshot_id)
            preserve_later_remaining(
                db,
                station_id,
                data.event_at.astimezone(UTC).replace(tzinfo=None),
                accounting["counters"],
                exclude_snapshot_id=snapshot_id,
            )
            if head is None:
                head = StockSnapshot(station_id=station_id, revision=1, created_at=now)
                db.add(head)
                db.flush()
            row = StockSnapshotRevision(
                snapshot_id=head.id,
                revision=head.revision,
                request_id=str(data.request_id),
                payload_digest=digest,
                event_at=data.event_at.astimezone(UTC).replace(tzinfo=None),
                entered_at=now,
                actor_id=actor.id,
                reason=data.reason if isinstance(data, StockSnapshotCorrection) else "",
                data={"scope": scope, **accounting},
            )
            db.add(row)
            db.add(
                AuditEvent(
                    actor_id=actor.id,
                    action="stock_snapshot_corrected"
                    if head.revision > 1
                    else "stock_snapshot_recorded",
                    occurred_at=now,
                    details={
                        "station_id": station_id,
                        "snapshot_id": head.id,
                        **values,
                        "revision": head.revision,
                    },
                )
            )
            db.commit()
            return snapshot_view(row, station_id)

        return stock_write(db, write)

    @router.get("")
    def list_snapshots(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        rows = list(
            db.scalars(
                select(StockSnapshotRevision)
                .join(
                    StockSnapshot,
                    and_(
                        StockSnapshot.id == StockSnapshotRevision.snapshot_id,
                        StockSnapshot.revision == StockSnapshotRevision.revision,
                    ),
                )
                .where(StockSnapshot.station_id == station_id)
                .order_by(StockSnapshotRevision.event_at, StockSnapshot.id)
            )
        )
        items = [snapshot_view(row, station_id) for row in rows]
        latest = items[-1] if items else None
        basis_current = snapshot_basis_current(db, station_id, rows[-1]) if rows else None
        counters = db.scalars(
            select(IssuanceCounter)
            .where(IssuanceCounter.station_id == station_id)
            .order_by(IssuanceCounter.id)
        )
        return {
            "scope": scope,
            "items": items,
            "latest": latest,
            "latest_basis_current": basis_current,
            "current_ordinary_issued_quantity": latest["ordinary_issued_quantity"]
            if latest is not None and basis_current
            else None,
            "snapshot_state": "missing"
            if latest is None
            else "complete"
            if latest["complete"]
            else "incomplete",
            "counters": [{"id": row.id, "code": row.code, "name": row.name} for row in counters],
        }

    @router.post("", status_code=201)
    def create_snapshot(
        station_id: int, data: StockSnapshotInput, response: Response, db: Database, actor: Ready
    ) -> dict[str, Any]:
        return save_snapshot(station_id, data, response, db, actor)

    @router.put("/{snapshot_id}")
    def correct_snapshot(
        station_id: int,
        snapshot_id: int,
        data: StockSnapshotCorrection,
        response: Response,
        db: Database,
        actor: Ready,
    ) -> dict[str, Any]:
        return save_snapshot(station_id, data, response, db, actor, snapshot_id)

    def read_head(db: Session, station_id: int, snapshot_id: int) -> StockSnapshot:
        head = db.scalar(
            select(StockSnapshot).where(
                StockSnapshot.id == snapshot_id, StockSnapshot.station_id == station_id
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
        return head

    @router.get("/{snapshot_id}/history")
    def history(station_id: int, snapshot_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, snapshot_id)
        rows = db.scalars(
            select(StockSnapshotRevision)
            .where(StockSnapshotRevision.snapshot_id == head.id)
            .order_by(StockSnapshotRevision.revision)
        )
        return {"items": [snapshot_view(row, station_id) for row in rows]}

    @router.get("/{snapshot_id}")
    def read_snapshot(
        station_id: int,
        snapshot_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, snapshot_id)
        row = db.scalar(
            select(StockSnapshotRevision).where(
                StockSnapshotRevision.snapshot_id == head.id,
                StockSnapshotRevision.revision
                == (revision if revision is not None else head.revision),
            )
        )
        if row is None:
            raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
        return snapshot_view(row, station_id)

    return router
