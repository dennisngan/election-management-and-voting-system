"""Outage report previews stay bound to the selected paper/reconciliation snapshot."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
from tests.desktop_support import TLS_DIRECTORY, HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_client_recovery_contract_desktop import RecoveryFaultServer
from tests.test_client_recovery_contract_desktop import (
    recovery_fault_server as recovery_fault_server,
)
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url


def test_preview_rejects_peer_paper_change_at_same_outage_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        options = officer.get(setup["rounds_path"])
        assert options.status_code == 200, options.text
        counted = officer.post(
            setup["rounds_path"], json=complete_f1_command(options.json())
        )
        assert counted.status_code == 201, counted.text
        round_id = counted.json()["id"]

        outage_path = f"/api/workspace/stations/{station_id}/outages"
        created = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 snapshot-bound report " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:00:01.123456+08:00",
                "ended_at": "2026-11-15T23:30:02.654321+08:00",
                "notes": "Signed paper was retained during the interruption.",
            },
        )
        assert created.status_code == 201, created.text
        outage_id = created.json()["id"]
        outage_record_path = f"{outage_path}/{outage_id}"
        first_reference = "T25-PAPER-FIRST-" + uuid4().hex[:8]
        first_paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": first_reference,
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:20:00+08:00",
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "First paper count reference.",
            },
        )
        assert first_paper.status_code == 201, first_paper.text

        peer_reference = "T25-PAPER-PEER-" + uuid4().hex[:8]
        peer_payload = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": peer_reference,
            "workflow": "count",
            "action": "submit",
            "original_event_at": "2026-11-15T23:21:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
            "notes": "Second officer's paper count reference.",
        }
        report_path = outage_record_path + "/statement"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "ca_file": str(TLS_DIRECTORY / "ca.pem"),
                "peer_username": setup["accounts"]["bothcounting"]["username"],
                "peer_password": READY_PASSWORD,
                "peer_paper_path": outage_record_path + "/paper-records",
                "peer_paper_payload": peer_payload,
                "statement_path": report_path,
                "first_reference": first_reference,
                "peer_reference": peer_reference,
            },
            f"""
            import httpx

            click('outagesNavigation')
            editor = controller.outages
            wait(lambda: not editor.property('state')['busy'])
            assert editor.loadOutage({outage_id}, False) is True
            wait(lambda: not editor.property('state')['busy'])
            before = editor.property('state')
            assert before['selected']['id'] == {outage_id}
            assert before['selected']['revision'] == 1
            assert len(before['selected']['paper_records']) == 1
            assert (
                before['selected']['paper_records'][0]['paper_reference']
                == setup['first_reference']
            )

            click('outageReportPreview')
            wait(lambda: not editor.property('state')['busy'])
            original_preview = editor.property('state')['report']
            assert original_preview['revision'] == 1
            editor.refresh()
            wait(lambda: not editor.property('state')['refreshing'])
            unchanged = editor.property('state')
            assert unchanged['newer_revision'] is False
            assert unchanged['report'] == original_preview

            with httpx.Client(verify=setup['ca_file'], timeout=10) as peer:
                login = peer.post(setup['server'] + '/api/auth/login', json={{
                    'username': setup['peer_username'], 'password': setup['peer_password']
                }})
                assert login.status_code == 200
                headers = {{'Authorization': 'Bearer ' + login.json()['token']}}
                inserted = peer.post(
                    setup['server'] + setup['peer_paper_path'],
                    json=setup['peer_paper_payload'], headers=headers)
                assert inserted.status_code == 201
                current_statement = peer.get(
                    setup['server'] + setup['statement_path'],
                    params={{'locale': 'en'}}, headers=headers)
                assert current_statement.status_code == 200
                current_report = current_statement.json()
                assert current_report['revision'] == 1
                flattened = '\\n'.join(current_report['preview_lines'])
                assert setup['first_reference'] in flattened
                assert setup['peer_reference'] in flattened

            # The local selection is still revision 1 with only the first paper,
            # while the statement GET now represents the same outage revision and
            # both paper references. It must require a fresh explicit comparison.
            click('outageReportPreview')
            wait(lambda: not editor.property('state')['busy'])
            stale = editor.property('state')
            assert stale['selected']['revision'] == 1
            assert len(stale['selected']['paper_records']) == 1
            assert stale['newer_revision'] is True
            assert stale['report'] == {{}}
            assert stale['error'] == 'outage_revision_conflict'
            """,
        )


def test_uncertain_outage_save_disables_report_preview(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
) -> None:
    stations = box_stations(admin)
    station_id = stations["N1"]["id"]
    clock = BoxClock()
    recovery_fault_server.clock.value = clock.value
    base = f"/api/workspace/stations/{station_id}/outages"
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        officer,
        account,
    ):
        created = officer.post(
            base,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 uncertain report guard " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T08:00:00+08:00",
                "ended_at": "2026-11-15T08:30:00+08:00",
                "notes": "Paper records were retained during the interruption.",
            },
        )
        assert created.status_code == 201, created.text
        outage_id = created.json()["id"]
        outage_path = f"{base}/{outage_id}"
        recovery_fault_server.fail_after_path = outage_path

        run_workspace_qml(
            {
                "server": recovery_fault_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            f"""
            click('outagesNavigation')
            editor = controller.outages
            wait(lambda: not editor.property('state')['busy'])
            assert editor.loadOutage({outage_id}, False) is True
            wait(lambda: not editor.property('state')['busy'])
            editor.setField('notes', 'The server commits but the response is lost.')
            editor.setField('amendment_reason', 'Matched the retained network log.')
            editor.save()
            wait(lambda: editor.property('state')['uncertain_save'])
            state = editor.property('state')
            assert state['dirty'] is True
            assert control('outageReportPreview').property('enabled') is False
            editor.previewReport('en')
            assert editor.property('state')['uncertain_save'] is True
            assert editor.property('state')['report'] == {{}}
            assert editor.property('state')['error'] == 'outage_uncertain_save_pending'
            """,
        )

        assert recovery_fault_server.request_count("PUT", outage_path) == 1
        assert recovery_fault_server.request_count(
            "GET", outage_path + "/statement"
        ) == 0
