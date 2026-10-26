"""Supervisor passwords stay ephemeral in the outage Material page."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url


def test_supervisor_password_clears_when_workspace_station_changes(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        supervisor = setup["accounts"]["supervisor"]
        n1_id = setup["stations"]["N1"]["id"]
        n2_id = setup["stations"]["N2"]["id"]
        counter = setup["counter"]
        rounds_path = setup["rounds_path"]
        options_response = counter.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = counter.post(rounds_path, json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        f2 = counter.put(
            f"{rounds_path}/{round_id}/f2",
            json=complete_f2_command(options),
        )
        assert f2.status_code == 200, f2.text
        outage_path = f"/api/workspace/stations/{n1_id}/outages"
        created = counter.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 supervisor password reset " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:10:00+08:00",
                "ended_at": "2026-11-15T23:50:00+08:00",
                "notes": "Paper records were retained during the interruption.",
            },
        )
        assert created.status_code == 201, created.text
        outage_id = created.json()["id"]
        paper = counter.post(
            f"{outage_path}/{outage_id}/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-SUPERVISOR-" + uuid4().hex[:8],
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:35:12+08:00",
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Signed paper count retained for Supervisor review.",
            },
        )
        assert paper.status_code == 201, paper.text
        assert paper.json()["status"] == "pending"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": supervisor["username"],
                "password": READY_PASSWORD,
                "station_id": n1_id,
                "locale": "en",
                "outage_id": outage_id,
                "next_station_id": n2_id,
                "approval_password": READY_PASSWORD,
            },
            """
            click('outagesNavigation')
            outages = controller.outages
            assert window.property('currentPage') == 'outages'
            wait(lambda: not outages.property('state')['busy'])
            assert outages.property('state')['station_id'] == setup['station_id']
            assert outages.property('state')['role'] == 'supervisor'
            assert outages.property('state')['writable'] is True
            assert outages.loadOutage(setup['outage_id'], False) is True
            wait(lambda: not outages.property('state')['busy'])
            assert outages.property('state')['selected']['id'] == setup['outage_id']
            assert len(outages.property('state')['selected']['paper_records']) == 1

            password_entry = control('outageApprovalPassword')
            assert password_entry.property('visible') is True
            assert password_entry.property('enabled') is True
            assert password_entry.property('textValue') == ''
            password_entry.setProperty('textValue', setup['approval_password'])
            assert password_entry.property('textValue') == setup['approval_password']
            assert setup['approval_password'] not in repr(controller.property('state'))
            assert setup['approval_password'] not in repr(outages.property('state'))

            workspace = controller.workspace
            workspace.selectStation(setup['next_station_id'])
            wait(lambda: not workspace.property('state')['busy'])
            assert (
                workspace.property('state')['selected']['station']['id']
                == setup['next_station_id']
            )
            wait(lambda: not outages.property('state')['busy'])
            assert outages.property('state')['station_id'] == setup['next_station_id']
            assert outages.property('state')['selected'] == {}
            assert window.property('currentPage') == 'outages'
            assert password_entry.property('textValue') == ''
            assert setup['approval_password'] not in repr(controller.property('state'))
            assert setup['approval_password'] not in repr(outages.property('state'))
            """,
        )
