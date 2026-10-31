"""Assess reviewed election completion through one authenticated interface."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.accounting import accounting_record
from election.server.accounting import record_view as accounting_view
from election.server.complaints import complaint_snapshot
from election.server.configuration_models import Constituency, Election
from election.server.constituency_result_labels import ReportLocale
from election.server.constituency_results import constituency_result
from election.server.counting_round_models import CountRoundRevision
from election.server.counting_rounds import round_at, round_context, round_view
from election.server.election_completion_models import (
    ElectionCompletionEvent,
    ElectionCompletionRequest,
)
from election.server.election_completion_reports import completion_csv
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent, LoginSession
from election.server.polling import as_utc, record_view
from election.server.polling_models import PollingRecord
from election.server.security import verify_password
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation


def _completion_context(
    db: Session,
    identity: tuple[Account, LoginSession],
    election_id: int,
    timestamp: Callable[[], datetime],
) -> tuple[Election, ActiveElection | None, list[PollingStation], Account]:
    actor_id, actor_revision = identity[0].id, identity[0].revision
    session_digest = identity[1].token_hash
    # Authentication is read-only, but starts a repeatable-read snapshot. Copy
    # identity before rollback expires ORM attributes; read facts after all locks.
    db.rollback()
    active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
    election = db.scalar(
        select(Election).where(Election.id == election_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    actor = db.scalar(
        select(Account).where(Account.id == actor_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    session = db.scalar(
        select(LoginSession).where(LoginSession.token_hash == session_digest)
        .execution_options(populate_existing=True)
    )
    if (
        actor is None or not actor.enabled or actor.revision != actor_revision
        or session is None or session.account_id != actor_id
        or timestamp() >= session.expires_at
    ):
        raise HTTPException(401, detail={"code": "session_expired"})
    if actor.must_change_password:
        raise HTTPException(403, detail={"code": "password_change_required"})
    if actor.role != "supervisor":
        raise HTTPException(403, detail={"code": "supervisor_required"})
    if election is None:
        raise HTTPException(404, detail={"code": "election_not_found"})
    stations = list(db.scalars(
        select(PollingStation).join(Constituency)
        .where(Constituency.election_id == election_id)
        .order_by(PollingStation.constituency_id, PollingStation.id)
    ))
    assigned = set(db.scalars(
        select(StationAssignment.station_id).where(StationAssignment.account_id == actor_id)
    ))
    if not stations or not {row.id for row in stations} <= assigned:
        raise HTTPException(403, detail={"code": "full_election_access_required"})
    return election, active, stations, actor


def _assess_completion(
    db: Session, election: Election, active: ActiveElection | None,
    stations: list[PollingStation], actor: Account, timestamp: Callable[[], datetime],
) -> dict[str, Any]:
    """Read source facts within the caller's already fresh, serialized transaction."""
    blockers: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for station in stations:
        row = db.scalar(
            select(PollingRecord)
            .where(
                PollingRecord.station_id == station.id,
                PollingRecord.kind == "service_completion",
            )
            .order_by(PollingRecord.revision.desc()).limit(1)
        )
        sources.append({
            "station_id": station.id,
            "record": {"id": row.id, **record_view(row)} if row is not None else None,
        })
        if row is None:
            blockers.append({
                "code": "polling_completion_missing",
                "station_id": station.id,
                "constituency_id": station.constituency_id,
            })
        elif row.status != "approved":
            blockers.append({
                "code": "polling_completion_approval_required",
                "station_id": station.id,
                "constituency_id": station.constituency_id,
                "revision": row.revision,
                "status": row.status,
            })
    accounting_sources: list[dict[str, Any]] = []
    for station in stations:
        accounting = accounting_record(db, station.id)
        accounting_sources.append({
            "station_id": station.id,
            "record": accounting_view(db, accounting) if accounting is not None else None,
        })
    current_accounting = {row["station_id"]: row["record"] for row in accounting_sources}
    results = [
        constituency_result(db, actor, constituency_id)
        for constituency_id in sorted({station.constituency_id for station in stations})
    ]
    selected_counts = []
    for result in results:
        for contribution in result["contributions"]:
            scope_id = contribution["scope_id"]
            options = round_context(db, actor, contribution["station_id"], scope_id)
            count_round = round_at(db, scope_id, contribution["round_id"])
            revision = db.get(CountRoundRevision, contribution["round_revision_id"])
            assert revision is not None
            selected_counts.append({
                "station_id": contribution["station_id"], "scope_id": scope_id,
                "record": round_view(db, count_round, revision, options),
            })
        constituency_id = result["context"]["constituency"]["id"]
        blockers.extend(
            {**pending, "constituency_id": constituency_id}
            for pending in result["pending"]
        )
        if (
            result["complete"] and result["tie_candidate_ids"]
            and result["resolved_candidate_id"] is None
        ):
            blockers.append({
                "code": "result_tie_resolution_required",
                "constituency_id": constituency_id,
                "candidate_ids": result["tie_candidate_ids"],
            })
    for blocker in blockers:
        if "source_accounting_revisions" not in blocker:
            continue
        references = []
        for frozen in blocker["source_accounting_revisions"]:
            current = current_accounting.get(frozen["station_id"])
            references.append({
                "station_id": frozen["station_id"],
                "record_id": current["id"] if current else None,
                **{key: current[key] if current else None for key in (
                    "revision", "status", "source_current", "approval_valid",
                )},
            })
        blocker["current_source_accounting_revisions"] = references
    complaints = [
        {
            "station_id": station.id,
            "records": complaint_snapshot(db, actor, station.id, timestamp())["items"],
        }
        for station in stations
    ]
    context = {
        "id": election.id, "name": election.name,
        "status": election.status, "revision": election.revision,
    }
    source_records = {
        "polling_completion": sources, "constituencies": results, "complaints": complaints,
        "accounting": accounting_sources, "selected_counts": selected_counts,
    }
    basis = {"election": context, "sources": source_records}
    return {
        "election": context,
        "active_election_id": active.election_id if active is not None else None,
        "can_finalize": bool(
            active is not None and active.election_id == election.id
            and election.status == "active" and results and not blockers
            and all(result["complete"] for result in results)
        ),
        "blockers": blockers,
        "sources": source_records,
        "basis_digest": hashlib.sha256(json.dumps(
            basis, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest(),
    }


class FinalizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_election_revision: int = Field(strict=True, ge=1)
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    password: str = Field(min_length=1, max_length=128, repr=False)


class ReopeningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_election_revision: int = Field(strict=True, ge=1)
    previous_finalization_id: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reopening reason is required")
        return value


def _completion_event_view(event: ElectionCompletionEvent) -> dict[str, Any]:
    return {
        "id": event.id, "election_id": event.election_id, "kind": event.kind,
        "election_revision": event.election_revision, "actor_id": event.actor_id,
        "accepted_at": as_utc(event.accepted_at), "reason": event.reason,
        "previous_finalization_id": event.previous_finalization_id,
        "basis_digest": event.basis_digest, "outcome": deepcopy(event.data),
    }


def election_completion_router(
    database: Callable[..., Any],
    authenticated: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/elections/{election_id}", tags=["Election completion"]
    )
    Database = Annotated[Session, Depends(database)]
    Identity = Annotated[tuple[Account, LoginSession], Depends(authenticated)]

    @router.get("/completion")
    def assessment(election_id: int, db: Database, identity: Identity) -> dict[str, Any]:
        election, active, stations, actor = _completion_context(
            db, identity, election_id, timestamp
        )
        return _assess_completion(db, election, active, stations, actor, timestamp)

    @router.get("/completion/history")
    def history(election_id: int, db: Database, identity: Identity) -> dict[str, Any]:
        election, active, _, _ = _completion_context(db, identity, election_id, timestamp)
        events = db.scalars(
            select(ElectionCompletionEvent)
            .where(ElectionCompletionEvent.election_id == election_id)
            .order_by(ElectionCompletionEvent.election_revision.desc())
        )
        return {
            "election": {
                "id": election.id, "name": election.name,
                "status": election.status, "revision": election.revision,
            },
            "active_election_id": active.election_id if active is not None else None,
            "events": [_completion_event_view(event) for event in events],
        }

    @router.get("/completion/history/{event_id}/statement.csv")
    def statement_csv(
        election_id: int, event_id: int, db: Database, identity: Identity,
        locale: ReportLocale = "tc",
    ) -> Response:
        _completion_context(db, identity, election_id, timestamp)
        event = db.scalar(select(ElectionCompletionEvent).where(
            ElectionCompletionEvent.id == event_id,
            ElectionCompletionEvent.election_id == election_id,
        ))
        if event is None:
            raise HTTPException(404, detail={"code": "election_completion_event_not_found"})
        frozen = _completion_event_view(event)
        db.rollback()
        return Response(
            completion_csv(frozen, locale, timestamp()), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": (
                f'attachment; filename="election-{election_id}-completion-{event_id}.csv"'
            )},
        )

    @router.get("/request-outcomes/{request_id}")
    def outcome(
        election_id: int, request_id: UUID, workflow: Literal["election_completion"],
        db: Database, identity: Identity,
    ) -> dict[str, Any]:
        _, _, _, actor = _completion_context(db, identity, election_id, timestamp)
        cached = db.scalar(select(ElectionCompletionRequest).where(
            ElectionCompletionRequest.request_id == str(request_id),
            ElectionCompletionRequest.election_id == election_id,
            ElectionCompletionRequest.actor_id == actor.id,
        ))
        if cached is None:
            return {"request_id": str(request_id), "workflow": workflow, "status": "not_found"}
        return {
            "request_id": str(request_id), "workflow": workflow,
            "status": "committed", "record": deepcopy(cached.response),
        }

    @router.post("/finalizations", status_code=201)
    def finalize(
        election_id: int, data: FinalizationInput, db: Database, identity: Identity,
    ) -> dict[str, Any]:
        election, active, stations, actor = _completion_context(
            db, identity, election_id, timestamp
        )
        if not verify_password(actor.password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        digest = hashlib.sha256(json.dumps({
            "actor_id": actor.id, "election_id": election_id, "action": "finalization",
            "command": data.model_dump(mode="json", exclude={"request_id", "password"}),
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        previous = db.scalar(
            select(ElectionCompletionRequest)
            .where(ElectionCompletionRequest.request_id == str(data.request_id))
            .with_for_update().execution_options(populate_existing=True)
        )
        if previous is not None:
            if previous.actor_id != actor.id:
                raise HTTPException(404, detail={"code": "request_not_found"})
            if (
                previous.election_id != election_id or previous.action != "finalization"
                or previous.digest != digest
            ):
                raise HTTPException(409, detail={"code": "request_conflict"})
            return deepcopy(previous.response)
        if active is None:
            raise HTTPException(503, detail={"code": "database_unavailable"})
        if active.election_id != election_id or election.status != "active":
            raise HTTPException(409, detail={"code": "active_election_required"})
        if election.revision != data.expected_election_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        reviewed = _assess_completion(db, election, active, stations, actor, timestamp)
        if reviewed["basis_digest"] != data.basis_digest:
            raise HTTPException(409, detail={"code": "election_completion_basis_conflict"})
        if not reviewed["can_finalize"]:
            raise HTTPException(409, detail={
                "code": "election_not_ready", "blockers": reviewed["blockers"],
            })
        now = timestamp()
        final_election = {
            **reviewed["election"], "status": "finalized", "revision": election.revision + 1,
        }
        results = []
        for result in reviewed["sources"]["constituencies"]:
            winner = result["resolved_candidate_id"]
            if winner is None:
                assert len(result["leader_candidate_ids"]) == 1
                winner = result["leader_candidate_ids"][0]
            results.append({
                "constituency": deepcopy(result["context"]["constituency"]),
                "candidate_totals": deepcopy(result["candidate_totals"]),
                "contributions": deepcopy(result["contributions"]),
                "winner_candidate_id": winner, "status": "finalized", "provisional": False,
                "tie_resolution": deepcopy(result["tie_resolution"])
                if result["tie_resolution"] and result["tie_resolution"]["valid"] else None,
                "basis_digest": result["basis_digest"],
            })
        outcome = {
            "election": final_election, "results": results,
            "sources": deepcopy(reviewed["sources"]),
        }
        event = ElectionCompletionEvent(
            election_id=election_id, kind="finalization",
            election_revision=final_election["revision"], actor_id=actor.id,
            accepted_at=now, reason="", previous_finalization_id=None,
            basis_digest=reviewed["basis_digest"], data=outcome,
        )
        old_active = active.election_id
        election.status, election.revision, election.updated_at = (
            "finalized", final_election["revision"], now,
        )
        active.election_id = None
        active.revision, active.updated_at = active.revision + 1, now
        db.add(event)
        try:
            db.flush()
            response = {
                "request_id": str(data.request_id), "election": final_election,
                "active_election_id": None, "event": _completion_event_view(event),
            }
            db.add(ElectionCompletionRequest(
                request_id=str(data.request_id), election_id=election_id, actor_id=actor.id,
                event_id=event.id, action="finalization", digest=digest,
                response=response, accepted_at=now,
            ))
            db.add(AuditEvent(
                actor_id=actor.id, action="election_finalized", occurred_at=now,
                details={
                    "election_id": election_id, "event_id": event.id,
                    "request_id": str(data.request_id), "basis_digest": reviewed["basis_digest"],
                    "before": {**reviewed["election"], "active_election_id": old_active},
                    "after": {**final_election, "active_election_id": None},
                },
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "request_conflict"}) from None
        return response

    @router.post("/reopenings", status_code=201)
    def reopen(
        election_id: int, data: ReopeningInput, db: Database, identity: Identity,
    ) -> dict[str, Any]:
        election, active, _, actor = _completion_context(db, identity, election_id, timestamp)
        if not verify_password(actor.password_hash, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        digest = hashlib.sha256(json.dumps({
            "actor_id": actor.id, "election_id": election_id, "action": "reopening",
            "command": data.model_dump(mode="json", exclude={"request_id", "password"}),
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        previous = db.scalar(
            select(ElectionCompletionRequest)
            .where(ElectionCompletionRequest.request_id == str(data.request_id))
            .with_for_update().execution_options(populate_existing=True)
        )
        if previous is not None:
            if previous.actor_id != actor.id:
                raise HTTPException(404, detail={"code": "request_not_found"})
            if (
                previous.election_id != election_id or previous.action != "reopening"
                or previous.digest != digest
            ):
                raise HTTPException(409, detail={"code": "request_conflict"})
            return deepcopy(previous.response)
        if active is None:
            raise HTTPException(503, detail={"code": "database_unavailable"})
        if active.election_id is not None:
            raise HTTPException(409, detail={"code": "active_election_conflict"})
        if election.status != "finalized":
            raise HTTPException(409, detail={"code": "finalized_election_required"})
        if election.revision != data.expected_election_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        finalized = db.scalar(
            select(ElectionCompletionEvent).where(
                ElectionCompletionEvent.election_id == election_id,
                ElectionCompletionEvent.kind == "finalization",
            ).order_by(ElectionCompletionEvent.election_revision.desc()).limit(1)
        )
        if (
            finalized is None or finalized.id != data.previous_finalization_id
            or finalized.election_revision != election.revision
        ):
            raise HTTPException(409, detail={"code": "previous_finalization_conflict"})
        now = timestamp()
        before = {
            "id": election.id, "name": election.name,
            "status": election.status, "revision": election.revision,
        }
        reopened_revision = election.revision + 1
        reopened = {**before, "status": "active", "revision": reopened_revision}
        event = ElectionCompletionEvent(
            election_id=election_id, kind="reopening", election_revision=reopened_revision,
            actor_id=actor.id, accepted_at=now, reason=data.reason,
            previous_finalization_id=finalized.id, basis_digest=finalized.basis_digest,
            data={"election": reopened, "previous_finalization_id": finalized.id},
        )
        election.status, election.revision, election.updated_at = (
            "active", reopened_revision, now,
        )
        active.election_id = election_id
        active.revision, active.updated_at = active.revision + 1, now
        db.add(event)
        try:
            db.flush()
            response = {
                "request_id": str(data.request_id), "election": reopened,
                "active_election_id": election_id, "event": _completion_event_view(event),
            }
            db.add(ElectionCompletionRequest(
                request_id=str(data.request_id), election_id=election_id, actor_id=actor.id,
                event_id=event.id, action="reopening", digest=digest,
                response=response, accepted_at=now,
            ))
            db.add(AuditEvent(
                actor_id=actor.id, action="election_reopened", occurred_at=now,
                details={
                    "election_id": election_id, "event_id": event.id,
                    "request_id": str(data.request_id), "reason": data.reason,
                    "previous_finalization_id": finalized.id,
                    "before": {**before, "active_election_id": None},
                    "after": {**reopened, "active_election_id": election_id},
                },
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "request_conflict"}) from None
        return response

    return router
