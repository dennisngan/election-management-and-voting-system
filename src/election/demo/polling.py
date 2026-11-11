"""Prepare a small polling demonstration through the normal authenticated API."""

from datetime import UTC, datetime
from typing import Any


def _approved_polling_event(
    api: Any, context: dict[str, Any], kind: str, event_at: str
) -> dict[str, Any]:
    polling = api.as_role("polling_officer")
    supervisor = api.as_role("supervisor")
    path = f"/api/workspace/stations/{context['station_id']}/polling/{kind}"
    label = f"polling/{kind}"
    draft = polling.step(
        label + "/save",
        "PUT",
        path,
        {
            "request_id": api.key(label + "/save"),
            "revision": 0,
            "event_at": event_at,
            "reason": "Prepared fictional demonstration record",
        },
    )
    submitted = polling.step(
        label + "/submit",
        "POST",
        path + "/submit",
        {"request_id": api.key(label + "/submit"), "revision": draft["revision"]},
    )
    approved: dict[str, Any] = supervisor.step(
        label + "/approve",
        "POST",
        path + "/approve",
        {
            "request_id": api.key(label + "/approve"),
            "revision": submitted["revision"],
            "password": supervisor.password,
        },
    )
    return approved


def prepare_polling(api: Any, context: dict[str, Any]) -> None:
    """Create 520 received papers, 300 ordinary issues, and reviewed turnout."""
    polling = api.as_role("polling_officer")
    supervisor = api.as_role("supervisor")
    base = f"/api/workspace/stations/{context['station_id']}"
    times = context["times"]
    scenario = context["scenario"]
    stock = scenario["stock"]
    series = stock["series"]
    context.setdefault("polling", {})["opening"] = _approved_polling_event(
        api, context, "opening", times["opening"]
    )
    context["stock_receipt"] = polling.step(
        "polling/stock",
        "POST",
        base + "/stock",
        {
            "request_id": api.key("polling/stock"),
            "series": series,
            "event_at": times["receipt"],
            "ranges": [
                {
                    "pool": pool,
                    "serial_from": stock[pool + "_from"],
                    "serial_to": stock[pool + "_to"],
                }
                for pool in ("ordinary", "replacement", "tendered")
            ],
            **{
                pool + "_quantity": int(stock[pool + "_to"]) - int(stock[pool + "_from"]) + 1
                for pool in ("ordinary", "replacement", "tendered")
            },
        },
    )
    allocations = []
    remaining = []
    counters = context["counters"]
    if len(counters) != 2:
        raise ValueError("The demonstration requires exactly two issuance counters")
    for index, counter in enumerate(counters):
        start = int(stock["ordinary_from"]) + index * 200
        end = start + 199
        label = f"polling/allocation/{index + 1}"
        allocations.append(
            polling.step(
                label,
                "POST",
                base + "/allocations",
                {
                    "request_id": api.key(label),
                    "counter_id": counter["id"],
                    "series": series,
                    "serial_from": f"{start:06d}",
                    "serial_to": f"{end:06d}",
                    "event_at": times["allocation"],
                },
            )
        )
        remaining.append(
            {
                "counter_id": counter["id"],
                "ranges": [
                    {
                        "series": series,
                        "serial_from": f"{end - 49:06d}",
                        "serial_to": f"{end:06d}",
                    }
                ],
            }
        )
    context["allocations"] = allocations
    snapshot = polling.step(
        "polling/snapshot",
        "POST",
        base + "/stock-snapshots",
        {
            "request_id": api.key("polling/snapshot"),
            "event_at": times["snapshot"],
            "counters": remaining,
        },
    )
    context["snapshot"] = snapshot
    context["special_papers"] = polling.step(
        "polling/special-papers",
        "POST",
        base + "/special-papers",
        {
            "request_id": api.key("polling/special-papers"),
            "event_at": times["turnout_end"],
            "stock_snapshot_id": snapshot["id"],
            "stock_snapshot_revision": snapshot["revision"],
            "series": [
                {
                    "series": series,
                    "replacement_issued_quantity": 0,
                    "spoilt_original_quantity": 0,
                    "tendered_issued_quantity": 0,
                    "retrieved_refused_quantity": 0,
                    "retrieved_found_quantity": 0,
                    "retrieved_held_quantity": 0,
                }
            ],
        },
    )
    schedule = polling.request("GET", base + "/turnout")["schedule"]
    turnout_draft = polling.step(
        "polling/turnout/save",
        "PUT",
        base + "/turnout/1",
        {
            "request_id": api.key("polling/turnout/save"),
            "expected_revision": 0,
            "expected_schedule_revision": schedule["revision"],
            "supplied_hourly": scenario["turnout"],
            "supplied_cumulative": scenario["turnout"],
            "source_context": "Fictional supplied turnout for the demonstration; no live EPR",
            "event_at": times["turnout_end"],
        },
    )
    submitted = polling.step(
        "polling/turnout/submit",
        "POST",
        base + "/turnout/1/submit",
        {
            "request_id": api.key("polling/turnout/submit"),
            "expected_revision": turnout_draft["revision"],
            "expected_schedule_revision": schedule["revision"],
        },
    )
    context["turnout"] = supervisor.step(
        "polling/turnout/approve",
        "POST",
        base + "/turnout/1/approve",
        {
            "request_id": api.key("polling/turnout/approve"),
            "expected_revision": submitted["revision"],
            "expected_schedule_revision": schedule["revision"],
            "password": supervisor.password,
        },
    )
    categories = polling.request("GET", base + "/complaint-categories")["items"]
    category = next(item for item in categories if item["code"] == "9" and item["enabled"])
    # Send UTC consistently, including endpoints accepting historical case timestamps.
    complaint_time = datetime.fromisoformat(times["snapshot"]).astimezone(UTC).isoformat()
    context["complaint"] = polling.step(
        "polling/complaint",
        "POST",
        base + "/complaints",
        {
            "request_id": api.key("polling/complaint"),
            "case_reference": "DEMO-C001",
            "received_at": complaint_time,
            "category_id": category["id"],
            "expected_category_revision": category["revision"],
            "description": "Fictional case: a visitor requests clearer entrance signs.",
            "work_status": "in_progress",
        },
    )
    context["queue"] = polling.step(
        "polling/queue",
        "POST",
        base + "/queue",
        {
            "request_id": api.key("polling/queue"),
            "expected_revision": 0,
            "event_at": times["snapshot"],
            "band": "under_30",
            "reason": "Fictional initial queue observation for the demonstration",
        },
    )
    api.save()


def finish_polling(api: Any, context: dict[str, Any]) -> None:
    """Approve the two separate closure events before preparing counting."""
    records = context.setdefault("polling", {})
    records["admission_closure"] = _approved_polling_event(
        api, context, "admission_closure", context["times"]["closing_admission"]
    )
    records["service_completion"] = _approved_polling_event(
        api, context, "service_completion", context["times"]["closing_complete"]
    )
    api.save()
