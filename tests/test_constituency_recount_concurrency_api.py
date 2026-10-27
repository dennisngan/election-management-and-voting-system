"""Independent Supervisor sessions serialize one complete constituency instruction."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import READY_PASSWORD, BoxClock
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


@contextmanager
def _independent_supervisor(
    database_url: str, clock: BoxClock, account: dict,
) -> Iterator[TestClient]:
    # Each client owns a separate real app/engine and authenticates independently.
    with TestClient(
        create_app(database_url, now=clock), base_url="https://testserver",
    ) as client:
        response = client.post("/api/auth/login", json={
            "username": account["username"], "password": READY_PASSWORD,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["account"]["id"] == account["id"]
        assert body["account"]["role"] == "supervisor"
        assert body["account"]["must_change_password"] is False
        client.headers["Authorization"] = "Bearer " + body["token"]
        yield client


@pytest.mark.parametrize("same_request", [True, False], ids=["same_uuid", "different_uuids"])
def test_concurrent_wide_instructions_have_one_parent_and_one_replacement_per_scope(
    admin: TestClient, database_url: str, same_request: bool,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        mixed = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}"
        target, result_path = base + "/recounts", base + "/results"
        baseline_response = supervisor.get(result_path)
        assert baseline_response.status_code == 200, baseline_response.text
        baseline = baseline_response.json()
        assert baseline["complete"] is True and baseline["pending"] == []
        assert [row["quantity"] for row in baseline["candidate_totals"]] == [6, 4]
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        sources = options["scope_sources"]
        assert options["can_instruct"] is True and options["instructions"] == []
        assert options["basis_digest"] == baseline["basis_digest"]
        assert len(sources) == 2
        assert [row["scope_id"] for row in sources] == [
            setup["scope"]["id"], setup["n3_scope"]["id"],
        ]
        priors = {setup["scope"]["id"]: mixed, setup["n3_scope"]["id"]: setup["n3_round"]}
        before_sources, before_options = {}, {}
        for source in sources:
            prior = priors[source["scope_id"]]
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            before_sources[source["scope_id"]] = response.json()
            listed = supervisor.get(rounds_path)
            assert listed.status_code == 200, listed.text
            assert [row["id"] for row in listed.json()["rounds"]] == [source["source_round_id"]]
            before_options[source["scope_id"]] = listed.json()
            local = supervisor.get(rounds_path.removesuffix("/rounds") + "/recounts")
            assert local.status_code == 200 and local.json()["instructions"] == []
        setup["clock"].value += timedelta(minutes=10)
        first = {
            "request_id": str(uuid4()), "basis_digest": options["basis_digest"],
            "scope_sources": deepcopy(sources),
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Concurrent sessions must preserve one complete required replacement set.",
            "password": READY_PASSWORD,
        }
        second = deepcopy(first)
        if not same_request:
            second["request_id"] = str(uuid4())
        commands = [first, second]
        start = Barrier(3)
        with (
            _independent_supervisor(
                database_url, setup["clock"], setup["accounts"]["supervisor"],
            ) as first_peer,
            _independent_supervisor(
                database_url, setup["clock"], setup["accounts"]["supervisor"],
            ) as second_peer,
        ):
            for peer in (first_peer, second_peer):
                ready = peer.get(target)
                assert ready.status_code == 200 and ready.json() == options

            def submit(peer: TestClient, payload: dict) -> tuple[int, dict]:
                start.wait(timeout=5)
                response = peer.post(target, json=payload)
                return response.status_code, response.json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(submit, peer, command) for peer, command in zip(
                    (first_peer, second_peer), commands, strict=True,
                )]
                start.wait(timeout=5)
                outcomes = [future.result(timeout=5) for future in futures]
            assert sorted(status for status, _body in outcomes) == (
                [200, 201] if same_request else [201, 409]
            ), [status for status, _body in outcomes]
            winner_index = next(
                index for index, outcome in enumerate(outcomes) if outcome[0] == 201
            )
            receipt = outcomes[winner_index][1]
            winning_command = commands[winner_index]
            parent = receipt["instruction"]
            assert parent["request_id"] == winning_command["request_id"]
            assert parent["actor_id"] == setup["accounts"]["supervisor"]["id"]
            assert parent["reason"] == first["reason"]
            assert parent["event_at"] == "2026-11-15T16:05:42.123456Z"
            assert parent["entered_at"] == "2026-11-15T16:10:00Z"
            assert parent["scope_sources"] == sources and parent["member_count"] == 2
            assert len(parent["members"]) == len(receipt["members"]) == 2
            assert parent["completed_member_count"] == 0 and parent["historical_complete"] is False
            assert [row["scope_source"] for row in parent["members"]] == sources
            assert [row["instruction"]["scope_id"] for row in receipt["members"]] == [
                row["scope_id"] for row in sources
            ]
            assert len({row["round"]["id"] for row in receipt["members"]}) == 2
            assert len({row["instruction"]["id"] for row in receipt["members"]}) == 2
            if same_request:
                assert outcomes[0][1] == outcomes[1][1]
            else:
                conflict = next(body for status, body in outcomes if status == 409)
                assert conflict == {"detail": {"code": "constituency_result_basis_stale"}}
                losing = commands[1 - winner_index]
                missing = second_peer.get(
                    base + f"/request-outcomes/{losing['request_id']}?workflow=constituency_recount"
                )
                assert missing.status_code == 200, missing.text
                assert missing.json() == {
                    "request_id": losing["request_id"], "workflow": "constituency_recount",
                    "status": "not_found",
                }
            outcome = first_peer.get(
                base + f"/request-outcomes/{parent['request_id']}?workflow=constituency_recount"
            )
            assert outcome.status_code == 200, outcome.text
            assert outcome.json() == {
                "request_id": parent["request_id"], "workflow": "constituency_recount",
                "status": "committed", "record": receipt,
            }

        history = supervisor.get(target)
        assert history.status_code == 200, history.text
        assert history.json()["can_instruct"] is False
        assert len(history.json()["instructions"]) == 1
        assert history.json()["instructions"][0] == parent
        for source, member in zip(sources, receipt["members"], strict=True):
            scope_id = source["scope_id"]
            prior = priors[scope_id]
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            listed = supervisor.get(rounds_path)
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["rounds"]) == 2
            assert {row["id"] for row in listed.json()["rounds"]} == {
                source["source_round_id"], member["round"]["id"],
            }
            assert listed.json()["selection"] == before_options[scope_id]["selection"]
            local = supervisor.get(rounds_path.removesuffix("/rounds") + "/recounts")
            assert local.status_code == 200, local.text
            assert len(local.json()["instructions"]) == 1
            assert local.json()["instructions"][0]["id"] == member["instruction"]["id"]
            created = supervisor.get(f"{rounds_path}/{member['round']['id']}")
            assert created.status_code == 200, created.text
            blank = created.json()["record"]
            assert len(created.json()["history"]) == 1
            assert blank["id"] != source["source_round_id"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft"
            assert blank["scope_basis"] == prior["selected"]["scope_basis"]
            assert blank["approval_valid"] is False and blank["selected"] is False
            assert all(blank[key] is None for key in (
                "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                "questionable_quantity", "f2", "completed_at",
            ))
            assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
            assert all(row["quantity"] is None for row in blank["invalid_papers"])
            preserved = supervisor.get(prior["round_path"])
            assert preserved.status_code == 200, preserved.text
            before = before_sources[scope_id]
            assert [row["revision_id"] for row in preserved.json()["history"]] == [
                row["revision_id"] for row in before["history"]
            ]
            for key in (
                "id", "revision_id", "revision", "status", "candidate_votes", "invalid_papers",
                "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                "approved_at", "approved_by",
            ):
                assert preserved.json()["record"][key] == before["record"][key]
            assert preserved.json()["record"]["approval_valid"] is True
        result = supervisor.get(result_path)
        assert result.status_code == 200, result.text
        assert result.json()["complete"] is False and result.json()["provisional"] is True
        assert result.json()["contributions"] == []
        assert [row["quantity"] for row in result.json()["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result.json()["pending"]} == set(priors)
        assert {row["code"] for row in result.json()["pending"]} == {"recount_pending"}
