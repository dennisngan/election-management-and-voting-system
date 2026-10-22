"""Scoped draft lookup, create replay and stale-edit rules shared by setup routes."""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from election.server.configuration_models import Candidate, Constituency, Election
from election.server.station_models import IssuanceCounter, PollingStation


def creation_digest(data: BaseModel, **scope: int) -> str:
    return hashlib.sha256(
        json.dumps(
            {**data.model_dump(mode="json", exclude={"request_id"}), **scope},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def find_election(db: Session, election_id: int, *, lock: bool = False) -> Election:
    query = select(Election).where(Election.id == election_id)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if not row:
        raise HTTPException(404, detail={"code": "configuration_not_found"})
    if lock and row.status != "draft":
        raise HTTPException(409, detail={"code": "draft_required"})
    return row


def find_constituency(
    db: Session, election_id: int, constituency_id: int, *, lock: bool = False
) -> Constituency:
    query = select(Constituency).where(
        Constituency.id == constituency_id, Constituency.election_id == election_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if not row:
        raise HTTPException(404, detail={"code": "configuration_not_found"})
    return row


def replay[T: Election | Constituency | Candidate | PollingStation | IssuanceCounter](
    db: Session, model: type[T], key: UUID, digest: str, response: Response
) -> T | None:
    # Authentication may have opened an older REPEATABLE READ snapshot. After waiting
    # for the election lock, use a current read to find a create committed by a retry.
    row = db.scalar(select(model).where(model.request_id == str(key)).with_for_update())
    if row:
        if row.creation_digest != digest:
            raise HTTPException(409, detail={"code": "request_conflict"})
        response.status_code = 200
    return row


def commit_configuration(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": "duplicate_configuration"}) from None


def check_revision(
    row: Election | Constituency | Candidate | PollingStation | IssuanceCounter, revision: int
) -> None:
    if row.revision != revision:
        raise HTTPException(409, detail={"code": "revision_conflict"})
