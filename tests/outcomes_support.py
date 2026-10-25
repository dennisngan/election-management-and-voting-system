"""Explicit observed outcome commands for public count workflows."""

from uuid import uuid4


def complete_f2_command(options: dict, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "scope_revision": options["scope"]["revision"],
        "event_at": "2026-11-15T23:20:17.654321+08:00",
        "determination_started_at": None,
        "accepted_votes": [
            {"candidate_id": row["id"], "quantity": 0} for row in options["candidates"]
        ],
        "rejected_papers": [
            {
                "reason_id": row["id"],
                "reason_revision": row["revision"],
                "quantity": 0,
                "explanation": "",
            }
            for row in options["f2_invalid_reasons"]
        ],
        "notes": "",
        **changes,
    }
