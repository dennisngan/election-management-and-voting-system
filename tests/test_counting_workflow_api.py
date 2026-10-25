"""Submission, exact-revision approval and explicit selection through public HTTP."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_count_submission_records_completion_and_preserves_observations(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        created = client.post(path, json=complete_f1_command(options))
        assert created.status_code == 201, created.text
        f1 = created.json()
        target = path + f"/{f1['id']}"
        saved = client.put(target + "/f2", json=complete_f2_command(options))
        assert saved.status_code == 200, saved.text
        draft = saved.json()
        assert draft["count_inputs_complete"] is True and draft["count_complete"] is False
        command = {
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "scope_revision": options["scope"]["revision"],
        }
        result = client.post(target + "/submit", json=command)
        assert result.status_code == 200, result.text
        submitted = result.json()
        assert submitted["status"] == "submitted" and submitted["revision"] == 3
        assert submitted["count_complete"] is True
        assert submitted["completed_at"] == "2026-11-15T16:00:00Z"
        assert submitted["submitted_at"] == submitted["completed_at"]
        assert submitted["submitted_by"] == setup["accounts"]["receiveronly"]["id"]
        assert submitted["event_at"] == f1["event_at"]
        assert submitted["f2"] == draft["f2"]
        assert submitted["scope_basis"] == draft["scope_basis"]
        assert submitted["completion_event"]["origin_revision"] == 3
        assert submitted["completion_event"]["event_at"] == submitted["completed_at"]
        assert submitted["approval_blockers"] == [
            {
                "code": "count_physical_difference_unaccepted",
                "source": "stock",
                "difference_quantity": -5,
            }
        ]
        resumed = client.get(target).json()
        assert resumed["record"] == submitted
        assert [row["revision"] for row in resumed["history"]] == [3, 2, 1]
        assert resumed["history"][1]["count_complete"] is False
        replay = client.post(target + "/submit", json=command)
        assert replay.status_code == 200 and replay.json() == submitted


def test_supervisor_approves_exact_submission_with_fresh_own_password(
    admin: TestClient,
    database_url: str,
) -> None:
    from tests.box_support import READY_PASSWORD

    with tally_setup(admin, database_url) as setup:
        client, supervisor, path = (
            setup["counter"],
            setup["clients"]["supervisor"],
            setup["rounds_path"],
        )
        options = client.get(path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = client.post(path, json=initial)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
        saved = client.put(target + "/f2", json=complete_f2_command(options))
        assert saved.status_code == 200, saved.text
        submitted = client.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        command = {
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
            "password": "Incorrect-Password-42!",
        }
        denied = supervisor.post(target + "/approve", json=command)
        assert denied.status_code == 401, denied.text
        command["password"] = READY_PASSWORD
        wrong_role = client.post(target + "/approve", json=command)
        assert wrong_role.status_code == 403, wrong_role.text
        approved = supervisor.post(target + "/approve", json=command)
        assert approved.status_code == 200, approved.text
        record = approved.json()
        assert record["status"] == "approved" and record["revision"] == 4
        assert record["approved_by"] == setup["accounts"]["supervisor"]["id"]
        assert record["reviewed_revision"] == 3
        assert record["reviewed_revision_id"] == submitted.json()["revision_id"]
        assert record["completed_at"] == submitted.json()["completed_at"]
        assert record["approval_valid"] is True and record["selected"] is False
        assert supervisor.get(path).json()["selection"] is None
        replay = supervisor.post(target + "/approve", json=command)
        assert replay.status_code == 200 and replay.json() == record
        command["password"] = "Incorrect-Password-42!"
        rejected_replay = supervisor.post(target + "/approve", json=command)
        assert rejected_replay.status_code == 401, rejected_replay.text
        history = supervisor.get(target).json()
        assert len(history["history"]) == 4
        import json

        public_text = json.dumps(history)
        assert READY_PASSWORD not in public_text and "Incorrect-Password-42!" not in public_text
