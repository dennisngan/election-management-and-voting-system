"""Current special-paper observations preserve their count-based reserve sources."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.special_paper_models import SpecialPaperRevision, SpecialPaperSnapshot
from election.server.stock_models import StockReceipt, StockReceiptRevision
from election.server.stock_serials import StockRangeInput


def current_special_papers(
    db: Session, station_id: int, *, lock: bool = False,
) -> list[SpecialPaperRevision]:
    query = (
        select(SpecialPaperRevision)
        .join(SpecialPaperSnapshot, and_(
            SpecialPaperSnapshot.id == SpecialPaperRevision.snapshot_id,
            SpecialPaperSnapshot.revision == SpecialPaperRevision.revision,
        ))
        .where(SpecialPaperSnapshot.station_id == station_id)
        .order_by(SpecialPaperRevision.event_at, SpecialPaperSnapshot.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(query))


@dataclass(frozen=True)
class _ReserveReceipt:
    series: str
    event_at: datetime
    replacement_quantity: int
    tendered_quantity: int


def preserve_special_reserves(
    db: Session,
    station_id: int,
    receipt_id: int,
    series: str,
    ranges: Sequence[StockRangeInput],
    event_at: datetime,
) -> None:
    """A receipt correction must retain reserves consumed by every current observation."""
    observations = current_special_papers(db, station_id, lock=True)
    if not observations:
        return
    receipts = db.scalars(
        select(StockReceiptRevision)
        .join(StockReceipt, and_(
            StockReceipt.id == StockReceiptRevision.receipt_id,
            StockReceipt.revision == StockReceiptRevision.revision,
        ))
        .where(StockReceipt.station_id == station_id)
        .order_by(StockReceipt.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    proposed = [
        _ReserveReceipt(
            row.series, row.event_at, row.replacement_quantity, row.tendered_quantity,
        )
        for row in receipts if row.receipt_id != receipt_id
    ] + [_ReserveReceipt(
        series,
        event_at,
        sum(row.quantity for row in ranges if row.pool == "replacement"),
        sum(row.quantity for row in ranges if row.pool == "tendered"),
    )]
    for observation in observations:
        available: dict[str, tuple[int, int]] = {}
        for source in proposed:
            if source.event_at > observation.event_at:
                continue
            replacement, tendered = available.get(source.series, (0, 0))
            available[source.series] = (
                replacement + source.replacement_quantity,
                tendered + source.tendered_quantity,
            )
        for consumed in observation.data["series"]:
            replacement, tendered = available.get(consumed["series"], (0, 0))
            if (
                consumed["replacement_issued_quantity"] > replacement
                or consumed["tendered_issued_quantity"] > tendered
            ):
                raise HTTPException(409, detail={"code": "special_paper_stock_conflict"})
