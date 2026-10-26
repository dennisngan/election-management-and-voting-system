"""Allocation paper reentry is exercised through real Material controls and public APIs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
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
def allocation_base_setup(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> Iterator[dict]:
    stations = box_stations(admin, activate=False)
    station = stations["N1"]
    station_id = station["id"]
    counter_path = (
        f"/api/elections/{station['election_id']}/constituencies/"
        f"{station['constituency_id']}/stations/{station_id}/counters"
    )
    second_counter = admin.post(
        counter_path,
        json={
            "code": "C2",
            "name": "第二發票櫃台",
            "request_id": str(uuid4()),
        },
    )
    assert second_counter.status_code == 201, second_counter.text
    activated = admin.post(
        f"/api/elections/{stations['election']['id']}/activate",
        json={
            "election_revision": stations["election"]["revision"],
            "schedule_revision": 1,
        },
    )
    assert activated.status_code == 200, activated.text
    clock = BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        polling,
        account,
    ):
        base = f"/api/workspace/stations/{station_id}"
        options = polling.get(base + "/allocations")
        assert options.status_code == 200, options.text
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        series = "T25-ALLOCATION-" + uuid4().hex[:8]
        received = polling.post(
            base + "/stock",
            json=stock_payload(
                series=series,
                event_at="2026-11-15T08:00:00+08:00",
            ),
        )
        assert received.status_code == 201, received.text
        yield {
            "admin": admin,
            "polling": polling,
            "account": account,
            "station": station,
            "base": base,
            "counter": counter,
            "second_counter": second_counter.json(),
            "series": series,
            "clock": clock,
            "database_url": database_url,
        }


def _register_paper(
    setup: dict,
    *,
    action: str,
    target: dict[str, int],
    event_at: str = "2026-11-15T08:15:00+08:00",
) -> tuple[str, dict]:
    polling, base = setup["polling"], setup["base"]
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
            "action": action,
            "original_event_at": event_at,
            "target": target,
            "notes": "Signed paper allocation return.",
        },
    )
    assert paper.status_code == 201, paper.text
    assert paper.json()["status"] == "pending"
    return outage_path, paper.json()


@pytest.fixture
def allocation_paper_setup(allocation_base_setup: dict) -> dict:
    setup = allocation_base_setup
    outage_path, paper = _register_paper(
        setup,
        action="create",
        target={"counter_id": setup["counter"]["id"]},
    )
    return {**setup, "outage_path": outage_path, "paper": paper}


def _counter_index_script(editor: str, counter_id: int) -> str:
    return (
        "next(i for i, row in enumerate("
        + editor
        + ".property('state')['counters']) if row['id'] == "
        + str(counter_id)
        + ")"
    )


def test_officer_links_pending_paper_through_visible_allocation_form(
    allocation_paper_setup: dict,
    https_server: HttpsServer,
) -> None:
    setup = allocation_paper_setup
    paper_id = setup["paper"]["id"]
    wrong_index = _counter_index_script("editor", setup["second_counter"]["id"])
    correct_index = _counter_index_script("editor", setup["counter"]["id"])
    scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        choose('allocationCounter', WRONG_INDEX)
        wait(idle)
        click('allocationPaperRefresh')
        wait(idle)
        assert editor.property('state')['paper_records'] == []
        assert editor.selectPaperRecord(PAPER_ID) is False
        assert editor.property('state')['paper_record'] == {}
        choose('allocationCounter', CORRECT_INDEX)
        wait(idle)
        click('allocationPaperRefresh')
        wait(idle)
        state = editor.property('state')
        assert [row['id'] for row in state['paper_records']] == [PAPER_ID], (
            state['forms']['counter_id'], state['counters'], state['error']
        )
        assert control('allocationPaperRecord').property('visible')
        choose('allocationPaperRecord', 1)
        state = editor.property('state')
        assert state['paper_record']['id'] == PAPER_ID
        assert state['paper_record']['status'] == 'pending'
        assert control('allocationEventAt').property('text') == '2026-11-15 08:15'
        choose('allocationCounter', WRONG_INDEX)
        state = editor.property('state')
        assert state['paper_record'] == {}
        choose('allocationCounter', CORRECT_INDEX)
        wait(idle)
        click('allocationPaperRefresh')
        wait(idle)
        choose('allocationPaperRecord', 1)
        choose('allocationCounter', CORRECT_INDEX)
        enter('allocationSeries', 'SERIES_VALUE')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000002')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['error'] == ''
        assert state['selected']['revision'] == 1
    """.replace("PAPER_ID", str(paper_id))
    scenario = scenario.replace("WRONG_INDEX", wrong_index).replace("CORRECT_INDEX", correct_index)
    scenario = scenario.replace("SERIES_VALUE", setup["series"])
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


def test_ordinary_allocation_then_reasoned_paper_amendment_use_material_form(
    allocation_base_setup: dict,
    https_server: HttpsServer,
) -> None:
    setup = allocation_base_setup
    correct_index = _counter_index_script("editor", setup["counter"]["id"])
    create_scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('allocationCounter', COUNTER_INDEX)
        enter('allocationSeries', 'SERIES_VALUE')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000002')
        enter('allocationEventAt', '2026-11-15 08:05')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['error'] == ''
        assert state['selected']['revision'] == 1
        assert state['paper_record'] == {}
    """.replace("COUNTER_INDEX", correct_index).replace("SERIES_VALUE", setup["series"])
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
        },
        create_scenario,
    )
    original = setup["polling"].get(setup["base"] + "/allocations")
    assert original.status_code == 200, original.text
    original_items = original.json()["items"]
    assert len(original_items) == 1
    assert original_items[0]["revision"] == 1

    event_at = "2026-11-15T08:15:00+08:00"
    outage_path, paper = _register_paper(
        setup,
        action="amend",
        target={
            "counter_id": setup["counter"]["id"],
            "allocation_id": original_items[0]["id"],
        },
        event_at=event_at,
    )
    amend_scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('allocationPicker', 0)
        wait(idle)
        assert editor.property('state')['selected']['revision'] == 1
        click('allocationPaperRefresh')
        wait(idle)
        assert [row['id'] for row in editor.property('state')['paper_records']] == [PAPER_ID]
        choose('allocationPaperRecord', 1)
        assert control('allocationEventAt').property('text') == '2026-11-15 08:15'
        enter('allocationSerialTo', '000003')
        enter('allocationReason', '核對簽署的紙本派票單')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['error'] == ''
        assert state['selected']['revision'] == 2
    """.replace("PAPER_ID", str(paper["id"]))
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": setup["account"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["station"]["id"],
        },
        amend_scenario,
    )

    current = setup["polling"].get(setup["base"] + "/allocations")
    assert current.status_code == 200, current.text
    assert len(current.json()["items"]) == 1
    corrected = current.json()["items"][0]
    assert corrected["revision"] == 2
    assert corrected["serial_to"] == "000003"
    assert current.json()["availability"][0]["available_quantity"] == 5
    history = setup["polling"].get(
        setup["base"] + f"/allocations/{corrected['id']}/history"
    )
    assert history.status_code == 200, history.text
    assert [row["revision"] for row in history.json()["items"]] == [1, 2]

    outage = setup["polling"].get(outage_path)
    assert outage.status_code == 200, outage.text
    entered = outage.json()["record"]["paper_records"][0]
    assert entered["id"] == paper["id"]
    assert entered["status"] == "entered"
    assert entered["reentry"]["record"] == corrected


def test_supervisor_cannot_select_polling_allocation_paper(
    allocation_paper_setup: dict,
    https_server: HttpsServer,
) -> None:
    setup = allocation_paper_setup
    with box_staff(
        setup["admin"],
        setup["database_url"],
        setup["clock"],
        "supervisor",
        [setup["station"]["id"]],
    ) as (_, supervisor):
        scenario = """
            click('allocationNavigation')
            editor = controller.property('allocations')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            assert editor.property('state')['role'] == 'supervisor'
            assert editor.property('state')['paper_records'] == []
            assert control('allocationPaperRecord').property('visible') is False
            assert editor.selectPaperRecord(PAPER_ID) is False
            assert editor.property('state')['paper_record'] == {}
        """.replace("PAPER_ID", str(setup["paper"]["id"]))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": supervisor["username"],
                "password": READY_PASSWORD,
                "station_id": setup["station"]["id"],
            },
            scenario,
        )


def test_lost_allocation_response_keeps_paper_binding_until_recovery_confirms_commit(
    allocation_paper_setup: dict,
    https_server: HttpsServer,
) -> None:
    setup = allocation_paper_setup
    paper_id = setup["paper"]["id"]
    counter_index = _counter_index_script("editor", setup["counter"]["id"])
    https_server.truncate_next_allocation_write = True
    scenario = """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('allocationCounter', COUNTER_INDEX)
        wait(idle)
        click('allocationPaperRefresh')
        wait(idle)
        choose('allocationPaperRecord', 1)
        enter('allocationSeries', 'SERIES_VALUE')
        enter('allocationSerialFrom', '000001')
        enter('allocationSerialTo', '000002')
        click('allocationSave')
        wait(idle)
        state = editor.property('state')
        assert state['paper_uncertain'] is True
        assert state['paper_record']['id'] == PAPER_ID
        assert control('allocationPaperRecord').property('enabled') is False
        assert control('allocationPaperClear').property('enabled') is False
        assert editor.selectPaperRecord(0) is False
        assert editor.property('state')['paper_record']['id'] == PAPER_ID

        recovery = controller.property('recovery')
        recovery.open()
        wait(lambda: not recovery.property('state')['busy'])
        commands = recovery.property('state')['commands']
        command = next(row for row in commands if row['workflow'] == 'allocation')
        assert command['status'] == 'uncertain'
        assert not any('password' in key.lower() for key in command)
        request_id = command['request_id']
        recovery.checkOutcome(request_id)
        wait(lambda: not recovery.property('state')['busy']
            and next(row for row in recovery.property('state')['commands']
                if row['request_id'] == request_id)['status'] == 'committed')
        wait(idle)
        state = editor.property('state')
        assert state['paper_uncertain'] is False
        assert state['paper_record'] == {}
        assert state['dirty'] is False
        assert state['selected']['revision'] == 1
    """.replace("PAPER_ID", str(paper_id))
    scenario = scenario.replace("COUNTER_INDEX", counter_index).replace(
        "SERIES_VALUE", setup["series"]
    )
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
    entered = outage.json()["record"]["paper_records"][0]
    assert entered["status"] == "entered"
    assert entered["reentry"]["record"] == items[0]
