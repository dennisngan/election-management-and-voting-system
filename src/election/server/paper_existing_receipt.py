"""Resolve an existing committed workflow receipt for later paper linkage."""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.counting_round_models import CountRound, CountRoundRevision
from election.server.counting_scope_models import CountingScope
from election.server.models import Account
from election.server.outage_models import OutagePaperRecord, OutagePaperRevision
from election.server.paper_reentry import RECEIPT_ADAPTER
from election.server.polling import as_utc
from election.server.request_outcomes import read_request_outcome


def _receipt_mismatch() -> HTTPException:
    return HTTPException(409, detail={"code": "paper_receipt_mismatch"})


def _receipt_preview(
    db: Session,
    paper: OutagePaperRecord,
    outcome: dict[str, Any],
    original_entered_at: datetime,
) -> dict[str, Any]:
    """Attach a digest after the original effect precedes the paper registration."""
    first_paper_entry_at = db.scalar(
        select(OutagePaperRevision.entered_at)
        .where(OutagePaperRevision.paper_id == paper.id)
        .order_by(OutagePaperRevision.revision.asc())
        .limit(1)
    )
    if first_paper_entry_at is None or original_entered_at >= first_paper_entry_at:
        raise _receipt_mismatch()

    canonical_outcome = RECEIPT_ADAPTER.dump_python(outcome, mode="json")
    digest = hashlib.sha256(
        json.dumps(
            canonical_outcome,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {**outcome, "receipt_digest": digest}


def _count_receipt_preview(
    db: Session,
    actor: Account,
    station_id: int,
    paper: OutagePaperRecord,
    revision: OutagePaperRevision,
    original_request_id: UUID,
) -> dict[str, Any]:
    """Return the immutable original count receipt for a paper count submission."""
    if paper.workflow != "count" or revision.data.get("action") != "submit":
        raise HTTPException(409, detail={"code": "paper_receipt_workflow_unsupported"})

    outcome = read_request_outcome(db, actor, station_id, original_request_id, "count")
    if outcome.get("status") != "committed":
        raise HTTPException(404, detail={"code": "request_not_found"})

    record = outcome.get("record")
    target = revision.data.get("target")
    if (
        not isinstance(record, dict)
        or not isinstance(target, dict)
        or set(target) != {"scope_id", "round_id"}
        or type(target.get("scope_id")) is not int
        or type(target.get("round_id")) is not int
        or record.get("status") != "submitted"
        or type(record.get("id")) is not int
        or type(record.get("scope_id")) is not int
        or type(record.get("revision")) is not int
        or record.get("id") != target["round_id"]
        or record.get("scope_id") != target["scope_id"]
        or type(record.get("revision_id")) is not int
    ):
        raise _receipt_mismatch()

    round_revision = db.scalar(
        select(CountRoundRevision)
        .join(CountRound, CountRound.id == CountRoundRevision.round_id)
        .join(CountingScope, CountingScope.id == CountRound.scope_id)
        .where(
            CountRoundRevision.id == record["revision_id"],
            CountRoundRevision.round_id == target["round_id"],
            CountRoundRevision.status == "submitted",
            CountRound.id == target["round_id"],
            CountRound.scope_id == target["scope_id"],
            CountingScope.station_id == station_id,
        )
    )
    if round_revision is None or record["revision"] != round_revision.revision:
        raise _receipt_mismatch()

    return _receipt_preview(db, paper, outcome, round_revision.entered_at)


def _allocation_receipt_preview(
    db: Session,
    actor: Account,
    station_id: int,
    paper: OutagePaperRecord,
    revision: OutagePaperRevision,
    original_request_id: UUID,
) -> dict[str, Any]:
    outcome = read_request_outcome(
        db, actor, station_id, original_request_id, "allocation"
    )
    if outcome.get("status") != "committed":
        raise HTTPException(404, detail={"code": "request_not_found"})

    record = outcome.get("record")
    target = revision.data.get("target")
    counter = record.get("counter") if isinstance(record, dict) else None
    record_event_at = record.get("event_at") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or not isinstance(target, dict)
        or set(target) != {"counter_id"}
        or type(target.get("counter_id")) is not int
        or target["counter_id"] < 1
        or record.get("status") != "recorded"
        or type(record.get("id")) is not int
        or type(record.get("revision")) is not int
        or type(record.get("station_id")) is not int
        or record.get("station_id") != station_id
        or not isinstance(counter, dict)
        or type(counter.get("id")) is not int
        or counter.get("id") != target["counter_id"]
        or not isinstance(record_event_at, datetime)
    ):
        raise _receipt_mismatch()

    allocation_revision = db.scalar(
        select(StockAllocationRevision)
        .join(StockAllocation, StockAllocation.id == StockAllocationRevision.allocation_id)
        .where(
            StockAllocationRevision.request_id == str(original_request_id),
            StockAllocationRevision.actor_id == actor.id,
            StockAllocationRevision.revision == 1,
            StockAllocationRevision.allocation_id == record["id"],
            StockAllocationRevision.counter_id == target["counter_id"],
            StockAllocation.station_id == station_id,
        )
    )
    if (
        allocation_revision is None
        or allocation_revision.revision != record["revision"]
        or as_utc(record_event_at) != as_utc(allocation_revision.event_at)
        or revision.data.get("original_event_at") != as_utc(allocation_revision.event_at)
    ):
        raise _receipt_mismatch()

    return _receipt_preview(db, paper, outcome, allocation_revision.entered_at)


def preview_existing_receipt(
    db: Session,
    actor: Account,
    station_id: int,
    paper: OutagePaperRecord,
    revision: OutagePaperRevision,
    original_request_id: UUID,
) -> dict[str, Any]:
    """Return an immutable original supported-workflow receipt for paper linkage."""
    action = revision.data.get("action")
    if paper.workflow == "count" and action == "submit":
        return _count_receipt_preview(
            db, actor, station_id, paper, revision, original_request_id
        )
    if paper.workflow == "allocation" and action == "create":
        return _allocation_receipt_preview(
            db, actor, station_id, paper, revision, original_request_id
        )
    raise HTTPException(409, detail={"code": "paper_receipt_workflow_unsupported"})
