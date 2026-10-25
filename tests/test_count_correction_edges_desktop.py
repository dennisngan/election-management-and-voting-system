"""Public Qt/HTTPS/MySQL edge cases for count correction and decision refresh."""

from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import (
    database_url as database_url,
)
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import (
    private_active_pointer as private_active_pointer,
)


def _approved_selected_count(setup: dict) -> tuple[dict, dict, str]:
    counter, path = setup["counter"], setup["rounds_path"]
    options = counter.get(path).json()
    initial = complete_f1_command(options, actual_counted_quantity=5)
    initial["candidate_votes"][0]["quantity"] = 5
    created = counter.post(path, json=initial)
    assert created.status_code == 201, created.text
    target = path + f"/{created.json()['id']}"
    f2 = counter.put(target + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    submitted = counter.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": f2.json()["revision"],
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    approved = setup["clients"]["supervisor"].post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": submitted.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = setup["clients"]["supervisor"].post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": approved.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.text
    return (
        {"options": options, "approved": approved.json(), "selected": selected.json()},
        options,
        target,
    )


def _revise_ready_scope(setup: dict) -> dict:
    scope = setup["scope"]
    path = f"{setup['paths']['n1_counting_scopes']}/{scope['id']}"
    peer = setup["clients"]["bothcounting"]
    revised = peer.put(
        path,
        json={
            "request_id": str(uuid4()),
            "expected_revision": scope["revision"],
            "reference": scope["reference"],
            "event_at": scope["event_at"],
            "box_revisions": [
                {"box_id": row["id"], "revision": row["revision"]} for row in scope["box_basis"]
            ],
            "accounting_revisions": [
                {"station_id": row["station_id"], "revision": row["revision"]}
                for row in scope["accounting_basis"]
            ],
            "notes": "Peer rechecked the current received-box basis.",
            "amendment_reason": "Confirm the current source records before F1 correction.",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == scope["revision"] + 1
    assert revised.json()["status"] == "draft"
    submitted = peer.post(
        path + "/submit",
        json={"request_id": str(uuid4()), "expected_revision": revised.json()["revision"]},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    setup["scope"] = submitted.json()
    return submitted.json()


def test_stale_selected_count_requires_refresh_basis_and_f1_correction_is_cancelable(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        seeded, old_options, target = _approved_selected_count(setup)
        old_approval = seeded["approved"]
        old_selection = seeded["selected"]["selection"]
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            before = editor.property("state")
            assert before["selected"]["status"] == "approved"
            assert before["selected"]["approval_valid"] is True
            assert before["selected"]["selection"]["valid"] is True

            successor = _revise_ready_scope(setup)
            assert successor["revision"] == 2 and successor["count_ready"] is True
            assert editor.reload() is True
            wait_for_editor_idle(qt_app, editor)
            stale = editor.property("state")
            assert stale["latest_scope"]["revision"] == 2
            assert stale["selected"]["scope_revision"] == 1
            assert stale["selected"]["source_current"] is False
            assert stale["selected"]["approval_valid"] is False
            assert stale["selected"]["selected"] is False
            assert stale["selected"]["selection"]["valid"] is False

            # A foreground reload acknowledges the ready scope successor. The
            # matching automatic refresh must not mark that same basis newer.
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            acknowledged = editor.property("state")
            assert acknowledged["latest_scope"]["revision"] == successor["revision"]
            assert acknowledged["newer_revision"] is False

            editor.startCorrection("f1", False)
            rejected = editor.property("state")
            assert rejected["error"] == "count_round_basis_stale"
            assert rejected["correction_stage"] == ""
            assert rejected["dirty"] is False

            original_forms = dict(rejected["forms"])
            editor.startCorrection("f1", True)
            refreshed = editor.property("state")
            assert refreshed["error"] == ""
            assert refreshed["correction_stage"] == "f1"
            assert refreshed["refresh_basis"] is True
            assert refreshed["scope"]["revision"] == 2
            assert refreshed["edit_scope_revision"] == 2
            assert {
                (row["candidate_id"], row["revision"]) for row in refreshed["candidate_inputs"]
            } == {(row["id"], row["revision"]) for row in refreshed["candidates"]}

            editor.setField("amendment_reason", "  ")
            requests_before_blank = https_server.request_count("POST", target + "/amend-f1")
            editor.saveDiscardingF2()
            blank = editor.property("state")
            assert blank["error"] == "count_amendment_reason_required"
            assert blank["dirty"] is True and blank["correction_stage"] == "f1"
            assert https_server.request_count("POST", target + "/amend-f1") == requests_before_blank

            editor.cancelCorrection()
            cancelled = editor.property("state")
            assert cancelled["correction_stage"] == ""
            assert cancelled["refresh_basis"] is False
            assert cancelled["dirty"] is False
            assert cancelled["forms"] == original_forms
            assert https_server.request_count("POST", target + "/amend-f1") == requests_before_blank

            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["newer_revision"] is False
            editor.startCorrection("f1", True)
            repeated = editor.property("state")
            assert repeated["correction_stage"] == "f1"
            assert repeated["scope"]["revision"] == successor["revision"]
            editor.cancelCorrection()

            next_successor = _revise_ready_scope(setup)
            assert next_successor["revision"] == successor["revision"] + 1
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            peer_changed = editor.property("state")
            assert peer_changed["latest_scope"]["revision"] == next_successor["revision"]
            assert peer_changed["newer_revision"] is True
            editor.startCorrection("f1", True)
            blocked = editor.property("state")
            assert blocked["error"] == "revision_conflict"
            assert blocked["correction_stage"] == ""
            assert blocked["dirty"] is False

            assert editor.reload() is True
            wait_for_editor_idle(qt_app, editor)
            reloaded = editor.property("state")
            assert reloaded["latest_scope"]["revision"] == next_successor["revision"]
            assert reloaded["newer_revision"] is False
            assert reloaded["selected"]["scope_revision"] == 1
            assert reloaded["selected"]["selection"]["valid"] is False
            editor.startCorrection("f1", True)
            after_reload = editor.property("state")
            assert after_reload["correction_stage"] == "f1"
            assert after_reload["scope"]["revision"] == next_successor["revision"]
            editor.cancelCorrection()

            editor.startCorrection("f1", True)
            editor.setField(
                "amendment_reason",
                "Correct the entry against the newly approved scope revision.",
            )
            editor.saveDiscardingF2()
            wait_for_editor_idle(qt_app, editor)
            corrected = editor.property("state")
            assert corrected["error"] == ""
            assert corrected["selected"]["id"] == old_selection["round_id"]
            assert corrected["selected"]["round_number"] == 1
            assert corrected["selected"]["revision"] == 5
            assert corrected["selected"]["status"] == "draft"
            assert corrected["selected"]["scope_revision"] == 2
            assert corrected["selected"]["source_current"] is True
            assert corrected["selected"]["f2"] is None
            assert corrected["selected"]["approval_valid"] is False
            assert corrected["selected"]["selected"] is False
            assert (
                corrected["selected"]["selection"]["round_revision_id"]
                == (old_selection["round_revision_id"])
            )
            assert corrected["selected"]["selection"]["valid"] is False
            assert https_server.request_count("POST", target + "/amend-f1") == 1

        history = setup["counter"].get(target)
        assert history.status_code == 200, history.text
        assert [row["revision"] for row in history.json()["history"]] == [5, 4, 3, 2, 1]
        assert history.json()["history"][1]["status"] == "approved"
        assert history.json()["history"][1]["approved_at"] == old_approval["approved_at"]
        assert history.json()["history"][1]["selection_history"][0]["revision"] == 1
        rounds = setup["counter"].get(setup["rounds_path"]).json()["rounds"]
        assert len(rounds) == 1 and rounds[0]["id"] == old_selection["round_id"]
        assert old_options["scope"]["revision"] == 1


def test_supervisor_decision_refresh_updates_same_round_and_preserves_dirty_corrections(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=0)
        created = counter.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        f2 = counter.put(target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["revision"] == 3 and submitted.json()["status"] == "submitted"

        with (
            f1_editor(
                https_server,
                qt_app,
                setup["accounts"]["receiveronly"],
                setup["stations"]["N1"]["id"],
                setup["scope"]["id"],
            ) as (_, dirty_editor),
            f1_editor(
                https_server,
                qt_app,
                setup["accounts"]["bothcounting"],
                setup["stations"]["N1"]["id"],
                setup["scope"]["id"],
            ) as (_, observer_editor),
        ):
            for editor, note in (
                (dirty_editor, "Unsaved correction from editor one."),
                (observer_editor, "Unsaved correction from editor two."),
            ):
                editor.startCorrection("f1", False)
                assert editor.property("state")["correction_stage"] == "f1"
                editor.setField("notes", note)
                editor.setField("amendment_reason", "Local reason not yet submitted.")
                assert editor.property("state")["dirty"] is True

            before = counter.get(target).json()["record"]
            assert before["revision"] == 3 and before["physical_decisions"] == []
            reason = "Supervisor accepted the observed stock difference after paper review."
            accepted = setup["clients"]["supervisor"].post(
                target + "/physical-differences/stock/accept",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 3,
                    "scope_revision": options["scope"]["revision"],
                    "expected_decision_revision": 0,
                    "password": READY_PASSWORD,
                    "reason": reason,
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["revision"] == before["revision"] == 3
            assert accepted.json()["status"] == "submitted"
            assert len(accepted.json()["physical_decisions"]) == 1
            expected_decision = {
                **accepted.json()["physical_decisions"][0],
                "expected_quantity_display": "5",
                "actual_quantity_display": "0",
                "difference_quantity_display": "-5",
            }

            for editor, note in (
                (dirty_editor, "Unsaved correction from editor one."),
                (observer_editor, "Unsaved correction from editor two."),
            ):
                editor.refresh()
                wait_for_editor_idle(qt_app, editor)
                state = editor.property("state")
                assert state["selected"]["revision"] == 3
                assert state["selected"]["physical_decisions"] == [expected_decision]
                assert state["decisions_changed"] is True
                assert state["dirty"] is True and state["correction_stage"] == "f1"
                assert state["forms"]["notes"] == note
                assert state["forms"]["amendment_reason"] == "Local reason not yet submitted."

            reread = counter.get(target).json()
            assert reread["record"]["revision"] == 3
            assert [row["revision"] for row in reread["history"]] == [3, 2, 1]
            stock = next(
                row for row in accepted.json()["physical_comparisons"] if row["source"] == "stock"
            )
            assert stock["status"] == "accepted" and stock["difference_quantity"] == -5
