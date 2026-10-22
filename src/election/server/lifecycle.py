"""Configure election schedules and activate one shared operational election."""

from collections.abc import Callable, Generator
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.configuration import election_view
from election.server.configuration_models import Candidate, Constituency, Election
from election.server.configuration_store import find_election
from election.server.lifecycle_models import ActiveElection, ElectionSchedule
from election.server.models import Account, AuditEvent
from election.server.station_models import IssuanceCounter, PollingStation

HKT = timezone(timedelta(hours=8), "HKT")


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    election_date: date
    planned_opening_at: AwareDatetime
    planned_closing_at: AwareDatetime
    reporting_interval_minutes: int = Field(strict=True, ge=1, le=1440)
    revision: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def ordered_hong_kong_schedule(self) -> ScheduleInput:
        if self.planned_opening_at.astimezone(HKT).date() != self.election_date:
            raise ValueError("Opening must fall on the election date in Hong Kong")
        if self.planned_closing_at <= self.planned_opening_at:
            raise ValueError("Closing must follow opening")
        return self


class ActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    election_revision: int = Field(strict=True, ge=1)
    schedule_revision: int = Field(strict=True, ge=1)


def schedule_view(row: ElectionSchedule) -> dict[str, Any]:
    return {
        "election_id": row.election_id,
        "election_date": row.election_date,
        "planned_opening_at": row.planned_opening_at.replace(tzinfo=UTC),
        "planned_closing_at": row.planned_closing_at.replace(tzinfo=UTC),
        "reporting_interval_minutes": row.reporting_interval_minutes,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def lifecycle_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(tags=["Election lifecycle"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]
    ReadyAccount = Annotated[Account, Depends(ready_account)]

    def schedule(db: Session, election_id: int, *, lock: bool = False) -> ElectionSchedule | None:
        query = select(ElectionSchedule).where(ElectionSchedule.election_id == election_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return db.scalar(query)

    def active_resource(
        db: Session, election_id: int | None, *, current_read: bool = False
    ) -> dict[str, Any]:
        if election_id is None:
            return {"election": None}
        if current_read:
            election = db.scalar(
                select(Election)
                .where(Election.id == election_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if election is None:
                raise HTTPException(503, detail={"code": "database_unavailable"})
        else:
            election = find_election(db, election_id)
        planned = schedule(db, election_id, lock=current_read)
        return {
            "election": {
                **election_view(election),
                "schedule": schedule_view(planned) if planned is not None else None,
            }
        }

    def complete_configuration(db: Session, election_id: int) -> None:
        constituency_ids = list(
            db.scalars(
                select(Constituency.id)
                .where(Constituency.election_id == election_id)
                .with_for_update()
            )
        )
        complete = bool(constituency_ids)
        for constituency_id in constituency_ids:
            candidate_id = db.scalar(
                select(Candidate.id)
                .where(Candidate.constituency_id == constituency_id)
                .limit(1)
                .with_for_update()
            )
            station_ids = list(
                db.scalars(
                    select(PollingStation.id)
                    .where(PollingStation.constituency_id == constituency_id)
                    .with_for_update()
                )
            )
            complete = complete and candidate_id is not None and bool(station_ids)
            for station_id in station_ids:
                counter_id = db.scalar(
                    select(IssuanceCounter.id)
                    .where(IssuanceCounter.station_id == station_id)
                    .limit(1)
                    .with_for_update()
                )
                complete = complete and counter_id is not None
        if not complete:
            raise HTTPException(409, detail={"code": "election_configuration_incomplete"})

    @router.get("/api/elections/{election_id}/schedule")
    def get_schedule(election_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        find_election(db, election_id)
        row = schedule(db, election_id)
        if row is None:
            raise HTTPException(404, detail={"code": "schedule_not_configured"})
        return schedule_view(row)

    @router.put("/api/elections/{election_id}/schedule")
    def save_schedule(
        election_id: int, data: ScheduleInput, db: Database, actor: Admin
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        row = schedule(db, election_id, lock=True)
        if data.revision != (row.revision if row is not None else 0):
            raise HTTPException(409, detail={"code": "revision_conflict"})
        before = jsonable_encoder(schedule_view(row)) if row is not None else None
        if row is None:
            row = ElectionSchedule(election_id=election_id, revision=0, created_at=timestamp())
            db.add(row)
        row.election_date = data.election_date
        row.planned_opening_at = data.planned_opening_at.astimezone(UTC).replace(tzinfo=None)
        row.planned_closing_at = data.planned_closing_at.astimezone(UTC).replace(tzinfo=None)
        row.reporting_interval_minutes = data.reporting_interval_minutes
        row.revision, row.updated_at = row.revision + 1, timestamp()
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="election_schedule_saved",
                occurred_at=timestamp(),
                details={
                    "election_id": election_id,
                    "schedule_revision": row.revision,
                    "before": before,
                    "after": jsonable_encoder(schedule_view(row)),
                },
            )
        )
        db.commit()
        return schedule_view(row)

    @router.get("/api/active-election")
    def get_active_election(db: Database, actor: ReadyAccount) -> dict[str, Any]:
        current = db.get(ActiveElection, 1)
        if current is None:
            raise HTTPException(503, detail={"code": "database_unavailable"})
        return active_resource(db, current.election_id)

    @router.post("/api/elections/{election_id}/activate")
    def activate(
        election_id: int, data: ActivationInput, db: Database, actor: Admin
    ) -> dict[str, Any]:
        # All activation contenders take this lock before any election lock. Setup
        # writes use the election lock, so validation and activation share a boundary.
        current = db.scalar(
            select(ActiveElection)
            .where(ActiveElection.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None:
            raise HTTPException(503, detail={"code": "database_unavailable"})
        if current.election_id is not None:
            if current.election_id != election_id:
                raise HTTPException(409, detail={"code": "active_election_conflict"})
            # The pointer was read under lock. Use current reads to avoid returning
            # the authentication transaction's older REPEATABLE READ snapshot.
            return active_resource(db, election_id, current_read=True)
        election = find_election(db, election_id, lock=True)
        if election.revision != data.election_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        planned = schedule(db, election_id, lock=True)
        if planned is None:
            raise HTTPException(409, detail={"code": "schedule_required"})
        if planned.revision != data.schedule_revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        complete_configuration(db, election_id)
        before = {
            "status": election.status,
            "election_revision": election.revision,
            "active_election_id": current.election_id,
            "active_revision": current.revision,
        }
        election.status, election.revision, election.updated_at = (
            "active",
            election.revision + 1,
            timestamp(),
        )
        current.election_id = election_id
        current.revision, current.updated_at = current.revision + 1, timestamp()
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="election_activated",
                occurred_at=timestamp(),
                details={
                    "election_id": election_id,
                    "election_revision": election.revision,
                    "schedule_revision": planned.revision,
                    "before": before,
                    "after": {
                        "status": election.status,
                        "election_revision": election.revision,
                        "active_election_id": current.election_id,
                        "active_revision": current.revision,
                    },
                },
            )
        )
        db.commit()
        return active_resource(db, election_id)

    return router
