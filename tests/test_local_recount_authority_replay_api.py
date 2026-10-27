"""Additional public acceptance of existing local recount authority/replay guards."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import INITIAL_PASSWORD, READY_PASSWORD, box_staff
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_local_recount_authority_and_original_replay_keep_one_blank_replacement(
    admin: TestClient,
    database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor = setup["clients"]["supervisor"]
        counter = setup["clients"]["receiveronly"]
        polling = setup["clients"]["polling"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        other_recounts = (
            f"/api/workspace/stations/{setup['n3_station_id']}/counting-scopes/"
            f"{setup['n3_scope']['id']}/recounts"
        )
        other_rounds_path = setup["n3_scope_path"] + f"/{setup['n3_scope']['id']}/rounds"
        assert prior["status"] == "approved" and prior["approval_valid"] is True
        assert prior["selected"] is True
        assert [row["quantity"] for row in prior["candidate_votes"]] == [6, 4]
        before_source_response = counter.get(source_path)
        assert before_source_response.status_code == 200, before_source_response.text
        before_source = before_source_response.json()
        before_rounds_response = counter.get(setup["rounds_path"])
        assert before_rounds_response.status_code == 200, before_rounds_response.text
        assert [row["id"] for row in before_rounds_response.json()["rounds"]] == [prior["id"]]
        other_before_response = supervisor.get(other_rounds_path)
        assert other_before_response.status_code == 200, other_before_response.text
        other_before = other_before_response.json()
        empty_response = supervisor.get(recount_path)
        assert empty_response.status_code == 200, empty_response.text
        assert empty_response.json()["instructions"] == []
        assert empty_response.json()["can_instruct"] is True
        setup["clock"].value += timedelta(minutes=10)
        command = {
            "request_id": str(uuid4()),
            "scope_revision": setup["scope"]["revision"],
            "expected_selection_revision": prior["selection"]["revision"],
            "source_round_id": prior["id"],
            "source_round_revision": prior["revision"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Review these same received boxes in one fresh physical tally.",
            "password": READY_PASSWORD,
        }
        created_response = supervisor.post(recount_path, json=command)
        assert created_response.status_code == 201, created_response.text
        original = created_response.json()
        instruction, blank = original["instruction"], original["round"]
        assert instruction["request_id"] == command["request_id"]
        assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert instruction["scope_id"] == scope_id
        assert instruction["source_round_id"] == prior["id"]
        assert instruction["source_round_revision_id"] == prior["revision_id"]
        assert instruction["new_round_id"] == blank["id"] != prior["id"]
        assert blank["round_number"] == 2 and blank["revision"] == 1
        assert blank["status"] == "draft" and blank["f2"] is None
        assert blank["approval_valid"] is False and blank["selected"] is False
        assert all(blank[key] is None for key in (
            "event_at", "entered_at", "actor_id", "actual_counted_quantity",
            "questionable_quantity", "completed_at",
        ))
        assert all(row["quantity"] is None for row in blank["candidate_votes"])
        assert all(row["quantity"] is None for row in blank["invalid_papers"])
        assert blank["revision_actor_id"] == instruction["actor_id"]
        assert blank["physical_decisions"] == []
        pending_response = supervisor.get(recount_path)
        assert pending_response.status_code == 200, pending_response.text
        assert pending_response.json()["pending"] is True
        assert pending_response.json()["can_instruct"] is False

        # Role and own-password checks precede even a matching cached receipt.
        for actor in (counter, polling, admin):
            for request_id in (command["request_id"], str(uuid4())):
                denied = actor.post(recount_path, json={**command, "request_id": request_id})
                assert denied.status_code == 403, denied.text
                assert denied.json()["detail"]["code"] == "supervisor_required"
        assert INITIAL_PASSWORD != READY_PASSWORD
        wrong_password = supervisor.post(
            recount_path, json={**command, "password": INITIAL_PASSWORD}
        )
        assert wrong_password.status_code == 401, wrong_password.text
        assert wrong_password.json()["detail"]["code"] == "invalid_credentials"
        fresh_pending = supervisor.post(
            recount_path, json={**command, "request_id": str(uuid4())}
        )
        assert fresh_pending.status_code == 409, fresh_pending.text
        assert fresh_pending.json()["detail"]["code"] == "local_recount_pending"

        # The original UUID/body replays BEFORE mutable pending preconditions.
        replay = supervisor.post(recount_path, json=command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == original
        for changed in (
            {**command, "reason": command["reason"] + " Revised wording."},
            {**command,
             "expected_selection_revision": command["expected_selection_revision"] + 1},
        ):
            conflict = supervisor.post(recount_path, json=changed)
            assert conflict.status_code == 409, conflict.text
            assert conflict.json()["detail"]["code"] == "request_conflict"
        # This is another real assigned scope, not an invalid/missing parent fixture.
        parent_conflict = supervisor.post(other_recounts, json=command)
        assert parent_conflict.status_code == 409, parent_conflict.text
        assert parent_conflict.json()["detail"]["code"] == "request_conflict"

        with box_staff(
            admin, database_url, setup["clock"], "supervisor", [station_id]
        ) as (other_supervisor, other_account):
            assert other_account["id"] != instruction["actor_id"]
            actor_conflict = other_supervisor.post(recount_path, json=command)
            assert actor_conflict.status_code == 409, actor_conflict.text
            assert actor_conflict.json()["detail"]["code"] == "request_conflict"
        with box_staff(
            admin, database_url, setup["clock"], "supervisor", [setup["stations"]["S1"]["id"]]
        ) as (unassigned_supervisor, _):
            for request_id in (command["request_id"], str(uuid4())):
                denied = unassigned_supervisor.post(
                    recount_path, json={**command, "request_id": request_id}
                )
                assert denied.status_code == 403, denied.text
                assert denied.json()["detail"]["code"] == "station_access_denied"

        final_replay = supervisor.post(recount_path, json=command)
        assert final_replay.status_code == 200, final_replay.text
        assert final_replay.json() == original
        final_response = supervisor.get(recount_path)
        assert final_response.status_code == 200, final_response.text
        final = final_response.json()
        assert len(final["instructions"]) == 1
        assert final["instructions"][0] == instruction
        assert final["latest_instruction"] == instruction and final["pending"] is True
        final_rounds_response = counter.get(setup["rounds_path"])
        assert final_rounds_response.status_code == 200, final_rounds_response.text
        rounds = final_rounds_response.json()["rounds"]
        assert [row["id"] for row in rounds] == [prior["id"], blank["id"]]
        assert [row["round_number"] for row in rounds] == [1, 2]
        fresh_blank_response = counter.get(f"{setup['rounds_path']}/{blank['id']}")
        assert fresh_blank_response.status_code == 200, fresh_blank_response.text
        assert fresh_blank_response.json()["record"] == blank
        final_source_response = counter.get(source_path)
        assert final_source_response.status_code == 200, final_source_response.text
        after_source = final_source_response.json()
        assert [row["revision_id"] for row in after_source["history"]] == [
            row["revision_id"] for row in before_source["history"]
        ]
        # These four live projection fields are the intended instruction effect;
        # all original canonical source/history values and selection stay exact.
        projection_keys = {
            "recount_instruction", "required_recount", "recount_pending", "contributes_to_result"
        }
        for before, after in zip(before_source["history"], after_source["history"], strict=True):
            assert {k: v for k, v in after.items() if k not in projection_keys} == {
                k: v for k, v in before.items() if k not in projection_keys
            }
        other_final_response = supervisor.get(other_rounds_path)
        assert other_final_response.status_code == 200, other_final_response.text
        assert other_final_response.json() == other_before
        other_instructions = supervisor.get(other_recounts)
        assert other_instructions.status_code == 200, other_instructions.text
        assert other_instructions.json()["instructions"] == []
