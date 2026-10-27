"""Validate immutable operational receipts against their saved command target."""

import re
from datetime import datetime
from typing import Any


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _same_time(first: Any, second: Any) -> bool:
    try:
        return datetime.fromisoformat(first) == datetime.fromisoformat(second)
    except (TypeError, ValueError):
        return False


def _physical_receipt(command: dict[str, Any], record: dict[str, Any], source: str) -> bool:
    payload = command["payload"]
    decision_revision = payload.get("expected_decision_revision")
    if (
        type(decision_revision) is not int or decision_revision < 0
        or record["revision"] != payload.get("expected_revision")
        or record["status"] != "submitted"
        or not record["source_current"]
        or not isinstance(record.get("physical_decisions"), list)
        or not isinstance(record.get("physical_comparisons"), list)
    ):
        return False
    matches = [
        row for row in record["physical_decisions"]
        if isinstance(row, dict) and row.get("source") == source
        and row.get("revision") == decision_revision + 1
    ]
    if len(matches) != 1:
        return False
    decision = matches[0]
    accepted_at = decision.get("accepted_at")
    if not isinstance(accepted_at, str):
        return False
    try:
        timestamp_valid = datetime.fromisoformat(accepted_at).utcoffset() is not None
    except (TypeError, ValueError):
        return False
    if not (
        timestamp_valid and _positive(decision.get("id"))
        and decision.get("round_id") == record["id"]
        and decision.get("reviewed_revision") == record["revision"]
        and decision.get("reviewed_revision_id") == record["revision_id"]
        and decision.get("scope_revision") == payload.get("scope_revision")
        and decision.get("actor_id") == command["actor_id"]
        and decision.get("reason") == payload.get("reason")
        and decision.get("valid") is True and decision.get("is_current") is True
        and decision.get("applies_to_revision") is True
        and isinstance(decision.get("fingerprint"), str)
        and re.fullmatch(r"[0-9a-f]{64}", decision["fingerprint"])
    ):
        return False
    return any(
        isinstance(row, dict) and row.get("source") == source
        and row.get("available") is True and row.get("status") == "accepted"
        and row.get("acceptance") == decision
        and all(row.get(key) == decision.get(key) for key in (
            "expected_quantity", "actual_quantity", "difference_quantity"
        ))
        for row in record["physical_comparisons"]
    )


def _recount_instruction_receipt(
    command: dict[str, Any], record: Any, station_id: int, scope_id: int
) -> bool:
    if command["method"] != "POST" or command["station_id"] != station_id:
        return False
    if not isinstance(record, dict) or set(record) != {"instruction", "round"}:
        return False
    instruction, round = record["instruction"], record["round"]
    if not isinstance(instruction, dict) or not isinstance(round, dict):
        return False
    payload = command["payload"]
    if not (
        all(_positive(instruction.get(key)) for key in (
            "id", "scope_id", "scope_revision", "scope_revision_id", "source_round_id",
            "source_round_revision", "source_round_revision_id", "new_round_id",
            "new_round_number", "actor_id",
        ))
        and instruction.get("request_id") == command["request_id"] == payload.get("request_id")
        and instruction["actor_id"] == command["actor_id"]
        and instruction["scope_id"] == scope_id
        and all(instruction.get(key) == payload.get(key) for key in (
            "scope_revision", "source_round_id", "source_round_revision", "reason"
        ))
        and _same_time(instruction.get("event_at"), payload.get("event_at"))
        and instruction["source_round_id"] != instruction["new_round_id"]
        and instruction.get("status") == "pending" and instruction.get("is_latest") is True
        and instruction.get("current_satisfied") is False
    ):
        return False
    entered_at = instruction.get("entered_at")
    if not isinstance(entered_at, str):
        return False
    try:
        if datetime.fromisoformat(entered_at).utcoffset() is None:
            return False
    except ValueError:
        return False
    basis = round.get("scope_basis")
    return bool(
        round.get("id") == instruction["new_round_id"]
        and round.get("round_number") == instruction["new_round_number"]
        and round.get("scope_id") == scope_id
        and round.get("scope_revision") == instruction["scope_revision"]
        and type(round.get("revision")) is int and round["revision"] == 1
        and _positive(round.get("revision_id")) and round.get("status") == "draft"
        and round.get("f1_complete") is False and round.get("selected") is False
        and round.get("approval_valid") is False
        and isinstance(basis, dict) and basis.get("revision_id") == instruction["scope_revision_id"]
        and all(round.get(key) is None for key in (
            "event_at", "entered_at", "actor_id", "questionable_quantity",
            "actual_counted_quantity", "f2", "completed_at", "approved_at", "approved_by",
        ))
        and round.get("revision_actor_id") == instruction["actor_id"]
        and _same_time(round.get("revision_event_at"), instruction["event_at"])
        and _same_time(round.get("revision_entered_at"), entered_at)
        and round.get("physical_decisions") == []
        and all(isinstance(round.get(key), list)
                and all(isinstance(row, dict) and row.get("quantity") is None for row in round[key])
                for key in ("candidate_votes", "invalid_papers"))
    )


def valid_operational_receipt(command: dict[str, Any], record: Any) -> bool:
    """Accept only a canonical workflow DTO identifying this original operation."""
    instruction_path = re.fullmatch(
        r"/api/workspace/stations/([1-9][0-9]*)/counting-scopes/([1-9][0-9]*)/recounts",
        command["path"],
    )
    if command["workflow"] == "count" and instruction_path is not None:
        return _recount_instruction_receipt(
            command, record, int(instruction_path[1]), int(instruction_path[2])
        )
    if not isinstance(record, dict) or not all(
        _positive(record.get(key)) for key in ("id", "revision")
    ):
        return False
    payload, path = command["payload"], command["path"]
    if command["workflow"] == "count":
        target = re.fullmatch(
            r"/api/workspace/stations/[1-9][0-9]*/counting-scopes/([1-9][0-9]*)"
            r"/rounds(?:/([1-9][0-9]*)(?:/([a-z0-9-]+|physical-differences/(?:stock|turnout)/accept))?)?",
            path
        )
        if target is None:
            return False
        scope_id, round_id, action = target.groups()
        if (
            record.get("scope_id") != int(scope_id)
            or (round_id is not None and record["id"] != int(round_id))
            or record.get("scope_revision") != payload.get("scope_revision")
            or not _positive(record.get("revision_id"))
            or record.get("status") not in {"draft", "submitted", "approved"}
            or not all(isinstance(record.get(key), list)
                       for key in ("candidate_votes", "invalid_papers", "blockers"))
            or not all(type(record.get(key)) is bool
                       for key in ("is_current", "source_current", "f1_complete"))
        ):
            return False
        expected = payload.get("expected_revision", 0)
        if action in (
            "physical-differences/stock/accept", "physical-differences/turnout/accept"
        ):
            return _physical_receipt(command, record, action.split("/")[1])
        if action == "select":
            selection = record.get("selection")
            return bool(
                record["revision"] == expected
                and isinstance(selection, dict)
                and selection.get("round_id") == record["id"]
                and selection.get("actor_id") == command["actor_id"]
                and selection.get("revision") == payload.get("expected_selection_revision", 0) + 1
            )
        if action == "approve":
            return bool(
                record["revision"] == expected + 1 and record["status"] == "approved"
                and record.get("revision_actor_id") == command["actor_id"]
                and record.get("approved_by") == command["actor_id"]
                and record.get("reviewed_revision") == expected
                and _positive(record.get("reviewed_revision_id"))
            )
        return bool(record["revision"] == expected + 1
                    and record.get("revision_actor_id") == command["actor_id"])
    if record.get("station_id") != command["station_id"]:
        return False
    if command["workflow"] == "allocation":
        target = re.fullmatch(r".*/allocations(?:/([1-9][0-9]*))?", path)
        counter = record.get("counter")
        return bool(
            target is not None
            and (target[1] is None or record["id"] == int(target[1]))
            and record["revision"] == payload.get("revision", 0) + 1
            and record.get("status") == "recorded"
            and record.get("actor_id") == command["actor_id"]
            and isinstance(counter, dict) and counter.get("id") == payload.get("counter_id")
            and all(record.get(key) == payload.get(key)
                    for key in ("series", "serial_from", "serial_to"))
            and _same_time(record.get("event_at"), payload.get("event_at"))
            and type(record.get("quantity")) is int
        )
    if command["workflow"] == "turnout":
        target = re.fullmatch(r".*/turnout/([1-9][0-9]*)(?:/(submit|approve|amend))?", path)
        if target is None:
            return False
        index, action = target.groups()
        expected = payload.get("expected_revision", 0)
        expected += 0 if action in {"submit", "approve"} else 1
        actor_key = {"submit": "submitted_by", "approve": "approved_by"}.get(action, "actor_id")
        return bool(
            record.get("period_index") == int(index)
            and record["revision"] == expected
            and record.get("schedule_revision") == payload.get("expected_schedule_revision")
            and record.get("status")
            == {"submit": "submitted", "approve": "approved"}.get(action, "draft")
            and record.get(actor_key) == command["actor_id"]
            and isinstance(record.get("start_at"), str) and isinstance(record.get("end_at"), str)
            and isinstance(record.get("provenance"), str)
        )
    return False
