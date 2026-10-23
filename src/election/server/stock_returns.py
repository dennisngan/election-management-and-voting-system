"""Physical returns of never-issued ordinary counter stock to the PRO."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocations import AllocationCorrection, AllocationInput
from election.server.models import Account, AuditEvent
from election.server.station_models import IssuanceCounter
from election.server.stock import stock_scope, stock_write
from election.server.stock_inventory import (
    allocation_fragments,
    covering_fragments,
    current_allocations,
    current_returns,
    preserve_issued_observations,
    reject_known_issued,
    validate_return_ownership,
)
from election.server.stock_return_models import CounterStockReturn, CounterStockReturnRevision
from election.server.stock_serials import serial_number
from election.server.stock_time import StockEventTime


class StockReturnInput(AllocationInput):
    event_at: StockEventTime


class StockReturnCorrection(AllocationCorrection):
    event_at: StockEventTime


def stock_return_view(row: CounterStockReturnRevision, station_id: int) -> dict[str, Any]:
    return {
        "id": row.return_id,
        "station_id": station_id,
        "revision": row.revision,
        "status": "recorded",
        "kind": "unissued_counter_to_pro",
        "counter": {"id": row.counter_id, "code": row.counter_code, "name": row.counter_name},
        "series": row.series,
        "serial_from": row.serial_from,
        "serial_to": row.serial_to,
        "quantity": row.quantity,
        "event_at": row.event_at.replace(tzinfo=UTC),
        "entered_at": row.entered_at.replace(tzinfo=UTC),
        "actor_id": row.actor_id,
        "reason": row.reason,
        "allocation_basis": row.allocation_basis,
    }


def stock_return_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/stock-returns",
        tags=["Unissued counter returns"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def list_returns(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        rows = current_returns(db, station_id)
        counters = db.scalars(
            select(IssuanceCounter)
            .where(IssuanceCounter.station_id == station_id)
            .order_by(IssuanceCounter.id)
        )
        return {
            "scope": scope,
            "items": [stock_return_view(row, station_id) for row in rows],
            "counters": [{"id": row.id, "code": row.code, "name": row.name} for row in counters],
        }

    def save_return(
        station_id: int,
        data: AllocationInput,
        response: Response,
        db: Session,
        actor: Account,
        return_id: int | None = None,
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            stock_scope(db, actor, station_id, write=True)
            head = None
            if return_id is not None:
                head = db.scalar(
                    select(CounterStockReturn)
                    .where(
                        CounterStockReturn.id == return_id,
                        CounterStockReturn.station_id == station_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if head is None:
                    raise HTTPException(404, detail={"code": "stock_return_not_found"})
            values = data.model_dump(mode="json", exclude={"request_id"})
            values["event_at"] = data.event_at.astimezone(UTC).isoformat()
            digest = hashlib.sha256(
                json.dumps(
                    {"station_id": station_id, "return_id": return_id, **values},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            saved = db.scalar(
                select(CounterStockReturnRevision)
                .where(CounterStockReturnRevision.request_id == str(data.request_id))
                .with_for_update()
            )
            if saved is not None:
                if saved.payload_digest != digest:
                    raise HTTPException(409, detail={"code": "request_conflict"})
                response.status_code = 200
                return stock_return_view(saved, station_id)
            if isinstance(data, AllocationCorrection):
                assert head is not None
                if head.revision != data.revision:
                    raise HTTPException(409, detail={"code": "revision_conflict"})
                head.revision += 1
            now = timestamp()
            event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
            if event_at > now:
                raise HTTPException(422, detail={"code": "event_time_in_future"})
            counter = db.scalar(
                select(IssuanceCounter)
                .where(
                    IssuanceCounter.id == data.counter_id, IssuanceCounter.station_id == station_id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if counter is None:
                raise HTTPException(404, detail={"code": "counter_not_found"})
            allocations = [
                row
                for row in current_allocations(db, station_id, lock=True)
                if row.event_at <= event_at
            ]
            returns = [
                row
                for row in current_returns(db, station_id, lock=True)
                if row.event_at <= event_at and row.return_id != return_id
            ]
            fragments = allocation_fragments(allocations, returns)
            first, last = serial_number(data.serial_from), serial_number(data.serial_to)
            reject_known_issued(db, station_id, data.series, first, last, event_at)
            portions = covering_fragments(fragments, counter.id, data.series, first, last)
            if portions is None:
                raise HTTPException(409, detail={"code": "return_outside_owned_stock"})
            basis: list[dict[str, int | str]] = [
                {
                    "allocation_id": fragment.allocation.allocation_id,
                    "revision": fragment.allocation.revision,
                    "serial_from": str(start).zfill(len(data.serial_from)),
                    "serial_to": str(end).zfill(len(data.serial_to)),
                    "quantity": end - start + 1,
                }
                for fragment, start, end in portions
            ]
            if head is None:
                head = CounterStockReturn(station_id=station_id, revision=1, created_at=now)
                db.add(head)
                db.flush()
            row = CounterStockReturnRevision(
                return_id=head.id,
                revision=head.revision,
                request_id=str(data.request_id),
                payload_digest=digest,
                counter_id=counter.id,
                counter_code=counter.code,
                counter_name=counter.name,
                series=data.series,
                serial_from=data.serial_from,
                serial_to=data.serial_to,
                serial_from_value=first,
                serial_to_value=last,
                quantity=data.quantity,
                event_at=event_at,
                entered_at=now,
                actor_id=actor.id,
                reason=data.reason if isinstance(data, AllocationCorrection) else "",
                allocation_basis=basis,
            )
            all_allocations = current_allocations(db, station_id, lock=True)
            proposed_returns = [
                item
                for item in current_returns(db, station_id, lock=True)
                if item.return_id != return_id
            ] + [row]
            validate_return_ownership(all_allocations, proposed_returns)
            preserve_issued_observations(db, station_id, all_allocations, proposed_returns)
            db.add(row)
            db.add(
                AuditEvent(
                    actor_id=actor.id,
                    action="counter_stock_return_corrected"
                    if head.revision > 1
                    else "counter_stock_returned",
                    occurred_at=now,
                    details={
                        "station_id": station_id,
                        "return_id": head.id,
                        **values,
                        "revision": head.revision,
                        "allocation_basis": basis,
                    },
                )
            )
            db.commit()
            return stock_return_view(row, station_id)

        return stock_write(db, write)

    @router.post("", status_code=201)
    def create_return(
        station_id: int, data: StockReturnInput, response: Response, db: Database, actor: Ready
    ) -> dict[str, Any]:
        return save_return(station_id, data, response, db, actor)

    @router.put("/{return_id}")
    def correct_return(
        station_id: int,
        return_id: int,
        data: StockReturnCorrection,
        response: Response,
        db: Database,
        actor: Ready,
    ) -> dict[str, Any]:
        return save_return(station_id, data, response, db, actor, return_id)

    def read_head(db: Session, station_id: int, return_id: int) -> CounterStockReturn:
        head = db.scalar(
            select(CounterStockReturn).where(
                CounterStockReturn.id == return_id, CounterStockReturn.station_id == station_id
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "stock_return_not_found"})
        return head

    @router.get("/{return_id}/history")
    def history(station_id: int, return_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, return_id)
        rows = db.scalars(
            select(CounterStockReturnRevision)
            .where(CounterStockReturnRevision.return_id == head.id)
            .order_by(CounterStockReturnRevision.revision)
        )
        return {"items": [stock_return_view(row, station_id) for row in rows]}

    @router.get("/{return_id}")
    def read_return(
        station_id: int,
        return_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = read_head(db, station_id, return_id)
        row = db.scalar(
            select(CounterStockReturnRevision).where(
                CounterStockReturnRevision.return_id == head.id,
                CounterStockReturnRevision.revision
                == (revision if revision is not None else head.revision),
            )
        )
        if row is None:
            raise HTTPException(404, detail={"code": "stock_return_not_found"})
        return stock_return_view(row, station_id)

    return router
