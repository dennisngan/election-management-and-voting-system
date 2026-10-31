"""Project instruction history separately from the latest replacement obligation."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.constituency_recount_models import (
    ConstituencyRecountInstruction,
    ConstituencyRecountMember,
)
from election.server.counting_round_models import (
    CountRound,
    CountRoundRevision,
    CountRoundSelection,
)
from election.server.counting_scope_models import CountingScopeRevision
from election.server.local_recount_models import LocalRecountInstruction
from election.server.polling import as_utc


def scope_recount_state(
    db: Session, scope_id: int, selection: dict[str, Any] | None
) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(
                LocalRecountInstruction, CountingScopeRevision, CountRoundRevision, CountRound,
                ConstituencyRecountInstruction,
            )
            .select_from(LocalRecountInstruction)
            .join(
                CountingScopeRevision,
                CountingScopeRevision.id == LocalRecountInstruction.scope_revision_id,
            )
            .join(
                CountRoundRevision,
                CountRoundRevision.id == LocalRecountInstruction.source_round_revision_id,
            )
            .join(CountRound, CountRound.id == LocalRecountInstruction.new_round_id)
            .outerjoin(
                ConstituencyRecountMember,
                ConstituencyRecountMember.local_instruction_id == LocalRecountInstruction.id,
            )
            .outerjoin(
                ConstituencyRecountInstruction,
                ConstituencyRecountInstruction.id == ConstituencyRecountMember.instruction_id,
            )
            .where(LocalRecountInstruction.scope_id == scope_id)
            .order_by(LocalRecountInstruction.id.desc())
            .with_for_update()
        )
    )
    if not rows:
        return {"instructions": [], "latest_instruction": None, "pending": False}
    replacement_ids = [row[0].new_round_id for row in rows]
    completions: dict[int, CountRoundSelection] = {}
    for pointer, approved in db.execute(
        select(CountRoundSelection, CountRoundRevision)
        .join(CountRoundRevision, CountRoundRevision.id == CountRoundSelection.round_revision_id)
        .where(
            CountRoundSelection.scope_id == scope_id,
            CountRoundRevision.round_id.in_(replacement_ids),
            CountRoundRevision.status == "approved",
        )
        .order_by(CountRoundSelection.revision)
        .with_for_update()
    ):
        if approved.data.get("completed_at") is not None:
            completions.setdefault(approved.round_id, pointer)
    instructions = []
    for index, (row, scope_revision, source, replacement, parent) in enumerate(rows):
        completion = completions.get(row.new_round_id)
        current = index == 0
        satisfied = bool(
            selection
            and selection.get("is_current")
            and selection.get("valid")
            and selection.get("round_id") == row.new_round_id
        )
        instructions.append(
            {
                "id": row.id,
                "request_id": row.request_id,
                "scope_id": row.scope_id,
                "scope_revision": scope_revision.revision,
                "scope_revision_id": row.scope_revision_id,
                "source_round_id": source.round_id,
                "source_round_revision": source.revision,
                "source_round_revision_id": source.id,
                "new_round_id": row.new_round_id,
                "new_round_number": replacement.round_number,
                "actor_id": row.actor_id,
                "reason": row.reason,
                "event_at": as_utc(row.event_at),
                "entered_at": as_utc(row.entered_at),
                "status": "completed" if completion else "pending",
                "is_latest": current,
                "current_satisfied": satisfied if current else None,
                "completed_at": as_utc(completion.selected_at) if completion else None,
                "completion_selection_id": completion.id if completion else None,
                "completion_selection_revision": completion.revision if completion else None,
                "completion_round_revision_id": (
                    completion.round_revision_id if completion else None
                ),
            }
        )
        if parent is not None:
            sources = parent.data["scope_sources"]
            instructions[-1]["constituency_recount"] = {
                "id": parent.id, "request_id": parent.request_id,
                "constituency_id": parent.constituency_id, "actor_id": parent.actor_id,
                "reason": parent.reason, "event_at": as_utc(parent.event_at),
                "entered_at": as_utc(parent.entered_at), "member_count": len(sources),
                "scope_ids": [source["scope_id"] for source in sources],
            }
    return {
        "instructions": instructions,
        "latest_instruction": instructions[0],
        "pending": not instructions[0]["current_satisfied"],
    }
