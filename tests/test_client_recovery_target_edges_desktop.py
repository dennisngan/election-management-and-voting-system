"""Recovery blocks blind same-target commands and settles definite conflicts."""

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.desktop_support import TLS_DIRECTORY, wait_for, wait_for_editor_idle
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_client_recovery_contract_desktop import (
    private_active_pointer as private_active_pointer,
)
from tests.test_client_recovery_contract_desktop import (
    recovery_fault_server as recovery_fault_server,
)
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_turnout_desktop import clear_private_active_pointer as clear_private_active_pointer
from tests.test_turnout_desktop import database_url as database_url
from tests.test_turnout_desktop import (
    fill_turnout,
    turnout_editor,
)
from tests.test_turnout_desktop import turnout_boundary_server as turnout_boundary_server
from tests.turnout_support import READY_PASSWORD as TURNOUT_READY_PASSWORD
from tests.turnout_support import TurnoutClock, turnout_draft, turnout_scope, turnout_staff


def _fresh_turnout_recovery_client(
    server,
    account: dict,
    station_id: int,
    qt_app: QCoreApplication,
) -> tuple[DesktopController, object]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    client.signIn(server.url, account["username"], TURNOUT_READY_PASSWORD)
    wait_for(qt_app, lambda: client.property("state")["phase"] == "workspace")
    workspace = client.property("workspace")
    wait_for_editor_idle(qt_app, workspace)
    workspace.selectStation(station_id)
    wait_for_editor_idle(qt_app, workspace)
    recovery = client.property("recovery")
    recovery.open()
    wait_for_editor_idle(qt_app, recovery)
    return client, recovery


def test_turnout_unresolved_save_blocks_submit_and_submit_blocks_amend_for_period(
    admin: TestClient,
    database_url: str,
    turnout_boundary_server,
    qt_app: QCoreApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "turnout-target-journal"))
    setup = turnout_scope(admin)
    station_id, path = setup["stations"][0]["id"], setup["path"]
    clock = TurnoutClock()
    turnout_boundary_server.clock.value = clock.value

    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_editor(turnout_boundary_server, qt_app, account, station_id) as (
            client,
            editor,
        ),
    ):
        fill_turnout(editor, hourly="10", source="Paper worksheet for period one.")
        turnout_boundary_server.truncate_next_mutation = True
        editor.save()
        wait_for_editor_idle(qt_app, editor)
        assert api.get(path + "/1").json()["status"] == "draft"
        assert editor.reload(True)
        wait_for_editor_idle(qt_app, editor)
        recovery = client.property("recovery")
        recovery.open()
        wait_for_editor_idle(qt_app, recovery)
        save_id = client.property("recovery").property("state")["commands"][0]["request_id"]
        assert editor.property("state")["selected"]["status"] == "draft"

        editor.submit()
        wait_for_editor_idle(qt_app, editor)
        assert turnout_boundary_server.request_count("POST", path + "/1/submit") == 0
        assert editor.property("state")["error"] == "recovery_pending_command"
        commands = client.property("recovery").property("state")["commands"]
        assert any(
            row["request_id"] == save_id and row["status"] == "uncertain" for row in commands
        )

        period_two = api.put(
            path + "/2",
            json=turnout_draft(
                supplied_hourly=5,
                supplied_cumulative=15,
                event_at="2026-11-15T10:30:00+08:00",
                source_context="Paper worksheet for period two.",
            ),
        )
        assert period_two.status_code == 200, period_two.text
        assert editor.selectPeriod(2)
        wait_for_editor_idle(qt_app, editor)
        turnout_boundary_server.truncate_next_mutation = True
        editor.submit()
        wait_for_editor_idle(qt_app, editor)
        assert api.get(path + "/2").json()["status"] == "submitted"
        assert editor.reload(True)
        wait_for_editor_idle(qt_app, editor)
        editor.setField("amendment_reason", "Reviewed correction after the paper submission.")
        editor.amend()
        wait_for_editor_idle(qt_app, editor)
        assert turnout_boundary_server.request_count("POST", path + "/2/amend") == 0
        assert editor.property("state")["error"] == "recovery_pending_command"


def test_not_found_retry_conflict_settles_as_rejected_and_allows_turnout_correction(
    admin: TestClient,
    database_url: str,
    recovery_fault_server,
    qt_app: QCoreApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "turnout-rejected-journal"))
    setup = turnout_scope(admin)
    station_id, path = setup["stations"][0]["id"], setup["path"]
    clock = TurnoutClock()
    recovery_fault_server.clock.value = clock.value

    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (api, account),
        turnout_staff(admin, database_url, clock, [station_id]) as (peer, _),
        turnout_editor(recovery_fault_server, qt_app, account, station_id) as (
            first_client,
            editor,
        ),
    ):
        recovery_fault_server.fail_before_path = path + "/1"
        fill_turnout(editor, hourly="10", source="Original uncertain paper report.")
        editor.save()
        wait_for_editor_idle(qt_app, editor)
        assert recovery_fault_server.request_count("PUT", path + "/1") == 1
        commands = first_client.property("recovery")
        commands.open()
        wait_for_editor_idle(qt_app, commands)
        original = commands.property("state")["commands"][0]
        request_id, original_payload = original["request_id"], dict(original["payload"])
        assert original["status"] == "uncertain"

        peer_saved = peer.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=3,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="Peer-confirmed paper report.",
            ),
        )
        assert peer_saved.status_code == 200, peer_saved.text
        recovery_fault_server.fail_before_path = ""

        recovered_client, recovery = _fresh_turnout_recovery_client(
            recovery_fault_server,
            account,
            station_id,
            qt_app,
        )
        try:
            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["error"] == "request_not_found"
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            rejected = next(
                row for row in recovery.property("state")["commands"]
                if row["request_id"] == request_id
            )
            assert rejected["status"] == "rejected"
            assert rejected["error"] == "revision_conflict"
            assert rejected["payload"] == original_payload
            assert recovery_fault_server.request_count("PUT", path + "/1") == 2

            turnout = recovered_client.property("turnout")
            turnout.open()
            wait_for_editor_idle(qt_app, turnout)
            assert turnout.property("state")["selected"]["revision"] == 1
            turnout.setField("supplied_hourly", "4")
            turnout.setField("source_context", "Corrected paper report after peer comparison.")
            turnout.save()
            wait_for_editor_idle(qt_app, turnout)
            assert turnout.property("state")["error"] == ""
            assert turnout.property("state")["selected"]["revision"] == 2
            assert recovery_fault_server.request_count("PUT", path + "/1") == 3

            recovery.reload()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            original = next(row for row in commands if row["request_id"] == request_id)
            corrected = next(row for row in commands if row["request_id"] != request_id)
            assert original["status"] == "rejected"
            assert corrected["status"] == "committed"
        finally:
            recovered_client.shutdown()
            recovered_client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_typed_count_form_waits_for_outcome_before_resending_original_identity(
    admin: TestClient,
    database_url: str,
    recovery_fault_server,
    qt_app: QCoreApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "count-form-journal"))
    with tally_setup(admin, database_url) as setup:
        server = recovery_fault_server
        server.clock.value = setup["clock"].value
        counter, rounds_path = setup["counter"], setup["rounds_path"]
        options = counter.get(rounds_path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = counter.post(rounds_path, json=f1)
        assert created.status_code == 201, created.text
        target = rounds_path + f"/{created.json()['id']}"
        station_id = setup["stations"]["N1"]["id"]
        server.fail_before_path = target
        with f1_editor(
            server,
            qt_app,
            setup["accounts"]["receiveronly"],
            station_id,
            setup["scope"]["id"],
        ) as (client, editor):
            editor.setField("notes", "The signed paper count is unchanged.")
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["uncertain_save"] is True
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            original = recovery.property("state")["commands"][0]
            request_id, original_payload = original["request_id"], dict(original["payload"])
            assert original["status"] == "uncertain"
            assert server.request_count("PUT", target) == 1

            editor.save()
            wait_for_editor_idle(qt_app, editor)
            assert server.request_count("PUT", target) == 1
            assert recovery.property("state")["commands"][0]["request_id"] == request_id

            recovery.checkOutcome(request_id)
            wait_for_editor_idle(qt_app, recovery)
            assert recovery.property("state")["commands"][0]["error"] == "request_not_found"
            assert server.request_count("PUT", target) == 1

            server.fail_before_path = ""
            recovery.retry(request_id, "")
            wait_for_editor_idle(qt_app, recovery)
            committed = recovery.property("state")["commands"][0]
            assert committed["status"] == "committed"
            assert committed["request_id"] == request_id
            assert committed["payload"] == original_payload
            assert server.request_count("PUT", target) == 2
            history = counter.get(target)
            assert history.status_code == 200, history.text
            assert [row["revision"] for row in history.json()["history"]] == [2, 1]
