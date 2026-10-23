"""Current received intervals and counter ownership, without enumerating papers."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.stock_models import StockReceipt, StockReceiptRange, StockReceiptRevision
from election.server.stock_return_models import CounterStockReturn, CounterStockReturnRevision
from election.server.stock_serials import StockRangeInput, serial_number
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision


@dataclass(frozen=True)
class ReceivedRange:
    receipt_id: int
    receipt_revision: int
    line_number: int
    series: str
    pool: str
    serial_from: str
    serial_to: str
    first: int
    last: int

    @property
    def quantity(self) -> int:
        return self.last - self.first + 1


def received_ranges(db: Session, station_id: int, *, lock: bool = False) -> list[ReceivedRange]:
    query = (
        select(StockReceiptRange, StockReceiptRevision)
        .join(StockReceiptRevision, StockReceiptRevision.id == StockReceiptRange.revision_id)
        .join(
            StockReceipt,
            and_(
                StockReceipt.id == StockReceiptRevision.receipt_id,
                StockReceipt.revision == StockReceiptRevision.revision,
            ),
        )
        .where(StockReceipt.station_id == station_id)
        .order_by(StockReceipt.id, StockReceiptRange.line_number)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return [
        ReceivedRange(
            receipt_id=revision.receipt_id,
            receipt_revision=revision.revision,
            line_number=line.line_number,
            series=revision.series,
            pool=line.pool,
            serial_from=line.serial_from,
            serial_to=line.serial_to,
            first=line.serial_from_value,
            last=line.serial_to_value,
        )
        for line, revision in db.execute(query)
    ]


def current_allocations(
    db: Session, station_id: int, *, lock: bool = False
) -> list[StockAllocationRevision]:
    query = (
        select(StockAllocationRevision)
        .join(
            StockAllocation,
            and_(
                StockAllocation.id == StockAllocationRevision.allocation_id,
                StockAllocation.revision == StockAllocationRevision.revision,
            ),
        )
        .where(StockAllocation.station_id == station_id)
        .order_by(StockAllocation.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(query))


def receipt_basis(
    lines: Sequence[ReceivedRange], series: str, first: int, last: int
) -> list[dict[str, int]]:
    candidates = sorted(
        (line for line in lines if line.series == series and line.pool == "ordinary"),
        key=lambda line: (line.first, line.last, line.receipt_id, line.line_number),
    )
    basis: list[dict[str, int]] = []
    cursor = first
    index = 0
    while cursor <= last:
        covering: ReceivedRange | None = None
        while index < len(candidates) and candidates[index].first <= cursor:
            line = candidates[index]
            if line.last >= cursor and (covering is None or line.last > covering.last):
                covering = line
            index += 1
        if covering is None:
            raise HTTPException(409, detail={"code": "allocation_outside_stock"})
        basis.append(
            {
                "receipt_id": covering.receipt_id,
                "revision": covering.receipt_revision,
                "range_line": covering.line_number,
            }
        )
        cursor = covering.last + 1
    if not basis:
        raise HTTPException(409, detail={"code": "allocation_outside_stock"})
    return basis


def preserve_allocations(
    db: Session,
    station_id: int,
    receipt_id: int,
    series: str,
    ranges: Sequence[StockRangeInput],
) -> None:
    current = received_ranges(db, station_id, lock=True)
    receipt_lines = [line for line in current if line.receipt_id == receipt_id]
    # The caller has already locked the existing receipt head. Every receipt
    # revision has at least one range, so absence here is an invariant failure.
    assert receipt_lines
    next_revision = receipt_lines[0].receipt_revision + 1
    proposed = [line for line in current if line.receipt_id != receipt_id]
    proposed.extend(
        ReceivedRange(
            receipt_id=receipt_id,
            receipt_revision=next_revision,
            line_number=index,
            series=series,
            pool=line.pool,
            serial_from=line.serial_from,
            serial_to=line.serial_to,
            first=serial_number(line.serial_from),
            last=serial_number(line.serial_to),
        )
        for index, line in enumerate(ranges)
    )
    for allocation in current_allocations(db, station_id, lock=True):
        try:
            receipt_basis(
                proposed,
                allocation.series,
                allocation.serial_from_value,
                allocation.serial_to_value,
            )
        except HTTPException as error:
            detail: object = error.detail
            if (
                error.status_code == 409
                and isinstance(detail, dict)
                and detail == {"code": "allocation_outside_stock"}
            ):
                raise HTTPException(409, detail={"code": "stock_allocations_conflict"}) from None
            raise


def availability(
    lines: list[ReceivedRange], allocations: Sequence[StockAllocationRevision | AllocationFragment]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for series in sorted({line.series for line in lines}):
        received = [line for line in lines if line.series == series]
        owned = sorted(
            (
                (allocation.serial_from_value, allocation.serial_to_value)
                for allocation in allocations
                if allocation.series == series
            )
        )
        ranges: list[dict[str, Any]] = []
        ordinary = sorted(
            (line for line in received if line.pool == "ordinary"),
            key=lambda line: (line.first, line.last, line.receipt_id, line.line_number),
        )
        allocation_index = 0
        for line in ordinary:
            cursor = line.first
            while allocation_index < len(owned) and owned[allocation_index][1] < cursor:
                allocation_index += 1
            index = allocation_index
            while index < len(owned) and owned[index][0] <= line.last:
                allocated_first, allocated_last = owned[index]
                if allocated_first > cursor:
                    ranges.append(_available_range(line, cursor, allocated_first - 1))
                cursor = max(cursor, allocated_last + 1)
                if cursor > line.last:
                    break
                index += 1
            if cursor <= line.last:
                ranges.append(_available_range(line, cursor, line.last))
        result.append(
            {
                "series": series,
                "ordinary_received_quantity": sum(line.quantity for line in ordinary),
                "allocated_quantity": sum(last - first + 1 for first, last in owned),
                "available_quantity": sum(row["quantity"] for row in ranges),
                "replacement_quantity": sum(
                    line.quantity for line in received if line.pool == "replacement"
                ),
                "tendered_quantity": sum(
                    line.quantity for line in received if line.pool == "tendered"
                ),
                "ranges": ranges,
            }
        )
    return result


def _available_range(line: ReceivedRange, first: int, last: int) -> dict[str, Any]:
    return {
        "serial_from": str(first).zfill(len(line.serial_from)),
        "serial_to": str(last).zfill(len(line.serial_to)),
        "quantity": last - first + 1,
        "receipt_id": line.receipt_id,
        "receipt_revision": line.receipt_revision,
    }


@dataclass(frozen=True)
class AllocationFragment:
    """The unreturned part of one allocation lineage, never a union of lineages."""

    allocation: StockAllocationRevision
    serial_from_value: int
    serial_to_value: int

    @property
    def series(self) -> str:
        return self.allocation.series

    @property
    def counter_id(self) -> int:
        return self.allocation.counter_id

    @property
    def quantity(self) -> int:
        return self.serial_to_value - self.serial_from_value + 1


def subtract_intervals(
    first: int, last: int, removed: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = first
    for start, end in sorted(removed):
        if end < cursor:
            continue
        if start > last:
            break
        if start > cursor:
            result.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
        if cursor > last:
            break
    if cursor <= last:
        result.append((cursor, last))
    return result


def current_returns(
    db: Session, station_id: int, *, lock: bool = False
) -> list[CounterStockReturnRevision]:
    query = (
        select(CounterStockReturnRevision)
        .join(
            CounterStockReturn,
            and_(
                CounterStockReturn.id == CounterStockReturnRevision.return_id,
                CounterStockReturn.revision == CounterStockReturnRevision.revision,
            ),
        )
        .where(CounterStockReturn.station_id == station_id)
        .order_by(CounterStockReturn.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(query))


def allocation_fragments(
    allocations: Sequence[StockAllocationRevision], returns: Sequence[CounterStockReturnRevision]
) -> list[AllocationFragment]:
    removed: dict[int, list[tuple[int, int]]] = {}
    for returned in returns:
        for part in returned.allocation_basis:
            removed.setdefault(int(part["allocation_id"]), []).append(
                (serial_number(str(part["serial_from"])), serial_number(str(part["serial_to"])))
            )
    return [
        AllocationFragment(row, first, last)
        for row in allocations
        for first, last in subtract_intervals(
            row.serial_from_value, row.serial_to_value, removed.get(row.allocation_id, [])
        )
    ]


def preserve_observed_stock(
    db: Session,
    station_id: int,
    allocation_id: int,
    counter_id: int,
    series: str,
    first: int,
    last: int,
    event_at: datetime,
) -> None:
    """A correction cannot release known-issued stock or orphan a physical return."""
    allocations = current_allocations(db, station_id, lock=True)
    returns = current_returns(db, station_id, lock=True)
    for returned in returns:
        for part in returned.allocation_basis:
            if int(part["allocation_id"]) == allocation_id and (
                returned.counter_id != counter_id
                or returned.series != series
                or first > serial_number(str(part["serial_from"]))
                or last < serial_number(str(part["serial_to"]))
                or event_at > returned.event_at
            ):
                raise HTTPException(409, detail={"code": "stock_returns_conflict"})
    proposed = [
        (row.counter_id, row.series, row.serial_from_value, row.serial_to_value, row.event_at)
        for row in allocations
        if row.allocation_id != allocation_id
    ]
    proposed.append((counter_id, series, first, last, event_at))
    observations = db.scalars(
        select(StockSnapshotRevision)
        .join(
            StockSnapshot,
            and_(
                StockSnapshot.id == StockSnapshotRevision.snapshot_id,
                StockSnapshot.revision == StockSnapshotRevision.revision,
            ),
        )
        .where(StockSnapshot.station_id == station_id)
        .with_for_update()
    )
    for observation in observations:
        for counter in observation.data["counters"]:
            for issued in counter.get("issued_ranges", []):
                cursor = serial_number(issued["serial_from"])
                issued_last = serial_number(issued["serial_to"])
                for owner_id, owner_series, start, end, allocated_at in sorted(
                    proposed, key=lambda p: p[2]
                ):
                    if (
                        owner_id != counter["counter"]["id"]
                        or owner_series != issued["series"]
                        or allocated_at > observation.event_at
                        or end < cursor
                    ):
                        continue
                    if start > cursor:
                        break
                    cursor = max(cursor, end + 1)
                    if cursor > issued_last:
                        break
                if cursor <= issued_last:
                    raise HTTPException(409, detail={"code": "stock_observations_conflict"})


def reject_known_issued(
    db: Session,
    station_id: int,
    series: str,
    first: int,
    last: int,
    event_at: datetime,
    *,
    exclude_snapshot_id: int | None = None,
) -> None:
    rows = db.scalars(
        select(StockSnapshotRevision)
        .join(
            StockSnapshot,
            and_(
                StockSnapshot.id == StockSnapshotRevision.snapshot_id,
                StockSnapshot.revision == StockSnapshotRevision.revision,
            ),
        )
        .where(StockSnapshot.station_id == station_id, StockSnapshotRevision.event_at <= event_at)
        .with_for_update()
    )
    for row in rows:
        if row.snapshot_id == exclude_snapshot_id:
            continue
        for counter in row.data["counters"]:
            for issued in counter.get("issued_ranges", []):
                if (
                    issued["series"] == series
                    and serial_number(issued["serial_from"]) <= last
                    and serial_number(issued["serial_to"]) >= first
                ):
                    raise HTTPException(409, detail={"code": "stock_already_issued"})


def validate_return_ownership(
    allocations: Sequence[StockAllocationRevision], returns: Sequence[CounterStockReturnRevision]
) -> None:
    """A return correction must preserve both current ownership and later allocation claims."""
    previous_end: dict[str, int] = {}
    for fragment in sorted(
        allocation_fragments(allocations, returns),
        key=lambda row: (row.series, row.serial_from_value),
    ):
        if fragment.serial_from_value <= previous_end.get(fragment.series, -1):
            raise HTTPException(409, detail={"code": "stock_returns_conflict"})
        previous_end[fragment.series] = fragment.serial_to_value
    for allocation in allocations:
        # Equal-time claims retain their creation order: a later allocation cannot
        # provide the return that would have released an earlier allocation.
        earlier = [
            row
            for row in allocations
            if (row.event_at, row.allocation_id)
            < (allocation.event_at, allocation.allocation_id)
        ]
        applicable_returns = [row for row in returns if row.event_at <= allocation.event_at]
        for fragment in allocation_fragments(earlier, applicable_returns):
            if (
                fragment.series == allocation.series
                and fragment.serial_from_value <= allocation.serial_to_value
                and fragment.serial_to_value >= allocation.serial_from_value
            ):
                raise HTTPException(409, detail={"code": "stock_returns_conflict"})
