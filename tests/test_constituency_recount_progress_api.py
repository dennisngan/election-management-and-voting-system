"""Wide recount completion history survives later replacement obligations."""

from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, box_staff
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.results_support import save_result_round
from tests.tally_support import complete_f1_command
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_progress_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _read(client: TestClient, path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _wide_instruction(
    setup: dict, event_at: str, reason: str, expected_round_number: int = 2,
) -> tuple[str, dict]:
    supervisor = setup["clients"]["supervisor"]
    target = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
    options = _read(supervisor, target)
    assert options["can_instruct"] is True
    assert len(options["scope_sources"]) == 2
    setup["clock"].value += timedelta(minutes=10)
    response = supervisor.post(target, json={
        "request_id": str(uuid4()), "basis_digest": options["basis_digest"],
        "scope_sources": options["scope_sources"], "event_at": event_at,
        "reason": reason, "password": READY_PASSWORD,
    })
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert len(receipt["members"]) == 2
    assert [row["round"]["round_number"] for row in receipt["members"]] == [
        expected_round_number, expected_round_number,
    ]
    assert [row["round"]["revision"] for row in receipt["members"]] == [1, 1]
    assert [row["round"]["status"] for row in receipt["members"]] == ["draft", "draft"]
    assert [row["round"]["actual_counted_quantity"] for row in receipt["members"]] == [None, None]
    assert [[vote["quantity"] for vote in row["round"]["candidate_votes"]]
            for row in receipt["members"]] == [[None, None], [None, None]]
    return target, receipt


def _progress(supervisor: TestClient, target: str, instruction_id: int) -> dict:
    instructions = _read(supervisor, target)["instructions"]
    return next(row for row in instructions if row["id"] == instruction_id)


def _member_path(member: dict) -> str:
    instruction = member["instruction"]
    basis = member["round"]["scope_basis"]
    return (
        f"/api/workspace/stations/{basis['station_id']}"
        f"/counting-scopes/{instruction['scope_id']}/rounds/{member['round']['id']}"
    )


def _submit_fresh_member(
    setup: dict, counter: TestClient, member: dict, quantities: list[int],
    actual_quantity: int, f1_event_at: str, f2_event_at: str,
) -> dict:
    path = _member_path(member)
    options = _read(counter, path.rsplit("/", 1)[0])
    setup["clock"].value += timedelta(minutes=10)
    instruction_time = datetime.fromisoformat(member["instruction"]["event_at"])
    assert instruction_time < datetime.fromisoformat(f1_event_at)
    assert datetime.fromisoformat(f1_event_at) < datetime.fromisoformat(f2_event_at)
    assert datetime.fromisoformat(f2_event_at) < setup["clock"].value
    command = complete_f1_command(
        options, expected_revision=1, event_at=f1_event_at,
        actual_counted_quantity=actual_quantity,
    )
    for row, quantity in zip(command["candidate_votes"], quantities, strict=True):
        row["quantity"] = quantity
    saved = counter.put(path, json=command)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert saved.json()["scope_basis"] == member["round"]["scope_basis"]
    assert [row["quantity"] for row in saved.json()["candidate_votes"]] == quantities
    determination = counter.put(path + "/f2", json=complete_f2_command(
        options, expected_revision=2, event_at=f2_event_at,
    ))
    assert determination.status_code == 200, determination.text
    assert determination.json()["revision"] == 3
    assert determination.json()["count_inputs_complete"] is True
    assert [row["quantity"] for row in determination.json()["final_candidate_votes"]] == quantities
    setup["clock"].value += timedelta(minutes=1)
    submitted = counter.post(path + "/submit", json={
        "request_id": str(uuid4()), "expected_revision": 3,
        "scope_revision": options["scope"]["revision"],
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["revision"] == 4
    return submitted.json()


def _approve_member(setup: dict, supervisor: TestClient, member: dict) -> dict:
    setup["clock"].value += timedelta(minutes=1)
    response = supervisor.post(_member_path(member) + "/approve", json={
        "request_id": str(uuid4()), "expected_revision": 4,
        "scope_revision": member["round"]["scope_revision"], "password": READY_PASSWORD,
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["revision"] == 5
    assert response.json()["approval_valid"] is True
    assert response.json()["contributes_to_result"] is False
    return response.json()


def _select_member(setup: dict, supervisor: TestClient, member: dict) -> dict:
    setup["clock"].value += timedelta(minutes=1)
    response = supervisor.post(_member_path(member) + "/select", json={
        "request_id": str(uuid4()), "expected_revision": 5,
        "scope_revision": member["round"]["scope_revision"],
        "expected_selection_revision": 1, "password": READY_PASSWORD,
    })
    assert response.status_code == 200, response.text
    selected = response.json()
    assert selected["selection"]["revision"] == 2
    assert selected["selection"]["round_id"] == member["round"]["id"]
    assert selected["contributes_to_result"] is True
    return selected


def _frozen_members(instruction: dict) -> list[dict]:
    return [{key: deepcopy(row[key]) for key in (
        "station_id", "scope_id", "local_instruction_id", "new_round_id",
        "new_round_number", "scope_source", "source_context",
    )} for row in instruction["members"]]


def _completion_events(instruction: dict) -> list[dict]:
    return [{key: row[key] for key in (
        "completed_at", "completion_selection_id", "completion_selection_revision",
        "completion_round_revision_id",
    )} for row in instruction["members"]]


def _assert_original_outcome(supervisor: TestClient, setup: dict, original: dict) -> None:
    request_id = original["instruction"]["request_id"]
    path = (
        f"/api/workspace/constituencies/{setup['constituency_id']}"
        f"/request-outcomes/{request_id}?workflow=constituency_recount"
    )
    assert _read(supervisor, path) == {
        "request_id": request_id, "workflow": "constituency_recount",
        "status": "committed", "record": original,
    }
    assert [row["round"]["revision"] for row in original["members"]] == [1, 1]
    assert [row["round"]["status"] for row in original["members"]] == ["draft", "draft"]


def test_member_progress_requires_selection_and_repeat_wide_keeps_first_completion(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        baseline = _read(supervisor, result_path)
        assert baseline["complete"] is True
        assert [row["quantity"] for row in baseline["candidate_totals"]] == [6, 4]
        n3_source = next(row for row in baseline["contributions"]
                         if row["scope_id"] == setup["n3_scope"]["id"])
        assert [row["quantity"] for row in n3_source["final_candidate_votes"]] == [0, 0]
        target, receipt = _wide_instruction(
            setup, "2026-11-16T00:05:42.123456+08:00", "Review both required North scopes.",
        )
        original = deepcopy(receipt)
        instruction_id = receipt["instruction"]["id"]
        frozen = _frozen_members(receipt["instruction"])
        n1, n3 = receipt["members"]
        assert [row["instruction"]["scope_id"] for row in (n1, n3)] == [
            setup["scope"]["id"], setup["n3_scope"]["id"],
        ]
        pending = _progress(supervisor, target, instruction_id)
        assert pending["completed_member_count"] == 0 and pending["historical_complete"] is False
        assert [row["progress"] for row in pending["members"]] == ["incomplete", "incomplete"]
        assert pending["completed_at"] is None
        submitted = _submit_fresh_member(
            setup, setup["clients"]["receiveronly"], n1, [7, 3], 10,
            "2026-11-16T00:11:12.123456+08:00", "2026-11-16T00:12:17.654321+08:00",
        )
        assert submitted["completed_at"] is not None
        progress = _progress(supervisor, target, instruction_id)
        assert progress["members"][0]["progress"] == "submitted"
        assert progress["completed_member_count"] == 0
        assert progress["members"][0]["completed_at"] is None
        _approve_member(setup, supervisor, n1)
        progress = _progress(supervisor, target, instruction_id)
        assert progress["members"][0]["progress"] == "approved"
        assert progress["completed_member_count"] == 0
        assert progress["members"][0]["completed_at"] is None
        assert _read(supervisor, result_path)["contributions"] == []
        n1_selected = _select_member(setup, supervisor, n1)
        partial = _progress(supervisor, target, instruction_id)
        assert partial["completed_member_count"] == 1 and partial["historical_complete"] is False
        assert [row["progress"] for row in partial["members"]] == ["completed", "incomplete"]
        assert partial["members"][0]["completed_at"] == n1_selected["selection"]["selected_at"]
        assert partial["completed_at"] is None
        result = _read(supervisor, result_path)
        assert [row["quantity"] for row in result["candidate_totals"]] == [7, 3]
        assert [row["scope_id"] for row in result["contributions"]] == [setup["scope"]["id"]]
        assert [(row["scope_id"], row["code"]) for row in result["pending"]] == [
            (setup["n3_scope"]["id"], "recount_pending"),
        ]
        assert result["complete"] is False and result["provisional"] is True
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [setup["n3_station_id"]],
        ) as (n3_counter, _):
            _submit_fresh_member(
                setup, n3_counter, n3, [0, 0], 0,
                "2026-11-16T00:24:12.123456+08:00", "2026-11-16T00:25:17.654321+08:00",
            )
            _approve_member(setup, supervisor, n3)
            n3_selected = _select_member(setup, supervisor, n3)
        complete = _progress(supervisor, target, instruction_id)
        assert complete["completed_member_count"] == 2 and complete["historical_complete"] is True
        assert [row["progress"] for row in complete["members"]] == ["completed", "completed"]
        assert complete["completed_at"] == n3_selected["selection"]["selected_at"]
        assert complete["completed_at"] != n1_selected["selection"]["selected_at"]
        assert [row["completion_selection_revision"] for row in complete["members"]] == [2, 2]
        assert _frozen_members(complete) == frozen
        result = _read(supervisor, result_path)
        assert result["complete"] is True and result["provisional"] is True
        assert result["pending"] == []
        assert [row["quantity"] for row in result["candidate_totals"]] == [7, 3]
        assert {row["scope_id"] for row in result["contributions"]} == {
            setup["scope"]["id"], setup["n3_scope"]["id"],
        }
        _assert_original_outcome(supervisor, setup, original)
        first_events = _completion_events(complete)
        _, second = _wide_instruction(
            setup, "2026-11-16T00:40:42.222222+08:00", "Repeat both completed North scopes.",
            expected_round_number=3,
        )
        history = _read(supervisor, target)["instructions"]
        assert [row["id"] for row in history] == [second["instruction"]["id"], instruction_id]
        later, preserved = history
        assert later["historical_complete"] is False and later["completed_member_count"] == 0
        assert [row["progress"] for row in later["members"]] == ["incomplete", "incomplete"]
        assert preserved["historical_complete"] is True and preserved["is_latest"] is False
        assert preserved["completed_member_count"] == 2
        assert preserved["completed_at"] == complete["completed_at"]
        assert preserved["scope_sources"] == complete["scope_sources"]
        assert _frozen_members(preserved) == frozen
        assert _completion_events(preserved) == first_events
        assert [row["current_required_round_id"] for row in preserved["members"]] == [
            row["round"]["id"] for row in second["members"]
        ]
        result = _read(supervisor, result_path)
        assert result["contributions"] == []
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        assert result["complete"] is False and result["provisional"] is True
        assert {row["scope_id"] for row in result["pending"]} == {
            setup["scope"]["id"], setup["n3_scope"]["id"],
        }
        assert {row["code"] for row in result["pending"]} == {"recount_pending"}
        _assert_original_outcome(supervisor, setup, original)


def test_later_local_recount_preserves_wide_completion_and_requires_its_new_round(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        baseline = _read(supervisor, result_path)
        assert baseline["complete"] is True
        assert [row["quantity"] for row in baseline["candidate_totals"]] == [6, 4]
        n3_source = next(row for row in baseline["contributions"]
                         if row["scope_id"] == setup["n3_scope"]["id"])
        assert [row["quantity"] for row in n3_source["final_candidate_votes"]] == [0, 0]
        target, receipt = _wide_instruction(
            setup, "2026-11-16T00:05:42.123456+08:00", "Complete one constituency recount.",
        )
        original = deepcopy(receipt)
        n1, n3 = receipt["members"]
        _submit_fresh_member(
            setup, setup["clients"]["receiveronly"], n1, [7, 3], 10,
            "2026-11-16T00:11:12.123456+08:00", "2026-11-16T00:12:17.654321+08:00",
        )
        _approve_member(setup, supervisor, n1)
        n1_selected = _select_member(setup, supervisor, n1)
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [setup["n3_station_id"]],
        ) as (n3_counter, _):
            _submit_fresh_member(
                setup, n3_counter, n3, [0, 0], 0,
                "2026-11-16T00:24:12.123456+08:00", "2026-11-16T00:25:17.654321+08:00",
            )
            _approve_member(setup, supervisor, n3)
            n3_selected = _select_member(setup, supervisor, n3)
        completed = _progress(supervisor, target, receipt["instruction"]["id"])
        assert completed["historical_complete"] is True and completed["completed_member_count"] == 2
        assert completed["completed_at"] == n3_selected["selection"]["selected_at"]
        assert [row["completion_selection_revision"] for row in completed["members"]] == [2, 2]
        frozen, events = _frozen_members(completed), _completion_events(completed)
        assert _read(supervisor, result_path)["complete"] is True
        setup["clock"].value += timedelta(minutes=10)
        local_path = (
            f"/api/workspace/stations/{setup['stations']['N1']['id']}"
            f"/counting-scopes/{setup['scope']['id']}/recounts"
        )
        local_response = supervisor.post(local_path, json={
            "request_id": str(uuid4()), "scope_revision": setup["scope"]["revision"],
            "expected_selection_revision": 2, "source_round_id": n1_selected["id"],
            "source_round_revision": 5, "event_at": "2026-11-16T00:40:42.222222+08:00",
            "reason": "A later local instruction must not erase the wide completion.",
            "password": READY_PASSWORD,
        })
        assert local_response.status_code == 201, local_response.text
        local = local_response.json()
        assert local["round"]["round_number"] == 3 and local["round"]["revision"] == 1
        assert local["round"]["id"] != n1["round"]["id"]
        assert local["round"]["scope_basis"] == n1["round"]["scope_basis"]
        preserved = _progress(supervisor, target, receipt["instruction"]["id"])
        assert preserved["historical_complete"] is True and preserved["completed_member_count"] == 2
        assert preserved["is_latest"] is True
        assert preserved["completed_at"] == completed["completed_at"]
        assert preserved["scope_sources"] == completed["scope_sources"]
        assert _frozen_members(preserved) == frozen
        assert _completion_events(preserved) == events
        assert [row["progress"] for row in preserved["members"]] == ["completed", "completed"]
        assert preserved["members"][0]["new_round_id"] == n1["round"]["id"]
        assert preserved["members"][0]["current_required_round_id"] == local["round"]["id"]
        assert preserved["members"][1]["current_required_round_id"] == n3["round"]["id"]
        result = _read(supervisor, result_path)
        assert result["complete"] is False and result["provisional"] is True
        assert [row["quantity"] for row in result["candidate_totals"]] == [0, 0]
        assert [row["scope_id"] for row in result["contributions"]] == [setup["n3_scope"]["id"]]
        assert [(row["scope_id"], row["code"]) for row in result["pending"]] == [
            (setup["scope"]["id"], "recount_pending"),
        ]
        _assert_original_outcome(supervisor, setup, original)
