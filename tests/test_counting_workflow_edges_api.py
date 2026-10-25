"""Submission, approval and selection edge cases through authenticated public APIs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import READY_PASSWORD, box_staff, event_command
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def _f1_with_outcomes(
    options: dict[str, Any], *, questionable: int = 0, actual: int = 5
) -> dict[str, Any]:
    command = complete_f1_command(
        options,
        questionable_quantity=questionable,
        actual_counted_quantity=actual,
    )
    command["candidate_votes"][0]["quantity"] = actual - questionable
    return command


def _prepare_draft(
    setup: dict[str, Any], *, questionable: int = 0, actual: int = 5,
    determination_started_at: str | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    client, path = setup["counter"], setup["rounds_path"]
    options = client.get(path).json()
    f1_command = _f1_with_outcomes(options, questionable=questionable, actual=actual)
    first = client.post(path, json=f1_command)
    assert first.status_code == 201, first.text
    f1 = first.json()
    f2_command = complete_f2_command(
        options,
        determination_started_at=determination_started_at,
    )
    if questionable:
        f2_command["accepted_votes"][0]["quantity"] = questionable
    saved = client.put(f"{path}/{f1['id']}/f2", json=f2_command)
    assert saved.status_code == 200, saved.text
    return options, path, f1, saved.json()


def _submit(client: TestClient, target: str, revision: int, scope_revision: int, **changes: Any):
    return client.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "scope_revision": scope_revision,
            **changes,
        },
    )


def _approve(
    client: TestClient, target: str, revision: int, scope_revision: int, **changes: Any
):
    return client.post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "scope_revision": scope_revision,
            "password": READY_PASSWORD,
            **changes,
        },
    )


def _select(
    client: TestClient,
    target: str,
    revision: int,
    scope_revision: int,
    expected_selection_revision: int = 0,
    **changes: Any,
):
    return client.post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "scope_revision": scope_revision,
            "expected_selection_revision": expected_selection_revision,
            "password": READY_PASSWORD,
            **changes,
        },
    )


def _run_together(
    clients: tuple[TestClient, TestClient],
    path: str,
    payloads: tuple[dict[str, Any], dict[str, Any]],
    *,
    method: str = "post",
) -> list[tuple[int, dict[str, Any]]]:
    barrier = Barrier(2)

    def send(index: int) -> tuple[int, dict[str, Any]]:
        barrier.wait(timeout=5)
        response = getattr(clients[index], method)(path, json=payloads[index])
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, index) for index in range(2)]
        return [future.result() for future in futures]


def _assert_f1_f2_edits_rejected(
    setup: dict[str, Any], options: dict[str, Any], target: str, revision: int
) -> None:
    f1_edit = complete_f1_command(
        options,
        expected_revision=revision,
        discard_f2=True,
    )
    f1_edit["candidate_votes"][0]["quantity"] = 5
    f1_edit["actual_counted_quantity"] = 5
    denied_f1 = setup["counter"].put(target, json=f1_edit)
    assert denied_f1.status_code == 409, denied_f1.text
    assert denied_f1.json()["detail"]["code"] == "count_round_read_only"
    f2_edit = complete_f2_command(
        options,
        expected_revision=revision,
        determination_started_at=None,
    )
    denied_f2 = setup["counter"].put(target + "/f2", json=f2_edit)
    assert denied_f2.status_code == 409, denied_f2.text
    assert denied_f2.json()["detail"]["code"] == "count_round_read_only"


def test_submission_rejects_incomplete_f1_and_missing_determination_start(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = complete_f1_command(options)
        f1["candidate_votes"][0]["quantity"] = None
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        incomplete = client.post(
            f"{path}/{created.json()['id']}/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "scope_revision": setup["scope"]["revision"],
            },
        )
        assert incomplete.status_code == 409, incomplete.text
        assert incomplete.json()["detail"]["code"] == "count_inputs_incomplete"


def test_submission_rejects_f2_without_required_determination_start(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, draft = _prepare_draft(setup, questionable=1, actual=1)
        assert draft["f2_complete"] is False
        assert {item["code"] for item in draft["blockers"]} >= {"determination_start_missing"}
        missing_start = _submit(
            setup["counter"],
            f"{path}/{f1['id']}",
            2,
            options["scope"]["revision"],
        )
        assert missing_start.status_code == 409, missing_start.text
        assert missing_start.json()["detail"]["code"] == "count_inputs_incomplete"


def test_submitted_and_approved_rounds_reject_ordinary_f1_and_f2_edits(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        submitted = _submit(setup["counter"], target, 2, options["scope"]["revision"])
        assert submitted.status_code == 200, submitted.text
        _assert_f1_f2_edits_rejected(setup, options, target, 3)


def test_approved_round_rejects_ordinary_f1_and_f2_edits(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        submitted = _submit(setup["counter"], target, 2, options["scope"]["revision"])
        assert submitted.status_code == 200, submitted.text
        approved = _approve(
            setup["clients"]["supervisor"],
            target,
            3,
            options["scope"]["revision"],
        )
        assert approved.status_code == 200, approved.text
        _assert_f1_f2_edits_rejected(setup, options, target, 4)


def test_stale_preconditions_and_cross_action_request_ids_are_rejected(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = client.post(path, json=_f1_with_outcomes(options))
        assert f1.status_code == 201, f1.text
        target = f"{path}/{f1.json()['id']}"
        f2_command = complete_f2_command(options)
        f2 = client.put(target + "/f2", json=f2_command)
        assert f2.status_code == 200, f2.text

        cross_action = client.post(
            target + "/submit",
            json={
                "request_id": f2_command["request_id"],
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert cross_action.status_code == 409, cross_action.text
        assert cross_action.json()["detail"]["code"] == "request_conflict"

        stale_round = _submit(client, target, 1, options["scope"]["revision"])
        assert stale_round.status_code == 409, stale_round.text
        assert stale_round.json()["detail"]["code"] == "revision_conflict"
        stale_scope = _submit(client, target, 2, options["scope"]["revision"] + 1)
        assert stale_scope.status_code == 409, stale_scope.text
        assert stale_scope.json()["detail"]["code"] == "count_scope_revision_conflict"

        submitted = _submit(client, target, 2, options["scope"]["revision"])
        assert submitted.status_code == 200, submitted.text
        stale_approval = _approve(
            setup["clients"]["supervisor"],
            target,
            2,
            options["scope"]["revision"],
        )
        assert stale_approval.status_code == 409, stale_approval.text
        assert stale_approval.json()["detail"]["code"] == "revision_conflict"


def test_role_and_station_assignment_bound_all_workflow_actions(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        submitted = _submit(
            setup["counter"], target, 2, options["scope"]["revision"]
        )
        assert submitted.status_code == 200, submitted.text

        polling_denied = setup["clients"]["polling"].post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert polling_denied.status_code == 403, polling_denied.text
        assert polling_denied.json()["detail"]["code"] == "counting_officer_required"
        wrong_role_approval = setup["clients"]["polling"].post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert wrong_role_approval.status_code == 403, wrong_role_approval.text
        assert wrong_role_approval.json()["detail"]["code"] == "supervisor_required"
        wrong_role_selection = setup["counter"].post(
            target + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert wrong_role_selection.status_code == 403, wrong_role_selection.text
        assert wrong_role_selection.json()["detail"]["code"] == "supervisor_required"

        n2_id = setup["stations"]["N2"]["id"]
        with box_staff(admin, database_url, setup["clock"], "counting_officer", [n2_id]) as (
            unassigned_counter,
            _,
        ):
            denied = unassigned_counter.post(
                target + "/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 3,
                    "scope_revision": options["scope"]["revision"],
                },
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["detail"]["code"] == "station_access_denied"

        with box_staff(admin, database_url, setup["clock"], "supervisor", [n2_id]) as (
            unassigned_supervisor,
            _,
        ):
            denied = unassigned_supervisor.post(
                target + "/approve",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 3,
                    "scope_revision": options["scope"]["revision"],
                    "password": READY_PASSWORD,
                },
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["detail"]["code"] == "station_access_denied"


def test_selection_replay_rechecks_the_supervisors_current_password(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        submitted = _submit(
            setup["counter"], target, 2, options["scope"]["revision"]
        )
        assert submitted.status_code == 200, submitted.text
        approved = _approve(
            setup["clients"]["supervisor"],
            target,
            3,
            options["scope"]["revision"],
        )
        assert approved.status_code == 200, approved.text
        command = {
            "request_id": str(uuid4()),
            "expected_revision": 4,
            "scope_revision": options["scope"]["revision"],
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        }
        selected = setup["clients"]["supervisor"].post(target + "/select", json=command)
        assert selected.status_code == 200, selected.text
        command["password"] = "Incorrect-Password-42!"
        rejected_replay = setup["clients"]["supervisor"].post(target + "/select", json=command)
        assert rejected_replay.status_code == 401, rejected_replay.text


def test_basis_correction_invalidates_selected_approval_but_keeps_exact_pointer(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        submitted = _submit(setup["counter"], target, 2, options["scope"]["revision"])
        assert submitted.status_code == 200, submitted.text
        approved = _approve(
            setup["clients"]["supervisor"],
            target,
            3,
            options["scope"]["revision"],
        )
        assert approved.status_code == 200, approved.text
        selected = _select(
            setup["clients"]["supervisor"],
            target,
            4,
            options["scope"]["revision"],
        )
        assert selected.status_code == 200, selected.text
        pointer = selected.json()["selection"]
        assert pointer["valid"] is True

        box = setup["boxes"]["local_n1"]
        corrected = setup["counter"].put(
            setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
            json=event_command(
                box["revision"],
                "2026-11-15T22:46:00+08:00",
                reason="Correct the source receipt time from the station record.",
            ),
        )
        assert corrected.status_code == 200, corrected.text

        history = setup["counter"].get(target)
        assert history.status_code == 200, history.text
        record = history.json()["record"]
        assert record["approval_valid"] is False
        assert record["source_current"] is False
        assert record["selected"] is False
        assert record["selection"]["valid"] is False
        assert record["selection"]["round_revision_id"] == pointer["round_revision_id"]
        assert record["selection"]["round_id"] == pointer["round_id"]
        assert record["selection_history"][0] == record["selection"]


def test_concurrent_same_uuid_submit_approve_and_select_have_one_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        clock = setup["clock"]
        with (
            TestClient(create_app(database_url, now=clock)) as counter_peer,
            TestClient(create_app(database_url, now=clock)) as supervisor_peer,
        ):
            counter_peer.headers.update(setup["counter"].headers)
            supervisor_peer.headers.update(setup["clients"]["supervisor"].headers)
            same_submit = {
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            }
            submitted = _run_together(
                (setup["counter"], counter_peer),
                target + "/submit",
                (same_submit, dict(same_submit)),
            )
            assert [status for status, _ in submitted] == [200, 200]
            assert submitted[0][1] == submitted[1][1]
            assert [row["revision"] for row in setup["counter"].get(target).json()["history"]] == [
                3,
                2,
                1,
            ]

            same_approval = {
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            }
            approved = _run_together(
                (setup["clients"]["supervisor"], supervisor_peer),
                target + "/approve",
                (same_approval, dict(same_approval)),
            )
            assert [status for status, _ in approved] == [200, 200]
            assert approved[0][1] == approved[1][1]
            assert approved[0][1]["revision"] == 4

            same_selection = {
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "scope_revision": options["scope"]["revision"],
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            }
            selected = _run_together(
                (setup["clients"]["supervisor"], supervisor_peer),
                target + "/select",
                (same_selection, dict(same_selection)),
            )
            assert [status for status, _ in selected] == [200, 200]
            assert selected[0][1] == selected[1][1]
            assert len(setup["clients"]["supervisor"].get(path).json()["selection_history"]) == 1


def test_concurrent_distinct_uuid_submit_approve_and_select_use_revision_cas(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        options, path, f1, _ = _prepare_draft(setup)
        target = f"{path}/{f1['id']}"
        clock = setup["clock"]
        with (
            TestClient(create_app(database_url, now=clock)) as counter_peer,
            TestClient(create_app(database_url, now=clock)) as supervisor_peer,
        ):
            counter_peer.headers.update(setup["counter"].headers)
            supervisor_peer.headers.update(setup["clients"]["supervisor"].headers)
            submit_commands = tuple(
                {
                    "request_id": str(uuid4()),
                    "expected_revision": 2,
                    "scope_revision": options["scope"]["revision"],
                }
                for _ in range(2)
            )
            submitted = _run_together(
                (setup["counter"], counter_peer), target + "/submit", submit_commands
            )
            assert sorted(status for status, _ in submitted) == [200, 409]
            conflict = next(body for status, body in submitted if status == 409)
            assert conflict["detail"]["code"] == "revision_conflict"

            approval_commands = tuple(
                {
                    "request_id": str(uuid4()),
                    "expected_revision": 3,
                    "scope_revision": options["scope"]["revision"],
                    "password": READY_PASSWORD,
                }
                for _ in range(2)
            )
            approved = _run_together(
                (setup["clients"]["supervisor"], supervisor_peer),
                target + "/approve",
                approval_commands,
            )
            assert sorted(status for status, _ in approved) == [200, 409]
            conflict = next(body for status, body in approved if status == 409)
            assert conflict["detail"]["code"] == "revision_conflict"

            selection_commands = tuple(
                {
                    "request_id": str(uuid4()),
                    "expected_revision": 4,
                    "scope_revision": options["scope"]["revision"],
                    "expected_selection_revision": 0,
                    "password": READY_PASSWORD,
                }
                for _ in range(2)
            )
            selected = _run_together(
                (setup["clients"]["supervisor"], supervisor_peer),
                target + "/select",
                selection_commands,
            )
            assert sorted(status for status, _ in selected) == [200, 409]
            conflict = next(body for status, body in selected if status == 409)
            assert conflict["detail"]["code"] == "selection_revision_conflict"
            assert len(setup["clients"]["supervisor"].get(path).json()["selection_history"]) == 1
