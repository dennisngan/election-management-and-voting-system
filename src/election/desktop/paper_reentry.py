"""Pending-paper selection shared by normal operational desktop forms."""

from copy import deepcopy
from datetime import datetime
from typing import Any

_TARGET_KEYS = {
    ("allocation", "create"): {"counter_id"},
    ("allocation", "amend"): {"counter_id", "allocation_id"},
    ("turnout", "save"): {"period_index"},
    ("turnout", "submit"): {"period_index"},
    ("count", "submit"): {"scope_id", "round_id"},
}


def _target(workflow: str, action: str, target: dict[str, int]) -> bool:
    return bool(
        set(target) == _TARGET_KEYS.get((workflow, action))
        and all(type(value) is int and value > 0 for value in target.values())
    )


def _matches(
    paper: dict[str, Any],
    *,
    station_id: int,
    workflow: str,
    action: str,
    target: dict[str, int],
) -> bool:
    if not (
        type(paper.get("id")) is int
        and paper["id"] > 0
        and paper.get("station_id") == station_id
        and paper.get("workflow") == workflow
        and paper.get("action") == action
        and paper.get("target") == target
        and _target(workflow, action, target)
        and paper.get("status") == "pending"
        and paper.get("reentry") is None
        and isinstance(paper.get("paper_reference"), str)
        and paper["paper_reference"]
        and isinstance(paper.get("original_event_at"), str)
    ):
        return False
    try:
        return (
            datetime.fromisoformat(paper["original_event_at"].replace("Z", "+00:00")).tzinfo
            is not None
        )
    except ValueError:
        return False


def paper_options(
    snapshot: dict[str, Any],
    *,
    station_id: int,
    workflow: str,
    target: dict[str, int],
    actions: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Expose only pending references matching this form's current operation."""
    outages = snapshot.get("outages")
    if not isinstance(outages, list):
        raise ValueError("invalid_response")
    options: list[dict[str, Any]] = []
    for outage in outages:
        if not isinstance(outage, dict) or not isinstance(outage.get("paper_records"), list):
            raise ValueError("invalid_response")
        for paper in outage["paper_records"]:
            if isinstance(paper, dict) and any(
                _matches(
                    paper, station_id=station_id, workflow=workflow, action=action, target=target
                )
                for action in actions
            ):
                options.append(deepcopy(paper))
    return sorted(options, key=lambda paper: paper["id"])


def paper_record_fields(
    paper: dict[str, Any],
    *,
    station_id: int,
    workflow: str,
    action: str,
    target: dict[str, int],
) -> dict[str, int]:
    """Omit legacy provenance, or bind one exact pending paper before journaling."""
    if not paper:
        return {}
    if not _matches(paper, station_id=station_id, workflow=workflow, action=action, target=target):
        raise ValueError("paper_target_conflict")
    return {"paper_record_id": paper["id"]}
