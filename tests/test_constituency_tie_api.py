"""Supervisor tie dispositions bind to the current constituency result basis."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import result_setup, save_result_round


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_resolves_equal_zero_totals_against_exact_result_basis(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        save_result_round(setup, [0, 0], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(path)
        assert before.status_code == 200, before.text
        basis = before.json()
        assert basis["tie_candidate_ids"]
        assert len(basis["tie_candidate_ids"]) == 2
        assert {row["quantity"] for row in basis["candidate_totals"]} == {0}
        command = {
            "request_id": str(uuid4()),
            "expected_resolution_revision": 0,
            "basis_digest": basis["basis_digest"],
            "candidate_id": basis["tie_candidate_ids"][0],
            "reason": "Supervisor reviewed the tie and recorded the authorized decision.",
            "password": READY_PASSWORD,
        }
        saved = supervisor.post(path + "/tie-resolutions", json=command)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        decision = result["tie_resolution"]
        assert decision["revision"] == 1
        assert decision["candidate_id"] == command["candidate_id"]
        assert decision["reason"] == command["reason"]
        assert decision["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert decision["accepted_at"]
        assert decision["basis_digest"] == basis["basis_digest"]
        assert decision["valid"] is True
        assert result["resolved_candidate_id"] == command["candidate_id"]
        assert len(result["resolution_history"]) == 1
        assert result["tie_candidate_ids"] == basis["tie_candidate_ids"]
        assert result["candidate_totals"] == basis["candidate_totals"]


def _tie_command(result: dict, candidate_id: int, *, request_id: str | None = None) -> dict:
    return {
        "request_id": request_id or str(uuid4()),
        "expected_resolution_revision": 0,
        "basis_digest": result["basis_digest"],
        "candidate_id": candidate_id,
        "reason": "Supervisor reviewed the tie and recorded the authorized decision.",
        "password": READY_PASSWORD,
    }


def test_changed_box_basis_invalidates_resolution_and_rejects_old_digest(
    admin: TestClient, database_url: str,
) -> None:
    from tests.box_support import event_command

    with result_setup(admin, database_url) as setup:
        save_result_round(setup, [0, 0], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(result_path).json()
        decision = supervisor.post(
            result_path + "/tie-resolutions",
            json=_tie_command(before, before["tie_candidate_ids"][0]),
        )
        assert decision.status_code == 200, decision.text
        saved = decision.json()["tie_resolution"]
        box = setup["boxes"]["local_n1"]
        corrected = setup["clients"]["polling"].post(
            setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
            json=event_command(
                box["revision"],
                "2026-11-15T22:46:00+08:00",
                reason="Correct the receipt event from the signed box log.",
            ),
        )
        assert corrected.status_code == 200, corrected.text
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        current = after.json()
        assert current["basis_digest"] != before["basis_digest"]
        assert current["tie_resolution"]["valid"] is False
        assert current["resolution_history"][0]["revision"] == saved["revision"]
        assert current["resolution_history"][0]["candidate_id"] == saved["candidate_id"]
        stale = supervisor.post(
            result_path + "/tie-resolutions",
            json={
                **_tie_command(current, saved["candidate_id"], request_id=str(uuid4())),
                "expected_resolution_revision": saved["revision"],
                "basis_digest": before["basis_digest"],
            },
        )
        assert stale.status_code == 409, stale.text
        reread = supervisor.get(result_path).json()
        assert reread["resolution_history"] == current["resolution_history"]


def test_tie_resolution_replay_is_idempotent_and_decision_revision_is_compare_and_set(
    admin: TestClient, database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        save_result_round(setup, [0, 0], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        initial = supervisor.get(path).json()
        command = _tie_command(initial, initial["tie_candidate_ids"][1])
        saved = supervisor.post(path + "/tie-resolutions", json=command)
        assert saved.status_code == 200, saved.text
        replay = supervisor.post(path + "/tie-resolutions", json=command)
        assert replay.status_code == 200, replay.text
        assert replay.json()["tie_resolution"] == saved.json()["tie_resolution"]
        assert len(replay.json()["resolution_history"]) == 1
        stale = supervisor.post(
            path + "/tie-resolutions",
            json={**command, "request_id": str(uuid4()), "expected_resolution_revision": 0},
        )
        assert stale.status_code == 409, stale.text
        reread = supervisor.get(path).json()
        assert len(reread["resolution_history"]) == 1
        assert reread["tie_resolution"]["revision"] == 1


def test_tie_resolution_rejects_nonleader_blank_reason_wrong_password_and_unauthorized_roles(
    admin: TestClient, database_url: str,
) -> None:
    from tests.box_support import box_staff

    with result_setup(admin, database_url, candidate_count=3) as setup:
        round_state = save_result_round(setup, [2, 2, 0], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        result = supervisor.get(path).json()
        assert len(result["tie_candidate_ids"]) == 2
        nonleader = round_state["options"]["candidates"][2]["id"]

        wrong_candidate = supervisor.post(
            path + "/tie-resolutions", json=_tie_command(result, nonleader)
        )
        assert wrong_candidate.status_code >= 400
        blank_reason = supervisor.post(
            path + "/tie-resolutions",
            json={**_tie_command(result, result["tie_candidate_ids"][0]), "reason": "   "},
        )
        assert blank_reason.status_code == 422
        wrong_password = supervisor.post(
            path + "/tie-resolutions",
            json={
                **_tie_command(result, result["tie_candidate_ids"][0]),
                "password": "Incorrect-Password-42!",
            },
        )
        assert wrong_password.status_code == 401
        limited_path = path + "/tie-resolutions"
        with box_staff(
            admin,
            database_url,
            setup["clock"],
            "supervisor",
            [setup["stations"]["N1"]["id"]],
        ) as (limited_supervisor, _):
            limited = limited_supervisor.post(
                limited_path,
                json=_tie_command(result, result["tie_candidate_ids"][0]),
            )
            assert limited.status_code == 403
        administrator = admin.post(
            path + "/tie-resolutions",
            json=_tie_command(result, result["tie_candidate_ids"][0]),
        )
        assert administrator.status_code == 403
        current = supervisor.get(path).json()
        assert current["tie_resolution"] is None
        assert current["resolution_history"] == []
