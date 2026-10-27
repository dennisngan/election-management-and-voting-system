"""Revisioned application outages and paper-reentry reconciliation records."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation
from election.server.counting_round_models import CountRound
from election.server.counting_scope_models import CountingScope
from election.server.models import Account, AuditEvent
from election.server.outage_models import (
    ApplicationOutage,
    ApplicationOutageRevision,
    OutagePaperRecord,
    OutagePaperRevision,
    OutageReconciliation,
    OutageRequest,
    PaperReentry,
)
from election.server.paper_existing_receipt import preview_existing_receipt
from election.server.paper_reentry import finish_paper_entry, guard_paper_entry
from election.server.polling import as_utc
from election.server.reporting_periods import period_bounds
from election.server.security import verify_password
from election.server.station_models import IssuanceCounter
from election.server.stock import stock_scope
from election.server.turnout_basis import locked_schedule, turnout_scope

OutageKind = Literal["network", "backend", "database", "unknown"]
Workflow = Literal["count", "turnout", "allocation"]
OPERATIONAL_ROLES = frozenset({"polling_officer", "counting_officer"})


class OutageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class OutageDraft(OutageCommand):
    reference: str = Field(min_length=1, max_length=160)
    kind: OutageKind
    started_at: AwareDatetime
    ended_at: AwareDatetime
    notes: str = Field(default="", max_length=2000)

    @field_validator("reference")
    @classmethod
    def normalized_reference(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("An outage reference is required")
        return value

    @field_validator("started_at", "ended_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class OutageAmendment(OutageDraft):
    expected_revision: int = Field(strict=True, ge=1)
    amendment_reason: str = Field(min_length=1, max_length=2000)

    @field_validator("amendment_reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An amendment reason is required")
        return value


class PaperCommand(OutageCommand):
    expected_outage_revision: int = Field(strict=True, ge=1)
    paper_reference: str = Field(min_length=1, max_length=160)
    workflow: Workflow
    action: str = Field(min_length=1, max_length=32)
    original_event_at: AwareDatetime
    target: dict[str, Any]
    notes: str = Field(default="", max_length=2000)

    @field_validator("paper_reference")
    @classmethod
    def normalized_paper_reference(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A paper reference is required")
        return value

    @field_validator("original_event_at")
    @classmethod
    def utc_original_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class PaperAmendment(OutageCommand):
    expected_outage_revision: int = Field(strict=True, ge=1)
    expected_revision: int = Field(strict=True, ge=1)
    original_event_at: AwareDatetime
    target: dict[str, Any]
    notes: str = Field(default="", max_length=2000)
    amendment_reason: str = Field(min_length=1, max_length=2000)

    @field_validator("original_event_at")
    @classmethod
    def utc_original_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("amendment_reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An amendment reason is required")
        return value


class ExistingReceiptLink(OutageCommand):
    expected_outage_revision: int = Field(ge=1, strict=True)
    expected_paper_revision: int = Field(ge=1, strict=True)
    original_request_id: UUID
    expected_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonblank linkage reason is required")
        return value.strip()


class PaperRevisionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: int = Field(strict=True, gt=0)
    revision: int = Field(strict=True, ge=1)


class OutageApproval(OutageCommand):
    expected_revision: int = Field(strict=True, ge=1)
    expected_reconciliation_revision: int = Field(strict=True, ge=0)
    paper_revisions: list[PaperRevisionRef]
    password: str = Field(min_length=1, max_length=128, repr=False)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reconciliation reason is required")
        return value


def _stored_time(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(action: str, station_id: int, resource_id: int, actor_id: int, data: BaseModel) -> str:
    payload = data.model_dump(mode="json", exclude={"request_id", "password"})
    encoded = json.dumps(
        {
            "action": action,
            "station_id": station_id,
            "resource_id": resource_id,
            "actor_id": actor_id,
            "data": payload,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def latest_outage_revision(
    db: Session, outage_id: int, *, lock: bool = False
) -> ApplicationOutageRevision | None:
    query = (
        select(ApplicationOutageRevision)
        .where(ApplicationOutageRevision.outage_id == outage_id)
        .order_by(ApplicationOutageRevision.revision.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def latest_paper_revision(
    db: Session, paper_id: int, *, lock: bool = False
) -> OutagePaperRevision | None:
    query = (
        select(OutagePaperRevision)
        .where(OutagePaperRevision.paper_id == paper_id)
        .order_by(OutagePaperRevision.revision.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def outage_revision_view(row: ApplicationOutageRevision) -> dict[str, Any]:
    return {
        **row.data,
        "id": row.outage_id,
        "revision_id": row.id,
        "revision": row.revision,
        "actor_id": row.actor_id,
        "entered_at": as_utc(row.entered_at),
        "amendment_reason": row.amendment_reason,
    }


def _paper_history(db: Session, paper_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(OutagePaperRevision)
            .where(OutagePaperRevision.paper_id == paper_id)
            .order_by(OutagePaperRevision.revision.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return [
        {
            **row.data,
            "revision_id": row.id,
            "revision": row.revision,
            "actor_id": row.actor_id,
            "entered_at": as_utc(row.entered_at),
            "amendment_reason": row.amendment_reason,
        }
        for row in rows
    ]


def _existing_link_view(db: Session, paper_id: int, entry: PaperReentry) -> dict[str, Any] | None:
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "paper_existing_receipt_linked",
            AuditEvent.actor_id == entry.actor_id,
            AuditEvent.details["paper_id"].as_integer() == paper_id,
            AuditEvent.details["original_request_id"].as_string() == entry.request_id,
        ).order_by(AuditEvent.id.desc()).limit(1)
    )
    if event is None:
        return None
    return {
        "request_id": event.details["link_request_id"],
        "reason": event.details["reason"],
        "actor_id": event.actor_id,
        "linked_at": as_utc(event.occurred_at),
        "receipt_digest": event.details["receipt_digest"],
    }


def paper_record_view(db: Session, paper: OutagePaperRecord) -> dict[str, Any]:
    revision = latest_paper_revision(db, paper.id)
    if revision is None:
        raise HTTPException(409, detail={"code": "paper_revision_missing"})
    entry = _paper_entry_at(db, paper.id)
    data = revision.data
    entered = bool(entry and entry.paper_revision_id == revision.id)
    return {
        **data,
        "id": paper.id,
        "outage_id": paper.outage_id,
        "station_id": paper.station_id,
        "paper_reference": paper.paper_reference,
        "workflow": paper.workflow,
        "revision_id": revision.id,
        "revision": revision.revision,
        "actor_id": revision.actor_id,
        "entered_at": as_utc(revision.entered_at),
        "amendment_reason": revision.amendment_reason,
        "status": "entered" if entered else "pending",
        "reentry": (
            {
                "workflow": entry.workflow,
                "request_id": entry.request_id,
                "actor_id": entry.actor_id,
                "entered_at": as_utc(entry.entered_at),
                "paper_revision_id": entry.paper_revision_id,
                "record": entry.record,
                "link": _existing_link_view(db, paper.id, entry),
            }
            if entered and entry
            else None
        ),
        "history": _paper_history(db, paper.id),
    }


def _reconciliation_basis(
    outage_revision: ApplicationOutageRevision,
    papers: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(papers, key=lambda row: row["id"])
    return {
        "outage_revision_id": outage_revision.id,
        "outage_revision": outage_revision.revision,
        "paper_revisions": [
            {
                "paper_id": paper["id"],
                "revision": paper["revision"],
            }
            for paper in ordered
        ],
        "paper_entries": [
            {
                "paper_id": paper["id"],
                "paper_revision_id": paper["revision_id"],
                "request_id": (paper.get("reentry") or {}).get("request_id"),
                "actor_id": (paper.get("reentry") or {}).get("actor_id"),
                "entered_at": (paper.get("reentry") or {}).get("entered_at"),
            }
            for paper in ordered
        ],
    }


def _reconciliation_digest(
    outage_revision: ApplicationOutageRevision,
    papers: list[dict[str, Any]],
) -> str:
    basis = _reconciliation_basis(outage_revision, papers)
    return hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def outage_view(
    db: Session,
    outage: ApplicationOutage,
    revision: ApplicationOutageRevision | None = None,
) -> dict[str, Any]:
    latest = revision or latest_outage_revision(db, outage.id)
    if latest is None:
        raise HTTPException(409, detail={"code": "outage_revision_missing"})
    papers = list(
        db.scalars(
            select(OutagePaperRecord)
            .where(OutagePaperRecord.outage_id == outage.id)
            .order_by(OutagePaperRecord.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    paper_views = [paper_record_view(db, paper) for paper in papers]
    reconciliation_rows = list(
        db.scalars(
            select(OutageReconciliation)
            .where(OutageReconciliation.outage_id == outage.id)
            .order_by(OutageReconciliation.revision.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    current_digest = _reconciliation_digest(latest, paper_views)
    all_entered = bool(paper_views) and all(row["status"] == "entered" for row in paper_views)
    reconciliation_history = [
        {
            "id": row.id,
            "revision": row.revision,
            "actor_id": row.actor_id,
            "accepted_at": as_utc(row.accepted_at),
            "reason": row.reason,
            "basis_digest": row.basis_digest,
            "basis": row.data,
            "is_current": index == 0,
            "valid": bool(index == 0 and all_entered and row.basis_digest == current_digest),
        }
        for index, row in enumerate(reconciliation_rows)
    ]
    current_reconciliation = reconciliation_history[0] if reconciliation_history else None
    return {
        **outage_revision_view(latest),
        "station_id": outage.station_id,
        "paper_records": paper_views,
        "reconciled": bool(current_reconciliation and current_reconciliation["valid"]),
        "reconciliation": current_reconciliation,
        "reconciliation_history": reconciliation_history,
    }


def _history(db: Session, outage_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(ApplicationOutageRevision)
            .where(ApplicationOutageRevision.outage_id == outage_id)
            .order_by(ApplicationOutageRevision.revision.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return [outage_revision_view(row) for row in rows]


def _get_outage(db: Session, station_id: int, outage_id: int, *, lock: bool) -> ApplicationOutage:
    query = select(ApplicationOutage).where(
        ApplicationOutage.id == outage_id,
        ApplicationOutage.station_id == station_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    outage = db.scalar(query)
    if outage is None:
        raise HTTPException(404, detail={"code": "outage_not_found"})
    return outage


def _receipt(db: Session, request_id: UUID) -> OutageRequest | None:
    return db.scalar(
        select(OutageRequest)
        .where(OutageRequest.request_id == str(request_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _replay(receipt: OutageRequest, digest: str) -> dict[str, Any]:
    if receipt.digest != digest:
        raise HTTPException(409, detail={"code": "request_conflict"})
    return receipt.response


def _save_receipt(
    db: Session,
    request_id: UUID,
    station_id: int,
    actor_id: int,
    digest: str,
    response: dict[str, Any],
) -> None:
    db.add(
        OutageRequest(
            request_id=str(request_id),
            station_id=station_id,
            actor_id=actor_id,
            digest=digest,
            response=response,
        )
    )


def _check_operational_role(actor: Account, workflow: str | None = None) -> None:
    if workflow == "count" and actor.role != "counting_officer":
        raise HTTPException(403, detail={"code": "counting_officer_required"})
    if workflow in ("turnout", "allocation") and actor.role != "polling_officer":
        raise HTTPException(403, detail={"code": "polling_officer_required"})
    if workflow is None and actor.role not in OPERATIONAL_ROLES:
        raise HTTPException(403, detail={"code": "operational_role_required"})


def _outage_data(data: OutageDraft) -> dict[str, Any]:
    return {
        "reference": data.reference,
        "kind": data.kind,
        "started_at": _time_text(data.started_at),
        "ended_at": _time_text(data.ended_at),
        "notes": data.notes,
    }


def _validate_outage_times(data: OutageDraft, now: datetime) -> None:
    start, end = _stored_time(data.started_at), _stored_time(data.ended_at)
    if end > now:
        raise HTTPException(422, detail={"code": "outage_time_in_future"})
    if start > end:
        raise HTTPException(422, detail={"code": "outage_interval_invalid"})


def _validate_original_time(value: datetime, now: datetime) -> None:
    if _stored_time(value) > now:
        raise HTTPException(422, detail={"code": "paper_time_in_future"})



def _paper_entry_at(db: Session, paper_id: int) -> PaperReentry | None:
    return db.scalar(
        select(PaperReentry).where(PaperReentry.paper_id == paper_id)
        .with_for_update().execution_options(populate_existing=True)
    )


def _validate_paper_target(
    db: Session, actor: Account, station_id: int, workflow: str,
    action: str, target: dict[str, Any],
) -> dict[str, int]:
    if workflow == "count":
        return _validate_count_target(db, station_id, action, target)
    if workflow == "turnout":
        if action not in {"save", "submit"} or set(target) != {"period_index"}:
            raise HTTPException(422, detail={"code": "paper_target_invalid"})
        index = target["period_index"]
        if type(index) is not int or index < 1:
            raise HTTPException(422, detail={"code": "paper_target_invalid"})
        scope = stock_scope(db, actor, station_id)
        schedule = locked_schedule(db, scope["election"]["id"])
        try:
            period_bounds(schedule, index)
        except IndexError:
            raise HTTPException(422, detail={"code": "paper_target_invalid"}) from None
        return {"period_index": index}
    keys = {"counter_id"} if action == "create" else {"counter_id", "allocation_id"}
    if workflow != "allocation" or action not in {"create", "amend"} or set(target) != keys:
        raise HTTPException(422, detail={"code": "paper_target_invalid"})
    if any(type(value) is not int or value < 1 for value in target.values()):
        raise HTTPException(422, detail={"code": "paper_target_invalid"})
    counter = db.scalar(
        select(IssuanceCounter).where(
            IssuanceCounter.id == target["counter_id"], IssuanceCounter.station_id == station_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if counter is None:
        raise HTTPException(404, detail={"code": "paper_target_not_found"})
    if action == "amend":
        allocation = db.scalar(
            select(StockAllocation).where(
                StockAllocation.id == target["allocation_id"],
                StockAllocation.station_id == station_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if allocation is None:
            raise HTTPException(404, detail={"code": "paper_target_not_found"})
    return {key: target[key] for key in keys}


def _validate_count_target(
    db: Session, station_id: int, action: str, target: dict[str, Any]
) -> dict[str, int]:
    if action != "submit" or set(target) != {"scope_id", "round_id"}:
        raise HTTPException(422, detail={"code": "paper_target_invalid"})
    scope_id, round_id = target.get("scope_id"), target.get("round_id")
    if type(scope_id) is not int or scope_id < 1 or type(round_id) is not int or round_id < 1:
        raise HTTPException(422, detail={"code": "paper_target_invalid"})
    scope = db.scalar(
        select(CountingScope)
        .where(CountingScope.id == scope_id, CountingScope.station_id == station_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if scope is None:
        raise HTTPException(404, detail={"code": "paper_target_not_found"})
    count_round = db.scalar(
        select(CountRound)
        .where(CountRound.id == round_id, CountRound.scope_id == scope_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if count_round is None:
        raise HTTPException(404, detail={"code": "paper_target_not_found"})
    return {"scope_id": scope_id, "round_id": round_id}


def _paper_data(
    *,
    paper_reference: str,
    workflow: str,
    action: str,
    outage_revision: int,
    original_event_at: datetime,
    target: dict[str, int],
    notes: str,
) -> dict[str, Any]:
    return {
        "paper_reference": paper_reference,
        "workflow": workflow,
        "action": action,
        "outage_revision": outage_revision,
        "original_event_at": _time_text(original_event_at),
        "target": target,
        "notes": notes,
    }


def _paper_ref_list(papers: list[PaperRevisionRef]) -> list[dict[str, int]]:
    return sorted((row.model_dump() for row in papers), key=lambda row: row["paper_id"])


def read_outage_snapshot(
    db: Session, actor: Account, station_id: int, outage_id: int,
) -> dict[str, Any]:
    """Read one assigned station's immutable outage and paper history."""
    stock_scope(db, actor, station_id)
    outage = _get_outage(db, station_id, outage_id, lock=False)
    # Match writers: acquire the revision before any paper/history locks.
    revision = latest_outage_revision(db, outage.id, lock=True)
    return {"record": outage_view(db, outage, revision), "history": _history(db, outage_id)}


def outage_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/outages", tags=["Application outages"]
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def list_outages(station_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        outages = list(
            db.scalars(
                select(ApplicationOutage)
                .where(ApplicationOutage.station_id == station_id)
                .order_by(ApplicationOutage.id.desc())
            )
        )
        return {"outages": [outage_view(db, row) for row in outages]}

    @router.post("", status_code=201)
    def create_outage(
        station_id: int,
        data: OutageDraft,
        db: Database,
        actor: Actor,
        response: Response,
    ) -> dict[str, Any]:
        _check_operational_role(actor)
        turnout_scope(db, actor, station_id, writable=True)
        now = timestamp()
        _validate_outage_times(data, now)
        digest = _digest("outage_create", station_id, 0, actor.id, data)
        receipt = _receipt(db, data.request_id)
        if receipt:
            response.status_code = 200
            return _replay(receipt, digest)
        outage = ApplicationOutage(station_id=station_id)
        db.add(outage)
        db.flush()
        revision = ApplicationOutageRevision(
            outage_id=outage.id,
            revision=1,
            actor_id=actor.id,
            entered_at=now,
            amendment_reason="",
            data=_outage_data(data),
        )
        db.add(revision)
        db.flush()
        result = outage_view(db, outage, revision)
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="application_outage_created",
                occurred_at=now,
                details={"station_id": station_id, "outage_id": outage.id, "revision": 1},
            )
        )
        db.commit()
        return result

    @router.get("/{outage_id}")
    def read_outage(station_id: int, outage_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        return read_outage_snapshot(db, actor, station_id, outage_id)

    @router.put("/{outage_id}")
    def amend_outage(
        station_id: int,
        outage_id: int,
        data: OutageAmendment,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        _check_operational_role(actor)
        turnout_scope(db, actor, station_id, writable=True)
        now = timestamp()
        _validate_outage_times(data, now)
        digest = _digest("outage_amend", station_id, outage_id, actor.id, data)
        receipt = _receipt(db, data.request_id)
        if receipt:
            return _replay(receipt, digest)
        outage = _get_outage(db, station_id, outage_id, lock=True)
        current = latest_outage_revision(db, outage.id, lock=True)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        row = ApplicationOutageRevision(
            outage_id=outage.id,
            revision=current.revision + 1,
            actor_id=actor.id,
            entered_at=now,
            amendment_reason=data.amendment_reason,
            data=_outage_data(data),
        )
        db.add(row)
        db.flush()
        result = outage_view(db, outage, row)
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="application_outage_amended",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "outage_id": outage.id,
                    "previous_revision": current.revision,
                    "revision": row.revision,
                    "reason": data.amendment_reason,
                },
            )
        )
        db.commit()
        return result

    @router.post("/{outage_id}/paper-records", status_code=201)
    def create_paper(
        station_id: int,
        outage_id: int,
        data: PaperCommand,
        db: Database,
        actor: Actor,
        response: Response,
    ) -> dict[str, Any]:
        _check_operational_role(actor, data.workflow)
        turnout_scope(db, actor, station_id, writable=True)
        now = timestamp()
        _validate_original_time(data.original_event_at, now)
        target = _validate_paper_target(
            db, actor, station_id, data.workflow, data.action, data.target
        )
        digest = _digest("paper_create", station_id, outage_id, actor.id, data)
        receipt = _receipt(db, data.request_id)
        if receipt:
            response.status_code = 200
            return _replay(receipt, digest)
        outage = _get_outage(db, station_id, outage_id, lock=True)
        outage_revision = latest_outage_revision(db, outage_id, lock=True)
        if outage_revision is None or outage_revision.revision != data.expected_outage_revision:
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        existing = db.scalar(
            select(OutagePaperRecord)
            .where(
                OutagePaperRecord.station_id == station_id,
                OutagePaperRecord.workflow == data.workflow,
                OutagePaperRecord.paper_reference == data.paper_reference,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            raise HTTPException(409, detail={"code": "paper_reference_conflict"})
        paper = OutagePaperRecord(
            outage_id=outage.id,
            station_id=station_id,
            workflow=data.workflow,
            paper_reference=data.paper_reference,
        )
        db.add(paper)
        db.flush()
        revision = OutagePaperRevision(
            paper_id=paper.id,
            revision=1,
            actor_id=actor.id,
            entered_at=now,
            amendment_reason="",
            data=_paper_data(
                paper_reference=paper.paper_reference,
                workflow=paper.workflow,
                action=data.action,
                outage_revision=outage_revision.revision,
                original_event_at=data.original_event_at,
                target=target,
                notes=data.notes,
            ),
        )
        db.add(revision)
        db.flush()
        result = paper_record_view(db, paper)
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="outage_paper_registered",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "outage_id": outage.id,
                    "paper_id": paper.id,
                    "paper_reference": paper.paper_reference,
                    "workflow": paper.workflow,
                    "action": data.action,
                },
            )
        )
        db.commit()
        return result

    @router.put("/{outage_id}/paper-records/{paper_id}")
    def amend_paper(
        station_id: int,
        outage_id: int,
        paper_id: int,
        data: PaperAmendment,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        _check_operational_role(actor)
        turnout_scope(db, actor, station_id, writable=True)
        now = timestamp()
        _validate_original_time(data.original_event_at, now)
        digest = _digest("paper_amend", station_id, paper_id, actor.id, data)
        receipt = _receipt(db, data.request_id)
        if receipt:
            replay = _replay(receipt, digest)
            if replay.get("outage_id") != outage_id:
                raise HTTPException(404, detail={"code": "outage_paper_not_found"})
            _check_operational_role(actor, replay["workflow"])
            return replay
        outage = _get_outage(db, station_id, outage_id, lock=True)
        outage_revision = latest_outage_revision(db, outage.id, lock=True)
        if outage_revision is None or outage_revision.revision != data.expected_outage_revision:
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        paper = db.scalar(
            select(OutagePaperRecord)
            .where(
                OutagePaperRecord.id == paper_id,
                OutagePaperRecord.outage_id == outage.id,
                OutagePaperRecord.station_id == station_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if paper is None:
            raise HTTPException(404, detail={"code": "outage_paper_not_found"})
        _check_operational_role(actor, paper.workflow)
        if _paper_entry_at(db, paper.id) is not None:
            raise HTTPException(409, detail={"code": "paper_already_entered"})
        current = latest_paper_revision(db, paper.id, lock=True)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "paper_revision_conflict"})
        target = _validate_paper_target(
            db, actor, station_id, paper.workflow, current.data["action"], data.target
        )
        row = OutagePaperRevision(
            paper_id=paper.id,
            revision=current.revision + 1,
            actor_id=actor.id,
            entered_at=now,
            amendment_reason=data.amendment_reason,
            data=_paper_data(
                paper_reference=paper.paper_reference,
                workflow=paper.workflow,
                action=current.data["action"],
                outage_revision=outage_revision.revision,
                original_event_at=data.original_event_at,
                target=target,
                notes=data.notes,
            ),
        )
        db.add(row)
        db.flush()
        result = paper_record_view(db, paper)
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="outage_paper_corrected",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "outage_id": outage.id,
                    "paper_id": paper.id,
                    "previous_revision": current.revision,
                    "revision": row.revision,
                    "reason": data.amendment_reason,
                },
            )
        )
        db.commit()
        return result

    def existing_receipt_paper(
        db: Session, actor: Account, station_id: int, outage_id: int,
        paper_id: int, *, lock: bool,
    ) -> tuple[OutagePaperRecord, OutagePaperRevision]:
        outage = _get_outage(db, station_id, outage_id, lock=lock)
        query = select(OutagePaperRecord).where(
            OutagePaperRecord.id == paper_id,
            OutagePaperRecord.outage_id == outage.id,
            OutagePaperRecord.station_id == station_id,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        paper = db.scalar(query)
        if paper is None:
            raise HTTPException(404, detail={"code": "outage_paper_not_found"})
        _check_operational_role(actor, paper.workflow)
        revision = latest_paper_revision(db, paper.id, lock=lock)
        if revision is None:
            raise HTTPException(409, detail={"code": "paper_revision_conflict"})
        return paper, revision

    @router.get("/{outage_id}/paper-records/{paper_id}/receipt")
    def preview_receipt(
        station_id: int, outage_id: int, paper_id: int, request_id: UUID,
        db: Database, actor: Actor,
    ) -> dict[str, Any]:
        _check_operational_role(actor)
        stock_scope(db, actor, station_id)
        paper, revision = existing_receipt_paper(
            db, actor, station_id, outage_id, paper_id, lock=False,
        )
        return preview_existing_receipt(db, actor, station_id, paper, revision, request_id)

    @router.post("/{outage_id}/paper-records/{paper_id}/link-receipt")
    def link_receipt(
        station_id: int, outage_id: int, paper_id: int, data: ExistingReceiptLink,
        db: Database, actor: Actor,
    ) -> dict[str, Any]:
        _check_operational_role(actor)
        turnout_scope(db, actor, station_id, writable=True)
        digest = _digest(f"paper_link_receipt:{outage_id}", station_id, paper_id, actor.id, data)
        previous = _receipt(db, data.request_id)
        if previous:
            replay = _replay(previous, digest)
            _check_operational_role(actor, replay["workflow"])
            return replay
        outage = _get_outage(db, station_id, outage_id, lock=True)
        outage_revision = latest_outage_revision(db, outage.id, lock=True)
        if outage_revision is None or outage_revision.revision != data.expected_outage_revision:
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        paper, revision = existing_receipt_paper(
            db, actor, station_id, outage_id, paper_id, lock=True,
        )
        if revision.revision != data.expected_paper_revision:
            raise HTTPException(409, detail={"code": "paper_revision_conflict"})
        checked = preview_existing_receipt(
            db, actor, station_id, paper, revision, data.original_request_id,
        )
        if checked["receipt_digest"] != data.expected_receipt_digest:
            raise HTTPException(409, detail={"code": "paper_receipt_mismatch"})
        if _paper_entry_at(db, paper.id) is not None:
            raise HTTPException(409, detail={"code": "paper_already_entered"})
        entry = guard_paper_entry(
            db, actor, station_id, paper.id, paper.workflow, revision.data["action"],
            revision.data["target"], data.original_request_id,
        )
        now = timestamp()
        finish_paper_entry(db, actor, entry, data.original_request_id, checked["record"], now)
        db.add(AuditEvent(
            actor_id=actor.id, action="paper_existing_receipt_linked", occurred_at=now,
            details={
                "station_id": station_id, "outage_id": outage_id, "paper_id": paper_id,
                "paper_revision": revision.revision, "workflow": paper.workflow,
                "original_request_id": str(data.original_request_id),
                "link_request_id": str(data.request_id), "reason": data.reason,
                "receipt_digest": checked["receipt_digest"],
            },
        ))
        db.flush()
        result = paper_record_view(db, paper)
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.commit()
        return result

    @router.post("/{outage_id}/approve")
    def approve_outage(
        station_id: int,
        outage_id: int,
        data: OutageApproval,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        turnout_scope(db, actor, station_id, writable=True)
        password_hash = db.scalar(
            select(Account.password_hash).where(Account.id == actor.id).with_for_update()
        )
        if not verify_password(password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        if not data.reason.strip():
            raise HTTPException(422, detail={"code": "outage_reconciliation_reason_required"})
        digest = _digest("outage_approve", station_id, outage_id, actor.id, data)
        receipt = _receipt(db, data.request_id)
        if receipt:
            return _replay(receipt, digest)
        outage = _get_outage(db, station_id, outage_id, lock=True)
        outage_revision = latest_outage_revision(db, outage.id, lock=True)
        if outage_revision is None or outage_revision.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        papers = list(
            db.scalars(
                select(OutagePaperRecord)
                .where(OutagePaperRecord.outage_id == outage.id)
                .order_by(OutagePaperRecord.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        views = [paper_record_view(db, paper) for paper in papers]
        supplied = _paper_ref_list(data.paper_revisions)
        expected = sorted(
            ({"paper_id": row["id"], "revision": row["revision"]} for row in views),
            key=lambda row: row["paper_id"],
        )
        if not views:
            raise HTTPException(409, detail={"code": "outage_paper_records_missing"})
        if len(supplied) != len({row["paper_id"] for row in supplied}) or supplied != expected:
            raise HTTPException(409, detail={"code": "outage_paper_revision_conflict"})
        if any(row["status"] != "entered" for row in views):
            raise HTTPException(409, detail={"code": "outage_papers_pending"})
        current_reconciliation = db.scalar(
            select(OutageReconciliation)
            .where(OutageReconciliation.outage_id == outage.id)
            .order_by(OutageReconciliation.revision.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current_revision = current_reconciliation.revision if current_reconciliation else 0
        if current_revision != data.expected_reconciliation_revision:
            raise HTTPException(409, detail={"code": "outage_reconciliation_revision_conflict"})
        now = timestamp()
        basis = _reconciliation_basis(outage_revision, views)
        basis_digest = hashlib.sha256(
            json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row = OutageReconciliation(
            outage_id=outage.id,
            revision=current_revision + 1,
            actor_id=actor.id,
            accepted_at=now,
            reason=data.reason,
            basis_digest=basis_digest,
            data=basis,
        )
        db.add(row)
        db.flush()
        result = {"record": outage_view(db, outage), "history": _history(db, outage.id)}
        _save_receipt(db, data.request_id, station_id, actor.id, digest, result)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="application_outage_reconciled",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "outage_id": outage.id,
                    "revision": row.revision,
                    "basis_digest": basis_digest,
                    "reason": data.reason,
                },
            )
        )
        db.commit()
        return result

    return router
