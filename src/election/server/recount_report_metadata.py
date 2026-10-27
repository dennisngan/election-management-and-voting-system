"""Render instruction provenance separately from observations and current eligibility."""

from typing import Any

from election.server.turnout_reports import hong_kong_time

_DETAIL_FIELDS = (
    "request_id",
    "scope_revision",
    "scope_revision_id",
    "source_round_id",
    "source_round_revision",
    "source_round_revision_id",
    "new_round_id",
    "new_round_number",
    "actor_id",
    "reason",
    "event_at",
    "entered_at",
    "status",
    "completed_at",
    "completion_selection_revision",
    "current_satisfied",
)


def _value(field: str, value: Any, labels: dict[str, str]) -> str:
    if field == "current_satisfied" and value is None:
        return labels["local_recount_historical_not_current"]
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if field.endswith("_at"):
        return hong_kong_time(value)
    if field == "status":
        return labels["local_recount_state_" + value]
    return str(value)


def recount_metadata(record: dict[str, Any], labels: dict[str, str]) -> list[list[str]]:
    required = record.get("required_recount")
    if required is None:
        return []
    associated = record.get("recount_instruction")
    rows = [
        [labels["local_recount_pending"], _value("pending", record["recount_pending"], labels)],
        [
            labels["local_recount_contributes_to_result"],
            _value("contributes", record["contributes_to_result"], labels),
        ],
        [
            labels["local_recount_associated_instruction"],
            str(associated["id"]) if associated else labels["not_recorded"],
        ],
        [labels["local_recount_required_instruction"], str(required["id"])],
    ]
    contexts = [("required", required)]
    if associated is not None and associated["id"] != required["id"]:
        contexts.append(("associated", associated))
    for prefix, instruction in contexts:
        rows.extend(
            [
                labels[f"local_recount_{prefix}_{field}"],
                _value(field, instruction.get(field), labels),
            ]
            for field in _DETAIL_FIELDS
        )
    return rows
