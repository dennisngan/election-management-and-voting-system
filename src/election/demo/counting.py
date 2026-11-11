"""Prepare one local physical count using the normal staff APIs."""

from typing import Any


def _remember(api: Any, context: dict[str, Any], name: str, value: Any) -> Any:
    context[name] = value
    api.save()
    return value


def prepare_counting(api: Any, context: dict[str, Any]) -> None:
    """Freeze and approve accounting, receive a box, and save a complete draft count."""
    counting = api.as_role("counting_officer")
    polling = api.as_role("polling_officer")
    supervisor = api.as_role("supervisor")
    station_id = context["station_id"]
    base = f"/api/workspace/stations/{station_id}"
    times = context["times"]
    scenario = context["scenario"]

    options = counting.request("GET", base + "/accounting")
    eligible = [row for row in options["special_options"] if row["source_current"]]
    turnout_options = [row["record"] for row in options["turnout_options"] if row["approval_valid"]]
    if not eligible or not turnout_options:
        raise RuntimeError("Complete polling preparation before importing the counting stage.")
    special = max(eligible, key=lambda row: (row["event_at"], row["id"]))
    turnout = max(turnout_options, key=lambda row: row["period_index"])
    accounting = counting.step(
        "accounting-draft",
        "PUT",
        base + "/accounting",
        {
            "request_id": api.key("accounting-draft"),
            "expected_revision": 0,
            "special_paper_id": special["id"],
            "special_paper_revision": special["revision"],
            "turnout_period_index": turnout["period_index"],
            "turnout_revision": turnout["revision"],
            "notes": (
                "Synthetic demo: 520 received, 300 issued, 220 never issued; no special papers."
            ),
        },
    )
    accounting = counting.step(
        "accounting-submit",
        "POST",
        base + "/accounting/submit",
        {
            "request_id": api.key("accounting-submit"),
            "expected_revision": accounting["revision"],
        },
    )
    accounting = supervisor.step(
        "accounting-approve",
        "POST",
        base + "/accounting/approve",
        {
            "request_id": api.key("accounting-approve"),
            "expected_revision": accounting["revision"],
            "password": supervisor.password,
        },
    )
    _remember(api, context, "accounting", accounting)

    box = polling.step(
        "box-prepare",
        "POST",
        base + "/boxes",
        {
            "request_id": api.key("box-prepare"),
            "box_reference": "DEMO-BOX-01",
            "seal_reference": "DEMO-SEAL-01",
            "prepared_at": times["closing_complete"],
        },
    )
    box = counting.step(
        "box-receive",
        "POST",
        f"{base}/boxes/{box['id']}/receipt",
        {
            "request_id": api.key("box-receive"),
            "expected_revision": box["revision"],
            "event_at": times["conversion"],
            "reason": "Synthetic demo box retained for local counting.",
        },
    )
    _remember(api, context, "box", box)
    for kind, event_at, box_id in (
        ("conversion_complete", times["conversion"], None),
        ("first_box_opening", times["box_open"], box["id"]),
    ):
        counting.step(
            "milestone-" + kind,
            "PUT",
            base + "/boxes/milestones/" + kind,
            {
                "request_id": api.key("milestone-" + kind),
                "expected_revision": 0,
                "event_at": event_at,
                "box_id": box_id,
            },
        )

    scope = counting.step(
        "counting-scope-draft",
        "POST",
        base + "/counting-scopes",
        {
            "request_id": api.key("counting-scope-draft"),
            "expected_revision": 0,
            "reference": "DEMO-COUNT-01",
            "event_at": times["box_open"],
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
            "accounting_revisions": [
                {"station_id": station_id, "revision": accounting["revision"]}
            ],
            "notes": "All received boxes from this demo station; counted once locally.",
        },
    )
    scope = counting.step(
        "counting-scope-submit",
        "POST",
        f"{base}/counting-scopes/{scope['id']}/submit",
        {
            "request_id": api.key("counting-scope-submit"),
            "expected_revision": scope["revision"],
        },
    )
    _remember(api, context, "counting_scope", scope)
    rounds_base = f"{base}/counting-scopes/{scope['id']}/rounds"
    round_options = counting.request("GET", rounds_base)
    candidates = round_options["candidates"]
    if len(candidates) != len(scenario["votes"]):
        raise RuntimeError("Demo candidate list differs from the prepared vote totals.")
    invalid_reasons = round_options["invalid_reasons"]
    if not any(reason["code"] == "gc-f1-d" for reason in invalid_reasons):
        raise RuntimeError("The configured Unmarked invalid-ballot reason is unavailable.")
    round_record = counting.step(
        "count-f1-draft",
        "POST",
        rounds_base,
        {
            "request_id": api.key("count-f1-draft"),
            "expected_revision": 0,
            "scope_revision": scope["revision"],
            "event_at": times["count"],
            "candidate_votes": [
                {"candidate_id": candidate["id"], "quantity": quantity}
                for candidate, quantity in zip(candidates, scenario["votes"], strict=True)
            ],
            "invalid_papers": [
                {
                    "reason_id": reason["id"],
                    "reason_revision": reason["revision"],
                    "quantity": scenario["invalid"] if reason["code"] == "gc-f1-d" else 0,
                }
                for reason in invalid_reasons
            ],
            "questionable_quantity": 0,
            "actual_counted_quantity": scenario["turnout"],
            "notes": "Synthetic demo: 170 and 125 valid votes plus 5 unmarked papers = 300.",
        },
    )
    round_record = counting.step(
        "count-f2-draft",
        "PUT",
        f"{rounds_base}/{round_record['id']}/f2",
        {
            "request_id": api.key("count-f2-draft"),
            "expected_revision": round_record["revision"],
            "scope_revision": scope["revision"],
            "event_at": times["count"],
            "determination_started_at": None,
            "accepted_votes": [
                {"candidate_id": candidate["id"], "quantity": 0} for candidate in candidates
            ],
            "rejected_papers": [
                {
                    "reason_id": reason["id"],
                    "reason_revision": reason["revision"],
                    "quantity": 0,
                }
                for reason in round_options["f2_invalid_reasons"]
            ],
            "notes": "Explicit zero determination outcomes: no questionable papers in this demo.",
        },
    )
    if not round_record["count_inputs_complete"]:
        raise RuntimeError("The imported count is incomplete; inspect the saved count blockers.")
    _remember(api, context, "count_round", round_record)


def prepare_results(api: Any, context: dict[str, Any]) -> None:
    """Submit, approve and select the prepared count, then preserve the final outcome."""
    counting = api.as_role("counting_officer")
    supervisor = api.as_role("supervisor")
    station_id = context["station_id"]
    scope = context["counting_scope"]
    round_record = context["count_round"]
    base = (
        f"/api/workspace/stations/{station_id}/counting-scopes/{scope['id']}"
        f"/rounds/{round_record['id']}"
    )
    round_record = counting.step(
        "count-submit",
        "POST",
        base + "/submit",
        {
            "request_id": api.key("count-submit"),
            "expected_revision": round_record["revision"],
            "scope_revision": scope["revision"],
        },
    )
    round_record = supervisor.step(
        "count-approve",
        "POST",
        base + "/approve",
        {
            "request_id": api.key("count-approve"),
            "expected_revision": round_record["revision"],
            "scope_revision": scope["revision"],
            "password": supervisor.password,
        },
    )
    round_record = supervisor.step(
        "count-select",
        "POST",
        base + "/select",
        {
            "request_id": api.key("count-select"),
            "expected_revision": round_record["revision"],
            "scope_revision": scope["revision"],
            "expected_selection_revision": 0,
            "password": supervisor.password,
        },
    )
    _remember(api, context, "selected_count_round", round_record)
    constituency_id = scope["context"]["constituency"]["id"]
    results_path = f"/api/workspace/constituencies/{constituency_id}/results"
    results = supervisor.request("GET", results_path)
    expected = context["scenario"]["votes"]
    actual = [row["quantity"] for row in results["candidate_totals"]]
    if not results["complete"] or actual != expected:
        raise RuntimeError("The selected constituency result differs from the demo scenario.")

    election_base = f"/api/workspace/elections/{context['election_id']}"
    if "completion_review" not in context:
        review = supervisor.request("GET", election_base + "/completion")
        if not review["can_finalize"]:
            codes = ", ".join(str(row["code"]) for row in review["blockers"])
            raise RuntimeError("Demo election is not ready for finalization: " + codes)
        _remember(api, context, "completion_review", review)
    review = context["completion_review"]
    finalization = supervisor.step(
        "election-finalize",
        "POST",
        election_base + "/finalizations",
        {
            "request_id": api.key("election-finalize"),
            "expected_election_revision": review["election"]["revision"],
            "basis_digest": review["basis_digest"],
            "password": supervisor.password,
        },
    )
    _remember(api, context, "finalization", finalization)
    results = supervisor.request("GET", results_path)
    if not results["complete"] or results["provisional"]:
        raise RuntimeError("The final demo result did not become complete and finalized.")
    _remember(api, context, "results", results)
    supervisor.request("GET", results_path + "/statement?locale=en")
