"""Seven real required scopes remain accessible through the Material recount view."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_recount_expanded_api import (
    _prepare_extra_zero_scope,
    _rebase_original_mixed_scope_before_counting,
    _receive_five_extra_n1_boxes,
)
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_material_recount_includes_all_seven_source_and_preserved_progress_rows(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        extra_boxes = _receive_five_extra_n1_boxes(setup)
        _rebase_original_mixed_scope_before_counting(setup)
        mixed = save_result_round(setup, [6, 4], approve_and_select=True)
        source_rounds = {
            setup["scope"]["id"]: mixed,
            setup["n3_scope"]["id"]: setup["n3_round"],
        }
        for number, box in enumerate(extra_boxes, 1):
            extra = _prepare_extra_zero_scope(setup, box, number)
            source_rounds[extra["selected"]["scope_id"]] = extra
        assert len(source_rounds) == 7
        base = f"/api/workspace/constituencies/{setup['constituency_id']}"
        target = base + "/recounts"
        before_result = supervisor.get(base + "/results")
        assert before_result.status_code == 200, before_result.text
        assert before_result.json()["complete"] is True
        assert before_result.json()["pending"] == []
        assert [row["quantity"] for row in before_result.json()["candidate_totals"]] == [6, 4]
        assert len(before_result.json()["contributions"]) == 7
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        sources = options["scope_sources"]
        assert options["can_instruct"] is True and options["instructions"] == []
        assert len(sources) == 7
        assert {row["scope_id"] for row in sources} == set(source_rounds)
        expected_order = sorted((row["station_id"], row["scope_id"]) for row in sources)
        assert [(row["station_id"], row["scope_id"]) for row in sources] == expected_order
        preserved_sources = {}
        for scope_id, prior in source_rounds.items():
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            preserved_sources[scope_id] = response.json()
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        reason = "Review every one of the seven North scope replacements in the Material view."
        assert https_server.request_count("POST", target) == 0
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en", "scope_sources": sources,
                "basis_digest": options["basis_digest"],
                "event_time": "2026-11-16 00:05:42.123456", "reason": reason,
            },
            """
            def visible_rows(prefix):
                pending = list(window.contentItem().childItems())
                found = []
                while pending:
                    item = pending.pop()
                    if item.objectName().startswith(prefix):
                        found.append(item)
                    pending.extend(item.childItems())
                return sorted(found, key=lambda item: item.mapToScene(QPointF(0, 0)).y())

            def data_property(item, name):
                value = item.property(name)
                return value.toVariant() if hasattr(value, 'toVariant') else value

            def rows_ready(prefix, expected_names):
                rows = visible_rows(prefix)
                return ([row.objectName() for row in rows] == expected_names
                    and all(row.property('visible') and row.width() > 0 and row.height() > 0
                        for row in rows))

            results = controller.property('constituencyResults')
            click('constituencyResultsNavigation')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            recounts = results.property('recounts')
            assert isinstance(recounts, QObject)
            wait(lambda: not any(recounts.property('state')[key]
                for key in ('busy', 'refreshing')))
            before = recounts.property('state')
            assert before['can_instruct'] is True and before['instructions'] == []
            assert before['basis_digest'] == setup['basis_digest']
            assert before['scope_sources'] == setup['scope_sources']
            source_names = ['constituencyRecountSource_' + str(row['scope_id'])
                for row in setup['scope_sources']]
            wait(lambda: rows_ready('constituencyRecountSource_', source_names))
            source_cards = visible_rows('constituencyRecountSource_')
            assert len(source_cards) == 7
            for card, source in zip(source_cards, setup['scope_sources'], strict=True):
                assert card.property('visible') is True
                assert card.width() > 0 and card.height() > 0
                assert data_property(card, 'modelData') == source
            assert control('constituencyRecountInstruct').property('enabled') is False
            enter('constituencyRecountEventAt', setup['event_time'])
            enter('constituencyRecountReason', setup['reason'])
            assert_multiline_inside_border('constituencyRecountReason')
            assert recounts.property('state')['forms'] == {
                'event_at': setup['event_time'], 'reason': setup['reason']}
            assert recounts.property('state')['dirty'] is True
            assert results.property('state')['dirty'] is False
            instructed = QSignalSpy(recounts.instructed)
            assert instructed.isValid()
            click('constituencyRecountInstruct')
            dialog = window.findChild(QObject, 'constituencyRecountPasswordDialog')
            assert dialog is not None
            wait(lambda: dialog.property('opened'))
            assert control('constituencyRecountPassword').property('text') == ''
            assert control('constituencyRecountPasswordConfirm').property('enabled') is False
            enter('constituencyRecountPassword', setup['password'])
            click('constituencyRecountPasswordConfirm')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing'))
                and not recounts.property('state')['dirty']
                and len(recounts.property('state')['instructions']) == 1)
            saved = recounts.property('state')
            assert saved['error'] == '' and saved['notice'] == 'constituency_recount_saved'
            assert saved['uncertain_save'] is False and saved['pending_request_id'] == ''
            assert saved['forms'] == {'event_at': '', 'reason': ''}
            assert instructed.count() == 1
            assert dialog.property('visible') is False
            assert control('constituencyRecountPassword').property('text') == ''
            instruction = saved['instructions'][0]
            assert instruction['reason'] == setup['reason']
            assert instruction['scope_sources'] == setup['scope_sources']
            assert instruction['member_count'] == 7 and len(instruction['members']) == 7
            assert instruction['completed_member_count'] == 0
            assert instruction['historical_complete'] is False
            assert [(row['station_id'], row['scope_id']) for row in instruction['members']] == [
                (row['station_id'], row['scope_id']) for row in setup['scope_sources']]
            assert [row['progress'] for row in instruction['members']] == ['incomplete'] * 7
            assert len({row['new_round_id'] for row in instruction['members']}) == 7
            prefix = 'constituencyRecountProgress_' + str(instruction['id']) + '_'
            progress_names = [prefix + str(row['scope_id']) for row in instruction['members']]
            wait(lambda: rows_ready(prefix, progress_names))
            progress_cards = visible_rows(prefix)
            assert len(progress_cards) == 7
            for card, member in zip(progress_cards, instruction['members'], strict=True):
                assert card.property('visible') is True
                assert card.width() > 0 and card.height() > 0
                assert data_property(card, 'member') == member
            recounts.reload()
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            assert recounts.property('state')['instructions'][0] == instruction
            assert len(visible_rows(prefix)) == 7
            assert instructed.count() == 1
            result = results.property('state')['result']
            assert result['complete'] is False and result['provisional'] is True
            assert result['contributions'] == []
            assert [row['quantity'] for row in result['candidate_totals']] == [None, None]
            assert len(result['pending']) == 7
            assert setup['password'] not in json.dumps(recounts.property('state'))
            """,
        )
        assert https_server.request_count("POST", target) == 1
        response = supervisor.get(target)
        assert response.status_code == 200, response.text
        view = response.json()
        assert len(view["instructions"]) == 1 and view["can_instruct"] is False
        instruction = view["instructions"][0]
        assert instruction["reason"] == reason and instruction["scope_sources"] == sources
        assert instruction["member_count"] == 7 and len(instruction["members"]) == 7
        assert [(row["station_id"], row["scope_id"]) for row in instruction["members"]] == (
            expected_order
        )
        assert len({row["new_round_id"] for row in instruction["members"]}) == 7
        for member in instruction["members"]:
            scope_id = member["scope_id"]
            prior = source_rounds[scope_id]
            old = prior["selected"]
            rounds_path = prior["round_path"].rsplit("/", 1)[0]
            listed = supervisor.get(rounds_path)
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["rounds"]) == 2
            assert {row["id"] for row in listed.json()["rounds"]} == {
                old["id"], member["new_round_id"],
            }
            assert listed.json()["selection"]["round_id"] == old["id"]
            created = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
            assert created.status_code == 200, created.text
            blank = created.json()["record"]
            assert len(created.json()["history"]) == 1
            assert blank["revision"] == 1 and blank["round_number"] == 2
            assert blank["status"] == "draft" and blank["scope_basis"] == old["scope_basis"]
            assert blank["actual_counted_quantity"] is None and blank["f2"] is None
            assert blank["approval_valid"] is False and blank["selected"] is False
            assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
            assert all(row["quantity"] is None for row in blank["invalid_papers"])
            preserved = supervisor.get(prior["round_path"])
            assert preserved.status_code == 200, preserved.text
            before = preserved_sources[scope_id]
            assert [row["revision_id"] for row in preserved.json()["history"]] == [
                row["revision_id"] for row in before["history"]
            ]
            for key in (
                "revision_id", "revision", "status", "candidate_votes", "invalid_papers",
                "f2", "scope_basis", "event_at", "entered_at", "actor_id",
                "approved_at", "approved_by",
            ):
                assert preserved.json()["record"][key] == before["record"][key]
            assert preserved.json()["record"]["approval_valid"] is True
