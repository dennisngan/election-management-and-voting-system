"""Current received intervals and counter ownership, without enumerating papers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.stock_models import StockReceipt, StockReceiptRange, StockReceiptRevision
from election.server.stock_serials import StockRangeInput, serial_number


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


def received_ranges(
    db: Session, station_id: int, *, lock: bool = False
) -> list[ReceivedRange]:
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
    lines: list[ReceivedRange], allocations: list[StockAllocationRevision]
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
