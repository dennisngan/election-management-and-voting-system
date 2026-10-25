"""Bind physical-paper acceptance to its frozen basis and exact compared quantities."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_discrepancy_models import CountPhysicalDecision
from election.server.counting_totals import physical_comparisons
from election.server.polling import as_utc


def comparison_fingerprint(data: dict[str, Any], comparison: dict[str, Any]) -> str:
    basis = {
        "scope_basis": data["scope_basis"],
        "candidate_basis": [
            {key: row[key] for key in ("candidate_id", "candidate_revision")}
            for row in sorted(data["candidate_votes"], key=lambda row: row["candidate_id"])
        ],
        "comparison": comparison,
    }
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def physical_review(
    db: Session, round_id: int, data: dict[str, Any], *, revision: int, source_current: bool
) -> dict[str, Any]:
    comparisons = physical_comparisons(data)
    by_source = {row["source"]: row for row in comparisons}
    rows = list(
        db.scalars(
            select(CountPhysicalDecision)
            .where(CountPhysicalDecision.round_id == round_id)
            .order_by(CountPhysicalDecision.id.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    latest: dict[str, int] = {}
    eligible: dict[str, int] = {}
    for row in rows:
        latest.setdefault(row.source, row.id)
        if row.data["reviewed_revision"] <= revision:
            eligible.setdefault(row.source, row.id)
    decisions = []
    accepted: dict[str, dict[str, Any]] = {}
    for row in rows:
        comparison = by_source[row.source]
        applies = bool(
            eligible.get(row.source) == row.id
            and comparison["available"]
            and comparison["difference_quantity"] != 0
            and row.fingerprint == comparison_fingerprint(data, comparison)
        )
        valid = bool(source_current and applies)
        decision = {
            **row.data,
            "id": row.id,
            "round_id": row.round_id,
            "source": row.source,
            "revision": row.revision,
            "reviewed_revision_id": row.round_revision_id,
            "actor_id": row.actor_id,
            "accepted_at": as_utc(row.accepted_at),
            "reason": row.reason,
            "fingerprint": row.fingerprint,
            "is_current": latest[row.source] == row.id,
            "applies_to_revision": applies,
            "valid": valid,
        }
        decisions.append(decision)
        if valid:
            accepted[row.source] = decision
    for comparison in comparisons:
        if comparison["source"] in accepted:
            comparison.update(status="accepted", acceptance=accepted[comparison["source"]])
    return {"physical_comparisons": comparisons, "physical_decisions": decisions}
