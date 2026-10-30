"""Assess reviewed election completion through one authenticated interface."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.accounting import accounting_record
from election.server.accounting import record_view as accounting_view
from election.server.complaints import complaint_snapshot
from election.server.configuration_models import Constituency, Election
from election.server.constituency_results import constituency_result
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, LoginSession
from election.server.polling import record_view
from election.server.polling_models import PollingRecord
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
        for result in results:
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
            "accounting": accounting_sources,
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

    return router
