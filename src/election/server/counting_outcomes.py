"""Questionable-paper determination drafts preserve their original F1 observations."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.boxes import utc_time
from election.server.counting_round_models import CountRoundRequest, CountRoundRevision
from election.server.counting_rounds import (
    CandidateVote,
    InvalidPapers,
    latest_round_revision,
    round_at,
    round_context,
    round_view,
    selection_context,
)
from election.server.counting_totals import f2_summary
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc
from election.server.turnout_basis import turnout_scope


class F2Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    scope_revision: int = Field(strict=True, ge=1)
    event_at: AwareDatetime
    determination_started_at: AwareDatetime | None = None
    accepted_votes: list[CandidateVote] = Field(default_factory=list)
    rejected_papers: list[InvalidPapers] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    amendment_reason: str = Field(default="", max_length=2000)

    @field_validator("event_at", "determination_started_at")
    @classmethod
    def supported_time(cls, value: datetime | None) -> datetime | None:
        return utc_time(value) if value is not None else None

    @model_validator(mode="after")
    def distinct_outcomes(self) -> F2Draft:
        if len({row.candidate_id for row in self.accepted_votes}) != len(self.accepted_votes):
            raise ValueError("Enter each candidate once")
        if len({row.reason_id for row in self.rejected_papers}) != len(self.rejected_papers):
            raise ValueError("Enter each rejected-paper reason once")
        return self


def f2_basis(
    options: dict[str, Any], data: F2Draft, now: datetime, actor_id: int
) -> dict[str, Any]:
    candidates = {row["id"]: row for row in options["candidates"]}
    reasons = {row["id"]: row for row in options["f2_invalid_reasons"]}
    accepted = {row.candidate_id: row for row in data.accepted_votes}
    rejected = {row.reason_id: row for row in data.rejected_papers}
    if accepted.keys() - candidates.keys():
        raise HTTPException(422, detail={"code": "count_candidate_invalid"})
    if rejected.keys() - reasons.keys():
        raise HTTPException(422, detail={"code": "count_invalid_reason_invalid"})
    votes = []
    for identity, candidate in candidates.items():
        accepted_entry = accepted.get(identity)
        votes.append(
            {
                "candidate_id": identity,
                "candidate_revision": candidate["revision"],
                "constituency_id": candidate["constituency_id"],
                "ballot_number": candidate["ballot_number"],
                "name": candidate["name"],
                "quantity": accepted_entry.quantity if accepted_entry else None,
            }
        )
    papers = []
    for identity, reason in reasons.items():
        rejected_entry = rejected.get(identity)
        if rejected_entry and rejected_entry.reason_revision != reason["revision"]:
            raise HTTPException(409, detail={"code": "invalid_reason_revision_conflict"})
        quantity = rejected_entry.quantity if rejected_entry else None
        explanation = rejected_entry.explanation if rejected_entry else ""
        if quantity and reason["explanation_required"] and not explanation.strip():
            raise HTTPException(422, detail={"code": "invalid_reason_explanation_required"})
        papers.append(
            {
                "reason_id": identity,
                "reason_revision": reason["revision"],
                **{
                    key: reason[key]
                    for key in (
                        "code",
                        "stage",
                        "label_tc",
                        "label_sc",
                        "label_en",
                        "source_english",
                        "source_letter",
                        "reference_page",
                        "reference_printed_page",
                        "verified_source",
                        "translation_provenance",
                        "is_other",
                        "explanation_required",
                    )
                },
                "quantity": quantity,
                "explanation": explanation,
            }
        )
    return {
        "event_at": as_utc(data.event_at),
        "entered_at": as_utc(now),
        "actor_id": actor_id,
        "determination_started_at": as_utc(data.determination_started_at),
        "accepted_votes": votes,
        "rejected_papers": papers,
        "notes": data.notes,
        "amendment_reason": data.amendment_reason,
    }


def counting_outcomes_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/rounds",
        tags=["questionable-paper outcomes"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    def persist(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: F2Draft,
        db: Session,
        actor: Account,
        *,
        correction: bool = False,
    ) -> dict[str, Any]:
        if actor.role != "counting_officer":
            raise HTTPException(403, detail={"code": "counting_officer_required"})
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        turnout_scope(db, actor, station_id, writable=True)
        options = round_context(db, actor, station_id, scope_id)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "action": "amend-f2" if correction else "f2",
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round_id,
                    "actor_id": actor.id,
                    "data": data.model_dump(mode="json", exclude={"request_id"}),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        receipt = db.scalar(
            select(CountRoundRequest)
            .where(CountRoundRequest.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt:
            if receipt.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return receipt.response
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        if not options["scope"]["count_ready"]:
            raise HTTPException(409, detail={"code": "count_scope_not_ready"})
        round = round_at(db, scope_id, round_id)
        current = latest_round_revision(db, round.id)
        if current is None or current.revision != data.expected_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        view = round_view(db, round, current, options)
        if correction and not data.amendment_reason.strip():
            raise HTTPException(422, detail={"code": "count_amendment_reason_required"})
        if current.status != "draft" and not correction:
            raise HTTPException(409, detail={"code": "count_round_read_only"})
        if not view["source_current"]:
            raise HTTPException(409, detail={"code": "count_round_basis_stale"})
        if not current.data["f1_complete"]:
            raise HTTPException(409, detail={"code": "f1_incomplete"})
        now = timestamp()
        if data.event_at.replace(tzinfo=None) > now:
            raise HTTPException(422, detail={"code": "event_time_in_future"})
        if data.determination_started_at and data.determination_started_at > data.event_at:
            raise HTTPException(422, detail={"code": "determination_time_invalid"})
        f2 = f2_basis(options, data, now, actor.id)
        previous_f2 = current.data.get("f2")
        if (
            previous_f2
            and previous_f2["determination_started_at"] is not None
            and previous_f2["determination_started_at"] != f2["determination_started_at"]
            and not data.amendment_reason.strip()
        ):
            raise HTTPException(422, detail={"code": "determination_reason_required"})
        if (
            previous_f2
            and previous_f2["determination_started_at"] == f2["determination_started_at"]
        ):
            f2["determination_event"] = deepcopy(previous_f2.get("determination_event"))
        elif f2["determination_started_at"] is not None:
            f2["determination_event"] = {
                "origin_revision": data.expected_revision + 1,
                "event_at": f2["determination_started_at"],
                "entered_at": f2["entered_at"],
                "actor_id": actor.id,
                "amendment_reason": data.amendment_reason,
            }
        else:
            f2["determination_event"] = None
        observed = [row["quantity"] for row in f2["accepted_votes"] + f2["rejected_papers"]]
        known_total = sum(value for value in observed if value is not None)
        if known_total > current.data["questionable_quantity"]:
            raise HTTPException(422, detail={"code": "f2_outcomes_exceed_questionable"})
        if (
            all(value is not None for value in observed)
            and known_total != current.data["questionable_quantity"]
        ):
            raise HTTPException(422, detail={"code": "f2_outcomes_unbalanced"})
        frozen = deepcopy(current.data)
        if correction:
            for key in (
                "submitted_at", "submitted_by", "completed_at", "completion_event",
                "approved_at", "approved_by", "reviewed_revision", "reviewed_revision_id",
                "approved_physical_decisions",
            ):
                frozen.pop(key, None)
        frozen.update(
            f1_metadata={
                key: view[key]
                for key in ("event_at", "entered_at", "actor_id", "notes", "amendment_reason")
            },
            f1_blockers=deepcopy(current.data.get("f1_blockers", current.data["blockers"])),
            f2=f2,
        )
        frozen.update(f2_summary(frozen))
        row = CountRoundRevision(
            round_id=round.id,
            revision=data.expected_revision + 1,
            status="draft",
            event_at=data.event_at.replace(tzinfo=None),
            entered_at=now,
            actor_id=actor.id,
            notes=data.notes,
            amendment_reason=data.amendment_reason,
            data=frozen,
        )
        db.add(row)
        db.flush()
        if correction:
            options.update(selection_context(db, scope_id, options))
        result = round_view(db, round, row, options)
        db.add(
            CountRoundRequest(
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
                action="f2_corrected" if correction else "f2_draft_saved",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "revision": row.revision,
                    **(
                        {
                            "reason": data.amendment_reason,
                            "previous_revision": data.expected_revision,
                        } if correction else {}
                    ),
                },
            )
        )
        db.commit()
        return result

    @router.put("/{round_id}/f2")
    def save(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: F2Draft,
        db: Database,
        actor: Actor,
        response: Response,
    ) -> dict[str, Any]:
        return persist(station_id, scope_id, round_id, data, db, actor)

    @router.post("/{round_id}/amend-f2")
    def correct_f2(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: F2Draft,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        return persist(station_id, scope_id, round_id, data, db, actor, correction=True)

    return router
