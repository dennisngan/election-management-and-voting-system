"""Received-box counting scopes through authenticated real-MySQL APIs."""

from collections.abc import Iterator

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
