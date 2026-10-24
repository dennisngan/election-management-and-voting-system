"""Cumulative reserve issues cannot regress across recorded observation times."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_later_observations_and_earlier_corrections_cannot_release_consumed_reserves(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        command = setup["command"]
        created = officer.post(path, json=command)
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        later = {
            **command, "request_id": str(uuid4()),
            "event_at": "2026-11-15T10:00:17.123456+08:00",
            "series": [{
                **setup["entered_series"], "replacement_issued_quantity": 1,
                "spoilt_original_quantity": 1,
            }],
        }
        rejected = officer.post(path, json=later)
        # Previously issued reserve papers must not become unused in a later observation.
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "special_paper_issuance_regression"
        assert officer.get(target).json() == first
        assert officer.get(target + "/history").json()["items"] == [first]
        later["series"] = [{
            **setup["entered_series"], "replacement_issued_quantity": 3,
            "spoilt_original_quantity": 3,
        }]
        accepted = officer.post(path, json=later)
        assert accepted.status_code == 201
        second = accepted.json()
        second_target = path + f"/{second['id']}"
        assert second["replacement_unissued_quantity"] == 0
        earlier_correction = {
            **command, "request_id": str(uuid4()), "revision": 1,
            "reason": "Earlier report claims two tendered issues before a later report of one.",
            "series": [{**setup["entered_series"], "tendered_issued_quantity": 2}],
        }
        rejected_correction = officer.put(target, json=earlier_correction)
        assert rejected_correction.status_code == 409
        assert rejected_correction.json()["detail"]["code"] == "special_paper_issuance_regression"
        assert officer.get(target).json() == first
        assert officer.get(target + "/history").json()["items"] == [first]
        assert officer.get(second_target).json() == second
        # Retrieved-unused observations can change without replenishing any never-issued pool.
        retrieved_correction = {
            **command, "request_id": str(uuid4()), "revision": 1,
            "reason": "One paper is no longer held pending the elector's return.",
            "series": [{**setup["entered_series"], "retrieved_held_quantity": 0}],
        }
        corrected = officer.put(target, json=retrieved_correction)
        assert corrected.status_code == 200
        revised = corrected.json()
        assert revised["retrieved_unused_quantity"] == 2
        assert revised["never_issued_quantity"] == 7
        assert revised["estimated_box_papers_quantity"] == 3
        assert officer.get(target, params={"revision": 1}).json() == first
        assert officer.get(second_target).json() == second
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
