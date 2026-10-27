"""A staff member checks the exact durable outcome of an uncertain count command."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_count_submission_lookup_returns_original_receipt_after_later_revisions(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        f2 = counter.put(target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text

        submit_request_id = str(uuid4())
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": submit_request_id,
                "expected_revision": f2.json()["revision"],
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        supervisor = setup["clients"]["supervisor"]
        approved = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        selected = supervisor.post(
            target + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": approved.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert selected.status_code == 200, selected.text
        current = counter.get(target).json()["record"]
        assert current["revision"] > submitted.json()["revision"]
        assert current["status"] == "approved" and current["selected"] is True

        station_id = setup["stations"]["N1"]["id"]
        outcome = counter.get(
            f"/api/workspace/stations/{station_id}/request-outcomes/{submit_request_id}",
            params={"workflow": "count"},
        )
        assert outcome.status_code == 200, outcome.text
        assert outcome.json() == {
            "request_id": submit_request_id,
            "workflow": "count",
            "status": "committed",
            "record": submitted.json(),
        }


def test_count_outcome_lookup_hides_other_actors_and_checks_station_assignment(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        request_id = str(uuid4())
        initial = complete_f1_command(
            options,
            actual_counted_quantity=2,
            request_id=request_id,
        )
        initial["candidate_votes"][0]["quantity"] = 2
        saved = counter.post(path, json=initial)
        assert saved.status_code == 201, saved.text
        station_id = setup["stations"]["N1"]["id"]
        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
        )

        other_counting_officer = setup["clients"]["bothcounting"]
        hidden = other_counting_officer.get(outcome_path, params={"workflow": "count"})
        assert hidden.status_code == 200, hidden.text
        assert hidden.json() == {
            "request_id": request_id,
            "workflow": "count",
            "status": "not_found",
        }
        assert "record" not in hidden.json()

        unknown = counter.get(
            f"/api/workspace/stations/{station_id}/request-outcomes/{uuid4()}",
            params={"workflow": "count"},
        )
        assert unknown.status_code == 200, unknown.text
        assert unknown.json()["status"] == "not_found"
        assert "record" not in unknown.json()

        wrong_station = counter.get(
            f"/api/workspace/stations/{setup['stations']['N2']['id']}"
            f"/request-outcomes/{request_id}",
            params={"workflow": "count"},
        )
        assert wrong_station.status_code == 403, wrong_station.text
