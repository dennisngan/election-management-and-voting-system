"""Validate immutable operational receipts against their saved command target."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5


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


def _complete_blank_rows(record: dict[str, Any]) -> bool:
    blockers = record.get("blockers")
    if not isinstance(blockers, list) or not all(isinstance(row, dict) for row in blockers):
        return False
    for field, identity, missing_code in (
        ("candidate_votes", "candidate_id", "f1_candidate_missing"),
        ("invalid_papers", "reason_id", "f1_invalid_reason_missing"),
    ):
        rows = record.get(field)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return False
        identifiers = [row.get(identity) for row in rows]
        missing = [row.get(identity) for row in blockers if row.get("code") == missing_code]
        if (not all(_positive(value) for value in identifiers)
                or len(set(identifiers)) != len(identifiers)
                or identifiers != missing
                or field == "candidate_votes" and not identifiers):
            return False
        if any(row.get("quantity") is not None for row in rows):
            return False
    return True


def _constituency_recount_receipt(command: dict[str, Any], record: Any) -> bool:
    target = re.fullmatch(r"/api/workspace/constituencies/([1-9][0-9]*)/recounts", command["path"])
    if (target is None or command["method"] != "POST"
            or not _positive(command.get("station_id"))
            or not isinstance(record, dict) or set(record) != {"instruction", "members"}):
        return False
    parent, receipts = record["instruction"], record["members"]
    payload = command["payload"]
    sources = payload.get("scope_sources")
    keys = {"station_id", "scope_id", "scope_revision", "source_round_id",
            "source_round_revision", "expected_selection_revision"}
    if not (
        isinstance(parent, dict) and isinstance(receipts, list)
        and isinstance(sources, list) and sources
        and all(isinstance(source, dict) and set(source) == keys
                and all(_positive(value) for value in source.values()) for source in sources)
        and len({source["scope_id"] for source in sources}) == len(sources)
        and sources == sorted(sources, key=lambda source: (
            source["station_id"], source["scope_id"],
        ))
        and all(_positive(parent.get(key)) for key in ("id", "actor_id", "constituency_id"))
        and parent.get("constituency_id") == int(target[1])
        and parent.get("actor_id") == command["actor_id"]
        and parent.get("request_id") == command["request_id"] == payload.get("request_id")
        and parent.get("reason") == payload.get("reason")
        and parent.get("basis_digest") == payload.get("basis_digest")
        and parent.get("scope_sources") == sources
        and _same_time(parent.get("event_at"), payload.get("event_at"))
        and type(parent.get("member_count")) is int and parent["member_count"] == len(sources)
        and type(parent.get("completed_member_count")) is int
        and parent["completed_member_count"] == 0
        and parent.get("historical_complete") is False and parent.get("completed_at") is None
        and parent.get("is_latest") is True
        and isinstance(parent.get("members"), list)
        and len(parent["members"]) == len(receipts) == len(sources)
    ):
        return False
    context = parent.get("context")
    if not (
        isinstance(context, dict)
        and all(isinstance(context.get(key), dict) and _positive(context[key].get("id"))
                for key in ("constituency", "election"))
        and context["constituency"]["id"] == int(target[1])
    ):
        return False
    try:
        if any(not isinstance(parent.get(key), str)
               or datetime.fromisoformat(parent[key]).utcoffset() is None
               for key in ("event_at", "entered_at")):
            return False
        request_id = UUID(command["request_id"])
    except (TypeError, ValueError):
        return False
    parent_provenance = {key: parent[key] for key in (
        "id", "request_id", "constituency_id", "actor_id", "reason", "event_at", "entered_at",
        "member_count",
    )}
    parent_provenance["scope_ids"] = [source["scope_id"] for source in sources]
    round_ids, instruction_ids = set(), set()
    for source, member, receipt in zip(sources, parent["members"], receipts, strict=True):
        if not isinstance(member, dict) or not isinstance(receipt, dict):
            return False
        local_id = str(uuid5(request_id, f"scope:{source['scope_id']}"))
        local_command = {
            "method": "POST", "station_id": source["station_id"],
            "actor_id": command["actor_id"], "request_id": local_id,
            "payload": {
                **{key: value for key, value in source.items()
                   if key not in {"station_id", "scope_id"}},
                "request_id": local_id, "event_at": payload["event_at"],
                "reason": payload["reason"],
            },
        }
        if not _recount_instruction_receipt(
            local_command, receipt, source["station_id"], source["scope_id"],
        ):
            return False
        instruction, round = receipt["instruction"], receipt["round"]
        if not _complete_blank_rows(round):
            return False
        frozen = member.get("source_context")
        source_context = frozen.get("context") if isinstance(frozen, dict) else None
        if not (
            isinstance(frozen, dict) and isinstance(source_context, dict)
            and all(isinstance(source_context.get(key), dict)
                    and _positive(source_context[key].get("id"))
                    for key in ("station", "constituency", "election"))
            and source_context["station"]["id"] == source["station_id"]
            and source_context["constituency"]["id"] == context["constituency"]["id"]
            and source_context["election"]["id"] == context["election"]["id"]
            and isinstance(frozen.get("scope_reference"), str)
            and frozen["scope_reference"].strip()
        ):
            return False
        if not (
            all(_positive(member.get(key)) for key in (
                "station_id", "scope_id", "local_instruction_id", "new_round_id",
                "new_round_number", "round_revision", "current_required_round_id",
            ))
            and all(_positive(round.get(key)) for key in (
                "id", "round_number", "scope_id", "scope_revision", "revision_id", "revision",
                "revision_actor_id",
            ))
            and member.get("station_id") == source["station_id"]
            and member.get("scope_id") == source["scope_id"]
            and member.get("scope_source") == source
            and member.get("local_instruction_id") == instruction["id"]
            and instruction.get("constituency_recount") == parent_provenance
            and round.get("required_recount") == instruction
            and round.get("recount_instruction") == instruction
            and round.get("recount_pending") is True
            and all(round.get(key) is False for key in (
                "contributes_to_result", "count_complete", "count_inputs_complete", "f2_complete",
            ))
            and member.get("new_round_id") == round["id"]
            and member.get("new_round_number") == round["round_number"]
            and member.get("round_revision") == 1 and member.get("progress") == "incomplete"
            and member.get("current_required_round_id") == round["id"]
            and all(member.get(key) is None for key in (
                "completed_at", "completion_selection_id", "completion_selection_revision",
                "completion_round_revision_id",
            ))
            and isinstance(member.get("source_context"), dict)
            and round["scope_basis"].get("id") == source["scope_id"]
            and round["scope_basis"].get("station_id") == source["station_id"]
        ):
            return False
        if round["id"] in round_ids or instruction["id"] in instruction_ids:
            return False
        round_ids.add(round["id"])
        instruction_ids.add(instruction["id"])
    return True


def _election_completion_receipt(command: dict[str, Any], record: Any) -> bool:
    target = re.fullmatch(
        r"/api/workspace/elections/([1-9][0-9]*)/(finalizations|reopenings)", command["path"],
    )
    if (
        target is None or command["method"] != "POST"
        or command.get("namespace") != "election" or "station_id" in command
        or command.get("election_id") != int(target[1])
        or not isinstance(record, dict)
        or set(record) != {"request_id", "election", "active_election_id", "event"}
    ):
        return False
    payload, election, event = command["payload"], record["election"], record["event"]
    expected = payload.get("expected_election_revision")
    finalizing = target[2] == "finalizations"
    if not (
        _positive(expected) and isinstance(election, dict) and isinstance(event, dict)
        and record["request_id"] == command["request_id"] == payload.get("request_id")
        and election.get("id") == int(target[1])
        and election.get("status") == ("finalized" if finalizing else "active")
        and type(election.get("revision")) is int and election["revision"] == expected + 1
        and isinstance(election.get("name"), str)
        and record["active_election_id"] == (None if finalizing else int(target[1]))
        and all(_positive(event.get(key)) for key in (
            "id", "election_id", "election_revision", "actor_id",
        ))
        and event["election_id"] == int(target[1])
        and event["election_revision"] == election["revision"]
        and event["actor_id"] == command["actor_id"]
        and event.get("kind") == ("finalization" if finalizing else "reopening")
        and isinstance(event.get("basis_digest"), str)
        and re.fullmatch(r"[0-9a-f]{64}", event["basis_digest"])
        and isinstance(event.get("outcome"), dict)
        and event["outcome"].get("election") == election
        and isinstance(event.get("accepted_at"), str)
    ):
        return False
    try:
        if datetime.fromisoformat(event["accepted_at"]).utcoffset() is None:
            return False
    except ValueError:
        return False
    if finalizing:
        outcome = event["outcome"]
        return bool(
            event["basis_digest"] == payload.get("basis_digest")
            and event.get("previous_finalization_id") is None and event.get("reason") == ""
            and isinstance(outcome.get("sources"), dict)
            and isinstance(outcome.get("results"), list) and outcome["results"]
            and all(isinstance(result, dict) and result.get("status") == "finalized"
                    and result.get("provisional") is False for result in outcome["results"])
        )
    return bool(
        _positive(payload.get("previous_finalization_id"))
        and event.get("previous_finalization_id") == payload["previous_finalization_id"]
        and event.get("reason") == payload.get("reason")
        and isinstance(event.get("reason"), str) and event["reason"].strip()
        and event["outcome"].get("previous_finalization_id")
        == payload["previous_finalization_id"]
    )


def valid_operational_receipt(command: dict[str, Any], record: Any) -> bool:
    """Accept only a canonical workflow DTO identifying this original operation."""
    if command["workflow"] == "election_completion":
        return _election_completion_receipt(command, record)
    if command["workflow"] == "constituency_recount":
        return _constituency_recount_receipt(command, record)
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
