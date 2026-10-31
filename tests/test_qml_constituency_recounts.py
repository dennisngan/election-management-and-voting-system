"""One constituency-wide recount through the real Supervisor Material workspace."""

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
def isolate_constituency_recount_material_context(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_instructs_two_blank_constituency_rounds_through_material_controls(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        constituency_id = setup["constituency_id"]
        result_path = f"/api/workspace/constituencies/{constituency_id}/results"
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        old_rounds = {
            setup["scope"]["id"]: saved,
            setup["n3_scope"]["id"]: setup["n3_round"],
        }
        old_history = {}
        for scope_id, prior in old_rounds.items():
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            old_history[scope_id] = response.json()
        before = supervisor.get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is True
        assert before.json()["pending"] == []
        assert [row["quantity"] for row in before.json()["candidate_totals"]] == [6, 4]
        assert before.json()["provisional"] is True
        assert [row["quantity"] for row in setup["n3_round"]["selected"]["candidate_votes"]] == [
            0, 0,
        ]
        options = supervisor.get(target)
        assert options.status_code == 200, options.text
        assert options.json()["can_instruct"] is True
        assert options.json()["instructions"] == []
        assert https_server.request_count("POST", target) == 0

        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        reason = "Recount every North scope; retain the approved 6/4 and observed zero."
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "n1_station_id": setup["stations"]["N1"]["id"],
                "n3_station_id": setup["stations"]["N3"]["id"],
                "n1_scope_id": setup["scope"]["id"],
                "n3_scope_id": setup["n3_scope"]["id"],
                "source_round_id": saved["selected"]["id"],
                "n3_source_round_id": setup["n3_round"]["selected"]["id"],
                "event_time": "2026-11-16 00:05:42.123456",
                "reason": reason,
            },
            """
            from PySide6.QtCore import QObject
            editor = controller.property('countingRounds')
            click('countingRoundsNavigation')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')))
            assert [row['id'] for row in editor.property('state')['scopes']] == [
                setup['n1_scope_id']]
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing'))
                and editor.property('state')['selected'].get('id') == setup['source_round_id'])
            assert editor.property('state')['selected']['revision'] == 4

            results = controller.property('constituencyResults')
            assert isinstance(results, QObject)
            click('constituencyResultsNavigation')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            recounts = results.property('recounts')
            assert isinstance(recounts, QObject), (
                'Constituency results must expose its public wide-recount controller')
            wait(lambda: not any(recounts.property('state')[key]
                for key in ('busy', 'refreshing'))
                and recounts.property('state')['can_instruct'] is True)
            state = recounts.property('state')
            assert [(row['station_id'], row['scope_id']) for row in state['scope_sources']] == [
                (setup['n1_station_id'], setup['n1_scope_id']),
                (setup['n3_station_id'], setup['n3_scope_id']),
            ]
            assert [row['source_round_id'] for row in state['scope_sources']] == [
                setup['source_round_id'], setup['n3_source_round_id']]
            assert [row['scope_revision'] for row in state['scope_sources']] == [2, 1]
            assert [row['source_round_revision'] for row in state['scope_sources']] == [4, 4]
            assert [row['expected_selection_revision'] for row in state['scope_sources']] == [1, 1]
            assert state['instructions'] == []
            assert state['dirty'] is False and state['uncertain_save'] is False
            assert state['pending_request_id'] == ''
            panel = control('constituencyRecountPanel')
            assert panel.property('visible') is True
            for scope_id in (setup['n1_scope_id'], setup['n3_scope_id']):
                assert control('constituencyRecountSource_' + str(scope_id)).property('visible')
            assert control('constituencyRecountInstruct').property('enabled') is False
            enter('constituencyRecountEventAt', setup['event_time'])
            assert control('constituencyRecountInstruct').property('enabled') is False
            enter('constituencyRecountReason', setup['reason'])
            assert_multiline_inside_border('constituencyRecountReason')
            assert recounts.property('state')['forms'] == {
                'event_at': setup['event_time'], 'reason': setup['reason']}
            assert recounts.property('state')['dirty'] is True
            assert results.property('state')['dirty'] is False
            click('constituencyRecountInstruct')
            dialog = window.findChild(QObject, 'constituencyRecountPasswordDialog')
            assert dialog is not None
            wait(lambda: dialog.property('opened'))
            assert control('constituencyRecountPassword').property('text') == ''

            for locale in ('tc', 'sc', 'en'):
                controller.setLocale(locale)
                expected_captions = {
                    controller.texts['constituency_recount_title'],
                    controller.texts['constituency_recount_time'],
                    controller.texts['constituency_recount_reason'],
                }
                def panel_captions():
                    return {item.property('text') for item in panel.findChildren(QObject)
                            if isinstance(item.property('text'), str)}
                wait(lambda: expected_captions <= panel_captions()
                    and control('constituencyRecountTitle').property('text')
                        == controller.texts['constituency_recount_title']
                    and control('constituencyRecountInstruct').property('text')
                        == controller.texts['constituency_recount_instruct']
                    and control('constituencyRecountPasswordConfirm').property('text')
                        == controller.texts['constituency_recount_confirm'])
                assert dialog.property('opened') is True
                assert control('constituencyRecountPasswordConfirm').property('enabled') is False
                assert recounts.property('state')['forms'] == {
                    'event_at': setup['event_time'], 'reason': setup['reason']}
            enter('constituencyRecountPassword', setup['password'])
            assert control('constituencyRecountPasswordConfirm').property('enabled') is True
            click('constituencyRecountPasswordConfirm')
            wait(lambda: not any(recounts.property('state')[key]
                for key in ('busy', 'refreshing'))
                and recounts.property('state')['dirty'] is False
                and len(recounts.property('state')['instructions']) == 1
                and results.property('state')['result']['complete'] is False)
            settled = recounts.property('state')
            assert settled['error'] == ''
            assert settled['notice'] == 'constituency_recount_saved'
            assert settled['uncertain_save'] is False
            assert settled['pending_request_id'] == ''
            assert settled['forms'] == {'event_at': '', 'reason': ''}
            assert dialog.property('visible') is False
            assert control('constituencyRecountPassword').property('text') == ''
            assert setup['password'] not in json.dumps(settled, ensure_ascii=False)
            instruction = settled['instructions'][0]
            assert instruction['reason'] == setup['reason']
            assert instruction['member_count'] == 2
            assert [row['scope_id'] for row in instruction['members']] == [
                setup['n1_scope_id'], setup['n3_scope_id']]
            assert [row['progress'] for row in instruction['members']] == [
                'incomplete', 'incomplete']
            for scope_id in (setup['n1_scope_id'], setup['n3_scope_id']):
                row_name = ('constituencyRecountProgress_' + str(instruction['id'])
                            + '_' + str(scope_id))
                assert control(row_name).property('visible') is True
            result = results.property('state')['result']
            assert result['contributions'] == []
            assert [row['quantity'] for row in result['candidate_totals']] == [None, None]
            assert result['provisional'] is True
            assert editor.property('state')['selected_scope_id'] == setup['n1_scope_id']
            assert editor.property('state')['selected']['id'] == setup['source_round_id']
            assert editor.property('state')['selected']['revision'] == 4
            assert editor.property('state')['dirty'] is False
            """,
        )
        assert https_server.request_count("POST", target) == 1
        history = supervisor.get(target)
        assert history.status_code == 200, history.text
        assert history.json()["can_instruct"] is False
        assert len(history.json()["instructions"]) == 1
        instruction = history.json()["instructions"][0]
        assert instruction["reason"] == reason
        assert instruction["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
        assert instruction["entered_at"] == "2026-11-15T16:10:00Z"
        assert instruction["member_count"] == 2
        assert [row["scope_id"] for row in instruction["members"]] == list(old_rounds)
        assert len({row["new_round_id"] for row in instruction["members"]}) == 2
        for member in instruction["members"]:
            scope_id = member["scope_id"]
            prior = old_rounds[scope_id]
            prefix = prior["round_path"].rsplit("/", 1)[0]
            response = supervisor.get(f"{prefix}/{member['new_round_id']}")
            assert response.status_code == 200, response.text
            blank = response.json()["record"]
            assert len(response.json()["history"]) == 1
            assert blank["id"] != prior["selected"]["id"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft"
            assert blank["scope_basis"] == prior["selected"]["scope_basis"]
            assert blank["physical_decisions"] == []
            assert blank["f1_complete"] is False
            assert blank["approval_valid"] is False and blank["selected"] is False
            assert blank.get("approved_at") is None
            assert all(blank[key] is None for key in (
                "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                "questionable_quantity", "f2", "completed_at",
            ))
            assert all(row["quantity"] is None for key in ("candidate_votes", "invalid_papers")
                       for row in blank[key])
            preserved = supervisor.get(prior["round_path"])
            assert preserved.status_code == 200, preserved.text
            assert [row["revision_id"] for row in preserved.json()["history"]] == [
                row["revision_id"] for row in old_history[scope_id]["history"]
            ]
            for key in ("revision_id", "revision", "status", "candidate_votes", "invalid_papers",
                        "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                        "approved_at", "approved_by"):
                assert preserved.json()["record"][key] == old_history[scope_id]["record"][key]
            assert preserved.json()["record"]["approval_valid"] is True
            assert preserved.json()["record"]["selection"]["id"] == (
                prior["selected"]["selection"]["id"]
            )
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        result = after.json()
        assert result["contributions"] == []
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result["pending"]} == set(old_rounds)
        assert all(row["code"] == "recount_pending" for row in result["pending"])
        assert result["complete"] is False and result["provisional"] is True
