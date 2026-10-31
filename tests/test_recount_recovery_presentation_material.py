"""Real Material recount cards preserve the original instruction receipt."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.tally_support import complete_f1_command
from tests.test_constituency_tie_api import complete_tie_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolate_recount_presentation(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


# Literal visible wording is independent of the translation dictionaries under test.
PRESENTATION_LABELS = {
    "en": {
        "count": "Count", "scope": "Counting scope", "instruction": "Recount instruction",
        "new_round": "New count round", "round": "Count round",
        "original_revision": "Original revision", "draft": "Draft",
        "committed": "Recorded by server", "original_receipt": "Original server receipt",
        "event_caption": "Original instruction time (Hong Kong time)",
        "history_hint": (
            "This receipt preserves the original instruction and blank round; "
            "it does not show the current count or recount status."
        ),
    },
    "tc": {
        "count": "點票", "scope": "點票範圍", "instruction": "重新點票指示",
        "new_round": "新點票輪次", "round": "點票輪次",
        "original_revision": "原修訂", "draft": "草稿",
        "committed": "伺服器已記錄", "original_receipt": "原伺服器收據",
        "event_caption": "原指示時間（香港時間）",
        "history_hint": "此收據保留原指示及空白輪次的回覆，不代表目前點票或重新點票狀態。",
    },
    "sc": {
        "count": "点票", "scope": "点票范围", "instruction": "重新点票指示",
        "new_round": "新点票轮次", "round": "点票轮次",
        "original_revision": "原修订", "draft": "草稿",
        "committed": "服务器已记录", "original_receipt": "原服务器收据",
        "event_caption": "原指示时间（香港时间）",
        "history_hint": "此收据保留原指示及空白轮次的回复，不代表当前点票或重新点票状态。",
    },
}


MATERIAL_SCENARIO = """
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields
recovery = controller.property('recovery')
click('recoveryNavigation')
wait(lambda: not any(recovery.property('state')[key] for key in ('busy', 'refreshing')))
matching = [row for row in recovery.property('state')['commands']
            if row['request_id'] == setup['request_id']]
assert len(matching) == 1
command = matching[0]
assert command['workflow'] == 'count' and command['method'] == 'POST'
assert command['path'] == setup['recount_path'] and command['status'] == 'committed'
assert command['actor_id'] == setup['actor_id'] and command['station_id'] == setup['station_id']
assert_public_business_fields(command['receipt']['record'], setup['original_wrapper'])
assert command['receipt']['record']['instruction']['status'] == 'pending'
assert command['receipt']['record']['round']['revision'] == 1
assert command['receipt']['record']['round']['status'] == 'draft'
assert setup['password'] not in json.dumps(recovery.property('state'))

card_name = 'recoveryCommand_' + setup['request_id']
click(card_name)
selected_panel = control('recoverySelectedCommandPanel')
assert selected_panel.property('visible') is True
assert control('recoveryPage').property('selectedRequestId') == setup['request_id']
for locale in ('en', 'tc', 'sc'):
    labels = setup['labels'][locale]
    controller.setLocale(locale)
    wait(lambda: control(card_name).property('text').startswith(labels['count'] + ' · '))
    card_text = control(card_name).property('text')
    # Intended first presentation RED: the real committed card says Target not recorded.
    for fragment in (
        labels['instruction'] + ' #' + str(setup['instruction_id']),
        labels['scope'] + ' #' + str(setup['scope_id']),
        labels['new_round'] + ' #' + str(setup['new_round_id']),
        labels['committed'],
    ):
        assert fragment in card_text, (locale, fragment, card_text)
    assert '—' not in card_text
    summary = control('recoveryReceiptSummary')
    assert summary.property('visible') is True
    summary_text = summary.property('text')
    for fragment in (
        labels['original_receipt'],
        labels['new_round'] + ' #' + str(setup['new_round_id']),
        labels['round'] + ' #2',
        labels['original_revision'] + ' 1',
        labels['draft'],
    ):
        assert fragment in summary_text, (locale, fragment, summary_text)
    assert '—' not in summary_text
    hint = control('recoveryReceiptHistoryHint')
    assert hint.property('visible') is True and hint.property('text') == labels['history_hint']
    visible_text = [item.property('text') for item in selected_panel.findChildren(QQuickItem)
                    if item.property('visible')]
    assert labels['event_caption'] in visible_text
    assert '2026-11-16 00:05:42.123456 HKT' in visible_text
    assert control('recoveryPage').property('selectedRequestId') == setup['request_id']
    assert control('recoveryCheckOutcome').property('enabled') is False
    assert control('recoveryRetryOriginal').property('visible') is False
    retained = next(row for row in recovery.property('state')['commands']
                    if row['request_id'] == setup['request_id'])
    assert_public_business_fields(retained['receipt']['record'], setup['original_wrapper'])
    assert retained['status'] == 'committed'
"""


def test_recount_recovery_card_retains_original_receipt_after_round_completion(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "recount-presentation-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor, counter = setup["clients"]["supervisor"], setup["clients"]["receiveronly"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        actor = setup["accounts"]["supervisor"]
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        source_response = counter.get(source_path)
        assert source_response.status_code == 200, source_response.text
        source_before = source_response.json()
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        with f1_editor(https_server, qt_app, actor, station_id, scope_id) as (client, editor):
            recounts = editor.property("recounts")
            assert isinstance(recounts, QObject)
            wait_for_editor_idle(qt_app, recounts)
            assert recounts.property("state")["can_instruct"] is True
            recounts.setField("event_at", "2026-11-16 00:05:42.123456")
            recounts.setField(
                "reason", "Retain the original receipt after the new tally completes.",
            )
            recounts.instruct(READY_PASSWORD)
            wait_for_editor_idle(qt_app, recounts)
            wait_for_editor_idle(qt_app, editor)
            assert recounts.property("state")["error"] == ""
            state_response = supervisor.get(recount_path)
            assert state_response.status_code == 200, state_response.text
            state = state_response.json()
            assert len(state["instructions"]) == 1 and state["pending"] is True
            instruction = state["instructions"][0]
            request_id = instruction["request_id"]
            assert str(UUID(request_id)) == request_id
            assert instruction["scope_id"] == scope_id and instruction["actor_id"] == actor["id"]
            assert instruction["source_round_id"] == prior["id"]
            assert instruction["new_round_id"] != prior["id"]
            new_path = f"{setup['rounds_path']}/{instruction['new_round_id']}"
            blank_response = counter.get(new_path)
            assert blank_response.status_code == 200, blank_response.text
            blank = blank_response.json()["record"]
            assert blank["round_number"] == 2 and blank["revision"] == 1
            assert blank["status"] == "draft" and blank["scope_basis"] == prior["scope_basis"]
            assert all(blank[key] is None for key in ("event_at", "entered_at", "actor_id"))
            outcome_path = (
                f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}?workflow=count"
            )
            outcome_response = supervisor.get(outcome_path)
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            assert outcome["status"] == "committed" and outcome["request_id"] == request_id
            wrapper = outcome["record"]
            assert set(wrapper) == {"instruction", "round"}
            assert wrapper == {"instruction": instruction, "round": blank}
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            matching = [row for row in recovery.property("state")["commands"]
                        if row["request_id"] == request_id]
            assert len(matching) == 1 and matching[0]["status"] == "committed"
            assert_public_business_fields(matching[0]["receipt"]["record"], wrapper)
        assert https_server.request_count("POST", recount_path) == 1
        material_setup = {
            "server": https_server.url, "username": actor["username"], "password": READY_PASSWORD,
            "station_id": station_id, "scope_id": scope_id, "actor_id": actor["id"],
            "locale": "en", "request_id": request_id, "recount_path": recount_path,
            "instruction_id": instruction["id"], "new_round_id": blank["id"],
            "original_wrapper": wrapper, "labels": PRESENTATION_LABELS,
        }
        run_workspace_qml(material_setup, MATERIAL_SCENARIO)
        assert https_server.request_count("POST", recount_path) == 1

        # Advance the live public record; never replace/edit the private journal receipt.
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        options_response = counter.get(setup["rounds_path"])
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1_command = complete_f1_command(
            options, expected_revision=blank["revision"],
            event_at="2026-11-16T00:12:12.123456+08:00", actual_counted_quantity=10,
        )
        for row, quantity in zip(f1_command["candidate_votes"], [8, 2], strict=True):
            row["quantity"] = quantity
        f1_response = counter.put(new_path, json=f1_command)
        assert f1_response.status_code == 200, f1_response.text
        f1 = f1_response.json()
        assert f1["revision"] == 2 and f1["f1_complete"] is True
        f2_response = counter.put(new_path + "/f2", json=complete_f2_command(
            options, expected_revision=f1["revision"], event_at="2026-11-16T00:13:17.654321+08:00",
        ))
        assert f2_response.status_code == 200, f2_response.text
        f2 = f2_response.json()
        assert f2["revision"] == 3 and f2["count_inputs_complete"] is True
        submitted_response = counter.post(new_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": f2["revision"],
            "scope_revision": setup["scope"]["revision"],
        })
        assert submitted_response.status_code == 200, submitted_response.text
        submitted = submitted_response.json()
        assert submitted["revision"] == 4 and submitted["status"] == "submitted"
        approved_response = supervisor.post(new_path + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": submitted["revision"],
            "scope_revision": setup["scope"]["revision"], "password": READY_PASSWORD,
        })
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        assert approved["revision"] == 5 and approved["approval_valid"] is True
        selected_response = supervisor.post(new_path + "/select", json={
            "request_id": str(uuid4()), "expected_revision": approved["revision"],
            "scope_revision": setup["scope"]["revision"], "password": READY_PASSWORD,
            "expected_selection_revision": prior["selection"]["revision"],
        })
        assert selected_response.status_code == 200, selected_response.text
        selected = selected_response.json()
        assert selected["revision"] == 5 and selected["status"] == "approved"
        assert selected["selected"] is True and selected["contributes_to_result"] is True
        assert selected["selection"]["revision"] == prior["selection"]["revision"] + 1
        assert [row["quantity"] for row in selected["final_candidate_votes"]] == [8, 2]
        completed_response = supervisor.get(recount_path)
        assert completed_response.status_code == 200, completed_response.text
        completed = completed_response.json()
        assert completed["pending"] is False and len(completed["instructions"]) == 1
        assert completed["latest_instruction"]["id"] == instruction["id"]
        assert completed["latest_instruction"]["status"] == "completed"
        assert completed["latest_instruction"]["current_satisfied"] is True
        immutable_response = supervisor.get(outcome_path)
        assert immutable_response.status_code == 200, immutable_response.text
        assert immutable_response.json() == outcome
        assert wrapper["round"]["revision"] == 1 and wrapper["round"]["status"] == "draft"
        assert wrapper["instruction"]["status"] == "pending"
        source_after_response = counter.get(source_path)
        assert source_after_response.status_code == 200, source_after_response.text
        source_after = source_after_response.json()
        assert [row["revision_id"] for row in source_after["history"]] == [
            row["revision_id"] for row in source_before["history"]
        ]
        for key in ("candidate_votes", "invalid_papers", "f2", "scope_basis", "event_at",
                    "entered_at", "actor_id", "approved_at", "approved_by"):
            assert source_after["record"][key] == source_before["record"][key]

        # A new real Material process reloads that same actor/origin/station's journal.
        run_workspace_qml(material_setup, MATERIAL_SCENARIO)
        final_outcome = supervisor.get(outcome_path)
        assert final_outcome.status_code == 200, final_outcome.text
        assert final_outcome.json() == outcome
        assert https_server.request_count("POST", recount_path) == 1
