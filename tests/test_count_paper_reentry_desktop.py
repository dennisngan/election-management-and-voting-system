"""Count-paper reentry through the actual Material count-round submission flow."""

from uuid import uuid4

import pytest
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
                "f1_votes": before["candidate_votes"],
                "f1_invalid": before["invalid_papers"],
                "f2_accepted": before["f2"]["accepted_votes"],
                "f2_rejected": before["f2"]["rejected_papers"],
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
            assert still_selected['selected']['candidate_votes'] == setup['f1_votes']
            assert still_selected['selected']['invalid_papers'] == setup['f1_invalid']
            assert still_selected['selected']['f2']['accepted_votes'] == setup['f2_accepted']
            assert still_selected['selected']['f2']['rejected_papers'] == setup['f2_rejected']

            outages = controller.outages
            assert outages.loadOutage(setup['outage_id'], False) is True
            wait(lambda: not outages.property('state')['busy'])
            pending = outages.property('state')['selected']['paper_records']
            assert len(pending) == 1
            assert pending[0]['status'] == 'pending'
            assert pending[0].get('reentry') is None

            click('countSubmit')
            wait(lambda: not editor.property('state')['busy']
                and editor.property('state')['notice'] == 'count_submitted')
            submitted = editor.property('state')
            assert submitted['selected']['status'] == 'submitted'
            assert submitted['selected']['candidate_votes'] == setup['f1_votes']
            assert submitted['selected']['invalid_papers'] == setup['f1_invalid']
            assert submitted['selected']['f2']['accepted_votes'] == setup['f2_accepted']
            assert submitted['selected']['f2']['rejected_papers'] == setup['f2_rejected']
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

            recovery = controller.recovery
            recovery.reload()
            wait(lambda: not recovery.property('state')['busy'])
            recovered = next(row for row in recovery.property('state')['commands']
                if row['request_id'] == linked['reentry']['request_id'])
            assert recovered['workflow'] == 'count'
            assert recovered['status'] == 'committed'
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
