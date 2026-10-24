"""Explicit zero reports and exhausted special-paper reserves retain their basis."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_explicit_zero_categories_record_real_zeroes_and_retain_unused_reserves(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        zero_series = {
            "series": "普通系列 A",
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 0,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }
        created = officer.post(path, json={**setup["command"], "series": [zero_series]})
        assert created.status_code == 201
        saved = created.json()
        assert type(saved["id"]) is int and saved["id"] > 0
        assert saved["revision"] == 1
        assert saved["stock_snapshot_id"] == setup["snapshot"]["id"]
        assert saved["stock_snapshot_revision"] == 1
        expected = {
            "received_quantity": 15,
            "ordinary_issued_quantity": 5,
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 0,
            "retrieved_unused_quantity": 0,
            "ordinary_unissued_quantity": 5,
            "replacement_unissued_quantity": 3,
            "tendered_unissued_quantity": 2,
            "never_issued_quantity": 10,
            "estimated_box_papers_quantity": 5,
        }
        assert len(saved["series"]) == 1
        row = saved["series"][0]
        for key, value in zero_series.items():
            assert row[key] == value
            if key != "series":
                assert type(row[key]) is int
        for key, value in expected.items():
            assert type(saved[key]) is int and saved[key] == value
            assert type(row[key]) is int and row[key] == value
        reopened = officer.get(path + f"/{saved['id']}")
        assert reopened.status_code == 200 and reopened.json() == saved
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]


def test_exhausted_reserves_reject_an_additional_replacement_without_changing_saved_context(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        exhausted_series = {
            "series": "普通系列 A",
            "replacement_issued_quantity": 3,
            "spoilt_original_quantity": 3,
            "tendered_issued_quantity": 2,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }
        created = officer.post(path, json={**setup["command"], "series": [exhausted_series]})
        assert created.status_code == 201
        saved = created.json()
        expected = {
            "received_quantity": 15,
            "ordinary_issued_quantity": 5,
            "replacement_issued_quantity": 3,
            "spoilt_original_quantity": 3,
            "tendered_issued_quantity": 2,
            "retrieved_unused_quantity": 0,
            "ordinary_unissued_quantity": 5,
            "replacement_unissued_quantity": 0,
            "tendered_unissued_quantity": 0,
            "never_issued_quantity": 5,
            "estimated_box_papers_quantity": 5,
        }
        assert len(saved["series"]) == 1
        row = saved["series"][0]
        for key, value in exhausted_series.items():
            assert row[key] == value
        for key, value in expected.items():
            assert type(saved[key]) is int and saved[key] == value
            assert type(row[key]) is int and row[key] == value
        rejected = officer.post(
            path,
            json={
                **setup["command"],
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:17.123456+08:00",
                "series": [{
                    **exhausted_series,
                    "replacement_issued_quantity": 4,
                    "spoilt_original_quantity": 4,
                }],
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "special_paper_bounds"
        reopened = officer.get(path + f"/{saved['id']}")
        assert reopened.status_code == 200 and reopened.json() == saved
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
