"""Public F2 and submit receipts retain the original F1 observer across assigned officers."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD, box_staff
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_second_officer_f2_and_submit_settle_exact_receipts_without_replacing_f1_actor(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "second-officer-commands"))
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        first_officer = setup["counter"]
        first_actor_id = setup["accounts"]["receiveronly"]["id"]
        path = setup["rounds_path"]
        options_response = first_officer.get(path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1_command = complete_f1_command(options, actual_counted_quantity=5)
        f1_command["candidate_votes"][0]["quantity"] = 5
        created = first_officer.post(path, json=f1_command)
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["revision"] == 1 and first["status"] == "draft"
        assert first["actor_id"] == first_actor_id
        assert first["f1_complete"] is True and first["questionable_quantity"] == 0
        target = path + f"/{first['id']}"
        f2_path, submit_path = target + "/f2", target + "/submit"
        frozen_fields = (
            "id", "scope_id", "scope_revision", "scope_basis", "candidate_votes",
            "invalid_papers", "questionable_quantity", "actual_counted_quantity",
            "event_at", "entered_at", "actor_id", "notes", "amendment_reason",
        )
        frozen_f1 = {field: first[field] for field in frozen_fields}

        # This helper creates, assigns and makes ready a distinct staff account
        # through public APIs, using the existing test READY_PASSWORD constant.
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [station_id]
        ) as (second_officer, second_account):
            second_actor_id = second_account["id"]
            assert second_actor_id != first_actor_id
            with f1_editor(
                https_server, qt_app, second_account, station_id, scope_id
            ) as (client, editor):
                assert editor.property("state")["selected"]["revision_id"] == first["revision_id"]
                editor.setF2Field("event_at", "2026-11-15 23:20:17.654321")
                editor.setF2Field("determination_started_at", "")
                editor.setF2Field("notes", "Second assigned officer explicitly records zero F2.")
                for candidate in options["candidates"]:
                    editor.setAcceptedQuantity(candidate["id"], "0")
                for reason in options["f2_invalid_reasons"]:
                    editor.setRejectedQuantity(reason["id"], "0")
                editor.saveF2()
                wait_for_editor_idle(qt_app, editor)

                # Establish the real committed effect before checking settlement.
                after_f2_response = second_officer.get(target)
                assert after_f2_response.status_code == 200, after_f2_response.text
                after_f2 = after_f2_response.json()
                saved_f2 = after_f2["record"]
                assert saved_f2["revision"] == 2 and saved_f2["status"] == "draft"
                assert saved_f2["revision_id"] != first["revision_id"]
                assert saved_f2["revision_actor_id"] == second_actor_id
                assert {field: saved_f2[field] for field in frozen_fields} == frozen_f1
                assert saved_f2["f2"]["actor_id"] == second_actor_id
                assert saved_f2["f2"]["event_at"] == "2026-11-15T15:20:17.654321Z"
                assert all(row["quantity"] == 0 for row in saved_f2["f2"]["accepted_votes"])
                assert all(row["quantity"] == 0 for row in saved_f2["f2"]["rejected_papers"])
                assert saved_f2["f2_complete"] is True
                assert saved_f2["count_inputs_complete"] is True
                assert [row["revision"] for row in after_f2["history"]] == [2, 1]
                assert https_server.request_count("PUT", f2_path) == 1

                recovery = client.property("recovery")
                assert recovery is not None
                recovery.open()
                wait_for_editor_idle(qt_app, recovery)
                f2_commands = [row for row in recovery.property("state")["commands"]
                               if row["path"] == f2_path]
                assert len(f2_commands) == 1
                f2_ack = f2_commands[0]
                f2_uuid = f2_ack["request_id"]
                assert str(UUID(f2_uuid)) == f2_uuid
                assert f2_ack["payload"]["request_id"] == f2_uuid
                assert f2_ack["actor_id"] == second_actor_id
                assert f2_ack["station_id"] == station_id and f2_ack["workflow"] == "count"
                assert f2_ack["method"] == "PUT"
                assert f2_ack["payload"]["expected_revision"] == 1
                assert READY_PASSWORD not in json.dumps(f2_ack)
                f2_outcome_path = (
                    f"/api/workspace/stations/{station_id}/request-outcomes/{f2_uuid}"
                )
                f2_outcome_response = second_officer.get(f2_outcome_path + "?workflow=count")
                assert f2_outcome_response.status_code == 200, f2_outcome_response.text
                f2_outcome = f2_outcome_response.json()
                assert f2_outcome["request_id"] == f2_uuid
                assert f2_outcome["status"] == "committed" and f2_outcome["workflow"] == "count"
                assert f2_outcome["record"] == saved_f2
                recovery.checkOutcome(f2_uuid)
                wait_for_editor_idle(qt_app, recovery)
                f2_checked = next(row for row in recovery.property("state")["commands"]
                                  if row["request_id"] == f2_uuid)

                # Expected first RED at 2e976397: both are uncertain despite r2.
                assert f2_ack["status"] == f2_checked["status"] == "committed", {
                    "ack_status": f2_ack["status"], "ack_error": f2_ack["error"],
                    "checked_status": f2_checked["status"], "checked_error": f2_checked["error"],
                }
                assert_public_business_fields(f2_ack["receipt"]["record"], f2_outcome["record"])
                assert_public_business_fields(f2_checked["receipt"]["record"], f2_outcome["record"])
                saved_state = editor.property("state")
                assert saved_state["uncertain_save"] is False and saved_state["dirty"] is False
                assert saved_state["error"] == "" and saved_state["notice"] == "f2_saved"
                assert_public_business_fields(saved_state["selected"], saved_f2)
                assert https_server.request_count("GET", f2_outcome_path) == 1

                editor.submitCount()
                wait_for_editor_idle(qt_app, editor)
                submitted_response = second_officer.get(target)
                assert submitted_response.status_code == 200, submitted_response.text
                submitted_history = submitted_response.json()
                submitted = submitted_history["record"]
                assert submitted["revision"] == 3 and submitted["status"] == "submitted"
                assert submitted["revision_id"] not in {
                    first["revision_id"], saved_f2["revision_id"]
                }
                assert submitted["revision_actor_id"] == second_actor_id
                assert submitted["submitted_by"] == second_actor_id
                assert submitted["completion_event"]["actor_id"] == second_actor_id
                assert submitted["count_complete"] is True
                assert {field: submitted[field] for field in frozen_fields} == frozen_f1
                assert submitted["f2"] == saved_f2["f2"]
                assert https_server.request_count("POST", submit_path) == 1

                recovery.reload()
                wait_for_editor_idle(qt_app, recovery)
                submit_commands = [row for row in recovery.property("state")["commands"]
                                   if row["path"] == submit_path]
                assert len(submit_commands) == 1
                submit_ack = submit_commands[0]
                submit_uuid = submit_ack["request_id"]
                assert str(UUID(submit_uuid)) == submit_uuid and submit_uuid != f2_uuid
                assert submit_ack["payload"]["request_id"] == submit_uuid
                assert submit_ack["actor_id"] == second_actor_id
                assert submit_ack["method"] == "POST"
                assert submit_ack["payload"]["expected_revision"] == 2
                submit_outcome_path = (
                    f"/api/workspace/stations/{station_id}/request-outcomes/{submit_uuid}"
                )
                submit_outcome_response = second_officer.get(
                    submit_outcome_path + "?workflow=count"
                )
                assert submit_outcome_response.status_code == 200, submit_outcome_response.text
                submit_outcome = submit_outcome_response.json()
                assert submit_outcome["request_id"] == submit_uuid
                assert submit_outcome["status"] == "committed"
                assert submit_outcome["record"] == submitted
                recovery.checkOutcome(submit_uuid)
                wait_for_editor_idle(qt_app, recovery)
                submit_checked = next(row for row in recovery.property("state")["commands"]
                                      if row["request_id"] == submit_uuid)
                assert submit_ack["status"] == submit_checked["status"] == "committed", {
                    "ack_status": submit_ack["status"], "ack_error": submit_ack["error"],
                    "checked_status": submit_checked["status"],
                    "checked_error": submit_checked["error"],
                }
                assert_public_business_fields(
                    submit_ack["receipt"]["record"], submit_outcome["record"]
                )
                assert_public_business_fields(
                    submit_checked["receipt"]["record"], submit_outcome["record"]
                )
                submitted_state = editor.property("state")
                assert submitted_state["uncertain_save"] is False
                assert submitted_state["dirty"] is False and submitted_state["error"] == ""
                assert submitted_state["notice"] == "count_submitted"
                assert_public_business_fields(submitted_state["selected"], submitted)
                assert recovery.property("state")["error"] == ""
                assert READY_PASSWORD not in json.dumps(recovery.property("state"))
                assert https_server.request_count("GET", submit_outcome_path) == 1

                # The older exact UUID still returns its immutable r2 receipt,
                # even though the live round now has the submitted r3 head.
                old_outcome_response = second_officer.get(f2_outcome_path + "?workflow=count")
                assert old_outcome_response.status_code == 200, old_outcome_response.text
                assert old_outcome_response.json() == f2_outcome
                final_response = second_officer.get(target)
                assert final_response.status_code == 200, final_response.text
                final = final_response.json()
                assert final["record"] == submitted
                assert [row["revision"] for row in final["history"]] == [3, 2, 1]
                assert [row["revision_id"] for row in final["history"]] == [
                    submitted["revision_id"], saved_f2["revision_id"], first["revision_id"]
                ]
                for row in final["history"]:
                    assert {field: row[field] for field in frozen_fields} == frozen_f1
                assert final["history"][1]["f2"] == saved_f2["f2"]
                assert final["history"][2]["f2"] is None
                assert https_server.request_count("PUT", f2_path) == 1
                assert https_server.request_count("POST", submit_path) == 1
