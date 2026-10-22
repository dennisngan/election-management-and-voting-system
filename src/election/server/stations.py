"""Draft station arrangements and identifiable ballot issuance counters."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.configuration_inputs import CodedInput
from election.server.configuration_store import (
    check_revision,
    commit_configuration,
    creation_digest,
    find_constituency,
    find_election,
    replay,
)
from election.server.models import Account, AuditEvent
from election.server.station_models import IssuanceCounter, PollingStation


class StationInput(CodedInput):
    counting_mode: Literal["local", "send"] = "local"
    destination_station_id: Annotated[int, Field(strict=True, ge=1)] | None = None

    @model_validator(mode="after")
    def counting_arrangement(self) -> StationInput:
        if (self.counting_mode == "local") != (self.destination_station_id is None):
            raise ValueError("Local stations have no destination; sending stations require one")
        return self


class StationCreate(StationInput):
    request_id: UUID


class StationEdit(StationInput):
    revision: int = Field(strict=True, ge=1)


class CounterCreate(CodedInput):
    request_id: UUID


class CounterEdit(CodedInput):
    revision: int = Field(strict=True, ge=1)


def station_view(row: PollingStation, election_id: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "election_id": election_id,
        "constituency_id": row.constituency_id,
        "name": row.name,
        "code": row.code,
        "counting_mode": row.counting_mode,
        "destination_station_id": row.destination_station_id,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def counter_view(row: IssuanceCounter, station: PollingStation, election_id: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "station_id": row.station_id,
        "election_id": election_id,
        "constituency_id": station.constituency_id,
        "code": row.code,
        "name": row.name,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def stations_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    base = "/api/elections/{election_id}/constituencies/{constituency_id}/stations"
    router = APIRouter(prefix=base, tags=["Station configuration"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]

    def station(
        db: Session, election_id: int, constituency_id: int, station_id: int, *, lock: bool = False
    ) -> PollingStation:
        find_constituency(db, election_id, constituency_id, lock=lock)
        query = select(PollingStation).where(
            PollingStation.id == station_id, PollingStation.constituency_id == constituency_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = db.scalar(query)
        if not row:
            raise HTTPException(404, detail={"code": "configuration_not_found"})
        return row

    def counter(
        db: Session, station_id: int, counter_id: int, *, lock: bool = False
    ) -> IssuanceCounter:
        query = select(IssuanceCounter).where(
            IssuanceCounter.id == counter_id, IssuanceCounter.station_id == station_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = db.scalar(query)
        if not row:
            raise HTTPException(404, detail={"code": "configuration_not_found"})
        return row

    def flush(db: Session) -> None:
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "duplicate_configuration"}) from None

    def validate_destination(
        db: Session, constituency_id: int, data: StationInput, station_id: int | None = None
    ) -> None:
        if data.counting_mode == "local":
            return
        destination = db.scalar(
            select(PollingStation)
            .where(
                PollingStation.id == data.destination_station_id,
                PollingStation.constituency_id == constituency_id,
                PollingStation.counting_mode == "local",
            )
            .with_for_update()
        )
        if not destination or destination.id == station_id:
            raise HTTPException(422, detail={"code": "invalid_counting_destination"})
        if station_id is not None:
            incoming = db.scalar(
                select(PollingStation.id)
                .where(PollingStation.destination_station_id == station_id)
                .with_for_update()
            )
            if incoming is not None:
                raise HTTPException(409, detail={"code": "receiver_in_use"})

    def audit(
        db: Session,
        actor: Account,
        action: str,
        election_id: int,
        constituency_id: int,
        station_id: int,
        details: dict[str, Any],
    ) -> None:
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action=action,
                occurred_at=timestamp(),
                details={
                    "election_id": election_id,
                    "constituency_id": constituency_id,
                    "station_id": station_id,
                    **details,
                },
            )
        )

    @router.get("")
    def list_stations(
        election_id: int, constituency_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        find_constituency(db, election_id, constituency_id)
        rows = db.scalars(
            select(PollingStation)
            .where(PollingStation.constituency_id == constituency_id)
            .order_by(PollingStation.code, PollingStation.id)
        )
        return {"items": [station_view(row, election_id) for row in rows]}

    @router.post("", status_code=201)
    def create_station(
        election_id: int,
        constituency_id: int,
        data: StationCreate,
        response: Response,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        find_constituency(db, election_id, constituency_id, lock=True)
        digest = creation_digest(data, constituency_id=constituency_id)
        existing = replay(db, PollingStation, data.request_id, digest, response)
        if existing:
            return station_view(existing, election_id)
        validate_destination(db, constituency_id, data)
        row = PollingStation(
            constituency_id=constituency_id,
            name=data.name,
            code=data.code,
            counting_mode=data.counting_mode,
            destination_station_id=data.destination_station_id,
            revision=1,
            request_id=str(data.request_id),
            creation_digest=digest,
            created_at=timestamp(),
            updated_at=timestamp(),
        )
        db.add(row)
        flush(db)
        audit(
            db,
            actor,
            "station_created",
            election_id,
            constituency_id,
            row.id,
            {"revision": 1, "after": data.model_dump(mode="json", exclude={"request_id"})},
        )
        commit_configuration(db)
        return station_view(row, election_id)

    @router.get("/{station_id}")
    def get_station(
        election_id: int, constituency_id: int, station_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        return station_view(station(db, election_id, constituency_id, station_id), election_id)

    @router.put("/{station_id}")
    def edit_station(
        election_id: int,
        constituency_id: int,
        station_id: int,
        data: StationEdit,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        row = station(db, election_id, constituency_id, station_id, lock=True)
        check_revision(row, data.revision)
        validate_destination(db, constituency_id, data, station_id)
        before = {
            "name": row.name,
            "code": row.code,
            "counting_mode": row.counting_mode,
            "destination_station_id": row.destination_station_id,
        }
        row.name, row.code = data.name, data.code
        row.counting_mode, row.destination_station_id = (
            data.counting_mode,
            data.destination_station_id,
        )
        row.revision, row.updated_at = row.revision + 1, timestamp()
        audit(
            db,
            actor,
            "station_edited",
            election_id,
            constituency_id,
            station_id,
            {
                "revision": row.revision,
                "before": before,
                "after": data.model_dump(mode="json", exclude={"revision"}),
            },
        )
        commit_configuration(db)
        return station_view(row, election_id)

    @router.get("/{station_id}/counters")
    def list_counters(
        election_id: int, constituency_id: int, station_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        parent = station(db, election_id, constituency_id, station_id)
        rows = db.scalars(
            select(IssuanceCounter)
            .where(IssuanceCounter.station_id == station_id)
            .order_by(IssuanceCounter.code, IssuanceCounter.id)
        )
        return {"items": [counter_view(row, parent, election_id) for row in rows]}

    @router.post("/{station_id}/counters", status_code=201)
    def create_counter(
        election_id: int,
        constituency_id: int,
        station_id: int,
        data: CounterCreate,
        response: Response,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        parent = station(db, election_id, constituency_id, station_id, lock=True)
        digest = creation_digest(data, station_id=station_id)
        existing = replay(db, IssuanceCounter, data.request_id, digest, response)
        if existing:
            return counter_view(existing, parent, election_id)
        row = IssuanceCounter(
            station_id=station_id,
            name=data.name,
            code=data.code,
            revision=1,
            request_id=str(data.request_id),
            creation_digest=digest,
            created_at=timestamp(),
            updated_at=timestamp(),
        )
        db.add(row)
        flush(db)
        audit(
            db,
            actor,
            "counter_created",
            election_id,
            constituency_id,
            station_id,
            {
                "counter_id": row.id,
                "revision": 1,
                "after": data.model_dump(mode="json", exclude={"request_id"}),
            },
        )
        commit_configuration(db)
        return counter_view(row, parent, election_id)

    @router.get("/{station_id}/counters/{counter_id}")
    def get_counter(
        election_id: int,
        constituency_id: int,
        station_id: int,
        counter_id: int,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        parent = station(db, election_id, constituency_id, station_id)
        return counter_view(counter(db, station_id, counter_id), parent, election_id)

    @router.put("/{station_id}/counters/{counter_id}")
    def edit_counter(
        election_id: int,
        constituency_id: int,
        station_id: int,
        counter_id: int,
        data: CounterEdit,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        parent = station(db, election_id, constituency_id, station_id, lock=True)
        row = counter(db, station_id, counter_id, lock=True)
        check_revision(row, data.revision)
        before = {"name": row.name, "code": row.code}
        row.name, row.code = data.name, data.code
        row.revision, row.updated_at = row.revision + 1, timestamp()
        audit(
            db,
            actor,
            "counter_edited",
            election_id,
            constituency_id,
            station_id,
            {
                "counter_id": row.id,
                "revision": row.revision,
                "before": before,
                "after": data.model_dump(mode="json", exclude={"revision"}),
            },
        )
        commit_configuration(db)
        return counter_view(row, parent, election_id)

    return router
