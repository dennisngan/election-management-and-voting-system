"""Exact final-count projections from preserved F1 and F2 observations."""

from typing import Any


def observed_total(rows: list[dict[str, Any]]) -> int | None:
    quantities = [row["quantity"] for row in rows]
    return sum(quantities) if all(value is not None for value in quantities) else None


def f2_summary(data: dict[str, Any]) -> dict[str, Any]:
    f2 = data["f2"]
    accepted = {row["candidate_id"]: row for row in f2["accepted_votes"]}
    accepted_total = observed_total(f2["accepted_votes"])
    rejected_total = observed_total(f2["rejected_papers"])
    final_votes = []
    blockers = list(data.get("f1_blockers", data["blockers"]))
    for initial in data["candidate_votes"]:
        identity = initial["candidate_id"]
        quantity = accepted[identity]["quantity"]
        if quantity is None:
            blockers.append({"code": "f2_candidate_missing", "candidate_id": identity})
        final_votes.append(
            {
                **initial,
                "initial_quantity": initial["quantity"],
                "accepted_questionable_quantity": quantity,
                "quantity": initial["quantity"] + quantity
                if initial["quantity"] is not None and quantity is not None
                else None,
            }
        )
    for reason in f2["rejected_papers"]:
        if reason["quantity"] is None:
            blockers.append({"code": "f2_invalid_reason_missing", "reason_id": reason["reason_id"]})
    if data["questionable_quantity"] and f2["determination_started_at"] is None:
        blockers.append({"code": "determination_start_missing"})
    outcomes_known = accepted_total is not None and rejected_total is not None
    conserved = (
        accepted_total is not None
        and rejected_total is not None
        and accepted_total + rejected_total == data["questionable_quantity"]
    )
    if outcomes_known and not conserved:
        blockers.append({"code": "f2_outcomes_unbalanced"})
    final_valid = observed_total(final_votes)
    clearly_invalid = data["clearly_invalid_quantity"]
    final_invalid = (
        clearly_invalid + rejected_total
        if (clearly_invalid is not None and rejected_total is not None)
        else None
    )
    final_accounted = (
        final_valid + final_invalid
        if (final_valid is not None and final_invalid is not None)
        else None
    )
    actual = data["actual_counted_quantity"]
    arithmetic = (
        actual == final_accounted if actual is not None and final_accounted is not None else None
    )
    if arithmetic is False:
        blockers.append({"code": "final_arithmetic_invalid"})
    f2_complete = bool(
        conserved and not any(row["code"] == "determination_start_missing" for row in blockers)
    )
    return {
        "f2_complete": f2_complete,
        "count_inputs_complete": bool(data["f1_complete"] and f2_complete and arithmetic is True),
        "count_complete": data.get("completed_at") is not None,
        "accepted_questionable_quantity": accepted_total,
        "rejected_questionable_quantity": rejected_total,
        "final_candidate_votes": final_votes,
        "final_valid_quantity": final_valid,
        "final_invalid_quantity": final_invalid,
        "final_accounted_quantity": final_accounted,
        "final_arithmetic_valid": arithmetic,
        "physical_comparisons": physical_comparisons(data),
        "blockers": blockers,
    }


def physical_comparisons(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare actual count with each frozen scope estimate without coercing missing values."""
    actual = data["actual_counted_quantity"]
    comparisons = []
    for source in ("stock", "turnout"):
        expected = data["scope_basis"].get(f"estimated_box_from_{source}_quantity")
        available = actual is not None and expected is not None
        difference = actual - expected if available else None
        comparisons.append(
            {
                "source": source,
                "expected_quantity": expected,
                "actual_quantity": actual,
                "difference_quantity": difference,
                "available": available,
                "status": (
                    "unavailable"
                    if not available
                    else "matching"
                    if difference == 0
                    else "pending"
                ),
            }
        )
    return comparisons


def physical_approval_blockers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Known physical differences require review; unavailable estimates stay unknown."""
    return [
        {
            "code": "count_physical_difference_unaccepted",
            "source": comparison["source"],
            "difference_quantity": comparison["difference_quantity"],
        }
        for comparison in physical_comparisons(data)
        if comparison["available"] and comparison["status"] == "pending"
    ]
