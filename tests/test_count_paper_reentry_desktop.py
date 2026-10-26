"""Count-paper reentry through the actual Material count-round submission flow."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.outcomes_support import complete_f2_command
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


@pytest.fixture(autouse=True)
def isolated_client_command_journal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "desktop-commands"))


def test_counting_officer_selects_pending_paper_and_submits_it_once_in_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = officer.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = officer.post(rounds_path, json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        round_path = f"{rounds_path}/{round_id}"
        f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        saved = officer.get(round_path)
        assert saved.status_code == 200, saved.text
        before = saved.json()["record"]
        assert before["status"] == "draft"
        assert before["f1_complete"] is True
        assert before["f2"] is not None

        outages_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outages_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 count paper outage " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:10:00+08:00",
                "ended_at": "2026-11-15T23:50:00+08:00",
                "notes": "The paper count form was retained during the interruption.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_path = f"{outages_path}/{outage_id}"
        paper_reference = "T25-PAPER-COUNT-" + uuid4().hex[:8]
        original_paper_time = "2026-11-15T23:35:12.345678+08:00"
        paper = officer.post(
            outage_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": paper_reference,
                "workflow": "count",
                "action": "submit",
                "original_event_at": original_paper_time,
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Count completed on the signed paper tally.",
            },
        )
        assert paper.status_code == 201, paper.text
        assert paper.json()["status"] == "pending"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": setup["scope"]["id"],
                "round_id": round_id,
                "paper_id": paper.json()["id"],
                "paper_reference": paper_reference,
                "outage_id": outage_id,
                "f2_notes": "The saved F2 observation remains separate from paper submission.",
                "f1_votes": [
                    [row["candidate_id"], row["quantity"]]
                    for row in before["candidate_votes"]
                ],
                "f1_invalid": [
                    [row["reason_id"], row["reason_revision"], row["quantity"], row["explanation"]]
                    for row in before["invalid_papers"]
                ],
                "f2_accepted": [
                    [row["candidate_id"], row["quantity"]]
                    for row in before["f2"]["accepted_votes"]
                ],
                "f2_rejected": [
                    [row["reason_id"], row["reason_revision"], row["quantity"], row["explanation"]]
                    for row in before["f2"]["rejected_papers"]
                ],
            },
            f"""
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectScope({setup['scope']['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectRound({round_id}) is True
            wait(lambda: not editor.property('state')['busy'])
            draft = editor.property('state')['selected']
            assert draft['status'] == 'draft'
            assert draft['revision'] == 2

            picker = control('countRoundPaperRecord')
            assert picker.property('visible') is True
            assert picker.property('enabled') is True
            option_count = int(picker.property('count'))
            assert option_count > 0
            for index in range(option_count):
                choose('countRoundPaperRecord', index)
                wait(lambda: not editor.property('state')['busy'])
                if editor.property('state')['paper_record'].get('id') == setup['paper_id']:
                    break
            selected_paper = editor.property('state')['paper_record']
            assert selected_paper['id'] == setup['paper_id']
            assert selected_paper['paper_reference'] == setup['paper_reference']
            assert setup['paper_reference'] in picker.property('displayText')

            # The paper identity is only attached to count submission. An ordinary
            # F2 save remains an ordinary observation and leaves the paper pending.
            editor.setF2Field('notes', setup['f2_notes'])
            click('f2Save')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['selected'].get('f2', {{}}).get('notes')
                == setup['f2_notes'])
            still_selected = editor.property('state')
            assert still_selected['paper_record']['id'] == setup['paper_id']
            assert [[row['candidate_id'], row['quantity']]
                for row in still_selected['selected']['candidate_votes']] == setup['f1_votes']
            assert [[row['reason_id'], row['reason_revision'], row['quantity'], row['explanation']]
                for row in still_selected['selected']['invalid_papers']] == setup['f1_invalid']
            assert (
                [[row['candidate_id'], row['quantity']]
                    for row in still_selected['selected']['f2']['accepted_votes']]
                == setup['f2_accepted']
            )
            assert (
                [[row['reason_id'], row['reason_revision'], row['quantity'], row['explanation']]
                    for row in still_selected['selected']['f2']['rejected_papers']]
                == setup['f2_rejected']
            )

            outages = controller.outages
            assert outages.loadOutage(setup['outage_id'], False) is True
            wait(lambda: not outages.property('state')['busy'])
            pending = outages.property('state')['selected']['paper_records']
            assert len(pending) == 1
            assert pending[0]['status'] == 'pending'
            assert pending[0].get('reentry') is None
            recovery = controller.recovery
            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            f2_command = next(row for row in recovery.property('state')['commands']
                if row['workflow'] == 'count' and row['path'].endswith('/f2'))
            assert f2_command['status'] == 'committed'
            assert 'paper_record_id' not in f2_command['payload']

            click('countSubmit')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['notice'] == 'count_submitted')
            submitted = editor.property('state')
            assert submitted['selected']['status'] == 'submitted'
            assert [[row['candidate_id'], row['quantity']]
                for row in submitted['selected']['candidate_votes']] == setup['f1_votes']
            assert [[row['reason_id'], row['reason_revision'], row['quantity'], row['explanation']]
                for row in submitted['selected']['invalid_papers']] == setup['f1_invalid']
            assert [[row['candidate_id'], row['quantity']]
                for row in submitted['selected']['f2']['accepted_votes']] == setup['f2_accepted']
            assert [[row['reason_id'], row['reason_revision'], row['quantity'], row['explanation']]
                for row in submitted['selected']['f2']['rejected_papers']] == setup['f2_rejected']
            assert submitted['paper_record'] == {{}}

            assert outages.loadOutage(setup['outage_id'], True) is True
            wait(lambda: not outages.property('state')['busy'])
            entered = outages.property('state')['selected']['paper_records']
            assert len(entered) == 1
            linked = entered[0]
            assert linked['status'] == 'entered'
            assert linked['paper_reference'] == setup['paper_reference']
            assert linked['original_event_at'] == '2026-11-15T15:35:12.345678Z'
            assert linked['reentry']['actor_id'] == controller.property('state')['account']['id']
            assert linked['reentry']['record']['id'] == submitted['selected']['id']
            assert linked['reentry']['record']['revision'] == submitted['selected']['revision']
            assert linked['reentry']['record']['status'] == 'submitted'
            assert linked['reentry']['record']['completed_at'] != linked['original_event_at']

            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            recovered = next(row for row in recovery.property('state')['commands']
                if row['request_id'] == linked['reentry']['request_id'])
            assert recovered['workflow'] == 'count'
            assert recovered['status'] == 'committed'
            assert recovered['payload']['paper_record_id'] == setup['paper_id']
            assert recovered['receipt']['record']['id'] == submitted['selected']['id']
            assert recovered['receipt']['record']['revision'] == submitted['selected']['revision']
            """,
        )

        current_outage = officer.get(outage_path)
        assert current_outage.status_code == 200, current_outage.text
        linked = current_outage.json()["record"]["paper_records"]
        assert len(linked) == 1
        assert linked[0]["status"] == "entered"
        assert linked[0]["paper_reference"] == paper_reference
        receipt_id = linked[0]["reentry"]["request_id"]
        outcome = officer.get(
            f"/api/workspace/stations/{station_id}/request-outcomes/{receipt_id}",
            params={"workflow": "count"},
        )
        assert outcome.status_code == 200, outcome.text
        assert outcome.json()["status"] == "committed"
        assert outcome.json()["record"] == linked[0]["reentry"]["record"]
        assert outcome.json()["record"]["status"] == "submitted"

        final_round = officer.get(round_path)
        assert final_round.status_code == 200, final_round.text
        history = final_round.json()["history"]
        assert sum(row["status"] == "submitted" for row in history) == 1
        assert sum(row["status"] == "draft" for row in history) == 3
        assert history[0]["candidate_votes"] == before["candidate_votes"]
        assert history[0]["invalid_papers"] == before["invalid_papers"]


def test_supervisor_cannot_select_pending_count_paper_in_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = officer.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        counted = officer.post(
            rounds_path, json=complete_f1_command(options_response.json())
        )
        assert counted.status_code == 201, counted.text

        outages_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outages_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 supervisor paper picker " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:10:00+08:00",
                "ended_at": "2026-11-15T23:50:00+08:00",
                "notes": "The paper count form was retained during the interruption.",
            },
        )
        assert outage.status_code == 201, outage.text
        paper = officer.post(
            f"{outages_path}/{outage.json()['id']}/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T25-PAPER-SUPERVISOR-" + uuid4().hex[:8],
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:35:12.345678+08:00",
                "target": {
                    "scope_id": setup["scope"]["id"],
                    "round_id": counted.json()["id"],
                },
                "notes": "Count completed on the signed paper tally.",
            },
        )
        assert paper.status_code == 201, paper.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            f"""
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectScope({setup['scope']['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectRound({counted.json()['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['role'] == 'supervisor'
            picker = control('countRoundPaperRecord')
            assert picker.property('visible') is False
            assert editor.selectPaperRecord({paper.json()['id']}) is False
            """,
        )


def test_ordinary_count_submit_does_not_add_a_paper_flag(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = officer.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = officer.post(rounds_path, json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        f2 = officer.put(
            f"{rounds_path}/{round_id}/f2", json=complete_f2_command(options)
        )
        assert f2.status_code == 200, f2.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": setup["scope"]["id"],
                "round_id": round_id,
            },
            f"""
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectScope({setup['scope']['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectRound({round_id}) is True
            wait(lambda: not editor.property('state')['busy'])
            click('countSubmit')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['notice'] == 'count_submitted')
            recovery = controller.recovery
            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            command = next(row for row in recovery.property('state')['commands']
                if row['workflow'] == 'count' and row['path'].endswith('/submit'))
            assert command['status'] == 'committed'
            assert 'paper_record_id' not in command['payload']
            """,
        )

        current = officer.get(f"{rounds_path}/{round_id}")
        assert current.status_code == 200, current.text
        assert current.json()["record"]["status"] == "submitted"


def test_lost_count_response_keeps_paper_binding_until_matching_outcome_check(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        recovery_fault_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = officer.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = officer.post(rounds_path, json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        round_path = f"{rounds_path}/{round_id}"
        f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text

        outages_path = f"/api/workspace/stations/{station_id}/outages"
        outage = officer.post(
            outages_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 uncertain count paper " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:10:00+08:00",
                "ended_at": "2026-11-15T23:50:00+08:00",
                "notes": "The paper count form was retained during the interruption.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_path = f"{outages_path}/{outage_id}"
        paper_reference = "T25-PAPER-LOST-" + uuid4().hex[:8]
        paper = officer.post(
            outage_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": paper_reference,
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:35:12.345678+08:00",
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Count completed on the signed paper tally.",
            },
        )
        assert paper.status_code == 201, paper.text
        paper_id = paper.json()["id"]
        submit_path = round_path + "/submit"
        recovery_fault_server.fail_after_path = submit_path

        run_workspace_qml(
            {
                "server": recovery_fault_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": setup["scope"]["id"],
                "round_id": round_id,
                "paper_id": paper_id,
                "paper_reference": paper_reference,
                "outage_id": outage_id,
            },
            f"""
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectScope({setup['scope']['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectRound({round_id}) is True
            wait(lambda: not editor.property('state')['busy']
                and any(row['id'] == setup['paper_id']
                    for row in editor.property('state')['paper_records']))
            choose('countRoundPaperRecord', 1)
            wait(lambda: editor.property('state')['paper_record'].get('id') == setup['paper_id'])
            click('countSubmit')
            wait(lambda: editor.property('state')['uncertain_save'])
            uncertain = editor.property('state')
            assert uncertain['paper_binding_locked'] is True
            assert uncertain['paper_record']['id'] == setup['paper_id']
            assert editor.selectPaperRecord(0) is False
            assert editor.property('state')['paper_record']['id'] == setup['paper_id']

            recovery = controller.recovery
            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            command = next(row for row in recovery.property('state')['commands']
                if row['workflow'] == 'count' and row['path'] == {submit_path!r})
            assert command['status'] == 'uncertain'
            assert command['payload']['paper_record_id'] == setup['paper_id']
            recovery.checkOutcome(command['request_id'])
            wait(lambda: not recovery.property('state')['busy']
                and next(row for row in recovery.property('state')['commands']
                    if row['request_id'] == command['request_id'])['status'] == 'committed')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['selected']['status'] == 'submitted')
            settled = editor.property('state')
            assert settled['uncertain_save'] is False
            assert settled['paper_binding_locked'] is False
            assert settled['paper_record'] == {{}}
            outages = controller.outages
            assert outages.loadOutage(setup['outage_id'], False) is True
            wait(lambda: not outages.property('state')['busy'])
            linked = outages.property('state')['selected']['paper_records'][0]
            assert linked['status'] == 'entered'
            assert linked['reentry']['request_id'] == command['request_id']
            assert linked['reentry']['record']['id'] == settled['selected']['id']
            """,
        )

        current = officer.get(outage_path)
        assert current.status_code == 200, current.text
        paper_record = current.json()["record"]["paper_records"][0]
        assert paper_record["status"] == "entered"
        assert paper_record["paper_reference"] == paper_reference
        assert paper_record["reentry"]["record"]["status"] == "submitted"
        linked_request_id = paper_record["reentry"]["request_id"]
        outcome = officer.get(
            f"/api/workspace/stations/{station_id}/request-outcomes/{linked_request_id}",
            params={"workflow": "count"},
        )
        assert outcome.status_code == 200, outcome.text
        assert outcome.json()["status"] == "committed"
        assert outcome.json()["record"] == paper_record["reentry"]["record"]


def test_ordinary_count_submit_keeps_legacy_command_without_paper_field(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = officer.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = officer.post(rounds_path, json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        round_path = f"{rounds_path}/{round_id}"
        f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": setup["scope"]["id"],
                "round_id": round_id,
            },
            f"""
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectScope({setup['scope']['id']}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.selectRound({round_id}) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['paper_record'] == {{}}
            click('countSubmit')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['notice'] == 'count_submitted')
            recovery = controller.recovery
            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            command = next(row for row in recovery.property('state')['commands']
                if row['workflow'] == 'count' and row['path'].endswith('/submit'))
            assert command['status'] == 'committed'
            assert 'paper_record_id' not in command['payload']
            """,
        )

        latest = officer.get(round_path)
        assert latest.status_code == 200, latest.text
        assert latest.json()["record"]["status"] == "submitted"
        assert sum(row["status"] == "submitted" for row in latest.json()["history"]) == 1
