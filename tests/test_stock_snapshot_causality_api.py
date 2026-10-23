"""A correction cannot remove the release that enabled a same-time reallocation."""

import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_support import stock_payload
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_return_correction_cannot_retarget_the_release_that_enabled_same_time_reallocation(
    admin: TestClient, database_url: str
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    station_options = admin.get("/api/accounts/station-options")
    assert station_options.status_code == 200
    constituency_id = next(
        row["constituency"]["id"] for row in station_options.json()["items"]
        if row["station"]["id"] == station_id
    )
    second_counter = admin.post(
        f"/api/elections/{scope['election']['id']}/constituencies/"
        f"{constituency_id}/stations/{station_id}/counters",
        json={"request_id": str(uuid4()), "code": "C2", "name": "第二發票櫃台"},
    )
    assert second_counter.status_code == 201
    activated = admin.post(
        f"/api/elections/{scope['election']['id']}/activate",
        json={
            "election_revision": scope["election"]["revision"],
            "schedule_revision": scope["schedule"]["revision"],
        },
    )
    assert activated.status_code == 200
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        received = officer.post(
            base + "/stock",
            json=stock_payload(
                ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": "000006"}],
                ordinary_quantity=6,
                replacement_quantity=0,
                tendered_quantity=0,
            ),
        )
        assert received.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counters = {row["code"]: row["id"] for row in options.json()["counters"]}
        event_at = "2026-11-15T09:00:00+08:00"
        allocation_command = {
            "request_id": str(uuid4()),
            "counter_id": counters["C1"],
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000006",
            "event_at": event_at,
        }
        allocated_a = officer.post(base + "/allocations", json=allocation_command)
        assert allocated_a.status_code == 201
        allocation_a = allocated_a.json()
        return_command = {
            **allocation_command,
            "request_id": str(uuid4()),
            "serial_from": "000006",
        }
        returned = officer.post(base + "/stock-returns", json=return_command)
        assert returned.status_code == 201
        original = returned.json()
        assert original["allocation_basis"] == [
            {
                "allocation_id": allocation_a["id"], "revision": 1,
                "serial_from": "000006", "serial_to": "000006", "quantity": 1,
            }
        ]

        # Allocation -> physical return -> reallocation is valid even when their
        # event timestamps are equal; no artificial time gap is required.
        allocated_b = officer.post(
            base + "/allocations",
            json={
                **allocation_command,
                "request_id": str(uuid4()),
                "counter_id": counters["C2"],
                "serial_from": "000006",
            },
        )
        assert allocated_b.status_code == 201
        allocation_b = allocated_b.json()
        assert allocation_a["event_at"] == original["event_at"] == allocation_b["event_at"]
        before = officer.get(base + "/allocations")
        assert before.status_code == 200
        assert before.json()["availability"][0]["allocated_quantity"] == 6
        assert before.json()["availability"][0]["available_quantity"] == 0

        # Retargeting that sole return to B would leave A unreleased when B was
        # allocated. Removing B at the end cannot make that ownership history valid.
        target = base + f"/stock-returns/{original['id']}"
        corrected = officer.put(
            target,
            json={
                **return_command,
                "request_id": str(uuid4()),
                "revision": 1,
                "counter_id": counters["C2"],
                "reason": "核對交收單，將退回櫃台更正為第二櫃台。",
            },
        )
        if corrected.status_code != 409:
            print(
                "Same-time causality public facts:",
                json.dumps(
                    {
                        "allocation_a_id": allocation_a["id"],
                        "allocation_b_id": allocation_b["id"],
                        "shared_event_at": original["event_at"],
                        "original_release": original,
                        "correction_status": corrected.status_code,
                        "correction_response": corrected.json(),
                        "persisted_current": officer.get(target).json(),
                        "persisted_history": officer.get(target + "/history").json(),
                    },
                    ensure_ascii=False,
                ),
            )
        assert corrected.status_code == 409, {
            "allocation_a_id": allocation_a["id"],
            "allocation_b_id": allocation_b["id"],
            "shared_event_at": original["event_at"],
            "original_release_basis": original["allocation_basis"],
            "correction_status": corrected.status_code,
            "correction_response": corrected.json(),
        }
        assert corrected.json() == {"detail": {"code": "stock_returns_conflict"}}
        retained = officer.get(target)
        assert retained.status_code == 200 and retained.json() == original
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [original]
        for expected in (allocation_a, allocation_b):
            current = officer.get(base + f"/allocations/{expected['id']}")
            assert current.status_code == 200 and current.json() == expected
        after = officer.get(base + "/allocations")
        assert after.status_code == 200
        assert after.json()["availability"] == before.json()["availability"]
