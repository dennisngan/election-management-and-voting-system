"""A wide instruction covers seven real required scopes without a fixture-sized cap."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, event_command, prepared_box
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


def _receive_five_extra_n1_boxes(setup: dict) -> list[dict]:
    polling, receiver = setup["clients"]["polling"], setup["clients"]["receiveronly"]
    path = setup["paths"]["n1_boxes"]
    received = []
    # Prepare every physical source box before freezing any additional scope.
    # Adding another box later would honestly invalidate its frozen coverage.
    for number in range(1, 6):
        created = polling.post(path, json=prepared_box(
            box_reference=f"Expanded North additional box {number}",
            seal_reference=f"Expanded North additional seal {number}",
        ))
        assert created.status_code == 201, created.text
        response = receiver.post(
            f"{path}/{created.json()['id']}/receipt",
            json=event_command(1, "2026-11-15T22:46:00+08:00"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["receipt"] is not None
        received.append(response.json())
    assert len({box["id"] for box in received}) == 5
    return received


def _rebase_original_mixed_scope_before_counting(setup: dict) -> None:
    receiver, scope = setup["clients"]["receiveronly"], setup["scope"]
    path = f"{setup['scope_path']}/{scope['id']}"
    stale = receiver.get(path)
    assert stale.status_code == 200, stale.text
    assert stale.json()["record"]["source_current"] is False
    # Keep its original mixed physical membership and approved P(18) records.
    # Explicitly review the changed source-box inventory before any N1 tally.
    changed = receiver.put(path, json={
        "request_id": str(uuid4()), "expected_revision": scope["revision"],
        "reference": scope["reference"], "event_at": scope["event_at"],
        "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}
                          for box in scope["box_basis"]],
        "accounting_revisions": [{"station_id": row["station_id"], "revision": row["revision"]}
                                 for row in scope["accounting_basis"]],
        "notes": "The same mixed boxes remain this scope's physical tally set.",
        "amendment_reason": "Review the five additional N1 boxes as separate counting scopes.",
    })
    assert changed.status_code == 200, changed.text
    revised = changed.json()
    assert revised["revision"] == scope["revision"] + 1
    assert revised["box_basis"] == scope["box_basis"]
    assert revised["accounting_basis"] == scope["accounting_basis"]
    assert revised["estimated_box_from_stock_quantity"] is None
    assert revised["estimated_box_from_turnout_quantity"] is None
    submitted = receiver.post(path + "/submit", json={
        "request_id": str(uuid4()), "expected_revision": revised["revision"],
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    setup["scope"] = submitted.json()


def _prepare_extra_zero_scope(setup: dict, box: dict, number: int) -> dict:
    receiver, station_id = setup["clients"]["receiveronly"], setup["stations"]["N1"]["id"]
    path = setup["paths"]["n1_counting_scopes"]
    response = receiver.post(path, json={
        "request_id": str(uuid4()), "expected_revision": 0,
        "reference": f"Expanded North observed-empty scope {number}",
        "event_at": "2026-11-15T23:10:00+08:00",
        "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
        "accounting_revisions": [{"station_id": station_id, "revision": 1}],
    })
    assert response.status_code == 201, response.text
    scope = response.json()
    assert len(scope["box_basis"]) == 1 and scope["box_basis"][0]["id"] == box["id"]
    assert scope["box_basis"][0]["receipt"] is not None
    assert scope["coverage"][0]["all_source_boxes_in_scope"] is False
    assert scope["estimated_box_from_stock_quantity"] is None
    assert scope["estimated_box_from_turnout_quantity"] is None
    assert scope["accounting_basis"][0]["approval_valid"] is True
    submitted = receiver.post(f"{path}/{scope['id']}/submit", json={
        "request_id": str(uuid4()), "expected_revision": scope["revision"],
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    extra_setup = {
        **setup, "scope": submitted.json(), "rounds_path": f"{path}/{scope['id']}/rounds",
    }
    # These are explicit observed zeros entered through F1/F2, not an estimate
    # divided between boxes or copied from the mixed scope's candidate totals.
    source = save_result_round(extra_setup, [0, 0], approve_and_select=True)
    assert source["selected"]["actual_counted_quantity"] == 0
    assert [row["quantity"] for row in source["selected"]["candidate_votes"]] == [0, 0]
    assert [row["quantity"] for row in source["selected"]["final_candidate_votes"]] == [0, 0]
    assert source["selected"]["approval_valid"] is True
    assert source["selected"]["selected"] is True
    assert source["selected"]["scope_basis"]["estimated_box_from_stock_quantity"] is None
    assert source["selected"]["scope_basis"]["estimated_box_from_turnout_quantity"] is None
    return source


def test_wide_recount_preserves_and_replaces_all_seven_required_scope_sources(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        n3_before = supervisor.get(setup["n3_round"]["round_path"])
        assert n3_before.status_code == 200, n3_before.text
        extra_boxes = _receive_five_extra_n1_boxes(setup)
        _rebase_original_mixed_scope_before_counting(setup)
        mixed = save_result_round(setup, [6, 4], approve_and_select=True)
        source_rounds = {
            setup["scope"]["id"]: mixed,
            setup["n3_scope"]["id"]: setup["n3_round"],
        }
        for number, box in enumerate(extra_boxes, 1):
            extra = _prepare_extra_zero_scope(setup, box, number)
            source_rounds[extra["selected"]["scope_id"]] = extra
        assert len(source_rounds) == 7
        n3_after = supervisor.get(setup["n3_round"]["round_path"])
        assert n3_after.status_code == 200 and n3_after.json() == n3_before.json()

        constituency_id = setup["constituency_id"]
        result_path = f"/api/workspace/constituencies/{constituency_id}/results"
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        baseline_response = supervisor.get(result_path)
        assert baseline_response.status_code == 200, baseline_response.text
        baseline = baseline_response.json()
        assert baseline["complete"] is True and baseline["pending"] == []
        assert baseline["provisional"] is True
        assert [row["quantity"] for row in baseline["candidate_totals"]] == [6, 4]
        assert len(baseline["contributions"]) == 7
        assert {row["scope_id"] for row in baseline["contributions"]} == set(source_rounds)
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        sources = options["scope_sources"]
        assert options["can_instruct"] is True and options["instructions"] == []
        assert options["basis_digest"] == baseline["basis_digest"]
        expected_order = sorted(
            (prior["selected"]["scope_basis"]["station_id"], scope_id)
            for scope_id, prior in source_rounds.items()
        )
        assert len(sources) == 7
        assert [(row["station_id"], row["scope_id"]) for row in sources] == expected_order
        assert [row["station_id"] for row in sources].count(setup["stations"]["N1"]["id"]) == 6
        assert [row["station_id"] for row in sources].count(setup["stations"]["N3"]["id"]) == 1
        assert all(row["station_id"] != setup["stations"]["N2"]["id"] for row in sources)
        preserved_sources = {}
        for source in sources:
            prior = source_rounds[source["scope_id"]]
            assert source["source_round_id"] == prior["selected"]["id"]
            assert source["source_round_revision"] == prior["selected"]["revision"]
            assert source["expected_selection_revision"] == (
                prior["selected"]["selection"]["revision"]
            )
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            preserved_sources[source["scope_id"]] = response.json()

        setup["clock"].value += timedelta(minutes=10)
        command = {
            "request_id": str(uuid4()), "basis_digest": options["basis_digest"],
            "scope_sources": sources, "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Recount all seven real North scopes without truncating the required set.",
            "password": READY_PASSWORD,
        }
        created = supervisor.post(target, json=command)
        assert created.status_code == 201, created.text
        original = created.json()
        parent = original["instruction"]
        assert parent["scope_sources"] == sources and parent["member_count"] == 7
        assert parent["request_id"] == command["request_id"]
        assert parent["completed_member_count"] == 0 and parent["historical_complete"] is False
        assert len(parent["members"]) == len(original["members"]) == 7
        assert [(member["station_id"], member["scope_id"]) for member in parent["members"]] == (
            expected_order
        )
        assert len({member["round"]["id"] for member in original["members"]}) == 7
        assert len({member["instruction"]["id"] for member in original["members"]}) == 7
        assert len({member["instruction"]["request_id"] for member in original["members"]}) == 7
        for source, member in zip(sources, original["members"], strict=True):
            local, blank = member["instruction"], member["round"]
            prior = source_rounds[source["scope_id"]]["selected"]
            assert local["scope_id"] == source["scope_id"]
            assert local["source_round_id"] == prior["id"]
            assert local["source_round_revision_id"] == prior["revision_id"]
            assert local["new_round_id"] == blank["id"] != prior["id"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft" and blank["scope_basis"] == prior["scope_basis"]
            assert blank["f1_complete"] is False and blank["approval_valid"] is False
            assert blank["selected"] is False and blank["physical_decisions"] == []
            assert all(blank[key] is None for key in (
                "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                "questionable_quantity", "f2", "completed_at",
            ))
            assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
            assert all(row["quantity"] is None for row in blank["invalid_papers"])

        replay = supervisor.post(target, json=command)
        assert replay.status_code == 200 and replay.json() == original
        history_response = supervisor.get(target)
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["can_instruct"] is False and len(history["instructions"]) == 1
        assert history["instructions"][0]["id"] == parent["id"]
        assert history["instructions"][0]["scope_sources"] == sources
        assert len(history["instructions"][0]["members"]) == 7
        for source, member in zip(sources, original["members"], strict=True):
            prior = source_rounds[source["scope_id"]]
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            listed = supervisor.get(rounds_path)
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["rounds"]) == 2
            assert {row["id"] for row in listed.json()["rounds"]} == {
                source["source_round_id"], member["round"]["id"],
            }
            assert listed.json()["selection"]["round_id"] == source["source_round_id"]
            local_path = rounds_path.removesuffix("/rounds") + "/recounts"
            locals_response = supervisor.get(local_path)
            assert locals_response.status_code == 200, locals_response.text
            assert len(locals_response.json()["instructions"]) == 1
            assert locals_response.json()["instructions"][0]["id"] == member["instruction"]["id"]
            blank_response = supervisor.get(f"{rounds_path}/{member['round']['id']}")
            assert blank_response.status_code == 200, blank_response.text
            assert len(blank_response.json()["history"]) == 1
            assert blank_response.json()["record"]["revision_id"] == member["round"]["revision_id"]
            preserved = supervisor.get(prior["round_path"])
            assert preserved.status_code == 200, preserved.text
            before = preserved_sources[source["scope_id"]]
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
        result_response = supervisor.get(result_path)
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()
        assert result["complete"] is False and result["provisional"] is True
        assert result["contributions"] == []
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result["pending"]} == set(source_rounds)
        assert {row["code"] for row in result["pending"]} == {"recount_pending"}
