"""Station handover reports retain physical box identity and unrecorded count values."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.box_support import BoxClock, box_staff, box_stations, event_command, prepared_box
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_receiver_previews_origin_handover_and_missing_count_completion(
    admin: TestClient, database_url: str
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, _):
        path = f"/api/workspace/stations/{origin['id']}/boxes"
        created = sender.post(path, json=prepared_box())
        assert created.status_code == 201
        box = created.json()
        departed = sender.post(
            f"{path}/{box['id']}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert departed.status_code == 201
    with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
        receiver,
        _,
    ):
        path = f"/api/workspace/stations/{destination['id']}/boxes"
        received = receiver.post(
            f"{path}/{box['id']}/receipt",
            json=event_command(2, "2026-11-15T23:00:00+08:00"),
        )
        assert received.status_code == 201
        response = receiver.get(path + "/statement?locale=tc")
        assert response.status_code == 200
        report = response.json()
        assert report["scope"]["station"]["id"] == destination["id"]
        assert report["items"][0]["origin"]["id"] == origin["id"]
        assert report["items"][0]["destination"]["id"] == destination["id"]
        assert report["items"][0]["status"] == "received"
        assert report["items"][0]["revision"] == 3
        assert report["count_completion"] is None
        assert report["milestones"] == []
        assert len(report["box_history"]) == 3
        assert "2026-11-15 23:00:00 HKT" in "\n".join(report["preview_lines"])
