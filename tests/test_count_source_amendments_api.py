"""Cross-layer source amendments use existing public MySQL API workflows."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def _approved_selected_round(setup: dict) -> tuple[dict, str, dict]:
    counter, rounds_path = setup["counter"], setup["rounds_path"]
    options = counter.get(rounds_path).json()
    f1_command = complete_f1_command(options, actual_counted_quantity=5)
    f1_command["candidate_votes"][0]["quantity"] = 5
    f1 = counter.post(rounds_path, json=f1_command)
    assert f1.status_code == 201, f1.text
    target = rounds_path + f"/{f1.json()['id']}"
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
    approved = setup["clients"]["supervisor"].post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = setup["clients"]["supervisor"].post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 4,
            "scope_revision": options["scope"]["revision"],
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selection"]["valid"] is True
    return options, target, selected.json()


def test_reasoned_p18_successor_invalidates_pinned_scope_and_selected_count_but_keeps_history(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, target, selected = _approved_selected_round(setup)
        scope_path = setup["paths"]["n1_counting_scopes"] + f"/{setup['scope']['id']}"
        original_scope = setup["counter"].get(scope_path).json()["record"]
        p18 = setup["accounting"]["N1"]
        p18_path = p18["path"]
        special = p18["special_papers"]

        revised = setup["clients"]["bothcounting"].put(
            p18_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": special["id"],
                "special_paper_revision": special["revision"],
                "notes": "Rechecked the original accounting papers.",
                "amendment_reason": "Correct the recorded P(18) note after paper review.",
            },
        )
        assert revised.status_code == 200, revised.text
        assert revised.json()["revision"] == 2 and revised.json()["status"] == "draft"

        submitted_source = setup["clients"]["bothcounting"].post(
            p18_path + "/submit",
            json={"request_id": str(uuid4()), "expected_revision": 2},
        )
        assert submitted_source.status_code == 200, submitted_source.text
        approved_source = setup["clients"]["supervisor"].post(
            p18_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "password": READY_PASSWORD,
            },
        )
        assert approved_source.status_code == 200, approved_source.text
        assert approved_source.json()["approval_valid"] is True

        source_history = setup["clients"]["bothcounting"].get(p18_path).json()
        assert [row["revision"] for row in source_history["history"]] == [2, 1]
        assert source_history["history"][1]["status"] == "approved"
        assert source_history["history"][1]["approval_valid"] is False

        scope_history = setup["counter"].get(scope_path).json()
        assert scope_history["record"]["revision"] == 1
        assert scope_history["record"]["source_current"] is False
        assert scope_history["record"]["count_ready"] is False
        assert scope_history["record"]["accounting_basis"] == original_scope["accounting_basis"]
        assert scope_history["record"]["accounting_basis"][0]["revision"] == 1
        assert scope_history["record"]["accounting_basis"][0]["approval_valid"] is True
        assert len(scope_history["history"]) == 1

        count_history = setup["counter"].get(target).json()
        current = count_history["record"]
        assert current["revision"] == 4 and current["status"] == "approved"
        assert current["source_current"] is False
        assert current["approval_valid"] is False and current["selected"] is False
        assert current["selection"]["valid"] is False
        assert (
            current["selection"]["round_revision_id"]
            == selected["selection"]["round_revision_id"]
        )
        assert count_history["history"][0]["approved_at"] == selected["approved_at"]
        assert count_history["history"][0]["is_current"] is True
        assert len(count_history["history"]) == 4


def _scope_payload(setup: dict, boxes: list[dict], accounting_codes: tuple[str, ...]) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "reference": "Ticket 20 successor scope " + uuid4().hex[:8],
        "event_at": "2026-11-15T23:10:00+08:00",
        "box_revisions": [
            {"box_id": box["id"], "revision": box["revision"]} for box in boxes
        ],
        "accounting_revisions": [
            {
                "station_id": setup["stations"][code]["id"],
                "revision": setup["accounting"][code]["record"]["revision"],
            }
            for code in accounting_codes
        ],
        "notes": "A received-box set pinned through the public API.",
    }


def test_reasoned_scope_box_set_change_cannot_double_assign_received_box(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        path = setup["paths"]["n1_counting_scopes"]
        local = setup["boxes"]["local_n1"]
        transferred = setup["boxes"]["transferred_n2"]

        first = receiver.post(
            path,
            json=_scope_payload(setup, [local], ("N1",)),
        )
        assert first.status_code == 201, first.text
        first_submit = receiver.post(
            f"{path}/{first.json()['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert first_submit.status_code == 200, first_submit.text
        assert first_submit.json()["count_ready"] is True

        second = receiver.post(
            path,
            json=_scope_payload(setup, [transferred], ("N2",)),
        )
        assert second.status_code == 201, second.text
        second_submit = receiver.post(
            f"{path}/{second.json()['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert second_submit.status_code == 200, second_submit.text
        assert second_submit.json()["count_ready"] is True

        correction = {
            **_scope_payload(setup, [local, transferred], ("N1", "N2")),
            "expected_revision": 1,
            "reference": second.json()["reference"],
            "amendment_reason": "Attempt to add the received local box to this scope.",
        }
        rejected = receiver.put(f"{path}/{second.json()['id']}", json=correction)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "box_already_in_scope"

        current = receiver.get(path).json()
        by_id = {row["id"]: row for row in current["scopes"]}
        assert by_id[first.json()["id"]]["revision"] == 1
        assert by_id[second.json()["id"]]["revision"] == 1
        assert by_id[second.json()["id"]]["box_basis"][0]["id"] == transferred["id"]
        box_membership = {row["id"]: row["scope_id"] for row in current["boxes"]}
        assert box_membership[local["id"]] == first.json()["id"]
        assert box_membership[transferred["id"]] == second.json()["id"]
        assert receiver.get(f"{path}/{second.json()['id']}").json()["history"] == [
            second_submit.json()
        ]
