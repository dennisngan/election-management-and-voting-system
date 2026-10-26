"""A Supervisor instructs a local recount through the actual Material workspace."""

from collections.abc import Iterator
from datetime import timedelta

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
def isolate_recount_material_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_instructs_a_blank_recount_without_switching_the_reviewed_round(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        counter = setup["clients"]["receiveronly"]
        prior = saved["selected"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is True, before.json()["pending"]
        assert [row["quantity"] for row in before.json()["candidate_totals"]] == [6, 4]
        prior_path = f"{setup['rounds_path']}/{prior['id']}"
        old_history_response = counter.get(prior_path)
        assert old_history_response.status_code == 200, old_history_response.text
        old_revision_ids = [row["revision_id"] for row in old_history_response.json()["history"]]
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        station_id = setup["stations"]["N1"]["id"]
        scope_id = setup["scope"]["id"]
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        reason = "The Supervisor instructs another physical tally of the same received boxes."
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": scope_id,
                "source_round_id": prior["id"],
                "source_round_revision": prior["revision"],
                "event_time": "2026-11-16 00:05:42.123456",
                "reason": reason,
            },
            """
            from PySide6.QtCore import QObject
            editor = controller.property('countingRounds')
            recounts = editor.property('recounts')
            assert isinstance(recounts, QObject), (
                'The counting workspace must expose its public recount instruction controller')

            click('countingRoundsNavigation')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')))
            assert [row['id'] for row in editor.property('state')['scopes']] == [setup['scope_id']]
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing'))
                and editor.property('state')['selected'].get('id') == setup['source_round_id']
                and not any(recounts.property('state')[key] for key in ('busy', 'refreshing')))
            reviewed = editor.property('state')['selected']
            assert reviewed['status'] == 'approved'
            assert reviewed['revision'] == setup['source_round_revision']

            enter('localRecountEventTime', setup['event_time'])
            enter('localRecountReason', setup['reason'])
            assert recounts.property('state')['dirty'] is True
            assert editor.property('state')['dirty'] is False
            assert control('localRecountInstruct').property('enabled') is True
            click('localRecountInstruct')
            enter('localRecountPassword', setup['password'])
            click('localRecountPasswordConfirm')
            wait(lambda: not any(recounts.property('state')[key]
                for key in ('busy', 'refreshing'))
                and recounts.property('state')['dirty'] is False
                and any(row['round_number'] == 2 for row in editor.property('state')['rounds']))
            assert recounts.property('state')['error'] == ''
            assert control('localRecountPassword').property('text') == ''
            assert setup['password'] not in json.dumps(recounts.property('state'))
            assert editor.property('state')['selected']['id'] == setup['source_round_id']
            assert editor.property('state')['selected']['revision'] == (
                setup['source_round_revision'])
            assert editor.property('state')['dirty'] is False
            """,
        )
        assert https_server.request_count("POST", recount_path) == 1
        instruction_response = supervisor.get(recount_path)
        assert instruction_response.status_code == 200, instruction_response.text
        instructions = instruction_response.json()["instructions"]
        assert len(instructions) == 1
        instruction = instructions[0]
        assert instruction_response.json()["latest_instruction"]["id"] == instruction["id"]
        assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert instruction["reason"] == reason
        assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
        assert instruction["source_round_id"] == prior["id"]
        assert instruction["status"] == "pending"
        assert instruction["new_round_number"] == 2
        rounds_response = counter.get(setup["rounds_path"])
        assert rounds_response.status_code == 200, rounds_response.text
        rounds = rounds_response.json()["rounds"]
        assert len(rounds) == 2
        recount = next(row for row in rounds if row["id"] == instruction["new_round_id"])
        assert recount["id"] != prior["id"] and recount["round_number"] == 2
        assert recount["status"] == "draft" and recount["actual_counted_quantity"] is None
        assert all(row["quantity"] is None for row in recount["candidate_votes"])
        assert recount["f2"] is None and recount["approval_valid"] is False
        preserved_response = counter.get(prior_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == old_revision_ids
        for key in ("candidate_votes", "invalid_papers", "f2", "approved_at", "approved_by"):
            assert preserved["record"][key] == prior[key]
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        assert after.json()["complete"] is False and after.json()["provisional"] is True
        pending = next(row for row in after.json()["pending"] if row["code"] == "recount_pending")
        assert pending["instruction_id"] == instruction["id"]
        assert pending["new_round_id"] == recount["id"]
        assert [row["quantity"] for row in after.json()["candidate_totals"]] == [0, 0]
