"""Additional public acceptance of exact manual turnout receipts in Material."""

import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
from tests.test_turnout_desktop import turnout_editor
from tests.test_turnout_paper_reentry_desktop import _outage, _paper
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


MATERIAL_MATCHING_SCENARIO = """
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields

def visual_descendants(root):
    pending = list(root.childItems())
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())

def assert_turnout_details(root):
    expected = {
        'Reported hourly quantity': '9007199254740993',
        'Reported cumulative quantity': '9007199254740993',
        'Derived hourly quantity': '—',
        'Derived cumulative at period start': '—',
        'Derived cumulative at period end': '—',
    }
    descendants = list(visual_descendants(root))
    for caption, literal in expected.items():
        details = [item for item in descendants if item.property('caption') == caption]
        assert len(details) == 1, (caption, len(details))
        detail = details[0]
        assert detail.property('visible') is True
        # Actual Material Detail and Label values, not a call to the formatting function.
        assert detail.property('value') == literal, (caption, detail.property('value'), literal)
        labels = [item for item in visual_descendants(detail)
                  if item.property('visible') and item.property('text') == literal]
        assert labels, (caption, literal)

recovery = controller.property('recovery')
click('recoveryNavigation')
wait(lambda: not any(recovery.property('state')[key] for key in ('busy', 'refreshing')))
for case in setup['cases']:
    commands = [row for row in recovery.property('state')['commands']
                if row['request_id'] == case['request_id']]
    assert len(commands) == 1
    command = commands[0]
    assert command['status'] == 'committed' and command['workflow'] == 'turnout'
    assert command['method'] == case['method'] and command['path'] == case['path']
    assert command['actor_id'] == setup['actor_id']
    assert_public_business_fields(command['receipt']['record'], case['record'])
    for key in ('supplied_hourly', 'supplied_cumulative'):
        assert type(command['receipt']['record'][key]) is int
        assert command['receipt']['record'][key] == 9007199254740993
    click('recoveryCommand_' + case['request_id'])
    assert control('recoverySelectedCommandPanel').property('visible') is True
    assert control('recoveryPage').property('selectedRequestId') == case['request_id']
    assert control('recoveryReceiptSummary').property('visible') is True
    assert control('recoveryCheckOutcome').property('enabled') is False
    assert control('recoveryRetryOriginal').property('visible') is False
assert setup['password'] not in json.dumps(recovery.property('state'))

click('outagesNavigation')
outages = controller.property('outages')
wait(lambda: not any(outages.property('state')[key] for key in ('busy', 'refreshing')))
click('outageOption_' + str(setup['outage_id']))
wait(lambda: not outages.property('state')['busy']
     and outages.property('state')['selected'].get('id') == setup['outage_id'])
for case in setup['cases']:
    paper_control = 'outagePaperOption_' + str(case['paper_id'])
    click(paper_control)
    wait(lambda: outages.property('state')['selected_paper_id'] == case['paper_id'])
    enter('outageExistingRequestId', case['request_id'])
    click('outageExistingReceiptCheck')
    wait(lambda: not any(outages.property('state')[key] for key in ('busy', 'refreshing')))
    assert outages.property('state')['error'] == ''
    checked = outages.property('state')['existing_receipt']['checked']
    assert checked['status'] == 'committed' and checked['workflow'] == 'turnout'
    assert checked['request_id'] == case['request_id']
    assert checked['receipt_digest'] == case['receipt_digest']
    assert_public_business_fields(checked['record'], case['record'])
    for key in ('supplied_hourly', 'supplied_cumulative'):
        assert type(checked['record'][key]) is int
        assert checked['record'][key] == 9007199254740993
    for key in ('derived_hourly', 'derived_cumulative_start', 'derived_cumulative_end'):
        assert checked['record'][key] is None
    frame()
    summary = control('outageExistingReceiptSummary')
    assert summary.property('visible') is True
    # Expected precision RED at 8eb0f6e: real QML conversion rounds this to ...992.
    assert_turnout_details(summary)
    facts = [item.property('value') for item in visual_descendants(summary)
             if item.property('caption') is not None]
    assert any(isinstance(value, str)
               and 'Hourly quantity 9007199254740993' in value
               and 'Cumulative quantity 9007199254740993' in value for value in facts), facts
    enter('outageExistingReceiptReason', 'Link the exact original manual turnout receipt.')
    click('outageExistingReceiptLink')
    wait(lambda: not any(outages.property('state')[key] for key in ('busy', 'refreshing')))
    assert outages.property('state')['error'] == ''
    linked = next(row for row in outages.property('state')['selected']['paper_records']
                  if row['id'] == case['paper_id'])
    assert linked['status'] == 'entered'
    assert linked['reentry']['request_id'] == case['request_id']
    assert_public_business_fields(linked['reentry']['record'], case['record'])
    frame()
    # The persisted paper card must display the same exact receipt after matching closes.
    assert_turnout_details(control(paper_control).parentItem())
    assert control('outageExistingReceiptSummary').property('visible') is False
assert setup['password'] not in json.dumps(outages.property('state'))
"""


def test_material_existing_turnout_receipts_keep_large_manual_quantities_exact(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "turnout-precision-journal"))
    large = 9007199254740993
    assert 2**53 < large < 9223372036854775807
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id, path = scope["stations"][0]["id"], scope["path"]
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        with turnout_editor(https_server, qt_app, account, station_id) as (client, editor):
            assert editor.property("state")["selected_period"] == 1
            editor.setField("supplied_hourly", str(large))
            editor.setField("supplied_cumulative", str(large))
            editor.setField("event_time", "2026-11-15 09:30")
            editor.setField("source_context", "Exact normal external/manual turnout worksheet.")
            assert editor.property("state")["forms"]["mode"] == "normal"
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["error"] == ""
            saved_response = officer.get(path + "/1")
            assert saved_response.status_code == 200, saved_response.text
            saved = saved_response.json()
            assert saved["status"] == "draft" and saved["revision"] == 1
            assert saved["provenance"] == "external_manual"
            assert_public_business_fields(editor.property("state")["selected"], saved)

            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["error"] == ""
            submitted_response = officer.get(path + "/1")
            assert submitted_response.status_code == 200, submitted_response.text
            submitted = submitted_response.json()
            assert submitted["status"] == "submitted" and submitted["revision"] == 1
            assert submitted["id"] == saved["id"]
            assert submitted["event_at"] == saved["event_at"]
            assert submitted["entered_at"] == saved["entered_at"]
            assert_public_business_fields(editor.property("state")["selected"], submitted)
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            cases = []
            for action, method, command_path, canonical in (
                ("save", "PUT", path + "/1", saved),
                ("submit", "POST", path + "/1/submit", submitted),
            ):
                matches = [row for row in recovery.property("state")["commands"]
                           if row["path"] == command_path and row["method"] == method]
                assert len(matches) == 1
                command = matches[0]
                assert command["status"] == "committed"
                assert command["actor_id"] == account["id"]
                assert command["station_id"] == station_id
                assert command["server_url"] == https_server.url
                request_id = command["request_id"]
                assert str(UUID(request_id)) == request_id
                assert "paper_record_id" not in command["payload"]
                assert_public_business_fields(command["receipt"]["record"], canonical)
                for key in ("supplied_hourly", "supplied_cumulative"):
                    assert type(canonical[key]) is int and canonical[key] == large
                # Save/Submit freeze no approval-derived values; do not invent them.
                for key in ("derived_hourly", "derived_cumulative_start", "derived_cumulative_end"):
                    assert canonical[key] is None
                outcome_path = (
                    f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"
                )
                outcome_response = officer.get(outcome_path, params={"workflow": "turnout"})
                assert outcome_response.status_code == 200, outcome_response.text
                outcome = outcome_response.json()
                assert outcome == {
                    "request_id": request_id, "workflow": "turnout",
                    "status": "committed", "record": canonical,
                }
                cases.append({
                    "action": action, "method": method, "path": command_path,
                    "request_id": request_id, "record": deepcopy(canonical),
                    "outcome_path": outcome_path, "outcome": outcome,
                })
            assert READY_PASSWORD not in json.dumps(recovery.property("state"))
        assert https_server.request_count("PUT", path + "/1") == 1
        assert https_server.request_count("POST", path + "/1/submit") == 1
        before_history_response = officer.get(path + "/1/history")
        assert before_history_response.status_code == 200, before_history_response.text
        before_history = before_history_response.json()
        assert before_history["items"] == [submitted]

        # Later paper registration is public API setup; the journal already exists naturally.
        clock.value += timedelta(minutes=30)
        https_server.clock.value = clock.value
        outage = _outage(
            officer, station_id, reference="Turnout precision " + uuid4().hex[:8],
            ended_at="2026-11-15T10:00:00+08:00",
        )
        outage_path = f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
        for case in cases:
            paper = _paper(
                officer, station_id, outage["id"],
                reference="TURNOUT-EXACT-" + case["action"] + "-" + uuid4().hex[:8],
                action=case["action"], period_index=1,
                event_at="2026-11-15T09:30:00+08:00",
            )
            assert paper["status"] == "pending"
            paper_path = outage_path + f"/paper-records/{paper['id']}"
            preview_response = officer.get(
                paper_path + "/receipt", params={"request_id": case["request_id"]},
            )
            assert preview_response.status_code == 200, preview_response.text
            preview = preview_response.json()
            assert preview["status"] == "committed" and preview["record"] == case["record"]
            case.update(paper_id=paper["id"], receipt_digest=preview["receipt_digest"])
        clock.value += timedelta(minutes=15)
        https_server.clock.value = clock.value
        run_workspace_qml({
            "server": https_server.url, "username": account["username"],
            "password": READY_PASSWORD, "station_id": station_id,
            "actor_id": account["id"], "locale": "en", "outage_id": outage["id"],
            "cases": cases,
        }, MATERIAL_MATCHING_SCENARIO)

        # Matching changes only the paper association, never creates another turnout effect.
        assert https_server.request_count("PUT", path + "/1") == 1
        assert https_server.request_count("POST", path + "/1/submit") == 1
        current_response = officer.get(path + "/1")
        history_response = officer.get(path + "/1/history")
        assert current_response.status_code == history_response.status_code == 200
        assert current_response.json() == submitted
        assert history_response.json() == before_history
        outage_response = officer.get(outage_path)
        assert outage_response.status_code == 200, outage_response.text
        papers = {row["id"]: row for row in outage_response.json()["record"]["paper_records"]}
        for case in cases:
            linked = papers[case["paper_id"]]
            assert linked["status"] == "entered"
            assert linked["reentry"]["request_id"] == case["request_id"]
            assert linked["reentry"]["record"] == case["record"]
            assert linked["reentry"]["link"]["receipt_digest"] == case["receipt_digest"]
            assert https_server.request_count(
                "POST", outage_path + f"/paper-records/{case['paper_id']}/link-receipt",
            ) == 1
            outcome_response = officer.get(case["outcome_path"], params={"workflow": "turnout"})
            assert outcome_response.status_code == 200, outcome_response.text
            assert outcome_response.json() == case["outcome"]
