"""Questionable-paper entry at the public Qt/HTTPS/real-MySQL boundary."""

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer


def test_counting_officer_saves_partial_then_complete_f2_through_desktop(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, questionable_quantity=3, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 2
        first = counter.post(path, json=initial)
        assert first.status_code == 201, first.text
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            state = editor.property("state")
            assert state["f2_forms"]["event_at"] == ""
            editor.setF2Field("event_at", "2026-11-15 23:20:17.654321")
            editor.setF2Field("determination_started_at", "2026-11-15 23:18:12.123456")
            editor.setF2Field("notes", "Partial determination saved by desktop")
            candidate_id = options["candidates"][0]["id"]
            editor.setAcceptedQuantity(candidate_id, "2")
            assert editor.property("state")["dirty"] is True
            editor.saveF2()
            wait_for_editor_idle(qt_app, editor)
            partial = editor.property("state")
            assert partial["selected"]["revision"] == 2
            assert partial["dirty"] is False and partial["notice"] == "f2_saved"
            assert partial["selected"]["f2_complete"] is False
            assert partial["selected"]["event_at"] == first.json()["event_at"]
            assert partial["accepted_inputs"][0]["quantity"] == "2"
            assert all(row["quantity"] == "" for row in partial["rejected_inputs"])
            for reason in options["f2_invalid_reasons"]:
                editor.setRejectedQuantity(
                    reason["id"], "1" if reason["code"] == "gc-f2-k" else "0"
                )
            editor.saveF2()
            wait_for_editor_idle(qt_app, editor)
            complete = editor.property("state")
            assert complete["selected"]["revision"] == 3
            assert complete["selected"]["f2_complete"] is True
            assert complete["selected"]["count_inputs_complete"] is True
            assert complete["selected"]["count_complete"] is False
            assert complete["selected"]["final_valid_quantity"] == 4
            assert complete["selected"]["final_valid_quantity_display"] == "4"
            assert complete["selected"]["final_invalid_quantity"] == 1
            assert complete["selected"]["final_invalid_quantity_display"] == "1"
            assert complete["f2_forms"]["notes"] == "Partial determination saved by desktop"
            resumed = counter.get(path + f"/{first.json()['id']}").json()["record"]
            assert resumed["f2"]["accepted_votes"][0]["quantity"] == 2
            assert resumed["f2"]["determination_started_at"] == "2026-11-15T15:18:12.123456Z"
            assert resumed["final_accounted_quantity"] == 5


def test_desktop_submission_approval_and_selection_use_separate_password_commands(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    import json

    from tests.box_support import READY_PASSWORD
    from tests.outcomes_support import complete_f2_command

    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        saved = counter.put(target + "/f2", json=complete_f2_command(options))
        assert saved.status_code == 200, saved.text
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")
            assert submitted["selected"]["status"] == "submitted"
            assert submitted["selected"]["count_complete"] is True
            assert submitted["selected"]["selected"] is False
            editor.setField("notes", "Forbidden ordinary edit after submission")
            assert editor.property("state")["dirty"] is False
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["supervisor"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.approveCount("Incorrect-Password-42!")
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["error"] == "invalid_credentials"
            editor.approveCount(READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)
            approved = editor.property("state")
            assert approved["selected"]["status"] == "approved"
            assert approved["selected"]["approval_valid"] is True
            assert approved["selected"]["selected"] is False
            editor.selectApproved(READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)
            selected = editor.property("state")
            assert selected["selected"]["selected"] is True
            assert selected["selected"]["selection"]["revision"] == 1
            assert READY_PASSWORD not in json.dumps(selected)
            assert "Incorrect-Password-42!" not in json.dumps(selected)
            editor.reload()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["selected"]["selected"] is True
        persisted = counter.get(target).json()["record"]
        assert persisted["status"] == "approved" and persisted["selection"]["valid"] is True
        assert persisted["completed_at"] == "2026-11-15T16:00:00Z"


def test_desktop_f1_replacement_requires_explicit_f2_reset_and_retains_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    from tests.outcomes_support import complete_f2_command

    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        created = counter.post(path, json=complete_f1_command(options))
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        saved = counter.put(target + "/f2", json=complete_f2_command(options))
        assert saved.status_code == 200, saved.text
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.setField("notes", "Corrected initial observation")
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            rejected = editor.property("state")
            assert rejected["error"] == "f2_discard_required"
            assert rejected["selected"]["revision"] == 2 and rejected["dirty"] is True
            editor.saveDiscardingF2()
            wait_for_editor_idle(qt_app, editor)
            reset = editor.property("state")
            assert reset["selected"]["revision"] == 3
            assert reset["selected"]["f2"] is None
            assert reset["selected"]["notes"] == "Corrected initial observation"
            assert reset["dirty"] is False
            assert reset["accepted_inputs"][0]["quantity"] == ""
        history = counter.get(target).json()["history"]
        assert [row["revision"] for row in history] == [3, 2, 1]
        assert history[1]["f2"] == saved.json()["f2"]
