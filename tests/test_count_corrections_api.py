"""Reasoned F1/F2 corrections through authenticated public count APIs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def _f1_command(
    options: dict[str, Any], *, expected_revision: int = 0, questionable: int = 0
) -> dict[str, Any]:
    actual = 5
    command = complete_f1_command(
        options,
        expected_revision=expected_revision,
        questionable_quantity=questionable,
        actual_counted_quantity=actual,
        notes="Original F1 paper tally note.",
    )
    command["candidate_votes"][0]["quantity"] = actual - questionable
    return command


def _prepared_round(
    setup: dict[str, Any], *, questionable: int = 0,
    determination_started_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    counter, path = setup["counter"], setup["rounds_path"]
    options = counter.get(path).json()
    f1_command = _f1_command(options, questionable=questionable)
    first = counter.post(path, json=f1_command)
    assert first.status_code == 201, first.text
    f1 = first.json()
    f2_command = complete_f2_command(
        options,
        determination_started_at=determination_started_at,
        notes="Original F2 determination note.",
    )
    if questionable:
        f2_command["accepted_votes"][0]["quantity"] = questionable
    saved = counter.put(f"{path}/{f1['id']}/f2", json=f2_command)
    assert saved.status_code == 200, saved.text
    return options, f1, saved.json(), f"{path}/{f1['id']}"


def _submit_approve_select(
    setup: dict[str, Any], target: str, options: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scope_revision = options["scope"]["revision"]
    submitted = setup["counter"].post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "scope_revision": scope_revision,
        },
    )
    assert submitted.status_code == 200, submitted.text
    approved = setup["clients"]["supervisor"].post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": scope_revision,
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = setup["clients"]["supervisor"].post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 4,
            "scope_revision": scope_revision,
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.text
    return submitted.json(), approved.json(), selected.json()


def _amend_f1(options: dict[str, Any], expected_revision: int, **changes: Any) -> dict[str, Any]:
    command = _f1_command(options, expected_revision=expected_revision, questionable=1)
    command.update(
        request_id=str(uuid4()),
        amendment_reason="Rechecked the original tally sheet and corrected the entry.",
        discard_f2=True,
        **changes,
    )
    return command


def test_f1_correction_stays_in_approved_selected_round_and_preserves_old_history(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, f1, f2, target = _prepared_round(setup)
        submitted, approved, selected = _submit_approve_select(setup, target, options)
        assert submitted["revision"] == 3
        assert approved["revision"] == 4
        assert selected["selection"]["revision"] == 1

        ordinary = setup["counter"].put(
            target,
            json=_amend_f1(options, expected_revision=4),
        )
        assert ordinary.status_code == 409, ordinary.text
        assert ordinary.json()["detail"]["code"] == "count_round_read_only"

        amendment = _amend_f1(options, expected_revision=4)
        missing_reason = setup["counter"].post(
            target + "/amend-f1",
            json={**amendment, "request_id": str(uuid4()), "amendment_reason": "  "},
        )
        assert missing_reason.status_code == 422, missing_reason.text

        no_discard = setup["counter"].post(
            target + "/amend-f1",
            json={**amendment, "request_id": str(uuid4()), "discard_f2": False},
        )
        assert no_discard.status_code == 409, no_discard.text

        corrected = setup["counter"].post(target + "/amend-f1", json=amendment)
        assert corrected.status_code == 200, corrected.text
        record = corrected.json()
        assert record["id"] == f1["id"] == f2["id"]
        assert record["round_number"] == 1 and record["revision"] == 5
        assert record["status"] == "draft"
        assert record["count_complete"] is False
        assert record["f2"] is None
        assert record["questionable_quantity"] == 1
        assert record["approval_valid"] is False and record["selected"] is False
        assert record["selection"]["revision"] == 1
        assert record["selection"]["valid"] is False

        wrong_role = setup["clients"]["polling"].post(
            target + "/amend-f1",
            json=_amend_f1(options, expected_revision=5),
        )
        assert wrong_role.status_code == 403, wrong_role.text

        history = setup["counter"].get(target).json()
        assert history["record"] == record
        assert [row["revision"] for row in history["history"]] == [5, 4, 3, 2, 1]
        assert history["history"][1]["status"] == "approved"
        assert history["history"][1]["approved_at"] == approved["approved_at"]
        assert history["history"][1]["f2"] == f2["f2"]
        assert history["history"][2]["completed_at"] == submitted["completed_at"]
        assert history["history"][1]["is_current"] is False

        rounds = setup["counter"].get(setup["rounds_path"]).json()["rounds"]
        assert len(rounds) == 1 and rounds[0]["id"] == f1["id"]


def test_f2_correction_reconciles_outcomes_then_requires_renewed_review_and_selection(
    admin: TestClient,
    database_url: str,
) -> None:
    start = "2026-11-15T23:18:12.123456+08:00"
    with tally_setup(admin, database_url) as setup:
        options, f1, f2, target = _prepared_round(
            setup, questionable=1, determination_started_at=start
        )
        submitted, approved, selected = _submit_approve_select(setup, target, options)
        original_event = f2["f2"]["determination_event"]
        reason = next(
            row for row in options["f2_invalid_reasons"] if not row["is_other"]
        )
        corrected_command = complete_f2_command(
            options,
            expected_revision=4,
            determination_started_at=start,
            amendment_reason="The original rejection was read from the marked paper again.",
        )
        next(
            row for row in corrected_command["rejected_papers"] if row["reason_id"] == reason["id"]
        )["quantity"] = 1
        corrected_command["request_id"] = str(uuid4())
        corrected = setup["counter"].post(target + "/amend-f2", json=corrected_command)
        assert corrected.status_code == 200, corrected.text
        record = corrected.json()
        assert record["id"] == f1["id"] == f2["id"]
        assert record["round_number"] == 1 and record["revision"] == 5
        assert record["status"] == "draft" and record["count_complete"] is False
        assert record["f1_complete"] is True
        assert record["accepted_questionable_quantity"] == 0
        assert record["rejected_questionable_quantity"] == 1
        assert record["f2"]["determination_event"] == original_event
        assert record["event_at"] == f1["event_at"]
        assert record["entered_at"] == f1["entered_at"]
        assert record["actor_id"] == f1["actor_id"]
        assert record["revision_amendment_reason"] == corrected_command["amendment_reason"]
        assert record["approval_valid"] is False and record["selected"] is False
        assert record["selection"]["valid"] is False
        assert (
            record["selection"]["round_revision_id"]
            == selected["selection"]["round_revision_id"]
        )

        history = setup["counter"].get(target).json()["history"]
        assert [row["revision"] for row in history] == [5, 4, 3, 2, 1]
        assert history[1]["status"] == "approved"
        assert history[1]["approved_at"] == approved["approved_at"]
        assert history[1]["f2"]["determination_event"] == original_event
        assert history[2]["completed_at"] == submitted["completed_at"]

        renewed = setup["counter"].post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 5,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert renewed.status_code == 200, renewed.text
        renewed_approval = setup["clients"]["supervisor"].post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 6,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert renewed_approval.status_code == 200, renewed_approval.text
        renewed_selection = setup["clients"]["supervisor"].post(
            target + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 7,
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 1,
                "password": READY_PASSWORD,
            },
        )
        assert renewed_selection.status_code == 200, renewed_selection.text
        assert renewed_selection.json()["selection"]["revision"] == 2
        assert renewed_selection.json()["selection"]["valid"] is True
        assert len(setup["counter"].get(setup["rounds_path"]).json()["rounds"]) == 1


def _revise_ready_scope(setup: dict[str, Any]) -> dict[str, Any]:
    receiver = setup["clients"]["receiveronly"]
    scope = setup["scope"]
    path = setup["paths"]["n1_counting_scopes"] + f"/{scope['id']}"
    revised = receiver.put(
        path,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "reference": scope["reference"],
            "event_at": scope["event_at"],
            "box_revisions":[
                {"box_id": row["id"], "revision": row["revision"]}
                for row in scope["box_basis"]
            ],
            "accounting_revisions": [
                {"station_id": row["station_id"], "revision": row["revision"]}
                for row in scope["accounting_basis"]
            ],
            "notes": "Same received-box basis rechecked.",
            "amendment_reason": "Rechecked the scope against its current source records.",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == 2 and revised.json()["count_ready"] is False
    submitted = receiver.post(
        path + "/submit",
        json={"request_id": str(uuid4()), "expected_revision": 2},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    return submitted.json()


def test_f1_correction_requires_explicit_refresh_for_new_ready_scope_basis(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, f1, _, target = _prepared_round(setup)
        _, approved, selected = _submit_approve_select(
            setup, target, setup["counter"].get(setup["rounds_path"]).json()
        )
        scope = _revise_ready_scope(setup)
        current_options = setup["counter"].get(setup["rounds_path"]).json()
        no_refresh = setup["counter"].post(
            target + "/amend-f1",
            json=_amend_f1(
                current_options,
                expected_revision=4,
                refresh_basis=False,
                scope_revision=scope["revision"],
            ),
        )
        assert no_refresh.status_code == 409, no_refresh.text
        assert no_refresh.json()["detail"]["code"] == "count_round_basis_stale"

        refreshed = setup["counter"].post(
            target + "/amend-f1",
            json=_amend_f1(
                current_options,
                expected_revision=4,
                refresh_basis=True,
                scope_revision=scope["revision"],
            ),
        )
        assert refreshed.status_code == 200, refreshed.text
        record = refreshed.json()
        assert record["id"] == f1["id"] and record["round_number"] == 1
        assert record["revision"] == 5 and record["status"] == "draft"
        assert record["scope_revision"] == scope["revision"] == 2
        assert record["source_current"] is True
        assert record["approval_valid"] is False and record["selected"] is False
        assert (
            record["selection"]["round_revision_id"]
            == selected["selection"]["round_revision_id"]
        )
        history = setup["counter"].get(target).json()["history"]
        assert history[1]["revision"] == 4 and history[1]["approved_at"] == approved["approved_at"]
        assert history[1]["scope_revision"] == 1
        assert len(setup["counter"].get(setup["rounds_path"]).json()["rounds"]) == 1


def test_two_counting_officers_cannot_amend_from_the_same_count_revision(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, _, _, target = _prepared_round(setup)
        submitted = setup["counter"].post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        clients = (setup["counter"], setup["clients"]["bothcounting"])
        barrier = Barrier(2)

        def amend(client: TestClient) -> Any:
            command = _amend_f1(options, expected_revision=3)
            barrier.wait(timeout=5)
            return client.post(target + "/amend-f1", json=command)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(amend, client) for client in clients]
            responses = [future.result() for future in futures]
        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["detail"]["code"] == "revision_conflict"
        current = setup["counter"].get(target)
        assert current.status_code == 200, current.text
        assert current.json()["record"]["revision"] == 4
        assert current.json()["record"]["status"] == "draft"
