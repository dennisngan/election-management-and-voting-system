"""Persist counter allocations directly and expose shared ordinary-stock availability."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.paper_reentry import PaperEntry, finish_paper_entry, guard_paper_entry
from election.server.station_models import IssuanceCounter
from election.server.stock import stock_scope, stock_write
from election.server.stock_inventory import (
    allocation_fragments,
    availability,
    current_allocations,
    current_returns,
    preserve_issued_observations,
    preserve_returned_stock,
    receipt_basis,
    received_ranges,
    subtract_intervals,
)
from election.server.stock_serials import serial_number


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    counter_id: int = Field(strict=True, gt=0)
    series: str = Field(min_length=1, max_length=64)
    serial_from: str = Field(min_length=1, max_length=18)
    serial_to: str = Field(min_length=1, max_length=18)
    event_at: AwareDatetime
    paper_record_id: int | None = Field(default=None, strict=True, gt=0)

    @field_validator("series")
    @classmethod
    def meaningful_series(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A ballot series is required")
        return value

    @model_validator(mode="after")
    def ordered_serials(self) -> AllocationInput:
        if serial_number(self.serial_to) < serial_number(self.serial_from):
            raise ValueError("Serial end must not precede its start")
        return self

    @property
    def quantity(self) -> int:
        return serial_number(self.serial_to) - serial_number(self.serial_from) + 1


class AllocationCorrection(AllocationInput):
    revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value


def allocation_view(row: StockAllocationRevision, scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.allocation_id,
        "station_id": scope["station"]["id"],
        "election_id": scope["election"]["id"],
        "constituency_id": scope["constituency"]["id"],
        "revision": row.revision,
        "status": "recorded",
        "counter": {"id": row.counter_id, "code": row.counter_code, "name": row.counter_name},
        "series": row.series,
        "serial_from": row.serial_from,
        "serial_to": row.serial_to,
        "quantity": row.quantity,
        "event_at": row.event_at.replace(tzinfo=UTC),
        "entered_at": row.entered_at.replace(tzinfo=UTC),
        "actor_id": row.actor_id,
        "reason": row.reason,
        "receipt_basis": row.receipt_basis,
    }


def allocation_digest(
    data: AllocationInput, station_id: int, allocation_id: int | None = None
) -> str:
    values = data.model_dump(mode="json", exclude={"request_id", "paper_record_id"})
    values["event_at"] = data.event_at.astimezone(UTC).isoformat()
    return hashlib.sha256(
        json.dumps(
            {"station_id": station_id, "allocation_id": allocation_id, **values},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def allocation_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/allocations", tags=["Counter allocations"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def validate_stock(
        db: Session,
        station_id: int,
        data: AllocationInput,
        *,
        exclude_id: int | None = None,
    ) -> tuple[IssuanceCounter, list[dict[str, int]]]:
        counter = db.scalar(
            select(IssuanceCounter)
            .where(IssuanceCounter.id == data.counter_id, IssuanceCounter.station_id == station_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if counter is None:
            raise HTTPException(404, detail={"code": "counter_not_found"})
        first, last = serial_number(data.serial_from), serial_number(data.serial_to)
        basis = receipt_basis(received_ranges(db, station_id, lock=True), data.series, first, last)
        allocations = current_allocations(db, station_id, lock=True)
        returns = current_returns(db, station_id, lock=True)
        returned_parts: list[tuple[int, int]] = []
        future_return_parts: list[tuple[int, int]] = []
        event_at = data.event_at.astimezone(UTC).replace(tzinfo=None)
        for returned in returns:
            if returned.series != data.series:
                continue
            for part in returned.allocation_basis:
                part_first = serial_number(str(part["serial_from"]))
                part_last = serial_number(str(part["serial_to"]))
                if int(part["allocation_id"]) == exclude_id:
                    returned_parts.append((part_first, part_last))
                elif returned.event_at > event_at:
                    future_return_parts.append((part_first, part_last))
        proposed = subtract_intervals(first, last, returned_parts)
        if any(
            part_first <= end and part_last >= start
            for part_first, part_last in future_return_parts
            for start, end in proposed
        ):
            raise HTTPException(409, detail={"code": "allocation_before_return"})
        for fragment in allocation_fragments(allocations, returns):
            owned = fragment.allocation
            if owned.allocation_id != exclude_id and owned.series == data.series:
                if any(
                    fragment.serial_from_value <= end and fragment.serial_to_value >= start
                    for start, end in proposed
                ):
                    raise HTTPException(409, detail={"code": "allocation_overlap"})
        return counter, basis

    def paper_entry(
        db: Session,
        actor: Account,
        station_id: int,
        allocation_id: int | None,
        data: AllocationInput,
    ) -> PaperEntry:
        if data.paper_record_id is None:
            return None
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        target = {"counter_id": data.counter_id}
        action = "create"
        if allocation_id is not None:
            target["allocation_id"] = allocation_id
            action = "amend"
        return guard_paper_entry(
            db,
            actor,
            station_id,
            data.paper_record_id,
            "allocation",
            action,
            target,
            data.request_id,
            event_at=data.event_at,
        )

    def persist(
        db: Session,
        actor: Account,
        scope: dict[str, Any],
        data: AllocationInput,
        head: StockAllocation,
        digest: str,
        counter: IssuanceCounter,
        basis: list[dict[str, int]],
        now: datetime,
        paper: PaperEntry,
    ) -> dict[str, Any]:
        if isinstance(data, AllocationCorrection):
            reason, action = data.reason, "stock_allocation_corrected"
        else:
            reason, action = "", "stock_allocated"
        row = StockAllocationRevision(
            allocation_id=head.id,
            revision=head.revision,
            request_id=str(data.request_id),
            payload_digest=digest,
            counter_id=counter.id,
            counter_code=counter.code,
            counter_name=counter.name,
            series=data.series,
            serial_from=data.serial_from,
            serial_to=data.serial_to,
            serial_from_value=serial_number(data.serial_from),
            serial_to_value=serial_number(data.serial_to),
            quantity=data.quantity,
            event_at=data.event_at.astimezone(UTC).replace(tzinfo=None),
            entered_at=now,
            actor_id=actor.id,
            reason=reason,
            receipt_basis=basis,
        )
        if isinstance(data, AllocationCorrection):
            proposed_allocations = [
                item
                for item in current_allocations(db, head.station_id, lock=True)
                if item.allocation_id != head.id
            ] + [row]
            preserve_issued_observations(
                db,
                head.station_id,
                proposed_allocations,
                current_returns(db, head.station_id, lock=True),
            )
        db.add(row)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action=action,
                occurred_at=now,
                details={
                    "allocation_id": head.id,
                    "station_id": head.station_id,
                    "election_id": scope["election"]["id"],
                    "constituency_id": scope["constituency"]["id"],
                    "revision": head.revision,
                    "quantity": data.quantity,
                    # The command's revision is the previous expected head.
                    **data.model_dump(
                        mode="json", exclude={"request_id", "revision", "paper_record_id"}
                    ),
                },
            )
        )
        result = allocation_view(row, scope)
        finish_paper_entry(db, actor, paper, data.request_id, result, now)
        db.commit()
        return result

    @router.get("")
    def list_allocations(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        rows = current_allocations(db, station_id)
        counters = db.scalars(
            select(IssuanceCounter)
            .where(IssuanceCounter.station_id == station_id)
            .order_by(IssuanceCounter.id)
        )
        return {
            "scope": scope,
            "items": [allocation_view(row, scope) for row in rows],
            "counters": [{"id": row.id, "code": row.code, "name": row.name} for row in counters],
            "availability": availability(
                received_ranges(db, station_id),
                allocation_fragments(rows, current_returns(db, station_id)),
            ),
        }

    @router.post("", status_code=201)
    def create_allocation(
        station_id: int, data: AllocationInput, response: Response, db: Database, actor: Ready
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            scope = stock_scope(db, actor, station_id, write=True)
            paper = paper_entry(db, actor, station_id, None, data)
            digest = allocation_digest(data, station_id)
            saved = db.scalar(
                select(StockAllocationRevision)
                .where(StockAllocationRevision.request_id == str(data.request_id))
                .with_for_update()
            )
            if saved is not None:
                if saved.payload_digest != digest or (
                    paper is not None and saved.actor_id != actor.id
                ):
                    raise HTTPException(409, detail={"code": "request_conflict"})
                response.status_code = 200
                result = allocation_view(saved, scope)
                if paper is not None:
                    finish_paper_entry(db, actor, paper, data.request_id, result, timestamp())
                    db.commit()
                return result
            counter, basis = validate_stock(db, station_id, data)
            now = timestamp()
            head = StockAllocation(station_id=station_id, revision=1, created_at=now)
            db.add(head)
            db.flush()
            return persist(db, actor, scope, data, head, digest, counter, basis, now, paper)

        return stock_write(db, write)

    @router.get("/{allocation_id}/history")
    def history(station_id: int, allocation_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        head = db.scalar(
            select(StockAllocation).where(
                StockAllocation.id == allocation_id, StockAllocation.station_id == station_id
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "allocation_not_found"})
        rows = db.scalars(
            select(StockAllocationRevision)
            .where(StockAllocationRevision.allocation_id == allocation_id)
            .order_by(StockAllocationRevision.revision)
        )
        return {
            "scope": scope,
            "allocation_id": allocation_id,
            "items": [allocation_view(row, scope) for row in rows],
        }

    @router.put("/{allocation_id}")
    def correct_allocation(
        station_id: int,
        allocation_id: int,
        data: AllocationCorrection,
        db: Database,
        actor: Ready,
    ) -> dict[str, Any]:
        def write() -> dict[str, Any]:
            scope = stock_scope(db, actor, station_id, write=True)
            paper = paper_entry(db, actor, station_id, allocation_id, data)
            head = db.scalar(
                select(StockAllocation)
                .where(
                    StockAllocation.id == allocation_id, StockAllocation.station_id == station_id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if head is None:
                raise HTTPException(404, detail={"code": "allocation_not_found"})
            digest = allocation_digest(data, station_id, allocation_id)
            saved = db.scalar(
                select(StockAllocationRevision)
                .where(StockAllocationRevision.request_id == str(data.request_id))
                .with_for_update()
            )
            if saved is not None:
                if saved.payload_digest != digest:
                    raise HTTPException(409, detail={"code": "request_conflict"})
                result = allocation_view(saved, scope)
                if paper is not None:
                    finish_paper_entry(db, actor, paper, data.request_id, result, timestamp())
                    db.commit()
                return result
            if head.revision != data.revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            counter, basis = validate_stock(db, station_id, data, exclude_id=head.id)
            preserve_returned_stock(
                db,
                station_id,
                head.id,
                counter.id,
                data.series,
                serial_number(data.serial_from),
                serial_number(data.serial_to),
                data.event_at.astimezone(UTC).replace(tzinfo=None),
            )
            head.revision += 1
            now = timestamp()
            return persist(db, actor, scope, data, head, digest, counter, basis, now, paper)

        return stock_write(db, write)

    @router.get("/{allocation_id}")
    def get_allocation(
        station_id: int,
        allocation_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        head = db.scalar(
            select(StockAllocation).where(
                StockAllocation.id == allocation_id, StockAllocation.station_id == station_id
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "allocation_not_found"})
        row = db.scalar(
            select(StockAllocationRevision).where(
                StockAllocationRevision.allocation_id == allocation_id,
                StockAllocationRevision.revision
                == (head.revision if revision is None else revision),
            )
        )
        if row is None:
            raise HTTPException(404, detail={"code": "allocation_not_found"})
        return allocation_view(row, scope)

    return router
