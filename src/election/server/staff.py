"""Individual staff accounts, explicit station access and revocable authorization."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.configuration_models import Constituency, Election
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent, LoginSession
from election.server.security import hash_password
from election.server.staff_models import StationAssignment
from election.server.station_models import PollingStation

StaffRole = Literal["administrator", "polling_officer", "counting_officer", "supervisor"]


class StaffSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    role: StaffRole
    enabled: bool = Field(default=True, strict=True)
    station_ids: list[Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=list)

    @field_validator("display_name")
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A display name is required")
        return value

    @model_validator(mode="after")
    def unique_assignments(self) -> StaffSettings:
        if len(self.station_ids) != len(set(self.station_ids)):
            raise ValueError("Station assignments must be distinct")
        return self


class StaffCreate(StaffSettings):
    username: str = Field(min_length=1, max_length=64)
    temporary_password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("username")
    @classmethod
    def normalized_username(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A username is required")
        return value.strip()


class StaffEdit(StaffSettings):
    revision: int = Field(strict=True, ge=1)


class StaffPasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_password: str = Field(min_length=12, max_length=128, repr=False)
    revision: int = Field(strict=True, ge=1)


def staff_view(db: Session, account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.display_name,
        "role": account.role,
        "enabled": account.enabled,
        "must_change_password": account.must_change_password,
        "revision": account.revision,
        "station_ids": list(
            db.scalars(
                select(StationAssignment.station_id)
                .where(StationAssignment.account_id == account.id)
                .order_by(StationAssignment.station_id)
            )
        ),
    }


def station_context(db: Session, account: Account, station: PollingStation) -> dict[str, Any]:
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    election = db.get(Election, constituency.election_id)
    assert election is not None
    return {
        "election": {"id": election.id, "name": election.name, "status": election.status},
        "constituency": {
            "id": constituency.id,
            "name": constituency.name,
            "code": constituency.code,
        },
        "station": {
            "id": station.id,
            "name": station.name,
            "code": station.code,
            "counting_mode": station.counting_mode,
            "destination_station_id": station.destination_station_id,
        },
        "account": staff_view(db, account),
        "capabilities": {
            "prepare_polling": account.role == "polling_officer",
            "prepare_counting": account.role == "counting_officer",
            "approve": account.role == "supervisor",
        },
    }


def require_station(
    db: Session,
    account: Account,
    station_id: int,
    *,
    roles: tuple[str, ...] = ("polling_officer", "counting_officer", "supervisor"),
) -> PollingStation:
    if account.role not in roles:
        raise HTTPException(403, detail={"code": "operational_role_required"})
    assigned = db.get(StationAssignment, (account.id, station_id))
    if assigned is None:
        raise HTTPException(403, detail={"code": "station_access_denied"})
    station = db.get(PollingStation, station_id)
    assert station is not None
    active = db.get(ActiveElection, 1)
    constituency = db.get(Constituency, station.constituency_id)
    assert constituency is not None
    if active and active.election_id is not None and constituency.election_id != active.election_id:
        raise HTTPException(409, detail={"code": "wrong_active_election"})
    return station


def staff_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/accounts", tags=["Staff administration"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]

    def account_row(db: Session, account_id: int, *, lock: bool = False) -> Account:
        query = select(Account).where(Account.id == account_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = db.scalar(query)
        if not row:
            raise HTTPException(404, detail={"code": "account_not_found"})
        return row

    def lock_administrators(db: Session) -> list[Account]:
        # Every account mutation takes the same ordered current read before the target.
        # Concurrent demotions/disables cannot remove the last enabled Administrator.
        return list(
            db.scalars(
                select(Account)
                .where(Account.enabled.is_(True), Account.role == "administrator")
                .order_by(Account.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def validate_assignments(db: Session, role: str, station_ids: list[int]) -> None:
        if role == "administrator" and station_ids:
            raise HTTPException(422, detail={"code": "invalid_station_assignment"})
        if station_ids:
            existing = set(
                db.scalars(
                    select(PollingStation.id)
                    .where(PollingStation.id.in_(station_ids))
                    .with_for_update()
                )
            )
            if existing != set(station_ids):
                raise HTTPException(422, detail={"code": "invalid_station_assignment"})

    def assign(db: Session, account_id: int, station_ids: list[int]) -> None:
        db.execute(delete(StationAssignment).where(StationAssignment.account_id == account_id))
        for station_id in station_ids:
            db.add(
                StationAssignment(
                    account_id=account_id, station_id=station_id, created_at=timestamp()
                )
            )

    def audit(
        db: Session,
        actor: Account,
        target: Account,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action=action,
                occurred_at=timestamp(),
                details={
                    "account_id": target.id,
                    "revision": target.revision,
                    "before": before,
                    "after": after,
                },
            )
        )

    @router.get("")
    def list_accounts(db: Database, actor: Admin) -> dict[str, Any]:
        return {
            "items": [
                staff_view(db, row)
                for row in db.scalars(select(Account).order_by(Account.id.desc()))
            ]
        }

    @router.post("", status_code=201)
    def create_account(data: StaffCreate, db: Database, actor: Admin) -> dict[str, Any]:
        lock_administrators(db)
        validate_assignments(db, data.role, data.station_ids)
        row = Account(
            username=data.username,
            display_name=data.display_name,
            role=data.role,
            enabled=data.enabled,
            must_change_password=True,
            password_hash=hash_password(data.temporary_password),
            created_at=timestamp(),
            revision=1,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "username_exists"}) from None
        assign(db, row.id, data.station_ids)
        db.flush()
        view = staff_view(db, row)
        audit(db, actor, row, "staff_created", {}, view)
        db.commit()
        return view

    @router.get("/station-options")
    def station_options(db: Database, actor: Admin) -> dict[str, Any]:
        return {
            "items": [
                station_context(db, actor, row)
                for row in db.scalars(select(PollingStation).order_by(PollingStation.id))
            ]
        }

    @router.get("/{account_id}/audit")
    def account_audit(account_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        account_row(db, account_id)
        rows = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.details["account_id"].as_integer() == account_id)
            .order_by(AuditEvent.id)
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "actor_id": row.actor_id,
                    "action": row.action,
                    "occurred_at": row.occurred_at.replace(tzinfo=UTC),
                    "details": row.details,
                }
                for row in rows
            ]
        }

    @router.get("/{account_id}")
    def get_account(account_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        return staff_view(db, account_row(db, account_id))

    @router.put("/{account_id}")
    def edit_account(
        account_id: int, data: StaffEdit, db: Database, actor: Admin
    ) -> dict[str, Any]:
        administrators = lock_administrators(db)
        row = account_row(db, account_id, lock=True)
        if row.revision != data.revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        if (
            row.enabled
            and row.role == "administrator"
            and (not data.enabled or data.role != "administrator")
            and len(administrators) <= 1
        ):
            raise HTTPException(409, detail={"code": "last_administrator_required"})
        validate_assignments(db, data.role, data.station_ids)
        before = staff_view(db, row)
        row.display_name, row.role, row.enabled = data.display_name, data.role, data.enabled
        row.revision += 1
        assign(db, row.id, data.station_ids)
        db.execute(delete(LoginSession).where(LoginSession.account_id == row.id))
        db.flush()
        after = staff_view(db, row)
        audit(db, actor, row, "staff_updated", before, after)
        db.commit()
        return after

    @router.post("/{account_id}/password-reset")
    def reset_password(
        account_id: int, data: StaffPasswordReset, db: Database, actor: Admin
    ) -> dict[str, Any]:
        lock_administrators(db)
        row = account_row(db, account_id, lock=True)
        if row.revision != data.revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        before = staff_view(db, row)
        row.password_hash = hash_password(data.temporary_password)
        row.must_change_password = True
        row.revision += 1
        db.execute(delete(LoginSession).where(LoginSession.account_id == row.id))
        after = staff_view(db, row)
        audit(db, actor, row, "staff_password_reset", before, after)
        db.commit()
        return after

    return router


def station_access_router(
    database: Callable[[], Generator[Session]], ready_account: Callable[..., Account]
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations", tags=["Assigned station context"])
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("")
    def list_assigned_stations(db: Database, account: Ready) -> dict[str, Any]:
        if account.role == "administrator":
            return {"items": []}
        query = (
            select(PollingStation)
            .join(StationAssignment, StationAssignment.station_id == PollingStation.id)
            .join(Constituency, Constituency.id == PollingStation.constituency_id)
            .where(StationAssignment.account_id == account.id)
            .order_by(PollingStation.id)
        )
        active = db.get(ActiveElection, 1)
        if active and active.election_id is not None:
            query = query.where(Constituency.election_id == active.election_id)
        stations = db.scalars(query)
        return {"items": [station_context(db, account, station) for station in stations]}

    @router.get("/{station_id}")
    def select_station(station_id: int, db: Database, account: Ready) -> dict[str, Any]:
        return station_context(db, account, require_station(db, account, station_id))

    return router
