"""Election-scoped complaint display labels with preserved source provenance."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.complaint_models import (
    ComplaintCategory,
    ComplaintCategoryRevision,
    ComplaintRequest,
)
from election.server.configuration_models import Election
from election.server.lifecycle_models import ActiveElection
from election.server.models import Account, AuditEvent
from election.server.polling import as_utc, station_scope

DEFAULT_CATEGORIES = (
    ("9", "Polling arrangements", "投票安排", "投票安排", 61, False),
    ("10", "NCZ arrangements", "NCZ 安排", "NCZ 安排", 61, False),
    (
        "11",
        "Illegal conduct at the polling station (e.g. photo-taking)",
        "投票站內的違法行為（例如拍照）",
        "投票站内的违法行为（例如拍照）",
        61,
        False,
    ),
    (
        "12",
        "Against Returning Officer or his/her staff",
        "針對選舉主任或其職員",
        "针对选举主任或其职员",
        61,
        False,
    ),
    (
        "30",
        "Miscellaneous (please specify nature)",
        "其他（請註明性質）",
        "其他（请注明性质）",
        62,
        True,
    ),
)


class ComplaintCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class CategoryInput(ComplaintCommand):
    label_en: str = Field(min_length=1, max_length=255)
    label_tc: str = Field(min_length=1, max_length=255)
    label_sc: str = Field(min_length=1, max_length=255)
    enabled: bool = Field(default=True, strict=True)
    description_required: bool = Field(default=False, strict=True)

    @field_validator("label_en", "label_tc", "label_sc")
    @classmethod
    def meaningful_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonblank display label is required")
        return value


class CategoryCreate(CategoryInput):
    code: str = Field(min_length=1, max_length=64)

    @field_validator("code")
    @classmethod
    def meaningful_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A nonblank project code is required")
        return value


class CategoryEdit(CategoryInput):
    expected_revision: int = Field(ge=1, strict=True)


def complaint_digest(
    data: ComplaintCommand,
    actor_id: int,
    action: str,
    election_id: int,
    *,
    station_id: int | None = None,
    target_id: int | None = None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "actor_id": actor_id,
                "action": action,
                "election_id": election_id,
                "station_id": station_id,
                "target_id": target_id,
            "data": data.model_dump(mode="json", exclude={"request_id", "password"}),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def complaint_replay(
    db: Session, request_id: UUID, digest: str, response: Response
) -> dict[str, Any] | None:
    previous = db.scalar(
        select(ComplaintRequest)
        .where(ComplaintRequest.request_id == str(request_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if previous:
        if previous.digest != digest:
            raise HTTPException(409, detail={"code": "request_conflict"})
        response.status_code = 200
        return previous.response
    return None


def save_complaint_response(
    db: Session,
    data: ComplaintCommand,
    digest: str,
    actor_id: int,
    action: str,
    election_id: int,
    station_id: int | None,
    result: dict[str, Any],
    now: datetime,
) -> None:
    db.add(
        ComplaintRequest(
            request_id=str(data.request_id),
            election_id=election_id,
            station_id=station_id,
            actor_id=actor_id,
            action=action,
            digest=digest,
            response=result,
            entered_at=now,
        )
    )
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action="complaint_" + action,
            occurred_at=now,
            details={"election_id": election_id, "station_id": station_id, "record": result},
        )
    )


def current_category_revision(db: Session, category_id: int) -> ComplaintCategoryRevision:
    row = db.scalar(
        select(ComplaintCategoryRevision)
        .where(ComplaintCategoryRevision.category_id == category_id)
        .order_by(ComplaintCategoryRevision.revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


def seed_election_categories(
    db: Session, election_id: int, actor_id: int | None, now: datetime
) -> None:
    """Add verified defaults inside the election-creation transaction."""
    for code, english, tc, sc, page, other in DEFAULT_CATEGORIES:
        category = ComplaintCategory(
            election_id=election_id,
            code=code,
            verified_source=True,
            source_english=english,
            reference_page=page,
            is_other=other,
        )
        db.add(category)
        db.flush()
        db.add(
            ComplaintCategoryRevision(
                category_id=category.id,
                revision=1,
                label_en=english,
                label_tc=tc,
                label_sc=sc,
                enabled=True,
                description_required=other,
                entered_at=now,
                actor_id=actor_id,
            )
        )


def category_view(category: ComplaintCategory, row: ComplaintCategoryRevision) -> dict[str, Any]:
    return {
        "id": category.id,
        "election_id": category.election_id,
        "code": category.code,
        "verified_source": category.verified_source,
        "source": "verified_reference" if category.verified_source else "project_configured",
        "source_english": category.source_english,
        "reference_page": category.reference_page,
        "is_other": category.is_other,
        "revision": row.revision,
        "label_en": row.label_en,
        "label_tc": row.label_tc,
        "label_sc": row.label_sc,
        "translation_provenance": "project_translation",
        "enabled": row.enabled,
        "description_required": row.description_required,
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
    }


def category_rows(db: Session, election_id: int) -> list[dict[str, Any]]:
    categories = list(
        db.scalars(
            select(ComplaintCategory)
            .where(ComplaintCategory.election_id == election_id)
            .order_by(ComplaintCategory.id)
        )
    )
    revisions = list(
        db.scalars(
            select(ComplaintCategoryRevision)
            .join(ComplaintCategory, ComplaintCategory.id == ComplaintCategoryRevision.category_id)
            .where(ComplaintCategory.election_id == election_id)
            .order_by(ComplaintCategoryRevision.revision)
        )
    )
    latest = {row.category_id: row for row in revisions}
    return [category_view(category, latest[category.id]) for category in categories]


def complaint_categories_router(
    database: Callable[[], Generator[Session]],
    administrator: Callable[..., Account],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(tags=["Complaint categories"])
    Database = Annotated[Session, Depends(database)]
    Admin = Annotated[Account, Depends(administrator)]
    Ready = Annotated[Account, Depends(ready_account)]

    def catalog_write(
        election_id: int,
        data: CategoryInput,
        actor: Account,
        db: Session,
        response: Response,
        *,
        category_id: int | None = None,
    ) -> dict[str, Any]:
        # Every complaint command takes this global barrier before its UUID key,
        # including catalog commands for different retained elections.
        db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
        election = db.scalar(
            select(Election)
            .where(Election.id == election_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if election is None:
            raise HTTPException(404, detail={"code": "configuration_not_found"})
        if election.status == "finalized":
            raise HTTPException(409, detail={"code": "election_read_only"})
        action = "category_created" if category_id is None else "category_edited"
        digest = complaint_digest(data, actor.id, action, election_id, target_id=category_id)
        previous = complaint_replay(db, data.request_id, digest, response)
        if previous is not None:
            return previous
        if isinstance(data, CategoryCreate):
            duplicate = db.scalar(
                select(ComplaintCategory.id)
                .where(
                    ComplaintCategory.election_id == election_id,
                    ComplaintCategory.code == data.code,
                )
                .with_for_update()
            )
            if duplicate is not None:
                raise HTTPException(409, detail={"code": "complaint_category_code_exists"})
            category = ComplaintCategory(
                election_id=election_id,
                code=data.code,
                verified_source=False,
                source_english="",
                reference_page=None,
                is_other=False,
            )
            db.add(category)
            db.flush()
            revision = 1
        else:
            assert isinstance(data, CategoryEdit)
            existing_category = db.scalar(
                select(ComplaintCategory)
                .where(
                    ComplaintCategory.id == category_id,
                    ComplaintCategory.election_id == election_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing_category is None:
                raise HTTPException(404, detail={"code": "complaint_category_not_found"})
            category = existing_category
            current = current_category_revision(db, category.id)
            if current.revision != data.expected_revision:
                raise HTTPException(409, detail={"code": "revision_conflict"})
            if category.is_other and (not data.description_required or not data.enabled):
                raise HTTPException(422, detail={"code": "complaint_other_required"})
            revision = current.revision + 1
        now = timestamp()
        row = ComplaintCategoryRevision(
            category_id=category.id,
            revision=revision,
            label_en=data.label_en,
            label_tc=data.label_tc,
            label_sc=data.label_sc,
            enabled=data.enabled,
            description_required=data.description_required,
            entered_at=now,
            actor_id=actor.id,
        )
        db.add(row)
        db.flush()
        result = category_view(category, row)
        save_complaint_response(
            db,
            data,
            digest,
            actor.id,
            action,
            election_id,
            None,
            result,
            now,
        )
        db.commit()
        return result

    @router.get("/api/elections/{election_id}/complaint-categories")
    def read_categories(election_id: int, db: Database, actor: Admin) -> dict[str, Any]:
        if db.get(Election, election_id) is None:
            raise HTTPException(404, detail={"code": "configuration_not_found"})
        return {"items": category_rows(db, election_id)}

    @router.get("/api/workspace/stations/{station_id}/complaint-categories")
    def read_station_categories(station_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        _, _, election = station_scope(db, actor, station_id)
        return {"items": category_rows(db, election.id)}

    @router.post("/api/elections/{election_id}/complaint-categories", status_code=201)
    def create_category(
        election_id: int, data: CategoryCreate, db: Database, actor: Admin, response: Response
    ) -> dict[str, Any]:
        return catalog_write(election_id, data, actor, db, response)

    @router.put("/api/elections/{election_id}/complaint-categories/{category_id}")
    def edit_category(
        election_id: int,
        category_id: int,
        data: CategoryEdit,
        db: Database,
        actor: Admin,
        response: Response,
    ) -> dict[str, Any]:
        return catalog_write(election_id, data, actor, db, response, category_id=category_id)

    return router
