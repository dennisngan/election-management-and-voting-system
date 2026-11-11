"""Current invalid-reason choices retain separate verified-source provenance."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.configuration_models import Election
from election.server.invalid_ballot_defaults import DEFAULT_INVALID_REASONS
from election.server.invalid_ballot_f2_defaults import DEFAULT_F2_INVALID_REASONS
from election.server.invalid_ballot_models import (
    InvalidBallotReason,
    InvalidBallotReasonRequest,
    InvalidBallotReasonRevision,
)
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.timestamps import as_utc
from election.server.turnout_basis import turnout_scope


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    label_en: str = Field(min_length=1, max_length=512)
    label_tc: str = Field(min_length=1, max_length=512)
    label_sc: str = Field(min_length=1, max_length=512)
    enabled: bool = Field(default=True, strict=True)
    explanation_required: bool = Field(default=False, strict=True)

    @field_validator("label_en", "label_tc", "label_sc")
    @classmethod
    def meaningful_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonblank display label is required")
        return value


class ReasonCreate(ReasonInput):
    code: str = Field(min_length=1, max_length=64)
    stage: Literal["f1", "f2"] = "f1"

    @field_validator("code")
    @classmethod
    def meaningful_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A nonblank project code is required")
        return value


class ReasonEdit(ReasonInput):
    expected_revision: int = Field(strict=True, ge=1)


def seed_invalid_ballot_reasons(
    db: Session,
    election_id: int,
    actor_id: int | None,
    now: datetime,
) -> None:
    for seed in (*DEFAULT_INVALID_REASONS, *DEFAULT_F2_INVALID_REASONS):
        reason = InvalidBallotReason(
            election_id=election_id,
            code=seed["code"],
            stage=seed["stage"],
            verified_source=seed["verified_source"],
            source_english=seed["source_english"],
            source_letter=seed["source_letter"],
            reference_page=seed["reference_page"],
            reference_printed_page=seed["reference_printed_page"],
            is_other=seed["is_other"],
        )
        db.add(reason)
        db.flush()
        db.add(
            InvalidBallotReasonRevision(
                reason_id=reason.id,
                revision=1,
                label_en=seed["label_en"],
                label_tc=seed["label_tc"],
                label_sc=seed["label_sc"],
                enabled=True,
                explanation_required=seed["explanation_required"],
                entered_at=now,
                actor_id=actor_id,
            )
        )


def invalid_reason_view(
    reason: InvalidBallotReason,
    row: InvalidBallotReasonRevision,
) -> dict[str, Any]:
    return {
        "id": reason.id,
        "election_id": reason.election_id,
        "code": reason.code,
        "stage": reason.stage,
        "verified_source": reason.verified_source,
        "source": "verified_reference" if reason.verified_source else "project_configured",
        "source_english": reason.source_english,
        "source_letter": reason.source_letter,
        "reference_page": reason.reference_page,
        "reference_printed_page": reason.reference_printed_page,
        "is_other": reason.is_other,
        "revision": row.revision,
        "revision_id": row.id,
        "label_en": row.label_en,
        "label_tc": row.label_tc,
        "label_sc": row.label_sc,
        "translation_provenance": "project_translation",
        "enabled": row.enabled,
        "explanation_required": row.explanation_required,
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
    }


def invalid_reason_rows(db: Session, election_id: int) -> list[dict[str, Any]]:
    reasons = list(
        db.scalars(
            select(InvalidBallotReason)
            .where(
                InvalidBallotReason.election_id == election_id,
            )
            .order_by(InvalidBallotReason.id)
            .with_for_update()
        )
    )
    revisions = list(
        db.scalars(
            select(InvalidBallotReasonRevision)
            .join(
                InvalidBallotReason,
                InvalidBallotReason.id == InvalidBallotReasonRevision.reason_id,
            )
            .where(InvalidBallotReason.election_id == election_id)
            .order_by(
                InvalidBallotReasonRevision.revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    latest = {row.reason_id: row for row in revisions}
    return [invalid_reason_view(reason, latest[reason.id]) for reason in reasons]


def catalog_election(db: Session, election_id: int, *, write: bool = False) -> Election:
    # Match count commands before any reason/revision locks, including reads.
    db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
    election = db.scalar(
        select(Election)
        .where(Election.id == election_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if election is None:
        raise HTTPException(404, detail={"code": "configuration_not_found"})
    if write and election.status == "finalized":
        raise HTTPException(409, detail={"code": "election_read_only"})
    return election


def catalog_reason(db: Session, election_id: int, reason_id: int) -> InvalidBallotReason:
    reason = db.scalar(
        select(InvalidBallotReason)
        .where(
            InvalidBallotReason.id == reason_id,
            InvalidBallotReason.election_id == election_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if reason is None:
        raise HTTPException(404, detail={"code": "invalid_reason_not_found"})
    return reason


def reason_history(db: Session, reason: InvalidBallotReason) -> list[dict[str, Any]]:
    revisions = db.scalars(
        select(InvalidBallotReasonRevision)
        .where(
            InvalidBallotReasonRevision.reason_id == reason.id,
        )
        .order_by(InvalidBallotReasonRevision.revision.desc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return [invalid_reason_view(reason, row) for row in revisions]


def invalid_ballot_reasons_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(tags=["Invalid-ballot reasons"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/api/elections/{election_id}/invalid-ballot-reasons")
    def read(
        election_id: int,
        db: Database,
        actor: Admin,
        stage: Literal["f1", "f2"] = "f1",
    ) -> dict[str, Any]:
        catalog_election(db, election_id)
        return {
            "items": [row for row in invalid_reason_rows(db, election_id) if row["stage"] == stage]
        }

    @router.get("/api/workspace/stations/{station_id}/invalid-ballot-reasons")
    def station_catalog(
        station_id: int,
        db: Database,
        actor: Ready,
        stage: Literal["f1", "f2"] = "f1",
    ) -> dict[str, Any]:
        scope = turnout_scope(db, actor, station_id)
        return {
            "items": [
                row
                for row in invalid_reason_rows(db, scope["election"]["id"])
                if row["stage"] == stage and row["enabled"]
            ]
        }

    @router.get("/api/elections/{election_id}/invalid-ballot-reasons/{reason_id}")
    def history(election_id: int, reason_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        catalog_election(db, election_id)
        reason = catalog_reason(db, election_id, reason_id)
        records = reason_history(db, reason)
        return {"record": records[0], "history": records}

    def write(
        election_id: int,
        data: ReasonInput,
        db: Session,
        actor: Account,
        response: Response,
        reason_id: int | None = None,
    ) -> dict[str, Any]:
        catalog_election(db, election_id, write=True)
        action = "created" if reason_id is None else "edited"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "actor_id": actor.id,
                    "election_id": election_id,
                    "action": action,
                    "reason_id": reason_id,
                    "data": data.model_dump(mode="json", exclude={"request_id"}),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        replay = db.scalar(
            select(InvalidBallotReasonRequest)
            .where(
                InvalidBallotReasonRequest.request_id == str(data.request_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if replay:
            if replay.digest != digest:
                raise HTTPException(409, detail={"code": "request_conflict"})
            response.status_code = 200
            return replay.response
        if isinstance(data, ReasonCreate):
            duplicate = db.scalar(
                select(InvalidBallotReason.id)
                .where(
                    InvalidBallotReason.election_id == election_id,
                    InvalidBallotReason.code == data.code,
                    InvalidBallotReason.stage == data.stage,
                )
                .with_for_update()
            )
            if duplicate is not None:
                raise HTTPException(409, detail={"code": "invalid_reason_code_exists"})
            reason = InvalidBallotReason(
                election_id=election_id,
                code=data.code,
                stage=data.stage,
                verified_source=False,
                source_english="",
                source_letter=None,
                reference_page=None,
                reference_printed_page=None,
                is_other=False,
            )
            db.add(reason)
            db.flush()
            revision = 1
        else:
            assert isinstance(data, ReasonEdit) and reason_id is not None
            reason = catalog_reason(db, election_id, reason_id)
            current = reason_history(db, reason)[0]
            if data.expected_revision != current["revision"]:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            if reason.is_other and (not data.enabled or not data.explanation_required):
                raise HTTPException(422, detail={"code": "invalid_reason_other_required"})
            revision = data.expected_revision + 1
        now = timestamp()
        row = InvalidBallotReasonRevision(
            reason_id=reason.id,
            revision=revision,
            label_en=data.label_en,
            label_tc=data.label_tc,
            label_sc=data.label_sc,
            enabled=data.enabled,
            explanation_required=data.explanation_required,
            entered_at=now,
            actor_id=actor.id,
        )
        db.add(row)
        db.flush()
        result = invalid_reason_view(reason, row)
        db.add(
            InvalidBallotReasonRequest(
                request_id=str(data.request_id),
                election_id=election_id,
                actor_id=actor.id,
                digest=digest,
                response=result,
            )
        )
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="invalid_reason_" + action,
                occurred_at=now,
                details={"election_id": election_id, "reason_id": reason.id, "record": result},
            )
        )
        db.commit()
        return result

    @router.post("/api/elections/{election_id}/invalid-ballot-reasons", status_code=201)
    def create(
        election_id: int,
        data: ReasonCreate,
        db: Database,
        actor: Admin,
        response: Response,
    ) -> dict[str, Any]:
        return write(election_id, data, db, actor, response)

    @router.put("/api/elections/{election_id}/invalid-ballot-reasons/{reason_id}")
    def edit(
        election_id: int,
        reason_id: int,
        data: ReasonEdit,
        db: Database,
        actor: Admin,
        response: Response,
    ) -> dict[str, Any]:
        return write(election_id, data, db, actor, response, reason_id)

    return router
