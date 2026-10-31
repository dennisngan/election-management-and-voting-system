"""A later local requirement preserves wide-parent provenance on the earlier round."""

from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, box_staff
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_recount_progress_api import (
    _approve_member,
    _assert_original_outcome,
    _completion_events,
    _frozen_members,
    _member_path,
    _progress,
    _read,
    _select_member,
    _submit_fresh_member,
    _wide_instruction,
)
from tests.test_constituency_recount_report_metadata_api import FROZEN_OBSERVATIONS
from tests.test_constituency_tie_api import complete_tie_setup

REQUIRED_PARENT_ID_LABEL = "Current required instruction · Constituency-wide instruction ID"
ASSOCIATED_PARENT_ID_LABEL = "This round's instruction · Constituency-wide instruction ID"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_completed_wide_round_reports_keep_the_parent_after_a_later_local_instruction(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        initial = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        target, receipt = _wide_instruction(
            setup, "2026-11-16T00:05:42.123456+08:00",
            "Complete both North scopes and preserve this instruction's original membership.",
        )
        original_receipt = deepcopy(receipt)
        parent = receipt["instruction"]
        n1, n3 = receipt["members"]
        assert [row["instruction"]["scope_id"] for row in (n1, n3)] == [
            setup["scope"]["id"], setup["n3_scope"]["id"],
        ]
        expected_parent = {
            "id": parent["id"], "request_id": parent["request_id"],
            "constituency_id": setup["constituency_id"],
            "actor_id": setup["accounts"]["supervisor"]["id"],
            "reason": parent["reason"], "event_at": "2026-11-15T16:05:42.123456Z",
            "entered_at": "2026-11-15T16:10:00Z", "member_count": 2,
            "scope_ids": [setup["scope"]["id"], setup["n3_scope"]["id"]],
        }
        _submit_fresh_member(
            setup, setup["clients"]["receiveronly"], n1, [7, 3], 10,
            "2026-11-16T00:11:12.123456+08:00", "2026-11-16T00:12:17.654321+08:00",
        )
        _approve_member(setup, supervisor, n1)
        n1_selected = _select_member(setup, supervisor, n1)
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [setup["n3_station_id"]],
        ) as (n3_counter, _):
            _submit_fresh_member(
                setup, n3_counter, n3, [0, 0], 0,
                "2026-11-16T00:24:12.123456+08:00", "2026-11-16T00:25:17.654321+08:00",
            )
            _approve_member(setup, supervisor, n3)
            n3_selected = _select_member(setup, supervisor, n3)
        completed = _progress(supervisor, target, parent["id"])
        assert completed["historical_complete"] is True
        assert completed["completed_member_count"] == 2
        assert completed["completed_at"] == n3_selected["selection"]["selected_at"]
        assert [row["completed_at"] for row in completed["members"]] == [
            n1_selected["selection"]["selected_at"], n3_selected["selection"]["selected_at"],
        ]
        assert [row["completion_selection_revision"] for row in completed["members"]] == [2, 2]
        frozen, first_events = _frozen_members(completed), _completion_events(completed)
        complete_result = _read(supervisor, result_path)
        assert complete_result["complete"] is True and complete_result["pending"] == []
        assert [row["quantity"] for row in complete_result["candidate_totals"]] == [7, 3]
        _assert_original_outcome(supervisor, setup, original_receipt)

        path = _member_path(n1)
        history_before = _read(supervisor, path)["history"]
        setup["clock"].value += timedelta(minutes=10)
        local_path = path.rsplit("/", 2)[0] + "/recounts"
        later_response = supervisor.post(local_path, json={
            "request_id": str(uuid4()), "scope_revision": setup["scope"]["revision"],
            "expected_selection_revision": 2, "source_round_id": n1_selected["id"],
            "source_round_revision": 5, "event_at": "2026-11-16T00:40:42.222222+08:00",
            "reason": "Repeat N1 locally while the completed wide instruction remains historical.",
            "password": READY_PASSWORD,
        })
        assert later_response.status_code == 201, later_response.text
        later = later_response.json()
        assert later["round"]["round_number"] == 3 and later["round"]["revision"] == 1
        assert "constituency_recount" not in later["instruction"]
        assert "constituency_recount" not in later["round"]["required_recount"]
        assert "constituency_recount" not in later["round"]["recount_instruction"]

        preserved = _progress(supervisor, target, parent["id"])
        assert preserved["historical_complete"] is True and preserved["is_latest"] is True
        assert preserved["completed_member_count"] == 2
        assert preserved["completed_at"] == completed["completed_at"]
        assert preserved["scope_sources"] == completed["scope_sources"]
        assert _frozen_members(preserved) == frozen
        assert _completion_events(preserved) == first_events
        assert [row["progress"] for row in preserved["members"]] == ["completed", "completed"]
        assert [row["current_required_round_id"] for row in preserved["members"]] == [
            later["round"]["id"], n3["round"]["id"],
        ]
        result = _read(supervisor, result_path)
        assert result["complete"] is False and result["provisional"] is True
        assert [row["quantity"] for row in result["candidate_totals"]] == [0, 0]
        assert [row["scope_id"] for row in result["contributions"]] == [setup["n3_scope"]["id"]]
        assert [(row["scope_id"], row["code"]) for row in result["pending"]] == [
            (setup["scope"]["id"], "recount_pending"),
        ]

        reports = {}
        for locale in ("en", "tc", "sc"):
            for form in ("statement", "count"):
                response = supervisor.get(
                    f"{path}/revisions/{n1_selected['revision']}/{form}",
                    params={"locale": locale},
                )
                assert response.status_code == 200, response.text
                report = response.json()
                record = report["record"]
                assert record["id"] == n1_selected["id"] and record["revision"] == 5
                assert record["status"] == "approved" and record["approval_valid"] is True
                assert record["selected"] is True and record["is_current"] is True
                assert record["recount_pending"] is True
                assert record["contributes_to_result"] is False
                assert record["required_recount"]["id"] == later["instruction"]["id"]
                assert "constituency_recount" not in record["required_recount"]
                assert record["recount_instruction"]["id"] == n1["instruction"]["id"]
                assert record["recount_instruction"]["constituency_recount"] == expected_parent
                assert {key: record[key] for key in FROZEN_OBSERVATIONS} == {
                    key: n1_selected[key] for key in FROZEN_OBSERVATIONS
                }
                assert [row["quantity"] for row in record["candidate_votes"]] == [7, 3]
                reports[(locale, form)] = report

        english = reports[("en", "statement")]["labels"]
        associated_keys = [key for key, value in english.items()
                           if value == ASSOCIATED_PARENT_ID_LABEL]
        required_keys = [key for key, value in english.items()
                         if value == REQUIRED_PARENT_ID_LABEL]
        assert len(associated_keys) == len(required_keys) == 1
        associated_key, required_key = associated_keys[0], required_keys[0]
        for (locale, form), report in reports.items():
            labels, metadata = report["labels"], report["metadata"]
            associated_label, required_label = labels[associated_key], labels[required_key]
            if locale == "en":
                assert associated_label == ASSOCIATED_PARENT_ID_LABEL
            else:
                assert associated_label != ASSOCIATED_PARENT_ID_LABEL
                assert any("\u4e00" <= character <= "\u9fff" for character in associated_label)
            row = [associated_label, str(parent["id"])]
            assert metadata.count(row) == 1
            assert " · ".join(row) in report["preview_lines"]
            assert not [row for row in metadata if row[0] == required_label]
            assert [labels["local_recount_required_instruction"],
                    str(later["instruction"]["id"])] in metadata
            assert [labels["local_recount_associated_instruction"],
                    str(n1["instruction"]["id"])] in metadata
            observation_keys = (
                ("event_at", "entered_at", "actor_id") if form == "statement"
                else ("f1_event_at", "f1_entered_at", "f1_actor_id")
            )
            for key, value in zip(observation_keys, (
                "2026-11-16 00:11:12.123456 HKT", "2026-11-16 00:20:00 HKT",
                str(setup["accounts"]["receiveronly"]["id"]),
            ), strict=True):
                assert [labels[key], value] in metadata

        history_after = _read(supervisor, path)["history"]
        assert [row["revision_id"] for row in history_after] == [
            row["revision_id"] for row in history_before
        ]
        for before, after in zip(history_before, history_after, strict=True):
            assert {key: after.get(key) for key in FROZEN_OBSERVATIONS} == {
                key: before.get(key) for key in FROZEN_OBSERVATIONS
            }
        original = _read(supervisor, initial["round_path"])["record"]
        assert {key: original[key] for key in FROZEN_OBSERVATIONS} == {
            key: initial["selected"][key] for key in FROZEN_OBSERVATIONS
        }
        assert [row["quantity"] for row in original["candidate_votes"]] == [6, 4]
        zero = _read(supervisor, _member_path(n3))["record"]
        assert {key: zero[key] for key in FROZEN_OBSERVATIONS} == {
            key: n3_selected[key] for key in FROZEN_OBSERVATIONS
        }
        assert [row["quantity"] for row in zero["candidate_votes"]] == [0, 0]
        _assert_original_outcome(supervisor, setup, original_receipt)
