"""Public API fixtures for constituency-result acceptance scenarios."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command


@contextmanager
def result_setup(
    admin: TestClient, database_url: str, *, candidate_count: int = 2,
) -> Iterator[dict]:
    """Yield two constituencies, a received mixed N1 scope, and public clients."""
    with counting_setup(admin, database_url, candidates_per_constituency=candidate_count) as setup:
        receiver = setup["clients"]["receiveronly"]
        scope_path = setup["paths"]["n1_counting_scopes"]
        selected_boxes = [setup["boxes"]["local_n1"], setup["boxes"]["transferred_n2"]]
        create = receiver.post(
            scope_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Mixed received N1 and transferred N2 result scope",
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [
                    {"box_id": box["id"], "revision": box["revision"]}
                    for box in selected_boxes
                ],
                "accounting_revisions": [
                    {"station_id": setup["stations"][code]["id"], "revision": 1}
                    for code in ("N1", "N2")
                ],
            },
        )
        assert create.status_code == 201, create.text
        scope = create.json()
        submitted_scope = receiver.post(
            f"{scope_path}/{scope['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": scope["revision"]},
        )
        assert submitted_scope.status_code == 200, submitted_scope.text
        assert submitted_scope.json()["count_ready"] is True
        yield {
            **setup,
            "scope": submitted_scope.json(),
            "scope_path": scope_path,
            "rounds_path": f"{scope_path}/{scope['id']}/rounds",
            "constituency_id": setup["stations"]["N1"]["constituency_id"],
        }


def save_result_round(
    setup: dict,
    quantities: list[int],
    *,
    approve_and_select: bool,
) -> dict:
    """Save a complete round using staff-facing HTTP routes and optionally select it."""
    counter = setup["clients"]["receiveronly"]
    supervisor = setup["clients"]["supervisor"]
    rounds_path = setup["rounds_path"]
    options_response = counter.get(rounds_path)
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()
    assert len(options["candidates"]) == len(quantities)
    initial = complete_f1_command(
        options,
        questionable_quantity=0,
        actual_counted_quantity=sum(quantities),
    )
    for row, quantity in zip(initial["candidate_votes"], quantities, strict=True):
        row["quantity"] = quantity
    f1 = counter.post(rounds_path, json=initial)
    assert f1.status_code == 201, f1.text
    round_path = f"{rounds_path}/{f1.json()['id']}"
    f2 = counter.put(round_path + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    submitted = counter.post(
        round_path + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": f2.json()["revision"],
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    if not approve_and_select:
        return {"round_path": round_path, "submitted": submitted.json(), "options": options}
    approved = supervisor.post(
        round_path + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": submitted.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = supervisor.post(
        round_path + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": approved.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.text
    return {
        "round_path": round_path,
        "submitted": submitted.json(),
        "approved": approved.json(),
        "selected": selected.json(),
        "options": options,
    }


def candidate_ids_by_constituency(admin: TestClient, election_id: int) -> dict[str, list[int]]:
    response = admin.get(f"/api/elections/{election_id}/constituencies")
    assert response.status_code == 200, response.text
    candidates: dict[str, list[int]] = {}
    for constituency in response.json()["items"]:
        listed = admin.get(
            f"/api/elections/{election_id}/constituencies/{constituency['id']}/candidates"
        )
        assert listed.status_code == 200, listed.text
        candidates[constituency["code"]] = [row["id"] for row in listed.json()["items"]]
    return candidates
