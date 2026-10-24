"""Reasoned special-paper corrections preserve immutable records and request identity."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_reasoned_corrections_keep_history_and_replay_the_exact_original_revision(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        command = setup["command"]
        created = officer.post(path, json=command)
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        correction = {
            **command, "request_id": str(uuid4()), "revision": 1,
            "reason": "核對補發數量及尋回選票。\n保留原始觀察時間。",
            "series": [{
                **setup["entered_series"], "replacement_issued_quantity": 3,
                "spoilt_original_quantity": 3, "retrieved_found_quantity": 0,
            }],
        }
        corrected = officer.put(target, json=correction)
        # First new-behavior assertion; the baseline has no correction route.
        assert corrected.status_code == 200
        second = corrected.json()
        assert second["id"] == first["id"] and second["revision"] == 2
        assert second["reason"] == correction["reason"]
        assert second["actor_id"] == setup["account"]["id"]
        assert second["event_at"] == first["event_at"] == "2026-11-15T01:45:17.123456Z"
        assert second["replacement_issued_quantity"] == second["spoilt_original_quantity"] == 3
        assert second["retrieved_unused_quantity"] == 2
        assert second["replacement_unissued_quantity"] == 0
        assert second["tendered_unissued_quantity"] == 1
        assert second["never_issued_quantity"] == 6
        assert second["estimated_box_papers_quantity"] == 3
        original = officer.get(target, params={"revision": 1})
        assert original.status_code == 200 and original.json() == first
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [first, second]
        stale = officer.put(target, json={**correction, "request_id": str(uuid4())})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "revision_conflict"
        third_response = officer.put(target, json={
            **correction, "request_id": str(uuid4()), "revision": 2,
            "reason": "核對重複選票及待選民返回的未用選票。",
            "series": [{
                **correction["series"][0], "tendered_issued_quantity": 2,
                "retrieved_held_quantity": 0,
            }],
        })
        assert third_response.status_code == 200
        third = third_response.json()
        assert third["revision"] == 3
        assert third["retrieved_unused_quantity"] == 1
        assert third["tendered_unissued_quantity"] == 0
        assert third["never_issued_quantity"] == 5
        assert third["estimated_box_papers_quantity"] == 4
        # An equivalent UTC event spelling is the same request, including after r3.
        replay = officer.put(target, json={
            **correction, "event_at": "2026-11-15T01:45:17.123456Z",
        })
        assert replay.status_code == 200 and replay.json() == second
        original_replay = officer.post(path, json={
            **command, "event_at": "2026-11-15T01:45:17.123456Z",
        })
        assert original_replay.status_code == 200 and original_replay.json() == first
        assert officer.get(target).json() == third
        assert officer.get(target, params={"revision": 1}).json() == first
        assert officer.get(target + "/history").json()["items"] == [first, second, third]
        stock = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert stock.status_code == 200 and stock.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
