"""Received-box counting scopes through authenticated real-MySQL APIs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import BoxClock, box_staff, box_stations, event_command, prepared_box
from tests.counting_support import counting_setup
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


def test_received_mixed_scope_pins_sources_without_attributing_whole_source_totals_twice(
    admin: TestClient, database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        path = setup["paths"]["n1_counting_scopes"]
        options = receiver.get(path)
        assert options.status_code == 200, options.text
        assert {source["station"]["id"] for source in options.json()["source_accounting"]} == {
            setup["stations"]["N1"]["id"], setup["stations"]["N2"]["id"]
        }
        for source in options.json()["source_accounting"]:
            assert source["record"]["approval_valid"] is True
        assert receiver.get(setup["paths"]["n2_accounting"]).status_code == 403
        selected = [setup["boxes"][key] for key in ("local_n1", "transferred_n2")]
        command = {
            "request_id": str(uuid4()), "expected_revision": 0,
            "reference": "Mixed local and transferred scope",
            "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}
                              for box in selected],
            "accounting_revisions": [
                {"station_id": setup["stations"][code]["id"], "revision": 1}
                for code in ("N1", "N2")
            ],
        }
        created = receiver.post(path, json=command)
        assert created.status_code == 201, created.text
        scope = created.json()
        assert len(scope["accounting_basis"]) == 2
        assert scope["estimated_box_from_stock_quantity"] is None
        assert scope["estimated_box_from_turnout_quantity"] is None
        assert [row["all_source_boxes_in_scope"] for row in scope["coverage"]] == [True, False]
        assert scope["blockers"] == []
        submitted = receiver.post(
            f"{path}/{scope['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["count_ready"] is True
        assert submitted.json()["box_basis"][1]["receipt"]["id"] == selected[1]["receipt"]["id"]

        # Receive the remaining physical source box, then explicitly revise the set.
        pending = setup["boxes"]["unreceived_n2"]
        received = receiver.post(
            f"{setup['paths']['n1_boxes']}/{pending['id']}/receipt",
            json=event_command(1, "2026-11-15T23:15:00+08:00"),
        )
        # Transferred boxes still require their origin departure before receipt.
        assert received.status_code == 409
        departed = setup["clients"]["polling"].post(
            f"{setup['paths']['n2_boxes']}/{pending['id']}/departure",
            json=event_command(1, "2026-11-15T23:12:00+08:00"),
        )
        assert departed.status_code == 201, departed.text
        received = receiver.post(
            f"{setup['paths']['n1_boxes']}/{pending['id']}/receipt",
            json=event_command(2, "2026-11-15T23:15:00+08:00"),
        )
        assert received.status_code == 201, received.text
        selection = {**command, "request_id": str(uuid4()), "expected_revision": 1,
                     "box_revisions": command["box_revisions"] + [
                         {"box_id": pending["id"], "revision": received.json()["revision"]}
                     ]}
        missing_reason = receiver.put(f"{path}/{scope['id']}", json=selection)
        assert missing_reason.status_code == 422
        revised = receiver.put(f"{path}/{scope['id']}", json={
            **selection, "request_id": str(uuid4()),
            "amendment_reason": "Include the newly received second N2 box.",
        })
        assert revised.status_code == 200, revised.text
        assert revised.json()["revision"] == 2
        assert len(revised.json()["box_basis"]) == 3
        assert len(revised.json()["accounting_basis"]) == 2
        assert revised.json()["estimated_box_from_stock_quantity"] == 10
        assert revised.json()["estimated_box_from_turnout_quantity"] is None
        old = receiver.get(f"{path}/{scope['id']}/revisions/1").json()
        assert old["status"] == "submitted"
        assert len(old["box_basis"]) == 2
        assert old["estimated_box_from_stock_quantity"] is None
        assert old["is_current"] is False
        assert old["count_ready"] is False
        history = receiver.get(f"{path}/{scope['id']}").json()
        assert [row["revision"] for row in history["history"]] == [2, 1]
