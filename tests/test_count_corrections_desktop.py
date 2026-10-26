"""Ticket 20 corrections at the public Qt/HTTPS/real-MySQL seam."""

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer


def _seed_submitted_or_selected_round(
    setup: dict,
    *,
    initial_valid: int,
    questionable: int,
    accepted: int,
    rejected: int,
    select: bool,
) -> dict:
    counter = setup["counter"]
    options = counter.get(setup["rounds_path"]).json()
    initial = complete_f1_command(
        options,
        questionable_quantity=questionable,
        actual_counted_quantity=initial_valid + questionable,
        notes="Original observations from the physical tally sheet.",
    )
    initial["candidate_votes"][0]["quantity"] = initial_valid
    created = counter.post(setup["rounds_path"], json=initial)
    assert created.status_code == 201, created.text
    target = setup["rounds_path"] + f"/{created.json()['id']}"
    f2 = complete_f2_command(options)
    if questionable:
        f2["event_at"] = "2026-11-15T23:20:17.654321+08:00"
        f2["determination_started_at"] = "2026-11-15T23:18:12.123456+08:00"
        f2["accepted_votes"][0]["quantity"] = accepted
        reason = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        next(row for row in f2["rejected_papers"] if row["reason_id"] == reason["id"])[
            "quantity"
        ] = rejected
    saved = counter.put(target + "/f2", json=f2)
    assert saved.status_code == 200, saved.text
    submitted = counter.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": saved.json()["revision"],
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    result = {"options": options, "target": target, "submitted": submitted.json()}
    if not select:
        return result
    supervisor = setup["clients"]["supervisor"]
    approved = supervisor.post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": submitted.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = supervisor.post(
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
    return {**result, "approved": approved.json(), "selected": selected.json()}


def test_desktop_corrects_approved_f1_with_explicit_f2_discard_and_renews_selection(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        round_state = _seed_submitted_or_selected_round(
            setup,
            initial_valid=5,
            questionable=0,
            accepted=0,
            rejected=0,
            select=True,
        )
        target = round_state["target"]
        old_round_id = round_state["selected"]["id"]
        old_selection_id = round_state["selected"]["selection"]["round_revision_id"]
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            state = editor.property("state")
            assert state["selected"]["status"] == "approved"
            assert state["selected"]["selected"] is True
            editor.startCorrection("f1", False)
            assert editor.property("state")["correction_stage"] == "f1"
            assert editor.property("state")["refresh_basis"] is False
            editor.setField("event_at", "2026-11-15 23:16:12.123456")
            editor.setField("amendment_reason", "Corrected from the signed initial tally sheet.")
            editor.saveDiscardingF2()
            wait_for_editor_idle(qt_app, editor)
            corrected = editor.property("state")
            assert corrected["selected"]["id"] == old_round_id
            assert corrected["selected"]["round_number"] == 1
            assert corrected["selected"]["revision"] == 5
            assert corrected["selected"]["status"] == "draft"
            assert corrected["selected"]["f2"] is None
            assert corrected["correction_stage"] == ""
            assert corrected["selected"]["approval_valid"] is False
            assert corrected["selected"]["selection"]["round_revision_id"] == old_selection_id
            assert corrected["selected"]["selection"]["valid"] is False
            assert corrected["selected"]["amendment_reason"] == (
                "Corrected from the signed initial tally sheet."
            )
            assert https_server.request_count("POST", target + "/amend-f1") == 1

            editor.setF2Field("event_at", "2026-11-15 23:20:17.654321")
            for candidate in round_state["options"]["candidates"]:
                editor.setAcceptedQuantity(candidate["id"], "0")
            for reason in round_state["options"]["f2_invalid_reasons"]:
                editor.setRejectedQuantity(reason["id"], "0")
            editor.saveF2()
            wait_for_editor_idle(qt_app, editor)
            saved_f2 = editor.property("state")
            assert saved_f2["selected"]["revision"] == 6
            assert saved_f2["selected"]["f2_complete"] is True
            assert https_server.request_count("POST", target + "/amend-f2") == 0

            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")["selected"]
            assert submitted["status"] == "submitted" and submitted["count_complete"] is True
            supervisor = setup["clients"]["supervisor"]
            approved = supervisor.post(
                target + "/approve",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": submitted["revision"],
                    "scope_revision": round_state["options"]["scope"]["revision"],
                    "password": READY_PASSWORD,
                },
            )
            assert approved.status_code == 200, approved.text
            selected = supervisor.post(
                target + "/select",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": approved.json()["revision"],
                    "scope_revision": round_state["options"]["scope"]["revision"],
                    "expected_selection_revision": 1,
                    "password": READY_PASSWORD,
                },
            )
            assert selected.status_code == 200, selected.text
            editor.reload()
            wait_for_editor_idle(qt_app, editor)
            current = editor.property("state")["selected"]
            assert current["id"] == old_round_id and current["round_number"] == 1
            assert current["status"] == "approved" and current["approval_valid"] is True
            assert current["selected"] is True
            assert current["selection"]["revision"] == 2
            assert current["selection"]["round_revision_id"] == selected.json()["selection"][
                "round_revision_id"
            ]

        history = setup["counter"].get(target).json()["history"]
        assert [row["revision"] for row in history] == list(range(8, 0, -1))
        assert history[4]["status"] == "approved"
        assert history[4]["f2"] is not None
        old_pointer = next(
            pointer for pointer in history[4]["selection_history"]
            if pointer["revision"] == 1
        )
        assert old_pointer["round_revision_id"] == old_selection_id
        assert old_pointer["valid"] is False
        assert history[0]["selection"]["round_revision_id"] != old_selection_id


def test_desktop_f2_correction_preserves_original_f1_and_reapproves_same_round(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        round_state = _seed_submitted_or_selected_round(
            setup,
            initial_valid=2,
            questionable=3,
            accepted=2,
            rejected=1,
            select=True,
        )
        target = round_state["target"]
        old_round_id = round_state["selected"]["id"]
        old_f1 = round_state["selected"]["f1_metadata"]
        original_f2 = round_state["selected"]["f2"]
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.startCorrection("f2", False)
            assert editor.property("state")["correction_stage"] == "f2"
            editor.setF2Field("notes", "Corrected F2 note from the determination sheet.")
            editor.setF2Field("amendment_reason", "Corrected the recorded determination note.")
            editor.saveF2()
            wait_for_editor_idle(qt_app, editor)
            corrected = editor.property("state")
            assert corrected["correction_stage"] == ""
            assert corrected["selected"]["id"] == old_round_id
            assert corrected["selected"]["revision"] == 5
            assert corrected["selected"]["status"] == "draft"
            assert corrected["selected"]["approval_valid"] is False
            assert corrected["selected"]["f1_metadata"] == old_f1
            assert corrected["selected"]["f2"]["notes"] == (
                "Corrected F2 note from the determination sheet."
            )
            assert https_server.request_count("POST", target + "/amend-f2") == 1
            assert corrected["selected"]["selection"]["valid"] is False

            editor.submitCount()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")["selected"]
            supervisor = setup["clients"]["supervisor"]
            approved = supervisor.post(
                target + "/approve",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": submitted["revision"],
                    "scope_revision": round_state["options"]["scope"]["revision"],
                    "password": READY_PASSWORD,
                },
            )
            assert approved.status_code == 200, approved.text
            selected = supervisor.post(
                target + "/select",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": approved.json()["revision"],
                    "scope_revision": round_state["options"]["scope"]["revision"],
                    "expected_selection_revision": 1,
                    "password": READY_PASSWORD,
                },
            )
            assert selected.status_code == 200, selected.text
            editor.reload()
            wait_for_editor_idle(qt_app, editor)
            current = editor.property("state")["selected"]
            assert current["id"] == old_round_id and current["round_number"] == 1
            assert current["status"] == "approved" and current["approval_valid"] is True
            assert current["selected"] is True
            assert current["f1_metadata"] == old_f1
            assert current["f2"]["determination_event"] == original_f2["determination_event"]

        history = setup["counter"].get(target).json()["history"]
        assert [row["revision"] for row in history] == [7, 6, 5, 4, 3, 2, 1]
        assert history[3]["status"] == "approved"
        assert history[3]["f2"] == original_f2
        old_pointer = next(
            pointer for pointer in history[3]["selection_history"]
            if pointer["revision"] == 1
        )
        assert old_pointer["valid"] is False
        assert history[0]["selection"]["revision"] == 2


def test_supervisor_accepts_difference_and_refreshes_same_round_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        _seed_submitted_or_selected_round(
            setup,
            initial_valid=4,
            questionable=0,
            accepted=0,
            rejected=0,
            select=False,
        )
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["supervisor"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            before = editor.property("state")["selected"]
            revision = before["revision"]
            stock = next(row for row in before["physical_comparisons"] if row["source"] == "stock")
            assert before["status"] == "submitted"
            assert stock["difference_quantity"] == -1 and stock["status"] == "pending"
            reason = "Observed stock difference checked against the sealed-box record."
            editor.acceptPhysicalDifference("stock", reason, READY_PASSWORD)
            wait_for_editor_idle(qt_app, editor)
            accepted = editor.property("state")["selected"]
            assert accepted["revision"] == revision
            stock = next(
                row for row in accepted["physical_comparisons"] if row["source"] == "stock"
            )
            assert stock["difference_quantity"] == -1 and stock["status"] == "accepted"
            assert reason in json.dumps(accepted, ensure_ascii=False)
            assert READY_PASSWORD not in json.dumps(editor.property("state"))
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            refreshed = editor.property("state")["selected"]
            stock = next(
                row for row in refreshed["physical_comparisons"] if row["source"] == "stock"
            )
            assert refreshed["revision"] == revision
            assert stock["difference_quantity"] == -1 and stock["status"] == "accepted"
            path = (
                f"/api/workspace/stations/{setup['stations']['N1']['id']}"
                f"/counting-scopes/{setup['scope']['id']}/rounds/{before['id']}"
                "/physical-differences/stock/accept"
            )
            assert https_server.request_count("POST", path) == 1
