"""Assess reviewed election completion through one authenticated interface."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
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
) -> tuple[Election, ActiveElection | None, list[PollingStation]]:
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
    return election, active, stations


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
        election, active, stations = _completion_context(db, identity, election_id, timestamp)
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
        context = {
            "id": election.id, "name": election.name,
            "status": election.status, "revision": election.revision,
        }
        basis = {"election": context, "polling_completion": sources}
        return {
            "election": context,
            "active_election_id": active.election_id if active is not None else None,
            # This first assessment slice cannot authorize finalization yet.
            "can_finalize": False,
            "blockers": blockers,
            "sources": {"polling_completion": sources},
            "basis_digest": hashlib.sha256(json.dumps(
                basis, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()).hexdigest(),
        }

    return router
