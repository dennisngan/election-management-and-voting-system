"""Real wide-recount recovery cards distinguish the original receipt from live progress."""

import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_recount_progress_api import (
    _approve_member,
    _member_path,
    _progress,
    _read,
    _select_member,
    _submit_fresh_member,
)
from tests.test_constituency_recount_restart_desktop import (
    _assert_credential_free,
    _results_client,
)
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


# Independent visible wording for this public Material contract, including the new
# Chinese equivalents; these expectations do not import production translations.
PRESENTATION_LABELS = {
    "en": {
        "workflow": "Constituency-wide recount", "constituency": "Constituency",
        "instruction": "Constituency recount instruction", "member_count": "Original member count",
        "new_round": "New count round", "round": "Count round",
        "original_revision": "Original revision",
        "draft": "Draft", "committed": "Recorded by server",
        "original_receipt": "Original server receipt",
        "event_caption": "Original instruction time (Hong Kong time)",
        "history_hint": (
            "This receipt preserves the original constituency instruction and blank member rounds; "
            "current recount progress is shown separately."
        ),
    },
    "tc": {
        "workflow": "整個選區重新點票", "constituency": "選區",
        "instruction": "整個選區重新點票指示", "member_count": "原有所需範圍數目",
        "new_round": "新點票輪次", "round": "點票輪次", "original_revision": "原修訂",
        "draft": "草稿", "committed": "伺服器已記錄", "original_receipt": "原伺服器收據",
        "event_caption": "原指示時間（香港時間）",
        "history_hint": "此收據保留原有選區指示及各範圍的空白輪次；目前重新點票進度另行顯示。",
    },
    "sc": {
        "workflow": "整个选区重新点票", "constituency": "选区",
        "instruction": "整个选区重新点票指示", "member_count": "原有所需范围数目",
        "new_round": "新点票轮次", "round": "点票轮次", "original_revision": "原修订",
        "draft": "草稿", "committed": "服务器已记录", "original_receipt": "原服务器收据",
        "event_caption": "原指示时间（香港时间）",
        "history_hint": "此收据保留原有选区指示及各范围的空白轮次；当前重新点票进度另行显示。",
    },
}


MATERIAL_SCENARIO = """
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
recovery = controller.property('recovery')
click('recoveryNavigation')
wait(lambda: not any(recovery.property('state')[key] for key in ('busy', 'refreshing')))
commands = recovery.property('state')['commands']
assert len(commands) == 1
command = commands[0]
assert command['request_id'] == setup['request_id']
assert command['workflow'] == 'constituency_recount' and command['method'] == 'POST'
assert command['path'] == setup['recount_path'] and command['status'] == 'committed'
assert command['server_url'] == setup['server']
assert command['actor_id'] == setup['actor_id'] and command['station_id'] == setup['station_id']
assert_public_business_fields(command['payload'], setup['original_payload'])
assert_public_business_fields(command['receipt']['record'], setup['original_wrapper'])
assert command['receipt']['record']['instruction']['completed_member_count'] == 0
assert command['receipt']['record']['instruction']['historical_complete'] is False
assert [row['round']['revision'] for row in command['receipt']['record']['members']] == [1, 1]
assert [row['round']['status'] for row in command['receipt']['record']['members']] == [
    'draft', 'draft',
]
assert setup['password'] not in json.dumps(recovery.property('state'))

card_name = 'recoveryCommand_' + setup['request_id']
click(card_name)
selected_panel = control('recoverySelectedCommandPanel')
assert selected_panel.property('visible') is True
assert control('recoveryPage').property('selectedRequestId') == setup['request_id']
for locale in ('en', 'tc', 'sc'):
    labels = setup['labels'][locale]
    controller.setLocale(locale)
    wait(lambda: controller.property('state')['locale'] == locale)
    frame()
    card_text = control(card_name).property('text')
    # Intended first RED: the real wide card has no explicit workflow presentation.
    assert card_text.startswith(labels['workflow'] + ' · '), (locale, card_text)
    for fragment in (
        labels['constituency'] + ' #' + str(setup['constituency_id']),
        labels['instruction'] + ' #' + str(setup['instruction_id']),
        labels['committed'],
    ):
        assert fragment in card_text, (locale, fragment, card_text)
    assert '—' not in card_text
    summary = control('recoveryReceiptSummary')
    assert summary.property('visible') is True
    summary_text = summary.property('text')
    assert labels['original_receipt'] in summary_text
    assert labels['member_count'] + ' 2' in summary_text, (locale, summary_text)
    for member in setup['original_wrapper']['members']:
        original_blank = member['round']
        fragment = (labels['new_round'] + ' #' + str(original_blank['id'])
            + ' · ' + labels['round'] + ' #2'
            + ' · ' + labels['original_revision'] + ' 1'
            + ' · ' + labels['draft'])
        assert fragment in summary_text, (locale, fragment, summary_text)
    assert '—' not in summary_text
    hint = control('recoveryReceiptHistoryHint')
    assert hint.property('visible') is True
    assert hint.property('text') == labels['history_hint']
    visible_text = [item.property('text') for item in selected_panel.findChildren(QQuickItem)
                    if item.property('visible')]
    assert labels['workflow'] in visible_text
    assert labels['event_caption'] in visible_text
    assert '2026-11-16 00:05:42.123456 HKT' in visible_text
    assert control('recoveryPage').property('selectedRequestId') == setup['request_id']
    assert control('recoveryCheckOutcome').property('enabled') is False
    assert control('recoveryRetryOriginal').property('visible') is False
    retained = recovery.property('state')['commands']
    assert len(retained) == 1 and retained[0]['status'] == 'committed'
    assert_public_business_fields(retained[0]['payload'], setup['original_payload'])
    assert_public_business_fields(retained[0]['receipt']['record'], setup['original_wrapper'])
"""


def test_material_wide_receipt_stays_original_after_one_member_is_approved_and_selected(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-recount-recovery-material-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        actor = setup["accounts"]["supervisor"]
        station_id, constituency_id = setup["stations"]["N1"]["id"], setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        reason = "Keep the original wide receipt while the actual required tallies progress."
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value

        # The product creates its own journal through the public Qt/HTTPS command.
        with _results_client(https_server, qt_app, actor, station_id) as (client, results, child):
            initial = deepcopy(child.property("state"))
            assert initial["can_instruct"] is True and len(initial["scope_sources"]) == 2
            child.setField("event_at", "2026-11-16 00:05:42.123456")
            child.setField("reason", reason)
            instructed = QSignalSpy(child.instructed)
            assert instructed.isValid()
            child.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, child)
            wait_for_editor_idle(qt_app, results)
            assert child.property("state")["uncertain_save"] is False
            assert child.property("state")["error"] == "" and instructed.count() == 1
            view = _read(supervisor, target)
            assert len(view["instructions"]) == 1
            parent = view["instructions"][0]
            request_id = parent["request_id"]
            assert str(UUID(request_id)) == request_id
            outcome_path = (
                f"/api/workspace/constituencies/{constituency_id}/request-outcomes/{request_id}"
                "?workflow=constituency_recount"
            )
            outcome = _read(supervisor, outcome_path)
            assert outcome["request_id"] == request_id and outcome["status"] == "committed"
            assert outcome["workflow"] == "constituency_recount"
            original_wrapper = deepcopy(outcome["record"])
            assert original_wrapper["instruction"] == parent
            assert parent["member_count"] == 2 and parent["completed_member_count"] == 0
            assert [row["round"]["revision"] for row in original_wrapper["members"]] == [1, 1]
            assert [row["round"]["status"] for row in original_wrapper["members"]] == [
                "draft", "draft",
            ]
            original_payload = {
                "request_id": request_id, "basis_digest": initial["basis_digest"],
                "scope_sources": initial["scope_sources"],
                "event_at": "2026-11-16T00:05:42.123456+08:00", "reason": reason,
            }
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            assert len(commands) == 1 and commands[0]["status"] == "committed"
            assert commands[0]["workflow"] == "constituency_recount"
            assert_public_business_fields(commands[0]["payload"], original_payload)
            assert_public_business_fields(commands[0]["receipt"]["record"], original_wrapper)

        journal_files = list(journal_directory.glob("*.json"))
        assert len(journal_files) == 1
        original_journal_bytes = journal_files[0].read_bytes()
        durable = json.loads(original_journal_bytes)
        assert durable["payload"] == original_payload
        assert durable["receipt"]["record"] == original_wrapper
        _assert_credential_free(durable)
        assert https_server.request_count("POST", target) == 1

        # Advance a real member, leaving the original receipt and the other blank alone.
        n1, n3 = original_wrapper["members"]
        _submit_fresh_member(
            setup, setup["clients"]["receiveronly"], n1, [7, 3], 10,
            "2026-11-16T00:11:12.123456+08:00", "2026-11-16T00:12:17.654321+08:00",
        )
        _approve_member(setup, supervisor, n1)
        selected = _select_member(setup, supervisor, n1)
        https_server.clock.value = setup["clock"].value
        assert selected["revision"] == 5 and selected["status"] == "approved"
        assert selected["selected"] is True and selected["approval_valid"] is True
        assert [row["quantity"] for row in selected["candidate_votes"]] == [7, 3]
        progress = _progress(supervisor, target, parent["id"])
        assert progress["completed_member_count"] == 1 and progress["historical_complete"] is False
        assert [row["progress"] for row in progress["members"]] == ["completed", "incomplete"]
        assert _read(supervisor, outcome_path) == outcome
        assert journal_files[0].read_bytes() == original_journal_bytes

        # This fresh actual Material process reads the same durable actor/origin/namespace.
        run_workspace_qml({
            "server": https_server.url, "username": actor["username"], "password": READY_PASSWORD,
            "station_id": station_id, "constituency_id": constituency_id, "actor_id": actor["id"],
            "locale": "en", "request_id": request_id, "recount_path": target,
            "instruction_id": parent["id"], "original_wrapper": original_wrapper,
            "original_payload": original_payload, "labels": PRESENTATION_LABELS,
        }, MATERIAL_SCENARIO)
        assert https_server.request_count("POST", target) == 1
        assert journal_files[0].read_bytes() == original_journal_bytes
        assert _read(supervisor, outcome_path) == outcome
        assert _progress(supervisor, target, parent["id"]) == progress
        assert _read(supervisor, _member_path(n1))["record"] == selected
        blank = _read(supervisor, _member_path(n3))["record"]
        assert blank["revision"] == 1 and blank["status"] == "draft"
        assert [row["quantity"] for row in blank["candidate_votes"]] == [None, None]
