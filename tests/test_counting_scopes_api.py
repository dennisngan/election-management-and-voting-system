"""Received-box counting scopes through authenticated real-MySQL APIs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import BoxClock, box_staff, box_stations, prepared_box
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_receiver_sees_unreceived_boxes_without_source_accounting_access(
    admin: TestClient, database_url: str,
) -> None:
    stations = box_stations(admin)
    clock = BoxClock()
    origin_id, destination_id = stations["N2"]["id"], stations["N1"]["id"]
    with (
        box_staff(admin, database_url, clock, "polling_officer", [origin_id]) as (polling, _),
        box_staff(admin, database_url, clock, "counting_officer", [destination_id]) as (
            receiver, _
        ),
    ):
        prepared = polling.post(
            f"/api/workspace/stations/{origin_id}/boxes", json=prepared_box()
        )
        assert prepared.status_code == 201
        response = receiver.get(
            f"/api/workspace/stations/{destination_id}/counting-scopes"
        )
        assert response.status_code == 200, response.text
        context = response.json()
        assert context["context"]["station"]["id"] == destination_id
        assert context["scopes"] == []
        assert len(context["boxes"]) == 1
        assert context["boxes"][0]["id"] == prepared.json()["id"]
        assert context["boxes"][0]["status"] == "prepared"
        assert context["boxes"][0]["scope_id"] is None
        assert context["source_accounting"] == []
        denied = receiver.get(f"/api/workspace/stations/{origin_id}/accounting")
        assert denied.status_code == 403


def test_unreceived_box_is_an_explicit_incomplete_draft_and_cannot_start_counting(
    admin: TestClient, database_url: str,
) -> None:
    stations = box_stations(admin)
    clock = BoxClock()
    origin_id, destination_id = stations["N2"]["id"], stations["N1"]["id"]
    with (
        box_staff(admin, database_url, clock, "polling_officer", [origin_id]) as (polling, _),
        box_staff(admin, database_url, clock, "counting_officer", [destination_id]) as (
            receiver, account
        ),
    ):
        box = polling.post(
            f"/api/workspace/stations/{origin_id}/boxes", json=prepared_box()
        ).json()
        path = f"/api/workspace/stations/{destination_id}/counting-scopes"
        command = {
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "reference": "北區 第一組",
            "event_at": "2026-11-15T23:00:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": 1}],
            "accounting_revisions": [],
            "notes": "Receipt and source accounting still pending.",
        }
        saved = receiver.post(path, json=command)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        assert record["revision"] == 1
        assert record["status"] == "draft"
        assert record["actor_id"] == account["id"]
        assert record["count_ready"] is False
        assert {item["code"] for item in record["blockers"]} == {
            "box_receipt_missing", "source_accounting_missing"
        }
        assert record["box_basis"][0]["id"] == box["id"]
        assert record["accounting_basis"] == []
        assert receiver.post(path, json=command).json() == record
        reread = receiver.get(path).json()
        assert reread["scopes"] == [record]
        assert reread["boxes"][0]["scope_id"] == record["id"]
        submitted = receiver.post(
            f"{path}/{record['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert submitted.status_code == 409
        assert submitted.json()["detail"]["code"] == "scope_incomplete"
        assert receiver.get(f"{path}/{record['id']}/revisions/1").json() == record
        history = receiver.get(f"{path}/{record['id']}")
        assert history.status_code == 200
        assert history.json() == {"record": record, "history": [record]}
