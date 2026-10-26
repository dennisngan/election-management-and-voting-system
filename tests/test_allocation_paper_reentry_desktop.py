"""Allocation paper reentry is selectable and saved through the real Material workflow."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import BoxClock, READY_PASSWORD, box_staff, box_stations
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def allocation_paper_setup(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> Iterator[dict]:
    station = box_stations(admin)["N1"]
    station_id = station["id"]
    clock = BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        polling,
        account,
    ):
        base = f"/api/workspace/stations/{station_id}"
        options = polling.get(base + "/allocations")
        assert options.status_code == 200, options.text
        counter = options.json()["counters"][0]
        series = "T25-ALLOCATION-" + uuid4().hex[:8]
        received = polling.post(
            base + "/stock",
            json=stock_payload(
                series=series,
                event_at="2026-11-15T08:00:00+08:00",
            ),
        )
        assert received.status_code == 201, received.text

        outage = polling.post(
            base + "/outages",
            json={
                "request_id": str(uuid4()),
                "reference": "T25 allocation paper " + uuid4().hex[:10],
                "kind": "network",
                "started_at": "2026-11-15T08:00:00+08:00",
                "ended_at": "2026-11-15T08:30:00+08:00",
                "notes": "A signed allocation return was retained during the interruption.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_path = base + f"/outages/{outage.json()['id']}"
        paper = polling.post(
            outage_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-PAPER-" + uuid4().hex[:12],
                "workflow": "allocation",
                "action": "create",
                "original_event_at": "2026-11-15T08:15:00+08:00",
                "target": {"counter_id": counter["id"]},
                "notes": "Signed paper allocation return.",
            },
        )
        assert paper.status_code == 201, paper.text
        assert paper.json()["status"] == "pending"
        yield {
            "polling": polling,
            "account": account,
            "station": station,
            "base": base,
            "counter": counter,
            "series": series,
            "outage_path": outage_path,
            "paper": paper.json(),
        }


def test_officer_links_pending_paper_through_visible_allocation_form(
    allocation_paper_setup: dict,
    https_server: HttpsServer,
) -> None:
    setup = allocation_paper_setup
    paper_id = setup["paper"]["id"]
    scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        choose('allocationCounter', 0)
        wait(idle)
        click('allocationPaperRefresh')
        wait(idle)
        state = editor.property('state')
        assert [row['id'] for row in state.get('paper_records', [])] == [PAPER_ID]
        assert control('allocationPaperRecord').property('visible')
        choose('allocationPaperRecord', 1)
        state = editor.property('state')
        assert state['paper_record']['id'] == PAPER_ID
        assert state['paper_record']['status'] == 'pending'
        assert control('allocationEventAt').property('text') == '2026-11-15 08:15'
        choose('allocationCounter', 0)
        enter('allocationSeries', 'SERIES_VALUE')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000002')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['error'] == ''
        assert state['selected']['revision'] == 1
    """.replace("PAPER_ID", str(paper_id)).replace("SERIES_VALUE", setup["series"])
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
        },
        scenario,
    )

    current = setup["polling"].get(setup["base"] + "/allocations")
    assert current.status_code == 200, current.text
    items = current.json()["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 2
    assert current.json()["availability"][0]["available_quantity"] == 6

    outage = setup["polling"].get(setup["outage_path"])
    assert outage.status_code == 200, outage.text
    rows = outage.json()["record"]["paper_records"]
    assert len(rows) == 1
    entered = rows[0]
    assert entered["id"] == paper_id
    assert entered["status"] == "entered"
    assert entered["reentry"]["request_id"]
    assert entered["reentry"]["record"] == items[0]
