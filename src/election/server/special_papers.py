"""Cumulative special-paper observations retain their stock and ordinary-issuance basis."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, select, tuple_
from sqlalchemy.orm import Session

from election.server.models import Account, AuditEvent
from election.server.special_paper_inventory import current_special_papers
from election.server.special_paper_models import SpecialPaperRevision, SpecialPaperSnapshot
from election.server.stock import stock_scope, stock_write
from election.server.stock_inventory import received_ranges
from election.server.stock_models import StockReceipt, StockReceiptRevision
from election.server.stock_serials import MAX_STOCK_QUANTITY
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_snapshots import snapshot_basis_current
from election.server.stock_time import StockEventTime

Quantity = Annotated[int, Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)]


class SpecialPaperSeriesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series: str = Field(min_length=1, max_length=64)
    replacement_issued_quantity: Quantity
    spoilt_original_quantity: Quantity
    tendered_issued_quantity: Quantity
    retrieved_refused_quantity: Quantity
    retrieved_found_quantity: Quantity
    retrieved_held_quantity: Quantity

    @field_validator("series")
    @classmethod
    def meaningful_series(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A ballot series is required")
        return value


class SpecialPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    event_at: StockEventTime
    stock_snapshot_id: int = Field(strict=True, gt=0)
    stock_snapshot_revision: int = Field(strict=True, ge=1)
    series: list[SpecialPaperSeriesInput]

    @model_validator(mode="after")
    def unique_series(self) -> SpecialPaperInput:
        if len({row.series for row in self.series}) != len(self.series):
            raise ValueError("Report each ballot series once")
        return self


class SpecialPaperCorrection(SpecialPaperInput):
    revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value


QUANTITIES = (
    "received_quantity",
    "ordinary_issued_quantity",
    "replacement_issued_quantity",
    "spoilt_original_quantity",
    "tendered_issued_quantity",
    "retrieved_refused_quantity",
    "retrieved_found_quantity",
    "retrieved_held_quantity",
    "retrieved_unused_quantity",
    "ordinary_unissued_quantity",
    "replacement_unissued_quantity",
    "tendered_unissued_quantity",
    "never_issued_quantity",
    "estimated_box_papers_quantity",
)


def special_paper_view(row: SpecialPaperRevision, station_id: int) -> dict[str, Any]:
    return {
        **row.data,
        "id": row.snapshot_id,
        "station_id": station_id,
        "status": "recorded",
        "revision": row.revision,
        "stock_snapshot_id": row.stock_snapshot_id,
        "stock_snapshot_revision": row.stock_snapshot_revision,
        "event_at": row.event_at.replace(tzinfo=UTC),
        "entered_at": row.entered_at.replace(tzinfo=UTC),
        "actor_id": row.actor_id,
        "reason": row.reason,
    }


def special_paper_accounting(
    db: Session,
    station_id: int,
    data: SpecialPaperInput,
    *,
    exclude_snapshot_id: int | None = None,
) -> dict[str, Any]:
    event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
    head = db.scalar(
        select(StockSnapshot)
        .where(
            StockSnapshot.id == data.stock_snapshot_id,
            StockSnapshot.station_id == station_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if head is None:
        raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
    if head.revision != data.stock_snapshot_revision:
        raise HTTPException(409, detail={"code": "stock_snapshot_basis_stale"})
    snapshot = db.scalar(
        select(StockSnapshotRevision)
        .where(
            StockSnapshotRevision.snapshot_id == head.id,
            StockSnapshotRevision.revision == head.revision,
        )
        .with_for_update()
    )
    assert snapshot is not None
    if not snapshot.data["complete"]:
        raise HTTPException(409, detail={"code": "stock_snapshot_incomplete"})
    if snapshot.event_at > event_at or not snapshot_basis_current(
        db,
        station_id,
        snapshot,
        lock=True,
    ):
        raise HTTPException(409, detail={"code": "stock_snapshot_basis_stale"})
    lines = received_ranges(db, station_id, lock=True)
    receipt_rows = list(
        db.scalars(
            select(StockReceiptRevision)
            .where(
                tuple_(StockReceiptRevision.receipt_id, StockReceiptRevision.revision).in_(
                    {(line.receipt_id, line.receipt_revision) for line in lines}
                ),
                StockReceiptRevision.event_at <= event_at,
            )
            .with_for_update()
        )
    )
    versions = {(row.receipt_id, row.revision) for row in receipt_rows}
    lines = [line for line in lines if (line.receipt_id, line.receipt_revision) in versions]
    if {row.series for row in data.series} != {line.series for line in lines}:
        raise HTTPException(409, detail={"code": "special_paper_series_incomplete"})
    issued: dict[str, int] = {}
    for counter in snapshot.data["counters"]:
        for line in counter["issued_ranges"]:
            issued[line["series"]] = issued.get(line["series"], 0) + line["quantity"]
    rows = []
    for entered in data.series:
        pools = {
            pool: sum(
                line.quantity
                for line in lines
                if line.series == entered.series and line.pool == pool
            )
            for pool in ("ordinary", "replacement", "tendered")
        }
        ordinary_issued = issued.get(entered.series, 0)
        retrieved = (
            entered.retrieved_refused_quantity
            + entered.retrieved_found_quantity
            + entered.retrieved_held_quantity
        )
        unissued = (
            pools["ordinary"] - ordinary_issued,
            pools["replacement"] - entered.replacement_issued_quantity,
            pools["tendered"] - entered.tendered_issued_quantity,
        )
        if min(unissued) < 0 or retrieved > ordinary_issued:
            raise HTTPException(409, detail={"code": "special_paper_bounds"})
        if entered.spoilt_original_quantity != entered.replacement_issued_quantity:
            raise HTTPException(409, detail={"code": "replacement_spoilt_mismatch"})
        rows.append(
            {
                **entered.model_dump(),
                "received_quantity": sum(pools.values()),
                "ordinary_issued_quantity": ordinary_issued,
                "retrieved_unused_quantity": retrieved,
                "ordinary_unissued_quantity": unissued[0],
                "replacement_unissued_quantity": unissued[1],
                "tendered_unissued_quantity": unissued[2],
                "never_issued_quantity": sum(unissued),
                # Replacements substitute for cancelled originals. Do not deduct the pair again.
                "estimated_box_papers_quantity": ordinary_issued - retrieved,
            }
        )
    entered_rows = {row["series"]: row for row in rows}
    for existing in current_special_papers(db, station_id, lock=True):
        if existing.snapshot_id == exclude_snapshot_id:
            continue
        retained_rows = {row["series"]: row for row in existing.data["series"]}
        for series in entered_rows.keys() | retained_rows.keys():
            for quantity in ("replacement_issued_quantity", "tendered_issued_quantity"):
                candidate = entered_rows.get(series, {}).get(quantity, 0)
                retained = retained_rows.get(series, {}).get(quantity, 0)
                if (
                    existing.event_at <= event_at
                    and candidate < retained
                    or existing.event_at >= event_at
                    and candidate > retained
                ):
                    raise HTTPException(409, detail={"code": "special_paper_issuance_regression"})
    return {
        "series": rows,
        **{key: sum(row[key] for row in rows) for key in QUANTITIES},
        "receipt_basis": [
            {"receipt_id": rid, "revision": revision} for rid, revision in sorted(versions)
        ],
        "received_ranges": [
            {
                "receipt_id": line.receipt_id,
                "revision": line.receipt_revision,
                "series": line.series,
                "pool": line.pool,
                "serial_from": line.serial_from,
                "serial_to": line.serial_to,
                "quantity": line.quantity,
            }
            for line in lines
        ],
        "stock_snapshot_event_at": snapshot.event_at.isoformat() + "Z",
        "stock_snapshot_data": snapshot.data,
    }


def special_paper_basis_current(
    db: Session,
    station_id: int,
    row: SpecialPaperRevision,
) -> bool:
    head = db.scalar(
        select(StockSnapshot).where(
            StockSnapshot.id == row.stock_snapshot_id,
            StockSnapshot.station_id == station_id,
        )
    )
    if head is None or head.revision != row.stock_snapshot_revision:
        return False
    snapshot = db.scalar(
        select(StockSnapshotRevision).where(
            StockSnapshotRevision.snapshot_id == head.id,
            StockSnapshotRevision.revision == head.revision,
        )
    )
    if snapshot is None or not snapshot_basis_current(db, station_id, snapshot):
        return False
    receipts = set(
        db.execute(
            select(StockReceipt.id, StockReceipt.revision)
            .join(
                StockReceiptRevision,
                and_(
                    StockReceipt.id == StockReceiptRevision.receipt_id,
                    StockReceipt.revision == StockReceiptRevision.revision,
                ),
            )
            .where(
                StockReceipt.station_id == station_id, StockReceiptRevision.event_at <= row.event_at
            )
        )
    )
    expected = {(source["receipt_id"], source["revision"]) for source in row.data["receipt_basis"]}
    return receipts == expected


def special_paper_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/special-papers",
        tags=["Special-paper accounting"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def save(
        station_id: int,
        data: SpecialPaperInput,
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
                    select(SpecialPaperSnapshot)
                    .where(
                        SpecialPaperSnapshot.id == snapshot_id,
                        SpecialPaperSnapshot.station_id == station_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if head is None:
                    raise HTTPException(404, detail={"code": "special_paper_not_found"})
            values = data.model_dump(mode="json", exclude={"request_id"})
            values["event_at"] = data.event_at.astimezone(UTC).isoformat()
            identity = {"station_id": station_id, **values}
            if snapshot_id is not None:
                identity["snapshot_id"] = snapshot_id
            digest = hashlib.sha256(
                json.dumps(
                    identity,
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            saved = db.scalar(
                select(SpecialPaperRevision)
                .where(
                    SpecialPaperRevision.request_id == str(data.request_id),
                )
                .with_for_update()
            )
            if saved is not None:
                if saved.payload_digest != digest:
                    raise HTTPException(409, detail={"code": "request_conflict"})
                response.status_code = 200
                return special_paper_view(saved, station_id)
            if isinstance(data, SpecialPaperCorrection):
                assert head is not None
                if head.revision != data.revision:
                    raise HTTPException(409, detail={"code": "revision_conflict"})
            now = timestamp()
            event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
            if event_at > now:
                raise HTTPException(422, detail={"code": "event_time_in_future"})
            accounting = special_paper_accounting(
                db, station_id, data, exclude_snapshot_id=snapshot_id
            )
            if head is None:
                head = SpecialPaperSnapshot(station_id=station_id, revision=1, created_at=now)
                db.add(head)
                db.flush()
            else:
                head.revision += 1
            row = SpecialPaperRevision(
                snapshot_id=head.id,
                revision=head.revision,
                request_id=str(data.request_id),
                payload_digest=digest,
                stock_snapshot_id=data.stock_snapshot_id,
                stock_snapshot_revision=data.stock_snapshot_revision,
                event_at=event_at,
                entered_at=now,
                actor_id=actor.id,
                reason=data.reason if isinstance(data, SpecialPaperCorrection) else "",
                data={"scope": scope, **accounting},
            )
            db.add(row)
            db.add(
                AuditEvent(
                    actor_id=actor.id,
                    action="special_papers_corrected"
                    if head.revision > 1
                    else "special_papers_recorded",
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
            return special_paper_view(row, station_id)

        return stock_write(db, write)

    @router.get("")
    def collection(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        rows = current_special_papers(db, station_id)
        items = [special_paper_view(row, station_id) for row in rows]
        return {
            "scope": scope,
            "items": items,
            "latest": items[-1] if items else None,
            "latest_basis_current": special_paper_basis_current(db, station_id, rows[-1])
            if rows
            else None,
        }

    @router.post("", status_code=201)
    def create(
        station_id: int, data: SpecialPaperInput, response: Response, db: Database, actor: Ready
    ) -> dict[str, Any]:
        return save(station_id, data, response, db, actor)

    @router.put("/{snapshot_id}")
    def correct(
        station_id: int,
        snapshot_id: int,
        data: SpecialPaperCorrection,
        response: Response,
        db: Database,
        actor: Ready,
    ) -> dict[str, Any]:
        return save(station_id, data, response, db, actor, snapshot_id)

    def read_head(db: Session, station_id: int, snapshot_id: int) -> SpecialPaperSnapshot:
        head = db.scalar(
            select(SpecialPaperSnapshot).where(
                SpecialPaperSnapshot.id == snapshot_id,
                SpecialPaperSnapshot.station_id == station_id,
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "special_paper_not_found"})
        return head

    @router.get("/{snapshot_id}/history")
    def history(station_id: int, snapshot_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, snapshot_id)
        rows = db.scalars(
            select(SpecialPaperRevision)
            .where(
                SpecialPaperRevision.snapshot_id == head.id,
            )
            .order_by(SpecialPaperRevision.revision)
        )
        return {"items": [special_paper_view(row, station_id) for row in rows]}

    @router.get("/{snapshot_id}")
    def read(
        station_id: int,
        snapshot_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, snapshot_id)
        row = db.scalar(
            select(SpecialPaperRevision).where(
                SpecialPaperRevision.snapshot_id == head.id,
                SpecialPaperRevision.revision
                == (revision if revision is not None else head.revision),
            )
        )
        if row is None:
            raise HTTPException(404, detail={"code": "special_paper_not_found"})
        return special_paper_view(row, station_id)

    return router
