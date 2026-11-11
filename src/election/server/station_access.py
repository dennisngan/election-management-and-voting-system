"""Authorization and active-election scope for assigned operational stations."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation


def station_scope(
    db: Session, actor: Account, station_id: int, *, write: bool = False
) -> tuple[PollingStation, Constituency, Election]:
    if actor.role not in ("polling_officer", "counting_officer", "supervisor"):
        raise HTTPException(403, detail={"code": "operational_role_required"})
    if db.get(StationAssignment, (actor.id, station_id)) is None:
        raise HTTPException(403, detail={"code": "station_access_denied"})
    station = db.get(PollingStation, station_id)
    if station is None:
        raise HTTPException(404, detail={"code": "configuration_not_found"})
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    election = db.get(Election, constituency.election_id)
    assert election is not None
    if write:
        # Current reads avoid the authentication dependency's older MySQL snapshot.
        active = db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        election = db.scalar(
            select(Election)
            .where(Election.id == election.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert election is not None
        if not active or active.election_id != election.id or election.status != "active":
            raise HTTPException(409, detail={"code": "active_election_required"})
        station = db.scalar(
            select(PollingStation)
            .where(PollingStation.id == station_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert station is not None
    return station, constituency, election
