"""Assigned-station received stock, conserved pools and immutable corrections."""

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.models import Account, AuditEvent
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation
from election.server.stock_inventory import preserve_allocations
from election.server.stock_models import StockReceipt, StockReceiptRange, StockReceiptRevision
from election.server.stock_serials import (
    MAX_STOCK_QUANTITY,
    StockRangeInput,
    pool_totals,
    serial_number,
)


class StockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    series: str = Field(min_length=1, max_length=64)
    event_at: AwareDatetime
    ranges: list[StockRangeInput] = Field(min_length=1)
    ordinary_quantity: int = Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)
    replacement_quantity: int = Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)
    tendered_quantity: int = Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)

    @field_validator("series")
    @classmethod
    def meaningful_series(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A ballot series is required")
        return value

    @model_validator(mode="after")
    def conserved_pools(self) -> StockInput:
        totals = pool_totals(self.ranges)
        if (self.ordinary_quantity, self.replacement_quantity, self.tendered_quantity) != (
            totals["ordinary"],
            totals["replacement"],
            totals["tendered"],
        ):
            raise ValueError("Declared starting pools must match their inclusive serial ranges")
        return self


class StockCorrection(StockInput):
    revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value


def stock_scope(
    db: Session, actor: Account, station_id: int, *, write: bool = False
) -> dict[str, Any]:
    roles = ("polling_officer",) if write else ("polling_officer", "counting_officer", "supervisor")
    if actor.role not in roles:
        raise HTTPException(403, detail={"code": "operational_role_required"})
    if not db.get(StationAssignment, (actor.id, station_id)):
        raise HTTPException(403, detail={"code": "station_access_denied"})
    station = db.get(PollingStation, station_id)
    assert station is not None
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    query = select(Election).where(Election.id == constituency.election_id)
    if write:
        # Match configuration lock order, then serialize cross-station physical ownership.
        query = query.with_for_update().execution_options(populate_existing=True)
    election = db.scalar(query)
    assert election is not None
    if write:
        constituency = db.scalar(
            select(Constituency)
            .where(Constituency.id == constituency.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert constituency is not None
        if election.status not in ("draft", "active"):
            raise HTTPException(409, detail={"code": "election_read_only"})
    return {
        "election": {"id": election.id, "name": election.name, "status": election.status},
        "constituency": {
            "id": constituency.id,
            "name": constituency.name,
            "code": constituency.code,
        },
        "station": {
            "id": station.id,
            "name": station.name,
            "code": station.code,
            "counting_mode": station.counting_mode,
            "destination_station_id": station.destination_station_id,
        },
    }


def receipt_views(
    db: Session,
    revisions: list[StockReceiptRevision],
    scope: dict[str, Any],
    *,
    current: bool = False,
) -> list[dict[str, Any]]:
    lines: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if revisions:
        query = (
            select(StockReceiptRange)
            .where(StockReceiptRange.revision_id.in_([r.id for r in revisions]))
            .order_by(StockReceiptRange.revision_id, StockReceiptRange.line_number)
        )
        if current:
            # A replay header can become visible after waiting for a lock even though
            # authentication opened an older snapshot. Its immutable lines need a current read too.
            query = query.with_for_update()
        for row in db.scalars(query):
            lines[row.revision_id].append(
                {
                    "pool": row.pool,
                    "serial_from": row.serial_from,
                    "serial_to": row.serial_to,
                    "quantity": row.quantity,
                }
            )
    return [
        {
            "id": row.receipt_id,
            "station_id": scope["station"]["id"],
            "election_id": scope["election"]["id"],
            "constituency_id": scope["constituency"]["id"],
            "revision": row.revision,
            "status": "recorded",
            "series": row.series,
            "event_at": row.event_at.replace(tzinfo=UTC),
            "entered_at": row.entered_at.replace(tzinfo=UTC),
            "actor_id": row.actor_id,
            "reason": row.reason,
            "ranges": lines[row.id],
            "ordinary_quantity": row.ordinary_quantity,
            "replacement_quantity": row.replacement_quantity,
            "tendered_quantity": row.tendered_quantity,
            "total_quantity": row.total_quantity,
        }
        for row in revisions
    ]


def stock_statement(
    db: Session,
    actor: Account,
    station_id: int,
    *,
    receipt_id: int | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    scope = stock_scope(db, actor, station_id)
    if receipt_id is not None:
        head = db.scalar(
            select(StockReceipt).where(
                StockReceipt.id == receipt_id, StockReceipt.station_id == station_id
            )
        )
        if not head:
            raise HTTPException(404, detail={"code": "stock_receipt_not_found"})
        revisions = list(
            db.scalars(
                select(StockReceiptRevision).where(
                    StockReceiptRevision.receipt_id == receipt_id,
                    StockReceiptRevision.revision
                    == (head.revision if revision is None else revision),
                )
            )
        )
        if not revisions:
            raise HTTPException(404, detail={"code": "stock_receipt_not_found"})
    else:
        revisions = list(
            db.scalars(
                select(StockReceiptRevision)
                .join(
                    StockReceipt,
                    and_(
                        StockReceipt.id == StockReceiptRevision.receipt_id,
                        StockReceipt.revision == StockReceiptRevision.revision,
                    ),
                )
                .where(StockReceipt.station_id == station_id)
                .order_by(StockReceipt.id)
            )
        )
    return {"scope": scope, "items": receipt_views(db, revisions, scope)}


def stock_write(db: Session, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return action()
        except OperationalError as error:
            db.rollback()
            if error.orig is None or error.orig.args[:1] != (1213,) or attempt == 2:
                raise
            # Different election locks can still contend on a new global request-key gap.
            # Restart the whole rolled-back transaction; replay then observes the winner.
    raise AssertionError("Unreachable stock transaction retry")


def stock_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/stock", tags=["Received stock"])
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def receipt(
        db: Session, station_id: int, receipt_id: int, *, lock: bool = False
    ) -> StockReceipt:
        query = select(StockReceipt).where(
            StockReceipt.id == receipt_id, StockReceipt.station_id == station_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = db.scalar(query)
        if not row:
            raise HTTPException(404, detail={"code": "stock_receipt_not_found"})
        return row

    def digest(data: StockInput, station_id: int, receipt_id: int | None) -> str:
        values = data.model_dump(mode="json", exclude={"request_id"})
        values["event_at"] = data.event_at.astimezone(UTC).isoformat()
        return hashlib.sha256(
            json.dumps(
                {"station_id": station_id, "receipt_id": receipt_id, **values},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def replay(db: Session, data: StockInput, expected: str) -> StockReceiptRevision | None:
        row = db.scalar(
            select(StockReceiptRevision)
            .where(StockReceiptRevision.request_id == str(data.request_id))
            .with_for_update()
        )
        if row and row.payload_digest != expected:
            raise HTTPException(409, detail={"code": "request_conflict"})
        return row

    def no_overlap(db: Session, scope: dict[str, Any], data: StockInput, exclude_id: int) -> None:
        current = list(
            db.scalars(
                select(StockReceiptRange)
                .join(
                    StockReceiptRevision, StockReceiptRevision.id == StockReceiptRange.revision_id
                )
                .join(
                    StockReceipt,
                    and_(
                        StockReceipt.id == StockReceiptRevision.receipt_id,
                        StockReceipt.revision == StockReceiptRevision.revision,
                    ),
                )
                .join(PollingStation, PollingStation.id == StockReceipt.station_id)
                .where(
                    PollingStation.constituency_id == scope["constituency"]["id"],
                    StockReceiptRevision.series == data.series,
                    StockReceipt.id != exclude_id,
                )
                .with_for_update()
            )
        )
        for incoming in data.ranges:
            first, last = serial_number(incoming.serial_from), serial_number(incoming.serial_to)
            if any(
                row.serial_from_value <= last and row.serial_to_value >= first for row in current
            ):
                raise HTTPException(409, detail={"code": "stock_overlap"})

    def persist(
        db: Session,
        actor: Account,
        scope: dict[str, Any],
        data: StockInput,
        head: StockReceipt,
        expected: str,
        correction: bool,
    ) -> StockReceiptRevision:
        now = timestamp()
        row = StockReceiptRevision(
            receipt_id=head.id,
            revision=head.revision,
            request_id=str(data.request_id),
            payload_digest=expected,
            series=data.series,
            event_at=data.event_at.astimezone(UTC).replace(tzinfo=None),
            entered_at=now,
            actor_id=actor.id,
            reason=data.reason if isinstance(data, StockCorrection) else "",
            ordinary_quantity=data.ordinary_quantity,
            replacement_quantity=data.replacement_quantity,
            tendered_quantity=data.tendered_quantity,
            total_quantity=data.ordinary_quantity
            + data.replacement_quantity
            + data.tendered_quantity,
        )
        db.add(row)
        db.flush()
        for line_number, line in enumerate(data.ranges):
            db.add(
                StockReceiptRange(
                    revision_id=row.id,
                    line_number=line_number,
                    pool=line.pool,
                    serial_from=line.serial_from,
                    serial_to=line.serial_to,
                    serial_from_value=serial_number(line.serial_from),
                    serial_to_value=serial_number(line.serial_to),
                    quantity=line.quantity,
                )
            )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="stock_corrected" if correction else "stock_received",
                occurred_at=now,
                details={
                    "receipt_id": head.id,
                    "station_id": scope["station"]["id"],
                    "constituency_id": scope["constituency"]["id"],
                    "election_id": scope["election"]["id"],
                    "revision": head.revision,
                    "reason": row.reason,
                    **data.model_dump(mode="json", exclude={"request_id", "revision", "reason"}),
                },
            )
        )
        db.commit()
        return row

    @router.get("")
    def list_stock(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        return stock_statement(db, actor, station_id)

    @router.post("", status_code=201)
    def create_stock(
        station_id: int, data: StockInput, response: Response, db: Database, actor: Ready
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            scope = stock_scope(db, actor, station_id, write=True)
            expected = digest(data, station_id, None)
            saved = replay(db, data, expected)
            if saved:
                response.status_code = 200
                return receipt_views(db, [saved], scope, current=True)[0]
            no_overlap(db, scope, data, 0)
            head = StockReceipt(station_id=station_id, revision=1, created_at=timestamp())
            db.add(head)
            db.flush()
            try:
                saved = persist(db, actor, scope, data, head, expected, False)
            except IntegrityError:
                db.rollback()
                saved = replay(db, data, expected)
                if not saved:
                    raise HTTPException(409, detail={"code": "request_conflict"}) from None
                response.status_code = 200
            return receipt_views(db, [saved], scope, current=True)[0]

        return stock_write(db, write)

    @router.get("/{receipt_id}/history")
    def history(station_id: int, receipt_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        receipt(db, station_id, receipt_id)
        rows = list(
            db.scalars(
                select(StockReceiptRevision)
                .where(StockReceiptRevision.receipt_id == receipt_id)
                .order_by(StockReceiptRevision.revision)
            )
        )
        return {"scope": scope, "receipt_id": receipt_id, "items": receipt_views(db, rows, scope)}

    @router.get("/{receipt_id}")
    def get_stock(
        station_id: int,
        receipt_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        item: dict[str, Any] = stock_statement(
            db, actor, station_id, receipt_id=receipt_id, revision=revision
        )["items"][0]
        return item

    @router.put("/{receipt_id}")
    def correct_stock(
        station_id: int, receipt_id: int, data: StockCorrection, db: Database, actor: Ready
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            scope = stock_scope(db, actor, station_id, write=True)
            head = receipt(db, station_id, receipt_id, lock=True)
            expected = digest(data, station_id, receipt_id)
            saved = replay(db, data, expected)
            if saved:
                return receipt_views(db, [saved], scope, current=True)[0]
            if head.revision != data.revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            no_overlap(db, scope, data, head.id)
            preserve_allocations(db, station_id, head.id, data.series, data.ranges)
            head.revision += 1
            try:
                saved = persist(db, actor, scope, data, head, expected, True)
            except IntegrityError:
                db.rollback()
                saved = replay(db, data, expected)
                if not saved:
                    raise HTTPException(409, detail={"code": "request_conflict"}) from None
            return receipt_views(db, [saved], scope, current=True)[0]

        return stock_write(db, write)

    return router
