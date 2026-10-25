"""F1 draft observations bound to one prepared received-box scope and count round."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.boxes import utc_time
from election.server.configuration_models import Candidate
from election.server.counting_round_models import (
    CountRound,
    CountRoundRequest,
    CountRoundRevision,
    CountRoundSelection,
)
from election.server.counting_scopes import scope_at, scope_options
from election.server.counting_totals import physical_approval_blockers, physical_comparisons
from election.server.invalid_ballot_reasons import invalid_reason_rows
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc
from election.server.turnout_basis import turnout_scope

Quantity = Annotated[int, Field(strict=True, ge=0)]


class CandidateVote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: int = Field(strict=True, gt=0)
    quantity: Quantity | None = None


class InvalidPapers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_id: int = Field(strict=True, gt=0)
    reason_revision: int = Field(strict=True, ge=1)
    quantity: Quantity | None = None
    explanation: str = Field(default="", max_length=2000)


class F1Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    scope_revision: int = Field(strict=True, ge=1)
    event_at: AwareDatetime
    candidate_votes: list[CandidateVote] = Field(default_factory=list)
    invalid_papers: list[InvalidPapers] = Field(default_factory=list)
    questionable_quantity: Quantity | None = None
    actual_counted_quantity: Quantity | None = None
    notes: str = Field(default="", max_length=2000)
    amendment_reason: str = Field(default="", max_length=2000)
    discard_f2: bool = Field(default=False, strict=True)

    @field_validator("event_at")
    @classmethod
    def supported_time(cls, value: datetime) -> datetime:
        return utc_time(value)

    @model_validator(mode="after")
    def distinct_rows(self) -> F1Draft:
        if len({row.candidate_id for row in self.candidate_votes}) != len(self.candidate_votes):
            raise ValueError("Enter each candidate once")
        if len({row.reason_id for row in self.invalid_papers}) != len(self.invalid_papers):
            raise ValueError("Enter each invalid reason once")
        return self


def latest_round_revision(db: Session, round_id: int) -> CountRoundRevision | None:
    return db.scalar(
        select(CountRoundRevision)
        .where(
            CountRoundRevision.round_id == round_id,
        )
        .order_by(CountRoundRevision.revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def round_at(db: Session, scope_id: int, round_id: int) -> CountRound:
    row = db.scalar(
        select(CountRound)
        .where(
            CountRound.id == round_id,
            CountRound.scope_id == scope_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, detail={"code": "count_round_not_found"})
    return row


def round_context(
    db: Session,
    actor: Account,
    station_id: int,
    scope_id: int,
) -> dict[str, Any]:
    options = scope_options(db, actor, station_id)
    scope_at(db, station_id, scope_id)
    scope = next(row for row in options["scopes"] if row["id"] == scope_id)
    candidates = list(
        db.scalars(
            select(Candidate)
            .where(
                Candidate.constituency_id == options["context"]["constituency"]["id"],
            )
            .order_by(Candidate.ballot_number, Candidate.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    result: dict[str, Any] = {
        "context": options["context"],
        "scope": scope,
        "candidates": [
            {
                "id": row.id,
                "constituency_id": row.constituency_id,
                "ballot_number": row.ballot_number,
                "name": row.name,
                "revision": row.revision,
            }
            for row in candidates
        ],
        "invalid_reasons": [
            row
            for row in invalid_reason_rows(
                db,
                options["context"]["election"]["id"],
            )
            if row["stage"] == "f1" and row["enabled"]
        ],
        "selection": None,
        "f2_invalid_reasons": [
            row
            for row in invalid_reason_rows(db, options["context"]["election"]["id"])
            if row["stage"] == "f2" and row["enabled"]
        ],
    }
    result.update(selection_context(db, scope_id, result))
    return result


def round_view(
    db: Session,
    round: CountRound,
    row: CountRoundRevision,
    options: dict[str, Any],
) -> dict[str, Any]:
    head = latest_round_revision(db, round.id)
    candidates = {candidate["id"]: candidate for candidate in options["candidates"]}
    frozen = row.data["candidate_votes"]
    candidate_current = len(candidates) == len(frozen) and all(
        vote["candidate_id"] in candidates
        and candidates[vote["candidate_id"]]["revision"] == vote["candidate_revision"]
        for vote in frozen
    )
    source_current = bool(
        options["scope"]["revision"] == row.data["scope_revision"]
        and options["scope"]["count_ready"]
        and candidate_current
    )
    blockers = list(row.data["blockers"])
    if not source_current:
        blockers.append({"code": "count_round_basis_stale"})
    approval_blockers = [*blockers, *physical_approval_blockers(row.data)]
    if not row.data.get("count_inputs_complete"):
        approval_blockers.append({"code": "count_inputs_incomplete"})
    return {
        **row.data,
        "id": round.id,
        "round_number": round.round_number,
        "scope_id": round.scope_id,
        "revision_id": row.id,
        "revision": row.revision,
        "status": row.status,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "notes": row.notes,
        "amendment_reason": row.amendment_reason,
        "is_current": bool(head and head.id == row.id),
        "source_current": source_current,
        "blockers": blockers,
        "f2": row.data.get("f2"),
        "f2_complete": row.data.get("f2_complete", False),
        "count_inputs_complete": row.data.get("count_inputs_complete", False),
        "count_complete": row.data.get("completed_at") is not None,
        "physical_comparisons": row.data.get(
            "physical_comparisons", physical_comparisons(row.data)
        ),
        "completed_at": row.data.get("completed_at"),
        "approval_blockers": approval_blockers,
        "approval_valid": bool(
            row.status == "approved" and head and head.id == row.id and not approval_blockers
        ),
        "selected": bool(
            options.get("selection")
            and options["selection"]["valid"]
            and options["selection"]["round_revision_id"] == row.id
        ),
        "selection": options.get("selection"),
        "selection_history": options.get("selection_history", []),
        "revision_event_at": as_utc(row.event_at),
        "revision_entered_at": as_utc(row.entered_at),
        "revision_actor_id": row.actor_id,
        "revision_notes": row.notes,
        "revision_amendment_reason": row.amendment_reason,
        **row.data.get("f1_metadata", {}),
    }


def selection_context(db: Session, scope_id: int, options: dict[str, Any]) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(CountRoundSelection)
            .where(CountRoundSelection.scope_id == scope_id)
            .order_by(CountRoundSelection.revision.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    history = []
    for index, pointer in enumerate(rows):
        target = db.scalar(
            select(CountRoundRevision)
            .where(CountRoundRevision.id == pointer.round_revision_id)
            .with_for_update()
        )
        assert target is not None
        round = round_at(db, scope_id, target.round_id)
        target_view = round_view(db, round, target, {**options, "selection": None})
        history.append(
            {
                "id": pointer.id,
                "revision": pointer.revision,
                "scope_id": scope_id,
                "round_id": round.id,
                "round_number": round.round_number,
                "round_revision": target.revision,
                "round_revision_id": target.id,
                "scope_revision": target.data["scope_revision"],
                "selected_at": as_utc(pointer.selected_at),
                "actor_id": pointer.actor_id,
                "is_current": index == 0,
                "valid": bool(index == 0 and target_view["approval_valid"]),
            }
        )
    return {"selection": history[0] if history else None, "selection_history": history}


def f1_basis(options: dict[str, Any], data: F1Draft) -> dict[str, Any]:
    candidates = {row["id"]: row for row in options["candidates"]}
    reasons = {row["id"]: row for row in options["invalid_reasons"]}
    votes = {row.candidate_id: row for row in data.candidate_votes}
    invalid = {row.reason_id: row for row in data.invalid_papers}
    if votes.keys() - candidates.keys():
        raise HTTPException(422, detail={"code": "count_candidate_invalid"})
    if invalid.keys() - reasons.keys():
        raise HTTPException(422, detail={"code": "count_invalid_reason_invalid"})
    blockers: list[dict[str, Any]] = []
    candidate_rows = []
    for candidate in options["candidates"]:
        entered = votes.get(candidate["id"])
        quantity = entered.quantity if entered else None
        if quantity is None:
            blockers.append({"code": "f1_candidate_missing", "candidate_id": candidate["id"]})
        candidate_rows.append(
            {
                "candidate_id": candidate["id"],
                "candidate_revision": candidate["revision"],
                "constituency_id": candidate["constituency_id"],
                "ballot_number": candidate["ballot_number"],
                "name": candidate["name"],
                "quantity": quantity,
            }
        )
    reason_rows = []
    for reason in options["invalid_reasons"]:
        entry = invalid.get(reason["id"])
        if entry and entry.reason_revision != reason["revision"]:
            raise HTTPException(409, detail={"code": "invalid_reason_revision_conflict"})
        quantity = entry.quantity if entry else None
        explanation = entry.explanation if entry else ""
        if quantity is None:
            blockers.append({"code": "f1_invalid_reason_missing", "reason_id": reason["id"]})
        if quantity and reason["explanation_required"] and not explanation.strip():
            raise HTTPException(422, detail={"code": "invalid_reason_explanation_required"})
        reason_rows.append(
            {
                **reason,
                "reason_id": reason["id"],
                "reason_revision": reason["revision"],
                "quantity": quantity,
                "explanation": explanation,
            }
        )
    for name, code in (
        ("questionable_quantity", "f1_questionable_missing"),
        ("actual_counted_quantity", "f1_actual_missing"),
    ):
        if getattr(data, name) is None:
            blockers.append({"code": code})
    valid_total = (
        None
        if any(row["quantity"] is None for row in candidate_rows)
        else sum(row["quantity"] for row in candidate_rows)
    )
    invalid_total = (
        None
        if any(row["quantity"] is None for row in reason_rows)
        else sum(row["quantity"] for row in reason_rows)
    )
    components = [valid_total, invalid_total, data.questionable_quantity]
    accounted = (
        None
        if any(value is None for value in components)
        else sum(value for value in components if value is not None)
    )
    balanced = (
        None
        if accounted is None or data.actual_counted_quantity is None
        else accounted == data.actual_counted_quantity
    )
    if balanced is False:
        raise HTTPException(
            422,
            detail={
                "code": "f1_arithmetic_invalid",
                "accounted_quantity": accounted,
                "actual_quantity": data.actual_counted_quantity,
            },
        )
    result: dict[str, Any] = jsonable_encoder(
        {
            "context": options["context"],
            "scope_revision": options["scope"]["revision"],
            "scope_basis": options["scope"],
            "candidate_votes": candidate_rows,
            "invalid_papers": reason_rows,
            "questionable_quantity": data.questionable_quantity,
            "actual_counted_quantity": data.actual_counted_quantity,
            "initial_valid_quantity": valid_total,
            "clearly_invalid_quantity": invalid_total,
            "initial_accounted_quantity": accounted,
            "initial_arithmetic_valid": balanced,
            "f1_complete": not blockers and balanced is True,
            "blockers": blockers,
        }
    )
    return result


def counting_rounds_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/rounds",
        tags=["count rounds"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def read(station_id: int, scope_id: int, db: Database, actor: Actor) -> dict[str, Any]:
        options = round_context(db, actor, station_id, scope_id)
        rounds = list(
            db.scalars(
                select(CountRound)
                .where(
                    CountRound.scope_id == scope_id,
                )
                .order_by(CountRound.round_number)
                .with_for_update()
            )
        )
        views = []
        for round in rounds:
            row = latest_round_revision(db, round.id)
            assert row is not None
            views.append(round_view(db, round, row, options))
        return {**options, "rounds": views}

    @router.get("/{round_id}")
    def history(
        station_id: int,
        scope_id: int,
        round_id: int,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        options = round_context(db, actor, station_id, scope_id)
        round = round_at(db, scope_id, round_id)
        rows = list(
            db.scalars(
                select(CountRoundRevision)
                .where(
                    CountRoundRevision.round_id == round_id,
                )
                .order_by(CountRoundRevision.revision.desc())
                .with_for_update()
            )
        )
        views = [round_view(db, round, row, options) for row in rows]
        return {"record": views[0], "history": views}

    @router.get("/{round_id}/revisions/{revision}")
    def revision(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: int,
        db: Database,
        actor: Actor,
    ) -> dict[str, Any]:
        options = round_context(db, actor, station_id, scope_id)
        round = round_at(db, scope_id, round_id)
        row = db.scalar(
            select(CountRoundRevision)
            .where(
                CountRoundRevision.round_id == round_id,
                CountRoundRevision.revision == revision,
            )
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, detail={"code": "count_round_not_found"})
        return round_view(db, round, row, options)

    def save(
        station_id: int,
        scope_id: int,
        round_id: int | None,
        data: F1Draft,
        db: Session,
        actor: Account,
        response: Response,
    ) -> dict[str, Any]:
        if actor.role != "counting_officer":
            raise HTTPException(403, detail={"code": "counting_officer_required"})
        # Serialize all count/catalog commands before locking scope and revisions.
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        turnout_scope(db, actor, station_id, writable=True)
        options = round_context(db, actor, station_id, scope_id)
        digest_data = data.model_dump(
            mode="json",
            exclude={"request_id", "discard_f2"},
        )
        if data.discard_f2:
            digest_data["discard_f2"] = True
        digest = hashlib.sha256(
            json.dumps(
                {
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round_id,
                    "actor_id": actor.id,
                    "data": digest_data,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        previous = db.scalar(
            select(CountRoundRequest)
            .where(
                CountRoundRequest.request_id == str(data.request_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if previous:
            if previous.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return previous.response
        if options["scope"]["revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_scope_revision_conflict"})
        if not options["scope"]["count_ready"]:
            raise HTTPException(409, detail={"code": "count_scope_not_ready"})
        round = round_at(db, scope_id, round_id) if round_id is not None else None
        current = latest_round_revision(db, round.id) if round else None
        if data.expected_revision != (current.revision if current else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        if current and current.data["scope_revision"] != data.scope_revision:
            raise HTTPException(409, detail={"code": "count_round_basis_stale"})
        if current and current.status != "draft":
            raise HTTPException(409, detail={"code": "count_round_read_only"})
        if current and current.data.get("f2") is not None and not data.discard_f2:
            raise HTTPException(409, detail={"code": "f2_discard_required"})
        event_at, now = data.event_at.replace(tzinfo=None), timestamp()
        if event_at > now:
            raise HTTPException(422, detail={"code": "event_time_in_future"})
        if round is None:
            existing = db.scalar(
                select(CountRound)
                .where(
                    CountRound.scope_id == scope_id,
                )
                .with_for_update()
            )
            if existing:
                raise HTTPException(409, detail={"code": "initial_round_exists"})
            round = CountRound(scope_id=scope_id, round_number=1)
            db.add(round)
            db.flush()
        frozen = f1_basis(options, data)
        row = CountRoundRevision(
            round_id=round.id,
            revision=data.expected_revision + 1,
            status="draft",
            event_at=event_at,
            entered_at=now,
            actor_id=actor.id,
            notes=data.notes,
            amendment_reason=data.amendment_reason,
            data=frozen,
        )
        db.add(row)
        db.flush()
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
                action="f1_draft_saved",
                occurred_at=now,
                details={
                    "station_id": station_id,
                    "scope_id": scope_id,
                    "round_id": round.id,
                    "revision": row.revision,
                },
            )
        )
        db.commit()
        return result

    @router.post("", status_code=201)
    def create(
        station_id: int,
        scope_id: int,
        data: F1Draft,
        db: Database,
        actor: Actor,
        response: Response,
    ) -> dict[str, Any]:
        return save(station_id, scope_id, None, data, db, actor, response)

    @router.put("/{round_id}")
    def amend(
        station_id: int,
        scope_id: int,
        round_id: int,
        data: F1Draft,
        db: Database,
        actor: Actor,
        response: Response,
    ) -> dict[str, Any]:
        return save(station_id, scope_id, round_id, data, db, actor, response)

    return router
