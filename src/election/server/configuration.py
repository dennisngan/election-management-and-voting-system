"""Administrator draft setup, scoped identities, revision checks and create replay."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.complaint_categories import seed_election_categories
from election.server.configuration_inputs import CodedInput, NamedInput
from election.server.configuration_models import Candidate, Constituency, Election
from election.server.configuration_store import (
    check_revision,
    commit_configuration,
    creation_digest,
    find_constituency,
    find_election,
    replay,
)
from election.server.models import Account, AuditEvent


class ElectionInput(NamedInput):
    pass


class ElectionCreate(ElectionInput):
    request_id: UUID


class ElectionEdit(ElectionInput):
    revision: int = Field(strict=True, ge=1)


class ConstituencyInput(CodedInput):
    seats: int = Field(default=1, strict=True, ge=1, le=1)
    choices_per_ballot: int = Field(default=1, strict=True, ge=1, le=1)


class ConstituencyCreate(ConstituencyInput):
    request_id: UUID


class ConstituencyEdit(ConstituencyInput):
    revision: int = Field(strict=True, ge=1)


class CandidateInput(NamedInput):
    ballot_number: int = Field(strict=True, ge=1, le=2147483647)


class CandidateCreate(CandidateInput):
    request_id: UUID


class CandidateEdit(CandidateInput):
    revision: int = Field(strict=True, ge=1)


def election_view(row: Election) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def constituency_view(row: Constituency) -> dict[str, Any]:
    return {
        "id": row.id,
        "election_id": row.election_id,
        "code": row.code,
        "name": row.name,
        "seats": row.seats,
        "choices_per_ballot": row.choices_per_ballot,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def candidate_view(row: Candidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "constituency_id": row.constituency_id,
        "ballot_number": row.ballot_number,
        "name": row.name,
        "revision": row.revision,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def configuration_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/elections", tags=["Draft configuration"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]

    def audit(db: Session, actor: Account, action: str, details: dict[str, Any]) -> None:
        db.add(
            AuditEvent(actor_id=actor.id, action=action, occurred_at=timestamp(), details=details)
        )

    @router.get("")
    def list_elections(db: Database, actor: Admin) -> dict[str, Any]:
        return {
            "items": [
                election_view(row)
                for row in db.scalars(select(Election).order_by(Election.id.desc()))
            ]
        }

    @router.post("", status_code=201)
    def create_election(
        data: ElectionCreate, response: Response, db: Database, actor: Admin
    ) -> dict[str, Any]:
        digest = creation_digest(data)
        existing = db.scalar(select(Election).where(Election.request_id == str(data.request_id)))
        if existing:
            if existing.creation_digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return election_view(existing)
        row = Election(
            name=data.name,
            status="draft",
            revision=1,
            created_at=timestamp(),
            updated_at=timestamp(),
            request_id=str(data.request_id),
            creation_digest=digest,
        )
        db.add(row)
        try:
            db.flush()
            seed_election_categories(db, row.id, actor.id, timestamp())
            audit(
                db,
                actor,
                "election_created",
                {"election_id": row.id, "revision": 1, "name": row.name},
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            # A concurrent retry may have committed the same create key first.
            existing = db.scalar(
                select(Election).where(Election.request_id == str(data.request_id))
            )
            if not existing or existing.creation_digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"}) from None
            response.status_code = 200
            return election_view(existing)
        return election_view(row)

    @router.get("/{election_id}")
    def get_election(election_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        return election_view(find_election(db, election_id))

    @router.put("/{election_id}")
    def edit_election(
        election_id: int, data: ElectionEdit, db: Database, actor: Admin
    ) -> dict[str, Any]:
        row = find_election(db, election_id, lock=True)
        if row.revision != data.revision:
            raise HTTPException(409, detail={"code": "revision_conflict"})
        before = row.name
        row.name, row.revision, row.updated_at = data.name, row.revision + 1, timestamp()
        audit(
            db,
            actor,
            "election_edited",
            {
                "election_id": row.id,
                "revision": row.revision,
                "before": {"name": before},
                "after": {"name": row.name},
            },
        )
        db.commit()
        return election_view(row)

    @router.get("/{election_id}/constituencies")
    def list_constituencies(election_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        find_election(db, election_id)
        rows = db.scalars(
            select(Constituency)
            .where(Constituency.election_id == election_id)
            .order_by(Constituency.code, Constituency.id)
        )
        return {"items": [constituency_view(row) for row in rows]}

    @router.post("/{election_id}/constituencies", status_code=201)
    def create_constituency(
        election_id: int, data: ConstituencyCreate, response: Response, db: Database, actor: Admin
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        digest = creation_digest(data, election_id=election_id)
        existing = replay(db, Constituency, data.request_id, digest, response)
        if existing:
            return constituency_view(existing)
        row = Constituency(
            election_id=election_id,
            code=data.code,
            name=data.name,
            seats=1,
            choices_per_ballot=1,
            revision=1,
            created_at=timestamp(),
            updated_at=timestamp(),
            request_id=str(data.request_id),
            creation_digest=digest,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "duplicate_configuration"}) from None
        audit(
            db,
            actor,
            "constituency_created",
            {
                "election_id": election_id,
                "constituency_id": row.id,
                "revision": 1,
                "name": row.name,
                "code": row.code,
            },
        )
        commit_configuration(db)
        return constituency_view(row)

    @router.get("/{election_id}/constituencies/{constituency_id}")
    def get_constituency(
        election_id: int, constituency_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        return constituency_view(find_constituency(db, election_id, constituency_id))

    @router.put("/{election_id}/constituencies/{constituency_id}")
    def edit_constituency(
        election_id: int, constituency_id: int, data: ConstituencyEdit, db: Database, actor: Admin
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        row = find_constituency(db, election_id, constituency_id, lock=True)
        check_revision(row, data.revision)
        before = {"code": row.code, "name": row.name}
        row.code, row.name = data.code, data.name
        row.revision, row.updated_at = row.revision + 1, timestamp()
        audit(
            db,
            actor,
            "constituency_edited",
            {
                "election_id": election_id,
                "constituency_id": row.id,
                "revision": row.revision,
                "before": before,
                "after": {"code": row.code, "name": row.name},
            },
        )
        commit_configuration(db)
        return constituency_view(row)

    candidate_path = "/{election_id}/constituencies/{constituency_id}/candidates"

    @router.get(candidate_path)
    def list_candidates(
        election_id: int, constituency_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        find_constituency(db, election_id, constituency_id)
        rows = db.scalars(
            select(Candidate)
            .where(Candidate.constituency_id == constituency_id)
            .order_by(Candidate.ballot_number, Candidate.id)
        )
        return {"items": [candidate_view(row) for row in rows]}

    @router.post(candidate_path, status_code=201)
    def create_candidate(
        election_id: int,
        constituency_id: int,
        data: CandidateCreate,
        response: Response,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        find_constituency(db, election_id, constituency_id)
        digest = creation_digest(data, constituency_id=constituency_id)
        existing = replay(db, Candidate, data.request_id, digest, response)
        if existing:
            return candidate_view(existing)
        row = Candidate(
            constituency_id=constituency_id,
            name=data.name,
            ballot_number=data.ballot_number,
            revision=1,
            created_at=timestamp(),
            updated_at=timestamp(),
            request_id=str(data.request_id),
            creation_digest=digest,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail={"code": "duplicate_configuration"}) from None
        audit(
            db,
            actor,
            "candidate_created",
            {
                "election_id": election_id,
                "constituency_id": constituency_id,
                "candidate_id": row.id,
                "revision": 1,
                "name": row.name,
                "ballot_number": row.ballot_number,
            },
        )
        commit_configuration(db)
        return candidate_view(row)

    def find_candidate(
        db: Session,
        election_id: int,
        constituency_id: int,
        candidate_id: int,
        *,
        lock: bool = False,
    ) -> Candidate:
        find_constituency(db, election_id, constituency_id)
        query = select(Candidate).where(
            Candidate.id == candidate_id, Candidate.constituency_id == constituency_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = db.scalar(query)
        if not row:
            raise HTTPException(404, detail={"code": "configuration_not_found"})
        return row

    @router.get(candidate_path + "/{candidate_id}")
    def get_candidate(
        election_id: int, constituency_id: int, candidate_id: int, db: Database, actor: Admin
    ) -> dict[str, Any]:
        return candidate_view(find_candidate(db, election_id, constituency_id, candidate_id))

    @router.put(candidate_path + "/{candidate_id}")
    def edit_candidate(
        election_id: int,
        constituency_id: int,
        candidate_id: int,
        data: CandidateEdit,
        db: Database,
        actor: Admin,
    ) -> dict[str, Any]:
        find_election(db, election_id, lock=True)
        row = find_candidate(db, election_id, constituency_id, candidate_id, lock=True)
        check_revision(row, data.revision)
        before = {"name": row.name, "ballot_number": row.ballot_number}
        row.name, row.ballot_number = data.name, data.ballot_number
        row.revision, row.updated_at = row.revision + 1, timestamp()
        audit(
            db,
            actor,
            "candidate_edited",
            {
                "election_id": election_id,
                "constituency_id": constituency_id,
                "candidate_id": row.id,
                "revision": row.revision,
                "before": before,
                "after": {"name": row.name, "ballot_number": row.ballot_number},
            },
        )
        commit_configuration(db)
        return candidate_view(row)

    return router
