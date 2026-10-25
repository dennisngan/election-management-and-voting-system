"""F1 edits remain compatible with preserved F2 determination drafts."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_legacy_f1_receipt_replays_with_explicit_false_discard_flag(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        legacy_payload = complete_f1_command(options)
        created = client.post(path, json=legacy_payload)
        assert created.status_code == 201, created.text
        record = created.json()

        replay = client.post(path, json={**legacy_payload, "discard_f2": False})
        assert replay.status_code == 200, replay.text
        assert replay.json() == record


def test_f1_discard_flag_accepts_only_a_json_boolean(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        payload = complete_f1_command(options)
        payload["discard_f2"] = "false"
        rejected = client.post(path, json=payload)
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"]["code"] == "validation_error"
        assert client.get(path).json()["rounds"] == []


def test_f1_update_requires_explicit_f2_discard_and_preserves_prior_history(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        initial = complete_f1_command(
            options,
            questionable_quantity=3,
            actual_counted_quantity=5,
        )
        initial["candidate_votes"][0]["quantity"] = 2
        first = client.post(path, json=initial)
        assert first.status_code == 201, first.text
        f1 = first.json()

        f2 = complete_f2_command(
            options,
            determination_started_at="2026-11-15T23:18:12.123456+08:00",
        )
        started = client.put(path + f"/{f1['id']}/f2", json=f2)
        assert started.status_code == 200, started.text
        with_f2 = started.json()
        assert with_f2["revision"] == 2 and with_f2["f2"] is not None

        f1_edit = complete_f1_command(
            options,
            questionable_quantity=3,
            actual_counted_quantity=5,
        )
        f1_edit["candidate_votes"][0]["quantity"] = 2
        f1_edit.update(
            request_id=str(uuid4()),
            expected_revision=2,
            questionable_quantity=3,
        )
        rejected = client.put(path + f"/{f1['id']}", json=f1_edit)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "f2_discard_required"
        unchanged = client.get(path + f"/{f1['id']}").json()
        assert unchanged["record"] == with_f2
        assert [row["revision"] for row in unchanged["history"]] == [2, 1]
        assert unchanged["history"][0]["f2"] == with_f2["f2"]
        assert unchanged["history"][1]["candidate_votes"] == f1["candidate_votes"]

        reset_payload = {**f1_edit, "request_id": str(uuid4()), "discard_f2": True}
        reset = client.put(path + f"/{f1['id']}", json=reset_payload)
        assert reset.status_code == 200, reset.text
        fresh_f1 = reset.json()
        assert fresh_f1["revision"] == 3
        assert fresh_f1["status"] == "draft"
        assert fresh_f1["f1_complete"] is True
        assert fresh_f1.get("f2") is None
        assert fresh_f1["questionable_quantity"] == 3
        replay = client.put(path + f"/{f1['id']}", json=reset_payload)
        assert replay.status_code == 200 and replay.json() == fresh_f1

        history = client.get(path + f"/{f1['id']}")
        assert history.status_code == 200, history.text
        assert history.json()["record"] == fresh_f1
        assert [row["revision"] for row in history.json()["history"]] == [3, 2, 1]
        assert history.json()["history"][1]["f2"] == with_f2["f2"]
        assert history.json()["history"][1]["is_current"] is False
        assert history.json()["history"][0].get("f2") is None
        assert history.json()["history"][2]["candidate_votes"] == f1["candidate_votes"]
        assert history.json()["history"][2]["is_current"] is False
