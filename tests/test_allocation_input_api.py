"""Reject malformed allocation commands without changing shared stock or history."""

from collections.abc import Iterator

import pytest

from tests.lifecycle_support import lifecycle_database_url
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup  # noqa: F401


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"counter_id": True}, id="boolean-counter"),
        pytest.param({"counter_id": "1"}, id="string-counter"),
        pytest.param({"counter_id": 0}, id="zero-counter"),
        pytest.param({"series": " \t "}, id="blank-series"),
        pytest.param({"serial_from": "０００００１"}, id="non-ascii-serial"),
        pytest.param({"serial_to": "00000A"}, id="nonnumeric-serial"),
        pytest.param({"serial_from": "0" * 19}, id="overlong-serial"),
        pytest.param({"serial_from": "000004"}, id="reversed-range"),
        pytest.param({"serial_to": 3}, id="nonstring-serial"),
        pytest.param({"event_at": "2026-11-08T08:05:00"}, id="naive-event-time"),
        pytest.param({"request_id": "not-a-uuid"}, id="invalid-request-id"),
        pytest.param({"quantity": 3}, id="caller-supplied-quantity"),
        pytest.param({"pool": "replacement"}, id="caller-supplied-reserve-pool"),
    ],
)
def test_invalid_create_preserves_existing_allocation_history_and_shared_availability(
    allocation_setup: dict, changes: dict
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    created = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    target = path + f"/{created.json()['id']}"
    before = officer.get(path)
    history_before = officer.get(target + "/history")
    assert before.status_code == history_before.status_code == 200

    rejected = officer.post(path, json={**allocation_payload(setup["counter"]["id"]), **changes})

    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json() == before.json()
    assert officer.get(target).json() == created.json()
    assert officer.get(target + "/history").json() == history_before.json()


@pytest.mark.parametrize(
    "reason", [pytest.param(None, id="missing"), pytest.param(" \t ", id="blank")]
)
def test_reasonless_correction_preserves_head_history_and_shared_availability(
    allocation_setup: dict, reason: str | None
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    created = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    target = path + f"/{created.json()['id']}"
    before = officer.get(path)
    history_before = officer.get(target + "/history")
    assert before.status_code == history_before.status_code == 200
    correction = allocation_payload(
        setup["counter"]["id"], revision=1, serial_from="000002", serial_to="000004"
    )
    if reason is not None:
        correction["reason"] = reason

    rejected = officer.put(target, json=correction)

    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "validation_error"
    assert officer.get(path).json() == before.json()
    assert officer.get(target).json() == created.json()
    assert officer.get(target + "/history").json() == history_before.json()


def test_same_instant_with_utc_offset_retries_the_original_create_without_another_effect(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    command = allocation_payload(setup["counter"]["id"])
    created = officer.post(path, json=command)
    assert created.status_code == 201
    before = officer.get(path)
    assert before.status_code == 200

    replay = officer.post(path, json={**command, "event_at": "2026-11-08T00:05:00Z"})

    assert replay.status_code == 200
    assert replay.json() == created.json()
    assert officer.get(path).json() == before.json()
    assert officer.get(path + f"/{created.json()['id']}/history").json()["items"] == [
        created.json()
    ]
