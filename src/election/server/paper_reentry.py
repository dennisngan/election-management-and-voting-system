"""Attach paper provenance inside an existing validated operational transaction."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.models import Account, AuditEvent
from election.server.outage_models import OutagePaperRecord, OutagePaperRevision, PaperReentry

PaperEntry = tuple[OutagePaperRecord, OutagePaperRevision] | None
RECEIPT_ADAPTER = TypeAdapter(dict[str, Any])


def guard_paper_entry(
    db: Session,
    actor: Account,
    station_id: int,
    paper_id: int | None,
    workflow: str,
    action: str,
    target: dict[str, int],
    request_id: UUID,
    *,
    event_at: datetime | None = None,
) -> PaperEntry:
    """Lock an exact pending paper identity after normal operational authorization."""
    if paper_id is None:
        return None
    paper = db.scalar(
        select(OutagePaperRecord)
        .where(
            OutagePaperRecord.id == paper_id,
            OutagePaperRecord.station_id == station_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if paper is None:
        raise HTTPException(404, detail={"code": "paper_record_not_found"})
    revision = db.scalar(
        select(OutagePaperRevision)
        .where(
            OutagePaperRevision.paper_id == paper.id,
        )
        .order_by(OutagePaperRevision.revision.desc())
        .limit(1)
        .with_for_update()
    )
    if revision is None:
        raise HTTPException(409, detail={"code": "paper_record_incomplete"})
    if (
        paper.workflow != workflow
        or revision.data.get("action") != action
        or revision.data.get("target") != target
    ):
        raise HTTPException(409, detail={"code": "paper_record_target_conflict"})
    if event_at is not None:
        from election.server.polling import as_utc

        normalized = event_at.astimezone(UTC) if event_at.tzinfo else event_at.replace(tzinfo=UTC)
        if revision.data.get("original_event_at") != as_utc(normalized):
            raise HTTPException(409, detail={"code": "paper_record_time_conflict"})
    prior = db.get(PaperReentry, paper.id, with_for_update=True)
    if prior is not None and (prior.request_id != str(request_id) or prior.actor_id != actor.id):
        raise HTTPException(409, detail={"code": "paper_record_already_entered"})
    receipt_owner = db.scalar(
        select(PaperReentry)
        .where(
            PaperReentry.workflow == workflow,
            PaperReentry.request_id == str(request_id),
        )
        .with_for_update()
    )
    if receipt_owner is not None and receipt_owner.paper_id != paper.id:
        raise HTTPException(409, detail={"code": "paper_request_already_linked"})
    return paper, revision


def finish_paper_entry(
    db: Session,
    actor: Account,
    entry: PaperEntry,
    request_id: UUID,
    record: dict[str, Any],
    now: datetime,
) -> None:
    """Persist the original receipt and paper link in the caller's effect commit."""
    if entry is None:
        return
    paper, revision = entry
    if db.get(PaperReentry, paper.id) is not None:
        return
    db.add(
        PaperReentry(
            paper_id=paper.id,
            paper_revision_id=revision.id,
            workflow=paper.workflow,
            request_id=str(request_id),
            actor_id=actor.id,
            entered_at=now,
            record=RECEIPT_ADAPTER.dump_python(record, mode="json"),
        )
    )
    db.add(
        AuditEvent(
            actor_id=actor.id,
            action="paper_record_reentered",
            occurred_at=now,
            details={
                "station_id": paper.station_id,
                "outage_id": paper.outage_id,
                "paper_id": paper.id,
                "paper_revision": revision.revision,
                "workflow": paper.workflow,
                "request_id": str(request_id),
            },
        )
    )
    db.flush()
