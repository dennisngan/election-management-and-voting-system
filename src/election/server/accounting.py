"""Source-station conservation, frozen revisions and exact review."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from election.server.accounting_models import AccountingRecord, AccountingRequest
from election.server.models import Account, AuditEvent
from election.server.security import verify_password
from election.server.special_paper_inventory import current_special_papers
from election.server.special_papers import special_paper_basis_current, special_paper_view
from election.server.stock_inventory import current_allocations, current_returns, received_ranges
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_snapshots import snapshot_view
from election.server.timestamps import as_utc
from election.server.turnout import approved_prefix, current_records, turnout_record_view
from election.server.turnout_basis import locked_schedule, turnout_scope


class AccountingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0)


class AccountingDraft(AccountingCommand):
    special_paper_id: int = Field(strict=True, gt=0)
    special_paper_revision: int = Field(strict=True, ge=1)
    turnout_period_index: int | None = Field(default=None, strict=True, ge=1)
    turnout_revision: int | None = Field(default=None, strict=True, ge=1)
    notes: str = Field(default="", max_length=2000)
    amendment_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def paired_turnout(self) -> AccountingDraft:
        if (self.turnout_period_index is None) != (self.turnout_revision is None):
            raise ValueError("Select an exact turnout revision or leave turnout missing")
        return self


class AccountingApproval(AccountingCommand):
    password: str = Field(min_length=1, max_length=128, repr=False)


def accounting_scope(
    db: Session,
    actor: Account,
    station_id: int,
    *,
    writable: bool = False,
) -> dict[str, Any]:
    # This takes ActiveElection → Election → Constituency before schedule/stock locks.
    # A destination assignment never grants this source-station permission.
    return turnout_scope(db, actor, station_id, writable=writable)


def accounting_record(
    db: Session,
    station_id: int,
    revision: int | None = None,
) -> AccountingRecord | None:
    query = select(AccountingRecord).where(AccountingRecord.station_id == station_id)
    if revision is not None:
        query = query.where(AccountingRecord.revision == revision)
    return db.scalar(
        query.order_by(AccountingRecord.revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def source_data(
    db: Session,
    station_id: int,
    election_id: int,
    data: AccountingDraft,
) -> tuple[datetime, dict[str, Any]]:
    schedule = locked_schedule(db, election_id)
    turnout_rows = current_records(db, station_id)
    _, valid_turnout = approved_prefix(turnout_rows, schedule, db)
    specials = current_special_papers(db, station_id, lock=True)
    special = next((row for row in specials if row.snapshot_id == data.special_paper_id), None)
    if special is None:
        raise HTTPException(404, detail={"code": "special_paper_not_found"})
    if (
        special.revision != data.special_paper_revision
        or special != specials[-1]
        or not special_paper_basis_current(db, station_id, special)
    ):
        raise HTTPException(409, detail={"code": "accounting_source_stale"})
    stock = db.scalar(
        select(StockSnapshotRevision)
        .where(
            StockSnapshotRevision.snapshot_id == special.stock_snapshot_id,
            StockSnapshotRevision.revision == special.stock_snapshot_revision,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert stock is not None
    latest_stock = db.scalar(
        select(StockSnapshotRevision)
        .join(
            StockSnapshot,
            and_(
                StockSnapshot.id == StockSnapshotRevision.snapshot_id,
                StockSnapshot.revision == StockSnapshotRevision.revision,
            ),
        )
        .where(StockSnapshot.station_id == station_id)
        .order_by(StockSnapshotRevision.event_at.desc(), StockSnapshot.id.desc())
        .limit(1)
        .with_for_update()
    )
    # A current preparation must cover all recorded stock activity, including
    # movement after the selected observation. Locking reads also avoid approval
    # validating receipt heads from authentication's older MySQL RR snapshot.
    allocations = [
        {"allocation_id": row.allocation_id, "revision": row.revision}
        for row in current_allocations(db, station_id, lock=True)
    ]
    returns = [
        {"return_id": row.return_id, "revision": row.revision}
        for row in current_returns(db, station_id, lock=True)
    ]
    receipts = {
        (line.receipt_id, line.receipt_revision)
        for line in received_ranges(db, station_id, lock=True)
    }
    expected_receipts = {
        (source["receipt_id"], source["revision"]) for source in special.data["receipt_basis"]
    }
    if (
        latest_stock is None
        or latest_stock.id != stock.id
        or allocations != stock.data["allocation_basis"]
        or returns != stock.data["return_basis"]
        or receipts != expected_receipts
    ):
        raise HTTPException(409, detail={"code": "accounting_source_stale"})
    observed = special.data
    ordinary_received = sum(
        row["quantity"] for row in observed["received_ranges"] if row["pool"] == "ordinary"
    )
    summary = {
        key: observed[key]
        for key in (
            "received_quantity",
            "ordinary_issued_quantity",
            "replacement_issued_quantity",
            "spoilt_original_quantity",
            "tendered_issued_quantity",
            "retrieved_refused_quantity",
            "retrieved_found_quantity",
            "retrieved_held_quantity",
            "retrieved_unused_quantity",
            "replacement_unissued_quantity",
            "tendered_unissued_quantity",
            "never_issued_quantity",
        )
    }
    summary.update(
        ordinary_received_quantity=ordinary_received,
        ordinary_central_unissued_quantity=(
            ordinary_received - stock.data["ordinary_net_allocated_quantity"]
        ),
        ordinary_at_desks_quantity=stock.data["ordinary_remaining_quantity"],
        estimated_box_from_stock_quantity=observed["estimated_box_papers_quantity"],
        estimated_box_from_turnout_quantity=None,
        observed_counted_quantity=None,
    )
    issued = sum(
        summary[key]
        for key in (
            "ordinary_issued_quantity",
            "replacement_issued_quantity",
            "tendered_issued_quantity",
        )
    )
    if (
        not stock.data["complete"]
        or any(value < 0 for value in summary.values() if value is not None)
        or summary["received_quantity"] != summary["never_issued_quantity"] + issued
        or observed["ordinary_unissued_quantity"]
        != (summary["ordinary_central_unissued_quantity"] + summary["ordinary_at_desks_quantity"])
        or summary["spoilt_original_quantity"] != summary["replacement_issued_quantity"]
    ):
        raise HTTPException(409, detail={"code": "accounting_balance_invalid"})
    turnout: dict[str, Any] = {
        "record": None,
        "approval_valid": False,
        "schedule_revision": schedule.revision,
    }
    if data.turnout_period_index is not None:
        selected = turnout_rows.get(data.turnout_period_index)
        if selected is None:
            raise HTTPException(404, detail={"code": "turnout_record_not_found"})
        if selected.revision != data.turnout_revision:
            raise HTTPException(409, detail={"code": "accounting_source_stale"})
        if selected.end_at > special.event_at:
            raise HTTPException(409, detail={"code": "accounting_turnout_time_invalid"})
        turnout.update(
            record=turnout_record_view(selected), approval_valid=selected.id in valid_turnout
        )
        if turnout["approval_valid"]:
            estimate = selected.derived_cumulative_end - summary["retrieved_unused_quantity"]
            if estimate < 0:
                raise HTTPException(409, detail={"code": "accounting_balance_invalid"})
            summary["estimated_box_from_turnout_quantity"] = estimate
    frozen: dict[str, Any] = jsonable_encoder(
        {
            "summary": summary,
            "stock_snapshot": snapshot_view(stock, station_id),
            "special_papers": special_paper_view(special, station_id),
            "turnout": turnout,
        }
    )
    return special.event_at, frozen


def sources_current(db: Session, row: AccountingRecord, election_id: int) -> bool:
    special = row.data["special_papers"]
    turnout = row.data["turnout"]["record"]
    selection = AccountingDraft(
        request_id=UUID(int=0),
        expected_revision=row.revision,
        special_paper_id=special["id"],
        special_paper_revision=special["revision"],
        turnout_period_index=turnout["period_index"] if turnout else None,
        turnout_revision=turnout["revision"] if turnout else None,
    )
    try:
        _, current = source_data(db, row.station_id, election_id, selection)
    except HTTPException:
        return False
    current["context"] = row.data.get("context", {})
    return current == row.data


def eligible_special_source(
    db: Session,
    station_id: int,
    election_id: int,
    special_id: int,
    revision: int,
) -> bool:
    selection = AccountingDraft(
        request_id=UUID(int=0),
        expected_revision=0,
        special_paper_id=special_id,
        special_paper_revision=revision,
    )
    try:
        source_data(db, station_id, election_id, selection)
    except HTTPException:
        return False
    return True


def record_view(db: Session, row: AccountingRecord) -> dict[str, Any]:
    from election.server.configuration_models import Constituency
    from election.server.station_models import PollingStation

    station = db.get(PollingStation, row.station_id)
    assert station is not None
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    current = accounting_record(db, row.station_id)
    source_current = sources_current(db, row, constituency.election_id)
    return {
        **row.data,
        "id": row.id,
        "station_id": row.station_id,
        "revision": row.revision,
        "status": row.status,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "notes": row.notes,
        "amendment_reason": row.amendment_reason,
        "submitted_at": as_utc(row.submitted_at),
        "submitted_by": row.submitted_by,
        "approved_at": as_utc(row.approved_at),
        "approved_by": row.approved_by,
        "source_current": source_current,
        "approval_valid": bool(
            current and current.id == row.id and source_current and row.status == "approved"
        ),
    }


def accounting_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/accounting", tags=["accounting"]
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        scope = accounting_scope(db, actor, station_id)
        schedule = locked_schedule(db, scope["election"]["id"])
        turnout = current_records(db, station_id)
        _, valid = approved_prefix(turnout, schedule, db)
        history = list(
            db.scalars(
                select(AccountingRecord)
                .where(
                    AccountingRecord.station_id == station_id,
                )
                .order_by(AccountingRecord.revision.desc())
                .with_for_update()
            )
        )
        views = [record_view(db, row) for row in history]
        special_options = [
            {
                **special_paper_view(row, station_id),
                "source_current": eligible_special_source(
                    db,
                    station_id,
                    scope["election"]["id"],
                    row.snapshot_id,
                    row.revision,
                ),
            }
            for row in current_special_papers(db, station_id, lock=True)
        ]
        return {
            **scope,
            "record": views[0] if views else None,
            "history": views,
            "special_options": special_options,
            "turnout_options": [
                {"record": turnout_record_view(row), "approval_valid": row.id in valid}
                for row in turnout.values()
            ],
            "server_time": as_utc(timestamp()),
        }

    @router.get("/revisions/{revision}")
    def revision(station_id: int, revision: int, db: Database, actor: Actor) -> dict[str, Any]:
        accounting_scope(db, actor, station_id)
        row = accounting_record(db, station_id, revision)
        if row is None:
            raise HTTPException(404, detail={"code": "accounting_not_found"})
        return record_view(db, row)

    def execute(
        station_id: int,
        action: str,
        data: AccountingCommand,
        db: Session,
        actor: Account,
    ) -> dict[str, Any]:
        role = "supervisor" if action == "approve" else "counting_officer"
        if actor.role != role:
            raise HTTPException(403, detail={"code": role + "_required"})
        scope = accounting_scope(db, actor, station_id, writable=True)
        if isinstance(data, AccountingApproval):
            password_hash = db.scalar(
                select(Account.password_hash).where(Account.id == actor.id).with_for_update()
            )
            if not verify_password(password_hash, data.password):
                raise HTTPException(401, detail={"code": "invalid_credentials"})
        digest = hashlib.sha256(
            json.dumps(
                {
                    "station_id": station_id,
                    "actor_id": actor.id,
                    "action": action,
                    "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        replay = db.scalar(
            select(AccountingRequest)
            .where(
                AccountingRequest.request_id == str(data.request_id),
            )
            .with_for_update()
        )
        if replay:
            if replay.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return replay.response
        current = accounting_record(db, station_id)
        if data.expected_revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        now = timestamp()
        if isinstance(data, AccountingDraft):
            if current and current.status != "draft" and not data.amendment_reason.strip():
                raise HTTPException(422, detail={"code": "accounting_reason_required"})
            event_at, frozen = source_data(db, station_id, scope["election"]["id"], data)
            frozen["context"] = scope
            if event_at > now:
                raise HTTPException(422, detail={"code": "event_time_in_future"})
            current = AccountingRecord(
                station_id=station_id,
                revision=data.expected_revision + 1,
                status="draft",
                event_at=event_at,
                entered_at=now,
                actor_id=actor.id,
                notes=data.notes,
                amendment_reason=data.amendment_reason,
                data=frozen,
            )
            db.add(current)
            db.flush()
        else:
            expected_status = "submitted" if action == "approve" else "draft"
            if current is None or current.status != expected_status:
                raise HTTPException(409, detail={"code": "accounting_state_conflict"})
            if not sources_current(db, current, scope["election"]["id"]):
                raise HTTPException(409, detail={"code": "accounting_source_stale"})
            if action == "submit":
                current.status, current.submitted_at, current.submitted_by = (
                    "submitted",
                    now,
                    actor.id,
                )
            else:
                current.status, current.approved_at, current.approved_by = "approved", now, actor.id
        result = record_view(db, current)
        db.add(
            AccountingRequest(
                request_id=str(data.request_id),
                station_id=station_id,
                actor_id=actor.id,
                digest=digest,
                response=result,
            )
        )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="accounting_" + action,
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "revision": current.revision,
                    "reason": current.amendment_reason,
                },
            )
        )
        db.commit()
        return result

    @router.put("")
    def save(station_id: int, data: AccountingDraft, db: Database, actor: Actor) -> dict[str, Any]:
        return execute(station_id, "save", data, db, actor)

    @router.post("/submit")
    def submit(
        station_id: int, data: AccountingCommand, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, "submit", data, db, actor)

    @router.post("/approve")
    def approve(
        station_id: int, data: AccountingApproval, db: Database, actor: Actor
    ) -> dict[str, Any]:
        return execute(station_id, "approve", data, db, actor)

    return router
