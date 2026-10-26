"""Resolve an existing committed workflow receipt for later paper linkage."""

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_round_models import CountRound, CountRoundRevision
from election.server.counting_scope_models import CountingScope
from election.server.models import Account
from election.server.outage_models import OutagePaperRecord, OutagePaperRevision
from election.server.request_outcomes import read_request_outcome


def _receipt_mismatch() -> HTTPException:
    return HTTPException(409, detail={"code": "paper_receipt_mismatch"})


def preview_existing_receipt(
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

    first_paper_entry_at = db.scalar(
        select(OutagePaperRevision.entered_at)
        .where(OutagePaperRevision.paper_id == paper.id)
        .order_by(OutagePaperRevision.revision.asc())
        .limit(1)
    )
    if first_paper_entry_at is None or round_revision.entered_at >= first_paper_entry_at:
        raise _receipt_mismatch()

    digest = hashlib.sha256(
        json.dumps(
            outcome,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {**outcome, "receipt_digest": digest}
