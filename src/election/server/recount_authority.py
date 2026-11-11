"""Recheck Supervisor access after serializing an operational recount decision."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.lifecycle_models import ActiveElection
from election.server.models import Account


def lock_recount_supervisor(db: Session, actor: Account) -> Account:
    """Reject credentials revoked while this request waited for the election lock."""
    if actor.role != "supervisor":
        raise HTTPException(403, detail={"code": "supervisor_required"})
    authenticated_revision = actor.revision
    db.scalar(select(ActiveElection).where(ActiveElection.id == 1).with_for_update())
    current = db.scalar(
        select(Account)
        .where(Account.id == actor.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Staff edits/reset revoke every session and increment this revision while
    # holding the same Account row. Keep that lock through the authorized read/write.
    if (
        current is None
        or not current.enabled
        or current.must_change_password
        or current.revision != authenticated_revision
    ):
        raise HTTPException(401, detail={"code": "session_expired"})
    if current.role != "supervisor":
        raise HTTPException(403, detail={"code": "supervisor_required"})
    return current
