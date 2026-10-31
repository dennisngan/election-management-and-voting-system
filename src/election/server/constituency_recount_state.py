"""Original constituency membership and first completion, beside latest local obligations."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.constituency_recount_models import (
    ConstituencyRecountInstruction,
    ConstituencyRecountMember,
)
from election.server.counting_rounds import latest_round_revision
from election.server.local_recount_models import LocalRecountInstruction
from election.server.polling import as_utc
from election.server.recount_state import scope_recount_state


def constituency_recount_instruction(
    db: Session, instruction: ConstituencyRecountInstruction, *, is_latest: bool,
) -> dict[str, Any]:
    rows = db.execute(
        select(ConstituencyRecountMember, LocalRecountInstruction)
        .join(LocalRecountInstruction, LocalRecountInstruction.id == (
            ConstituencyRecountMember.local_instruction_id
        ))
        .where(ConstituencyRecountMember.instruction_id == instruction.id)
        .order_by(ConstituencyRecountMember.position)
        .with_for_update()
    )
    members = []
    for member, local in rows:
        state = scope_recount_state(db, member.scope_id, None)
        original = next(row for row in state["instructions"] if row["id"] == local.id)
        revision = latest_round_revision(db, local.new_round_id)
        assert revision is not None
        progress = (
            "completed" if original["completed_at"] is not None
            else "approved" if revision.status == "approved"
            else "submitted" if revision.status == "submitted" else "incomplete"
        )
        members.append({
            "station_id": member.station_id, "scope_id": member.scope_id,
            "local_instruction_id": local.id, "progress": progress,
            "new_round_id": local.new_round_id,
            "new_round_number": original["new_round_number"],
            "round_revision": revision.revision,
            "scope_source": deepcopy(instruction.data["scope_sources"][member.position]),
            "source_context": deepcopy(instruction.data["source_contexts"][member.position]),
            "completed_at": original["completed_at"],
            "completion_selection_id": original["completion_selection_id"],
            "completion_selection_revision": original["completion_selection_revision"],
            "completion_round_revision_id": original["completion_round_revision_id"],
            "current_required_round_id": state["latest_instruction"]["new_round_id"],
        })
    completed = [row["completed_at"] for row in members if row["completed_at"] is not None]
    complete = bool(members) and len(completed) == len(members)
    return {
        "id": instruction.id, "request_id": instruction.request_id,
        "constituency_id": instruction.constituency_id, "actor_id": instruction.actor_id,
        "reason": instruction.reason, "event_at": as_utc(instruction.event_at),
        "entered_at": as_utc(instruction.entered_at), "basis_digest": instruction.basis_digest,
        "context": deepcopy(instruction.data["context"]),
        "scope_sources": deepcopy(instruction.data["scope_sources"]),
        "members": members, "member_count": len(members),
        "completed_member_count": len(completed), "historical_complete": complete,
        "completed_at": max(completed, key=datetime.fromisoformat) if complete else None,
        "is_latest": is_latest,
    }


def constituency_recount_history(db: Session, constituency_id: int) -> list[dict[str, Any]]:
    rows = list(db.scalars(
        select(ConstituencyRecountInstruction)
        .where(ConstituencyRecountInstruction.constituency_id == constituency_id)
        .order_by(ConstituencyRecountInstruction.id.desc()).with_for_update()
    ))
    return [constituency_recount_instruction(db, row, is_latest=index == 0)
            for index, row in enumerate(rows)]
