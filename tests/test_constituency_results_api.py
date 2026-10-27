"""Constituency result projections use only selected approved scope rounds."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.box_support import box_staff
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import candidate_ids_by_constituency, result_setup, save_result_round
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_selected_approved_mixed_scope_contributes_once_to_constituency_result(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        round_state = save_result_round(setup, [4, 0], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        response = supervisor.get(
            f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["context"]["constituency"]["id"] == setup["constituency_id"]
        assert len(result["contributions"]) == 1
        contribution = result["contributions"][0]
        assert contribution["scope_id"] == setup["scope"]["id"]
        assert contribution["station_id"] == setup["stations"]["N1"]["id"]
        assert contribution["scope_revision"] == setup["scope"]["revision"]
        assert contribution["round_id"] == round_state["selected"]["id"]
        assert contribution["round_revision"] == round_state["selected"]["revision"]
        assert contribution["selection_revision"] == 1
        totals = {row["candidate_id"]: row["quantity"] for row in result["candidate_totals"]}
        candidate_ids = [row["id"] for row in round_state["options"]["candidates"]]
        assert totals == {candidate_ids[0]: 4, candidate_ids[1]: 0}
        assert result["leader_candidate_ids"] == [candidate_ids[0]]
        assert result["tie_candidate_ids"] == []
        assert result["provisional"] is True
        assert result["complete"] is False
        assert any(item["code"] == "station_boxes_missing" for item in result["pending"])
        assert all(
            row["station_id"] != setup["stations"]["N2"]["id"]
            for row in result["contributions"]
        )


def test_submitted_count_without_selection_is_pending_and_not_a_candidate_total(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        round_state = save_result_round(setup, [4, 0], approve_and_select=False)
        response = setup["clients"]["supervisor"].get(
            f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["contributions"] == []
        assert {row["quantity"] for row in result["candidate_totals"]} == {None}
        assert any(
            item["code"] == "selected_count_missing"
            and item["scope_id"] == setup["scope"]["id"]
            and item["station_id"] == setup["stations"]["N1"]["id"]
            for item in result["pending"]
        )
        pending_scope = next(
            item for item in result["pending"]
            if item["code"] == "selected_count_missing"
            and item["scope_id"] == setup["scope"]["id"]
        )
        assert pending_scope["scope_revision"] == 1
        assert pending_scope["source_accounting_revisions"] == [
            {
                "station_id": source["context"]["station"]["id"],
                "record_id": source["id"],
                "revision": source["revision"],
                "status": "approved",
                "source_current": True,
                "approval_valid": True,
            }
            for source in setup["scope"]["accounting_basis"]
        ]
        assert result["complete"] is False
        assert result["provisional"] is True
        assert result["leader_candidate_ids"] == []
        assert result["tie_candidate_ids"] == []
        assert round_state["submitted"]["status"] == "submitted"


def test_zero_selected_totals_stay_zero_and_candidate_ids_do_not_cross_constituencies(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        round_state = save_result_round(setup, [0, 0], approve_and_select=True)
        candidate_ids = candidate_ids_by_constituency(admin, setup["election"]["id"])
        assert set(candidate_ids["N"]).isdisjoint(candidate_ids["S"])
        supervisor = setup["clients"]["supervisor"]
        north = supervisor.get(
            f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        )
        assert north.status_code == 200, north.text
        north_result = north.json()
        north_totals = {
            row["candidate_id"]: row["quantity"] for row in north_result["candidate_totals"]
        }
        assert north_totals == dict.fromkeys(candidate_ids["N"], 0)
        assert set(north_result["tie_candidate_ids"]) == set(candidate_ids["N"])
        assert set(north_result["leader_candidate_ids"]) == set(candidate_ids["N"])
        south_id = setup["stations"]["S1"]["constituency_id"]
        south = supervisor.get(f"/api/workspace/constituencies/{south_id}/results")
        assert south.status_code == 200, south.text
        south_result = south.json()
        south_totals = {
            row["candidate_id"]: row["quantity"] for row in south_result["candidate_totals"]
        }
        assert south_totals == dict.fromkeys(candidate_ids["S"], None)
        assert not (set(candidate_ids["N"]) & set(south_totals))
        assert north_result["contributions"][0]["round_id"] == round_state["selected"]["id"]
        assert any(item["code"] == "station_boxes_missing" for item in south_result["pending"])


def test_results_require_administrator_excluded_operational_access_and_full_supervisor_scope(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        assert admin.get(path).status_code == 403
        with box_staff(
            admin,
            database_url,
            setup["clock"],
            "supervisor",
            [setup["stations"]["N1"]["id"]],
        ) as (limited_supervisor, _):
            denied = limited_supervisor.get(path)
            assert denied.status_code == 403
