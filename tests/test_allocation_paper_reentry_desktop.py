"""Allocation paper reentry is selectable and saved through the real Material workflow."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.desktop_support import ControlledClock, HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import READY_PASSWORD
from tests.test_allocation_api import allocation_setup as allocation_setup


@pytest.fixture
def paper_registration_client(
    database_url: str,
    allocation_setup: dict,
    https_server: HttpsServer,
) -> Iterator[tuple[str, dict]]:
    setup = allocation_setup
    clock = ControlledClock(datetime(2026, 11, 15, 1, 0, tzinfo=UTC))
    https_server.clock.value = clock.value
    with TestClient(create_app(database_url, now=clock), base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={"username": setup["account"]["username"], "password": READY_PASSWORD},
        )
        assert login.status_code == 200, login.text
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        base = setup["base"]
        outage = client.post(
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
        event_at = "2026-11-15T08:15:00+08:00"
        paper = client.post(
            outage_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-ALLOCATION-" + uuid4().hex[:12],
                "workflow": "allocation",
                "action": "create",
                "original_event_at": event_at,
                "target": {"counter_id": setup["counter"]["id"]},
                "notes": "Signed paper allocation return.",
            },
        )
        assert paper.status_code == 201, paper.text
        assert paper.json()["status"] == "pending"
        yield outage_path, paper.json()


def test_officer_links_pending_paper_through_visible_allocation_form(
    allocation_setup: dict,
    paper_registration_client: tuple[str, dict],
    https_server: HttpsServer,
) -> None:
    setup = allocation_setup
    outage_path, paper = paper_registration_client
    scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        state = editor.property('state')
        assert [row['id'] for row in state.get('paper_records', [])] == [PAPER_ID]
        assert control('allocationPaperRecord').property('visible')
        choose('allocationPaperRecord', 1)
        state = editor.property('state')
        assert state['paper_record']['id'] == PAPER_ID
        assert state['paper_record']['status'] == 'pending'
        assert control('allocationEventAt').property('text') == '2026-11-15 08:15'
        choose('allocationCounter', 0)
        enter('allocationSeries', '普通系列 A')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000002')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['error'] == ''
        assert state['selected']['revision'] == 1
    """.replace("PAPER_ID", str(paper["id"]))
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
        },
        scenario,
    )

    current = setup["officer"].get(setup["base"] + "/allocations")
    assert current.status_code == 200, current.text
    items = current.json()["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 2
    assert current.json()["availability"][0]["available_quantity"] == 6

    outage = setup["officer"].get(outage_path)
    assert outage.status_code == 200, outage.text
    rows = outage.json()["record"]["paper_records"]
    assert len(rows) == 1
    entered = rows[0]
    assert entered["id"] == paper["id"]
    assert entered["status"] == "entered"
    assert entered["reentry"]["request_id"]
    assert entered["reentry"]["record"] == items[0]
