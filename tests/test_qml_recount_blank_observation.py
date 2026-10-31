"""A recount instruction leaves the Counting Officer observation form blank."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_material_recount_f1_starts_blank_and_preserves_the_source_observation(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        source_response = setup["clients"]["receiveronly"].get(source_path)
        assert source_response.status_code == 200, source_response.text
        source_history_ids = [row["revision_id"] for row in source_response.json()["history"]]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        supervisor_id = setup["accounts"]["supervisor"]["id"]
        counter_id = setup["accounts"]["receiveronly"]["id"]
        assert supervisor_id != counter_id
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        request_id = str(uuid4())
        instructed_response = setup["clients"]["supervisor"].post(
            recount_path,
            json={
                "request_id": request_id,
                "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": prior["selection"]["revision"],
                "source_round_id": prior["id"],
                "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": "A fresh physical tally is instructed; no new observation exists yet.",
                "password": READY_PASSWORD,
            },
        )
        assert instructed_response.status_code == 201, instructed_response.text
        instruction = instructed_response.json()["instruction"]
        blank = instructed_response.json()["round"]
        assert instruction["request_id"] == request_id
        assert blank["id"] == instruction["new_round_id"] and blank["id"] != prior["id"]
        # Prove the API null contract before reaching the expected UI-only RED.
        assert all(blank[key] is None for key in ("event_at", "entered_at", "actor_id"))
        assert blank["revision_actor_id"] == instruction["actor_id"] == supervisor_id
        assert blank["revision_event_at"] == instruction["event_at"]
        assert blank["revision_entered_at"] == instruction["entered_at"]
        assert all(row["quantity"] is None for row in blank["candidate_votes"])
        assert all(row["quantity"] is None for row in blank["invalid_papers"])
        assert blank["actual_counted_quantity"] is None and blank["questionable_quantity"] is None
        assert blank["f2"] is None and blank["physical_decisions"] == []
        assert blank["approval_valid"] is False and blank["selected"] is False

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": scope_id,
                "source_id": prior["id"],
                "new_round_id": blank["id"],
                "instruction_id": instruction["id"],
                "instruction_request_id": request_id,
                "instruction_actor_id": supervisor_id,
                "instruction_event_at": instruction["event_at"],
                "instruction_entered_at": instruction["entered_at"],
                "source_event_at": prior["event_at"],
                "source_event_text": "2026-11-15 23:15:12.123456",
                "source_actor_id": prior["actor_id"],
                "source_notes": prior["notes"],
                "source_approved_at": prior["approved_at"],
                "source_approved_by": prior["approved_by"],
                "source_candidate_votes": prior["candidate_votes"],
                "source_history_ids": source_history_ids,
            },
            """
            click('countingRoundsNavigation')
            editor = controller.property('countingRounds')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            assert [row['id'] for row in editor.property('state')['scopes']] == [setup['scope_id']]
            choose('countingRoundsScope', 1)
            wait(lambda: idle()
                and editor.property('state')['selected_scope_id'] == setup['scope_id'])
            assert len(editor.property('state')['rounds']) == 2

            # The real picker maps exactly the public nonempty rounds list.
            def round_index(round_id):
                return next(index for index, row in enumerate(editor.property('state')['rounds'])
                    if row['id'] == round_id)
            choose('countingRoundsRound', round_index(setup['source_id']))
            wait(lambda: idle()
                and editor.property('state')['selected']['id'] == setup['source_id'])
            choose('countingRoundsRound', round_index(setup['new_round_id']))
            wait(lambda: idle()
                and editor.property('state')['selected']['id'] == setup['new_round_id'])

            # Expected first RED at63d5d5b: this actual control contains an em dash.
            assert control('f1EventAt').property('text') == '', (
                'A Supervisor instruction must not populate the CO observation-time input')
            assert control('f1EventAt').property('readOnly') is False
            state = editor.property('state')
            record = state['selected']
            assert state['role'] == 'counting_officer' and state['dirty'] is False
            assert all(state['forms'][key] == '' for key in (
                'event_at', 'notes', 'questionable_quantity', 'actual_counted_quantity'))
            assert control('f1Notes').property('text') == ''
            assert control('f1QuestionableQuantity').property('text') == ''
            assert control('f1ActualCountedQuantity').property('text') == ''
            for row in state['candidate_inputs']:
                assert row['quantity'] == ''
                name = 'f1CandidateQuantity_' + str(row['candidate_id'])
                assert control(name).property('text') == ''
            for row in state['invalid_inputs']:
                assert row['quantity'] == '' and row['explanation'] == ''
                assert control('f1InvalidQuantity_' + str(row['reason_id'])).property('text') == ''
            assert all(record[key] is None for key in ('event_at', 'entered_at', 'actor_id'))
            assert record['revision_actor_id'] == setup['instruction_actor_id']
            assert record['revision_event_at'] == setup['instruction_event_at']
            assert record['revision_entered_at'] == setup['instruction_entered_at']
            assert record['recount_instruction']['id'] == setup['instruction_id']
            assert record['recount_instruction']['request_id'] == setup['instruction_request_id']
            assert record['f2'] is None and record['physical_decisions'] == []
            assert record['completed_at'] is None and record.get('approved_at') is None
            assert record.get('approved_by') is None and record.get('submitted_by') is None
            assert record.get('submitted_at') is None
            assert record['approval_valid'] is False and record['selected'] is False
            assert record['selection']['round_id'] == setup['source_id']

            choose('countingRoundsRound', round_index(setup['source_id']))
            wait(lambda: idle()
                and editor.property('state')['selected']['id'] == setup['source_id'])
            old = editor.property('state')
            assert control('f1EventAt').property('text') == setup['source_event_text']
            assert old['selected']['event_at'] == setup['source_event_at']
            assert old['selected']['actor_id'] == setup['source_actor_id']
            assert old['selected']['approved_at'] == setup['source_approved_at']
            assert old['selected']['approved_by'] == setup['source_approved_by']
            assert old['selected']['notes'] == setup['source_notes']
            assert control('f1Notes').property('text') == setup['source_notes']
            assert [row['quantity'] for row in old['selected']['candidate_votes']] == [6, 4]
            for row in setup['source_candidate_votes']:
                name = 'f1CandidateQuantity_' + str(row['candidate_id'])
                assert control(name).property('text') == str(row['quantity'])
            assert [row['revision_id'] for row in old['history']] == setup['source_history_ids']
            assert old['dirty'] is False
            """,
        )
        # This client only views records; its session creates no operational writes.
        assert not [item for item in https_server.requests
                    if item[0] in ("POST", "PUT", "PATCH", "DELETE")
                    and item[1].startswith("/api/workspace/")]
        preserved_response = setup["clients"]["receiveronly"].get(source_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == source_history_ids
        for key in ("candidate_votes", "invalid_papers", "f2", "event_at", "entered_at",
                    "actor_id", "approved_at", "approved_by", "notes"):
            assert preserved["record"][key] == prior[key]
