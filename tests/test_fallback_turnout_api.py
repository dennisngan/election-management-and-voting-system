"""Mixed-mode turnout counts only ordinary issuance after confirmed fallback."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.fallback_support import confirm_fallback_activation, fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_mixed_period_adds_five_ordinary_issues_without_counting_special_reserves(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, base = setup["officer"], setup["base"]
        activation = confirm_fallback_activation(setup)
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        endpoint = observed.json()
        assert endpoint["complete"] is True
        assert endpoint["ordinary_issued_quantity"] == 115
        assert endpoint["ordinary_remaining_quantity"] == 85
        assert endpoint["event_at"] == "2026-11-15T04:00:00Z"
        special = officer.post(base + "/special-papers", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "series": [{
                "series": "普通系列 A", "replacement_issued_quantity": 3,
                "spoilt_original_quantity": 3, "tendered_issued_quantity": 2,
                "retrieved_refused_quantity": 0, "retrieved_found_quantity": 0,
                "retrieved_held_quantity": 0,
            }],
        })
        assert special.status_code == 201
        assert special.json()["replacement_issued_quantity"] == 3
        assert special.json()["spoilt_original_quantity"] == 3
        assert special.json()["tendered_issued_quantity"] == 2
        assert special.json()["ordinary_issued_quantity"] == 115
        snapshot_path = base + f"/stock-snapshots/{endpoint['id']}"
        unchanged_endpoint = officer.get(snapshot_path)
        assert unchanged_endpoint.status_code == 200 and unchanged_endpoint.json() == endpoint
        path = setup["scope"]["path"]
        drafted = officer.put(path + "/2", json=turnout_draft(
            mode="fallback", fallback_activation_id=activation["id"],
            fallback_activation_revision=1, stock_snapshot_id=endpoint["id"],
            stock_snapshot_revision=1, event_at="2026-11-15T12:00:00+08:00",
            supplied_hourly=None, supplied_cumulative=None,
            source_context="Normal 11:00-11:20 then ordinary-stock fallback through noon.",
        ))
        # First new-feature assertion: the existing normal-only command rejects these fields.
        # Derived quantities, coverage and approval assertions remain unreached in this RED.
        assert drafted.status_code == 200
        draft = drafted.json()
        assert draft["status"] == "draft" and draft["revision"] == 1
        assert draft["provenance"] == "mixed"
        assert draft["supplied_hourly"] is None and draft["supplied_cumulative"] is None
        expected_basis = {
            "activation_id": activation["id"], "activation_revision": 1,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "ordinary_issued_since_activation_quantity": 5,
            "stock_derived_cumulative_quantity": 115,
            "coverage": [
                {
                    "mode": "normal", "start_at": "2026-11-15T03:00:00Z",
                    "end_at": "2026-11-15T03:20:00Z", "cumulative_start_quantity": 100,
                    "cumulative_end_quantity": 110, "hourly_quantity": 10,
                },
                {
                    "mode": "fallback", "start_at": "2026-11-15T03:20:00Z",
                    "end_at": "2026-11-15T04:00:00Z", "cumulative_start_quantity": 110,
                    "cumulative_end_quantity": 115, "hourly_quantity": 5,
                },
            ],
        }
        for key, value in expected_basis.items():
            assert draft["source_basis"][key] == value
        submitted = officer.post(path + "/2/submit", json=turnout_command(1))
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["source_basis"] == draft["source_basis"]
        confirmed = setup["supervisor"].post(
            path + "/2/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        approved = confirmed.json()
        assert approved["status"] == "approved" and approved["revision"] == 1
        assert approved["provenance"] == "mixed"
        assert approved["derived_cumulative_start"] == 100
        assert approved["derived_hourly"] == 15
        assert approved["derived_cumulative_end"] == 115
        assert approved["source_basis"] == draft["source_basis"]
        current = officer.get(path)
        assert current.status_code == 200
        assert current.json()["approved_prefix"]["periods"] == 2
        assert current.json()["approved_prefix"]["cumulative_end"] == 115
        assert current.json()["items"][1]["record"] == approved
        unchanged_endpoint = officer.get(snapshot_path)
        assert unchanged_endpoint.status_code == 200 and unchanged_endpoint.json() == endpoint
