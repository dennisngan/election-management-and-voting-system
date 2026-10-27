"""Public API edge cases for Supervisor decisions on physical differences."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, box_staff
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def _submitted_round(setup: dict, *, actual_counted: int = 0) -> tuple[dict, str]:
    counter, path = setup["counter"], setup["rounds_path"]
    options = counter.get(path).json()
    initial = complete_f1_command(options, actual_counted_quantity=actual_counted)
    if actual_counted:
        initial["candidate_votes"][0]["quantity"] = actual_counted
    created = counter.post(path, json=initial)
    assert created.status_code == 201, created.text
    round_id = created.json()["id"]
    target = path + f"/{round_id}"
    f2_command = complete_f2_command(options)
    saved = counter.put(target + "/f2", json=f2_command)
    assert saved.status_code == 200, saved.text
    submitted = counter.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    return options, target


def _decision_command(options: dict, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": 3,
        "scope_revision": options["scope"]["revision"],
        "expected_decision_revision": 0,
        "password": READY_PASSWORD,
        "reason": "Physical stock was checked against the signed paper record.",
        **changes,
    }


def _decision_path(target: str, source: str = "stock") -> str:
    return target + f"/physical-differences/{source}/accept"


def test_physical_decision_checks_supervisor_role_password_reason_and_comparison_availability(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, target = _submitted_round(setup)
        counter = setup["counter"]
        supervisor = setup["clients"]["supervisor"]
        path = _decision_path(target)

        denied_role = counter.post(path, json=_decision_command(options))
        assert denied_role.status_code == 403, denied_role.text

        wrong_password = supervisor.post(
            path,
            json=_decision_command(options, password="Incorrect-Password-42!"),
        )
        assert wrong_password.status_code == 401, wrong_password.text

        blank_reason = supervisor.post(path, json=_decision_command(options, reason="  "))
        assert blank_reason.status_code == 422
        assert blank_reason.json()["detail"]["code"] == "physical_difference_reason_required"

        unavailable = supervisor.post(
            _decision_path(target, "turnout"), json=_decision_command(options)
        )
        assert unavailable.status_code == 409, unavailable.text
        assert unavailable.json()["detail"]["code"] == "physical_difference_unavailable"

        history = supervisor.get(target)
        assert history.status_code == 200, history.text
        assert history.json()["record"]["physical_decisions"] == []


def test_matching_physical_source_is_not_pending_for_acceptance(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, target = _submitted_round(setup, actual_counted=5)
        supervisor = setup["clients"]["supervisor"]
        rejected = supervisor.post(
            _decision_path(target), json=_decision_command(options)
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "physical_difference_not_pending"
        record = supervisor.get(target).json()["record"]
        assert record["revision"] == 3 and record["status"] == "submitted"
        assert record["physical_decisions"] == []


def test_physical_decision_rejects_stale_count_and_scope_revisions(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, target = _submitted_round(setup)
        supervisor = setup["clients"]["supervisor"]
        stale_count = supervisor.post(
            _decision_path(target),
            json=_decision_command(options, expected_revision=2),
        )
        assert stale_count.status_code == 409, stale_count.text
        assert stale_count.json()["detail"]["code"] == "revision_conflict"

        stale_scope = supervisor.post(
            _decision_path(target),
            json=_decision_command(options, scope_revision=options["scope"]["revision"] + 1),
        )
        assert stale_scope.status_code == 409, stale_scope.text
        assert stale_scope.json()["detail"]["code"] == "count_scope_revision_conflict"
        assert supervisor.get(target).json()["record"]["physical_decisions"] == []


def test_physical_decision_revision_compare_and_swap_allows_only_one_supervisor(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, target = _submitted_round(setup)
        first = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        with box_staff(
            admin, database_url, setup["clock"], "supervisor", [station_id]
        ) as (second, _):
            barrier = Barrier(2)

            def accept(client: TestClient) -> object:
                command = _decision_command(options)
                barrier.wait()
                return client.post(_decision_path(target), json=command)

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(accept, (first, second)))

        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["detail"]["code"] == "physical_decision_revision_conflict"
        record = first.get(target).json()["record"]
        assert record["revision"] == 3 and record["status"] == "submitted"
        assert len(record["physical_decisions"]) == 1
        decision = record["physical_decisions"][0]
        assert decision["revision"] == 1 and decision["reviewed_revision"] == 3


def test_physical_decision_replay_conflict_and_hard_validation_remain_separate(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options = setup["counter"].get(setup["rounds_path"]).json()
        malformed = complete_f1_command(options, actual_counted_quantity=1)
        rejected_f1 = setup["counter"].post(setup["rounds_path"], json=malformed)
        assert rejected_f1.status_code == 422
        assert rejected_f1.json()["detail"]["code"] == "f1_arithmetic_invalid"
        assert setup["counter"].get(setup["rounds_path"]).json()["rounds"] == []

        options, target = _submitted_round(setup)
        supervisor = setup["clients"]["supervisor"]
        path = _decision_path(target)
        command = _decision_command(options)
        accepted = supervisor.post(path, json=command)
        assert accepted.status_code == 200, accepted.text
        receipt = accepted.json()
        assert receipt["revision"] == 3 and receipt["status"] == "submitted"
        stock_comparison = next(
            row for row in receipt["physical_comparisons"] if row["source"] == "stock"
        )
        assert stock_comparison["status"] == "accepted"
        assert stock_comparison["acceptance"]["reason"] == command["reason"]
        assert len(receipt["physical_decisions"]) == 1

        replay = supervisor.post(
            path,
            json={**command, "request_id": command["request_id"]},
        )
        assert replay.status_code == 200 and replay.json() == receipt

        changed_reason = supervisor.post(
            path,
            json={**command, "reason": "A conflicting explanation."},
        )
        assert changed_reason.status_code == 409, changed_reason.text
        assert changed_reason.json()["detail"]["code"] == "request_conflict"

        forged_observation = supervisor.post(
            path,
            json={**_decision_command(options), "actual_quantity": 0},
        )
        assert forged_observation.status_code == 422, forged_observation.text

        import json

        public_history = json.dumps(supervisor.get(target).json())
        assert READY_PASSWORD not in public_history
        assert "Incorrect-Password-42!" not in public_history
