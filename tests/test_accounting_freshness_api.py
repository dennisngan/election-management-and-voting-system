"""A prepared P(18) must visibly require review after later stock activity."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.stock_support import stock_payload
from tests.test_accounting_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_accounting_api import database_url as database_url
from tests.turnout_support import READY_PASSWORD, turnout_staff


@pytest.mark.parametrize("movement", ["receipt", "return"])
def test_later_stock_activity_invalidates_current_p18_and_retains_its_accounting(
    admin: TestClient,
    database_url: str,
    movement: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer = setup["officer"]
        special = officer.post(setup["path"], json=setup["command"])
        assert special.status_code == 201
        station_id, path = special.json()["station_id"], setup["base"] + "/accounting"
        with (
            turnout_staff(
                admin, database_url, setup["clock"], [station_id], "counting_officer"
            ) as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id], "supervisor") as (
                supervisor,
                _,
            ),
        ):
            selection = {
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
            }
            saved = counter.put(path, json=selection)
            assert saved.status_code == 200
            assert (
                counter.post(
                    path + "/submit",
                    json={
                        "request_id": str(uuid4()),
                        "expected_revision": 1,
                    },
                ).status_code
                == 200
            )
            approved = supervisor.post(
                path + "/approve",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "password": READY_PASSWORD,
                },
            )
            assert approved.status_code == 200
            assert approved.json()["approval_valid"] is True
            if movement == "receipt":
                changed = officer.post(
                    setup["base"] + "/stock",
                    json=stock_payload(
                        event_at="2026-11-15T10:00:00+08:00",
                        ordinary_quantity=5,
                        replacement_quantity=0,
                        tendered_quantity=0,
                        ranges=[
                            {"pool": "ordinary", "serial_from": "000100", "serial_to": "000104"}
                        ],
                    ),
                )
            else:
                changed = officer.post(
                    setup["base"] + "/stock-returns",
                    json={
                        "request_id": str(uuid4()),
                        "event_at": "2026-11-15T10:00:00+08:00",
                        "counter_id": setup["snapshot"]["counters"][0]["counter"]["id"],
                        "series": "普通系列 A",
                        "serial_from": "000006",
                        "serial_to": "000010",
                    },
                )
            assert changed.status_code == 201, changed.text
            current = counter.get(path)
            assert current.status_code == 200
            assert current.json()["record"]["source_current"] is False
            assert current.json()["record"]["approval_valid"] is False
            assert current.json()["record"]["summary"] == approved.json()["summary"]
            assert current.json()["special_options"][0]["source_current"] is False
            stale = counter.put(
                path,
                json={
                    **selection,
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "amendment_reason": "Recheck after later stock movement",
                },
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "accounting_source_stale"


def test_older_cumulative_special_observation_is_not_offered_as_current_p18_source(
    admin: TestClient,
    database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        first = setup["officer"].post(setup["path"], json=setup["command"])
        assert first.status_code == 201
        second = setup["officer"].post(
            setup["path"],
            json={
                **setup["command"],
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:00+08:00",
            },
        )
        assert second.status_code == 201
        current = setup["officer"].get(setup["base"] + "/accounting")
        assert current.status_code == 200
        assert [
            (row["id"], row["source_current"]) for row in current.json()["special_options"]
        ] == [
            (first.json()["id"], False),
            (second.json()["id"], True),
        ]
