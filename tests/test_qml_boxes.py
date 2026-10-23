"""Box QML controls execute real station workflows; native Computer proof is separate."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.box_support import (
    READY_PASSWORD,
    BoxClock,
    box_staff,
    box_stations,
    event_command,
    prepared_box,
)
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_uses_visible_box_fields_departure_and_report_buttons(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    station, clock = box_stations(admin)["N2"], BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station["id"],
                "locale": locale,
            },
            """
            click('boxesNavigation')
            boxes = controller.property('boxes')
            wait(lambda: not boxes.property('state')['busy'])
            frame()
            assert control('boxReference').property('visible') is True
            enter('boxReference', '界面票箱 0001')
            enter('boxSeal', '封條 000099')
            enter('boxPreparedTime', '2026-11-15 22:40')
            assert boxes.property('state')['forms']['box_reference'] == '界面票箱 0001'
            click('boxCreate')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['error'] == ''
            assert boxes.property('state')['selected']['revision'] == 1
            assert control('boxOrigin').property('value').startswith('N2 · ')
            assert control('boxDestination').property('value').startswith('N1 · ')
            frame()
            enter('boxEventTime', '2026-11-15 22:45')
            enter('boxEventReason', '核對封條後送箱')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('boxDepart').property('activeFocus'))
            click('boxDepart')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['error'] == ''
            assert boxes.property('state')['selected']['revision'] == 2
            assert boxes.property('state')['selected']['status'] == 'departed'
            frame()
            click('boxPreview')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['report']['locale'] == setup['locale']
            assert '界面票箱 0001' in control('boxReportPreview').property('text')
            """,
        )
        saved = api.get(f"/api/workspace/stations/{station['id']}/boxes").json()["items"]
        assert len(saved) == 1
        assert saved[0]["box_reference"] == "界面票箱 0001"
        assert saved[0]["seal_reference"] == "封條 000099"
        assert saved[0]["status"] == "departed"


def test_counting_officer_receives_sixth_arrival_and_records_milestones_through_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, _):
        with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
            receiver,
            account,
        ):
            for index in range(6):
                created = sender.post(
                    f"/api/workspace/stations/{origin['id']}/boxes",
                    json=prepared_box(box_reference=f"界面送箱 {index + 1:04d}"),
                )
                assert created.status_code == 201
                box_id = created.json()["id"]
                departed = sender.post(
                    f"/api/workspace/stations/{origin['id']}/boxes/{box_id}/departure",
                    json=event_command(1, "2026-11-15T22:45:00+08:00"),
                )
                assert departed.status_code == 201
                if index < 5:
                    received = receiver.post(
                        f"/api/workspace/stations/{destination['id']}/boxes/{box_id}/receipt",
                        json=event_command(2, "2026-11-15T22:50:00+08:00"),
                    )
                    assert received.status_code == 201
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": destination["id"],
                    "box_id": box_id,
                    "locale": "sc",
                },
                """
                click('boxesNavigation')
                boxes = controller.property('boxes')
                wait(lambda: not boxes.property('state')['busy'])
                frame()
                assert control('boxCreate').property('visible') is False
                choose('boxPicker', 5)
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['selected']['id'] == setup['box_id']
                frame()
                enter('boxEventTime', '2026-11-15 22:59')
                click('boxReceive')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                assert boxes.property('state')['selected']['status'] == 'received'
                frame()
                enter('boxMilestoneTime', '2026-11-15 23:00')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                frame()
                choose('boxMilestoneKind', 1)
                wait(lambda: boxes.property('state')['milestone_kind'] == 'first_box_opening')
                frame()
                choose('boxMilestoneBox', 5)
                assert boxes.property('state')['milestone_forms']['box_id'] == str(setup['box_id'])
                enter('boxMilestoneTime', '2026-11-15 23:05')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                frame()
                choose('boxMilestoneKind', 2)
                wait(lambda: boxes.property('state')['milestone_kind']
                    == 'questionable_determination_start')
                frame()
                enter('boxMilestoneTime', '2026-11-15 23:10')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                assert len(boxes.property('state')['milestone_history']) == 3
                assert boxes.property('state')['count_completion'] is None
                frame()
                click('boxPreview')
                wait(lambda: not boxes.property('state')['busy'])
                assert '界面送箱 0006' in control('boxReportPreview').property('text')
                """,
            )
            saved = receiver.get(f"/api/workspace/stations/{destination['id']}/boxes").json()
            assert len(saved["items"]) == 6
            assert all(row["status"] == "received" for row in saved["items"])
            assert saved["milestones"][1]["box_id"] == box_id
            assert saved["count_completion"] is None
