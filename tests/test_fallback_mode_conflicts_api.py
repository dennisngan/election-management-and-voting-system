"""Overlapping activation sources return the public fallback_source_conflict code."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.fallback_support import fallback_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import READY_PASSWORD, turnout_command


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_confirmed_activation_rejects_overlapping_draft_and_new_activation(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        first_created = officer.post(path, json=setup["command"])
        assert first_created.status_code == 201
        first = first_created.json()
        second_created = officer.post(path, json={
            **setup["command"], "request_id": str(uuid4()),
        })
        assert second_created.status_code == 201
        second = second_created.json()
        assert first["id"] != second["id"]
        assert first["status"] == second["status"] == "draft"
        assert first["event_at"] == second["event_at"] == "2026-11-15T03:20:00Z"
        assert first["cumulative_quantity"] == second["cumulative_quantity"] == 110
        first_path = path + f"/{first['id']}"
        submitted = officer.post(first_path + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
        confirmed = setup["supervisor"].post(
            first_path + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        approved = confirmed.json()
        assert approved["status"] == "approved" and approved["revision"] == 1
        assert approved["stock_snapshot"] == setup["snapshot"]
        second_path = path + f"/{second['id']}"
        denied = officer.post(second_path + "/submit", json=turnout_command(1))
        # First new-feature assertion: the competing draft cannot join the live mode timeline.
        # Later approval/create conflicts and unchanged-history checks remain unreached in RED.
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "fallback_source_conflict"
        denied_approval = setup["supervisor"].post(
            second_path + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert denied_approval.status_code == 409
        assert denied_approval.json()["detail"]["code"] == "fallback_source_conflict"
        another = officer.post(path, json={**setup["command"], "request_id": str(uuid4())})
        assert another.status_code == 409
        assert another.json()["detail"]["code"] == "fallback_source_conflict"
        collection = officer.get(path)
        assert collection.status_code == 200
        records = collection.json()["items"]
        assert len(records) == 2
        assert {row["id"]: row for row in records} == {
            approved["id"]: approved, second["id"]: second,
        }
        assert [row for row in records if row["status"] == "approved"] == [approved]
        assert collection.json()["mode"] == "fallback"
        assert collection.json()["active_activation_id"] == approved["id"]
        unchanged = officer.get(first_path)
        assert unchanged.status_code == 200 and unchanged.json() == approved
        history = officer.get(first_path + "/history")
        assert history.status_code == 200 and history.json() == {"items": [approved]}
        untouched_draft = officer.get(second_path)
        assert untouched_draft.status_code == 200 and untouched_draft.json() == second
        draft_history = officer.get(second_path + "/history")
        assert draft_history.status_code == 200 and draft_history.json() == {"items": [second]}


def test_backdated_activation_cannot_overlap_a_later_confirmed_activation(
    admin: TestClient, database_url: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        earlier = officer.post(setup["base"] + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T11:10:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000106", "serial_to": "000200",
            }]}],
        })
        assert earlier.status_code == 201 and earlier.json()["ordinary_issued_quantity"] == 105
        # This earlier draft exists before the later event is confirmed.
        command = {
            **setup["command"], "request_id": str(uuid4()),
            "event_at": "2026-11-15T11:10:00+08:00", "cumulative_quantity": 105,
            "stock_snapshot_id": earlier.json()["id"],
        }
        drafted = officer.post(path, json=command)
        assert drafted.status_code == 201
        first = officer.post(path, json=setup["command"])
        assert first.status_code == 201
        target = path + f"/{first.json()['id']}"
        assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
        approved = setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert approved.status_code == 200
        denied = officer.post(path + f"/{drafted.json()['id']}/submit", json=turnout_command(1))
        # A confirmed future event must constrain an older pending source too.
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "fallback_source_conflict"
        duplicate = officer.post(path, json={**command, "request_id": str(uuid4())})
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "fallback_source_conflict"
        assert officer.get(target).json() == approved.json()
        collection = officer.get(path)
        assert collection.status_code == 200
        assert collection.json()["mode"] == "fallback"
        assert collection.json()["active_activation_id"] == first.json()["id"]
        assert sum(row["status"] == "approved" for row in collection.json()["items"]) == 1
