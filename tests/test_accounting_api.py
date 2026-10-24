"""P(18) source accounting is observed only through authenticated MySQL APIs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.special_paper_support import special_paper_setup
from tests.turnout_support import READY_PASSWORD, approve_period, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_counting_officer_freezes_conserved_stock_without_inventing_observed_papers(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = special.json()["station_id"]
        with turnout_staff(
            admin, database_url, setup["clock"], [station_id], "counting_officer"
        ) as (counter, account):
            path = setup["base"] + "/accounting"
            command = {
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
                "turnout_period_index": 1,
                "turnout_revision": 1,
                "notes": "Paper reconciliation before counting; no physical transfer needed.",
            }
            saved = counter.put(path, json=command)
            assert saved.status_code == 200, saved.text
            record = saved.json()
            assert record["status"] == "draft"
            assert record["revision"] == 1
            assert record["actor_id"] == account["id"]
            assert record["summary"] == {
                "received_quantity": 15,
                "ordinary_received_quantity": 10,
                "ordinary_central_unissued_quantity": 0,
                "ordinary_at_desks_quantity": 5,
                "replacement_unissued_quantity": 1,
                "tendered_unissued_quantity": 1,
                "ordinary_issued_quantity": 5,
                "replacement_issued_quantity": 2,
                "spoilt_original_quantity": 2,
                "tendered_issued_quantity": 1,
                "retrieved_refused_quantity": 1,
                "retrieved_found_quantity": 1,
                "retrieved_held_quantity": 1,
                "retrieved_unused_quantity": 3,
                "never_issued_quantity": 7,
                "estimated_box_from_stock_quantity": 2,
                "estimated_box_from_turnout_quantity": None,
                "observed_counted_quantity": None,
            }
            assert record["turnout"]["record"]["supplied_cumulative"] == 5
            assert record["turnout"]["approval_valid"] is False
            assert record["stock_snapshot"]["id"] == setup["snapshot"]["id"]
            assert record["special_papers"]["id"] == special.json()["id"]
            assert counter.put(path, json=command).json() == record
            current = counter.get(path)
            assert current.status_code == 200
            assert current.json()["record"] == record
            assert current.json()["record"]["source_current"] is True
            assert len(current.json()["history"]) == 1


def test_exact_review_preserves_original_and_requires_reasoned_correction(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special = setup["officer"].post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id = special.json()["station_id"]
        with (
            turnout_staff(
                admin, database_url, setup["clock"], [station_id], "counting_officer"
            ) as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id], "supervisor") as (
                supervisor,
                approver,
            ),
        ):
            approve_period(supervisor, setup["base"] + "/turnout", 1)
            path = setup["base"] + "/accounting"
            selection = {
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
                "turnout_period_index": 1,
                "turnout_revision": 1,
            }
            saved = counter.put(path, json=selection)
            assert saved.status_code == 200, saved.text
            assert saved.json()["summary"]["estimated_box_from_turnout_quantity"] == 2
            submitted = counter.post(
                path + "/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                },
            )
            assert submitted.status_code == 200, submitted.text
            approval = {
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "password": READY_PASSWORD,
            }
            approved = supervisor.post(path + "/approve", json=approval)
            assert approved.status_code == 200, approved.text
            assert approved.json()["approval_valid"] is True
            assert approved.json()["approved_by"] == approver["id"]
            assert supervisor.post(path + "/approve", json=approval).json() == approved.json()
            corrected = counter.put(
                path,
                json={
                    **selection,
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "notes": "Corrected source note",
                },
            )
            assert corrected.status_code == 422
            corrected = counter.put(
                path,
                json={
                    **selection,
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "notes": "Corrected source note",
                    "amendment_reason": "Checked paper reference",
                },
            )
            assert corrected.status_code == 200, corrected.text
            assert corrected.json()["revision"] == 2
            assert corrected.json()["status"] == "draft"
            assert corrected.json()["approval_valid"] is False
            old = counter.get(path + "/revisions/1").json()
            assert old["status"] == "approved"
            assert old["approved_by"] == approver["id"]
            assert old["notes"] == ""
            assert old["approval_valid"] is False
            assert len(counter.get(path).json()["history"]) == 2
