"""One constituency instruction preserves every reviewed source and its replacement."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
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


def test_one_constituency_instruction_creates_two_blank_rounds_and_retains_reviewed_sources(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        constituency_id = setup["constituency_id"]
        result_path = f"/api/workspace/constituencies/{constituency_id}/results"
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        old_rounds = {
            setup["scope"]["id"]: saved,
            setup["n3_scope"]["id"]: setup["n3_round"],
        }
        old_history = {}
        for scope_id, prior in old_rounds.items():
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            old_history[scope_id] = response.json()

        before = supervisor.get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is True
        assert before.json()["pending"] == []
        assert [row["quantity"] for row in before.json()["candidate_totals"]] == [6, 4]
        assert before.json()["provisional"] is True

        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        sources = options["scope_sources"]
        assert options["can_instruct"] is True
        assert options["basis_digest"] == before.json()["basis_digest"]
        assert [(row["station_id"], row["scope_id"]) for row in sources] == [
            (setup["stations"]["N1"]["id"], setup["scope"]["id"]),
            (setup["stations"]["N3"]["id"], setup["n3_scope"]["id"]),
        ]
        assert [row["scope_revision"] for row in sources] == [2, 1]
        assert [row["expected_selection_revision"] for row in sources] == [1, 1]
        assert [row["source_round_revision"] for row in sources] == [4, 4]

        setup["clock"].value += timedelta(minutes=10)
        request_id = str(uuid4())
        command = {
            "request_id": request_id,
            "basis_digest": options["basis_digest"],
            "scope_sources": sources,
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Recount every North scope while retaining both reviewed sources.",
            "password": READY_PASSWORD,
        }
        response = supervisor.post(target, json=command)
        assert response.status_code == 201, response.text
        receipt = response.json()
        instruction = receipt["instruction"]
        assert instruction["id"] > 0
        assert instruction["request_id"] == request_id
        assert instruction["constituency_id"] == constituency_id
        assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert instruction["reason"] == command["reason"]
        assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
        assert instruction["entered_at"] == "2026-11-15T16:10:00Z"
        assert instruction["scope_sources"] == sources
        assert len(receipt["members"]) == 2
        assert [row["instruction"]["scope_id"] for row in receipt["members"]] == [
            setup["scope"]["id"], setup["n3_scope"]["id"],
        ]
        assert len({row["instruction"]["request_id"] for row in receipt["members"]}) == 2
        assert len({row["round"]["id"] for row in receipt["members"]}) == 2

        for member in receipt["members"]:
            local, blank = member["instruction"], member["round"]
            scope_id = local["scope_id"]
            old = old_rounds[scope_id]["selected"]
            assert local["source_round_id"] == old["id"]
            assert local["source_round_revision_id"] == old["revision_id"]
            assert local["new_round_id"] == blank["id"] != old["id"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft" and blank["selected"] is False
            assert blank["f1_complete"] is False and blank["approval_valid"] is False
            assert blank["scope_basis"] == old["scope_basis"]
            assert blank["physical_decisions"] == []
            assert all(blank[key] is None for key in (
                "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                "questionable_quantity", "f2", "completed_at",
            ))
            assert all(row["quantity"] is None for key in ("candidate_votes", "invalid_papers")
                       for row in blank[key])
            prefix = old_rounds[scope_id]["round_path"].rsplit("/", 1)[0]
            persisted = supervisor.get(f"{prefix}/{blank['id']}")
            assert persisted.status_code == 200, persisted.text
            assert persisted.json()["record"]["revision_id"] == blank["revision_id"]
            assert len(persisted.json()["history"]) == 1

            preserved = supervisor.get(old_rounds[scope_id]["round_path"])
            assert preserved.status_code == 200, preserved.text
            assert [row["revision_id"] for row in preserved.json()["history"]] == [
                row["revision_id"] for row in old_history[scope_id]["history"]
            ]
            for key in ("revision_id", "revision", "status", "candidate_votes", "invalid_papers",
                        "f2", "scope_basis", "event_at", "entered_at", "actor_id"):
                assert preserved.json()["record"][key] == old_history[scope_id]["record"][key]
            assert preserved.json()["record"]["approval_valid"] is True

        history = supervisor.get(target)
        assert history.status_code == 200, history.text
        assert history.json()["can_instruct"] is False
        assert len(history.json()["instructions"]) == 1
        assert history.json()["instructions"][0]["id"] == instruction["id"]
        assert history.json()["instructions"][0]["scope_sources"] == sources
        assert len(history.json()["instructions"][0]["members"]) == 2
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        result = after.json()
        assert result["contributions"] == []
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result["pending"]} == set(old_rounds)
        assert all(row["code"] == "recount_pending" for row in result["pending"])
        assert result["complete"] is False and result["provisional"] is True
