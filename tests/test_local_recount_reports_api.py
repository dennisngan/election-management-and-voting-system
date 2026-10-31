"""Existing count previews retain both recount requirement and frozen observation context."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup

RECOUNT_DETAIL_FIELDS = (
    "request_id", "scope_revision", "scope_revision_id", "source_round_id",
    "source_round_revision", "source_round_revision_id", "new_round_id", "new_round_number",
    "actor_id", "reason", "event_at", "entered_at", "status", "completed_at",
    "completion_selection_revision", "current_satisfied",
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_all_count_previews_keep_recount_requirement_separate_from_frozen_observations(
    admin: TestClient,
    database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        counter = setup["clients"]["receiveronly"]
        supervisor = setup["clients"]["supervisor"]
        source_path = f"{setup['rounds_path']}/{prior['id']}"
        history_before_response = counter.get(source_path)
        assert history_before_response.status_code == 200, history_before_response.text
        history_before = history_before_response.json()["history"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        actor_id = setup["accounts"]["supervisor"]["id"]
        setup["clock"].value += timedelta(minutes=10)
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        request_id = str(uuid4())
        reason = "A new physical tally is required while the approved source stays in history."
        instructed_response = supervisor.post(
            recount_path,
            json={
                "request_id": request_id,
                "scope_revision": setup["scope"]["revision"],
                "expected_selection_revision": prior["selection"]["revision"],
                "source_round_id": prior["id"],
                "source_round_revision": prior["revision"],
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": reason,
                "password": READY_PASSWORD,
            },
        )
        assert instructed_response.status_code == 201, instructed_response.text
        instruction = instructed_response.json()["instruction"]
        blank = instructed_response.json()["round"]
        assert instruction["request_id"] == request_id
        assert instruction["scope_id"] == scope_id
        assert instruction["actor_id"] == actor_id
        assert instruction["source_round_id"] == prior["id"]
        assert instruction["source_round_revision_id"] == prior["revision_id"]
        assert instruction["new_round_id"] == blank["id"]
        assert instruction["status"] == "pending" and instruction["current_satisfied"] is False
        assert instruction["event_at"] == "2026-11-15T16:05:42.123456Z"
        assert instruction["entered_at"] == "2026-11-15T16:10:00Z"

        frozen_fields = (
            "candidate_votes", "invalid_papers", "questionable_quantity",
            "actual_counted_quantity", "scope_basis", "f2", "event_at", "entered_at",
            "actor_id", "notes", "approved_at", "approved_by",
        )
        reports = {}
        # Establish all ten real routes and their record DTOs before any new-label assertion.
        for kind, round_id, revision in (
            ("source", prior["id"], prior["revision"]),
            ("blank", blank["id"], 1),
        ):
            for form in ("statement", "f2", "f3", "f4", "count"):
                response = supervisor.get(
                    f"{setup['rounds_path']}/{round_id}/revisions/{revision}/{form}",
                    params={"locale": "en"},
                )
                assert response.status_code == 200, response.text
                report = response.json()
                assert report["round_id"] == round_id and report["revision"] == revision
                assert report["locale"] == "en"
                record = report["record"]
                assert record["scope_id"] == scope_id
                assert record["required_recount"]["id"] == instruction["id"]
                for field in RECOUNT_DETAIL_FIELDS:
                    assert record["required_recount"][field] == instruction[field]
                assert record["recount_pending"] is True
                assert record["contributes_to_result"] is False
                assert record["scope_basis"] == prior["scope_basis"]
                if kind == "source":
                    assert record["recount_instruction"] is None
                    assert {key: record[key] for key in frozen_fields} == {
                        key: prior[key] for key in frozen_fields
                    }
                    assert [row["quantity"] for row in record["candidate_votes"]] == [6, 4]
                else:
                    assert record["recount_instruction"]["id"] == instruction["id"]
                    assert record["recount_instruction"]["actor_id"] == actor_id
                    assert record["recount_instruction"]["source_round_id"] == prior["id"]
                    assert all(record[key] is None
                               for key in ("event_at", "entered_at", "actor_id"))
                    assert record["revision_actor_id"] == actor_id
                    assert record["revision_event_at"] == instruction["event_at"]
                    assert record["revision_entered_at"] == instruction["entered_at"]
                    assert all(row["quantity"] is None for row in record["candidate_votes"])
                    assert all(row["quantity"] is None for row in record["invalid_papers"])
                    assert record["actual_counted_quantity"] is None
                    assert record["questionable_quantity"] is None and record["f2"] is None
                reports[(kind, form)] = report

        expected_required = {
            "request_id": request_id,
            "scope_revision": str(setup["scope"]["revision"]),
            "scope_revision_id": str(setup["scope"]["revision_id"]),
            "source_round_id": str(prior["id"]),
            "source_round_revision": str(prior["revision"]),
            "source_round_revision_id": str(prior["revision_id"]),
            "new_round_id": str(blank["id"]),
            "new_round_number": "2",
            "actor_id": str(actor_id),
            "reason": reason,
            # Literal worked UTC+08 conversions, without importing the report formatter.
            "event_at": "2026-11-16 00:05:42.123456 HKT",
            "entered_at": "2026-11-16 00:10:00 HKT",
            "completed_at": "Not recorded",
            "completion_selection_revision": "Not recorded",
            "current_satisfied": "No",
        }
        required_label_keys = {
            "local_recount_pending", "local_recount_contributes_to_result",
            "local_recount_associated_instruction", "local_recount_required_instruction",
            "local_recount_state_pending",
            *("local_recount_required_" + field for field in RECOUNT_DETAIL_FIELDS),
        }
        for (kind, form), report in reports.items():
            labels, metadata = report["labels"], report["metadata"]
            # Expected first RED at0b600ea: these new labels/rows do not exist yet.
            assert not (required_label_keys - labels.keys()), sorted(
                required_label_keys - labels.keys()
            )
            assert all(isinstance(labels[key], str) and labels[key]
                       and labels[key] != key for key in required_label_keys)
            assert labels["yes"] == "Yes" and labels["no"] == "No"
            assert labels["not_recorded"] == "Not recorded"
            assert all(isinstance(row, list) and len(row) == 2
                       and all(isinstance(value, str) for value in row) for row in metadata)
            rows = [
                [labels["local_recount_pending"], "Yes"],
                [labels["local_recount_contributes_to_result"], "No"],
                [labels["local_recount_associated_instruction"],
                 str(instruction["id"]) if kind == "blank" else "Not recorded"],
                [labels["local_recount_required_instruction"], str(instruction["id"])],
            ]
            expected = {**expected_required, "status": labels["local_recount_state_pending"]}
            rows.extend([labels["local_recount_required_" + field], expected[field]]
                        for field in RECOUNT_DETAIL_FIELDS)
            for row in rows:
                assert metadata.count(row) == 1, row
                assert " · ".join(row) in report["preview_lines"]
            # None or the same associated instruction needs no second detail block.
            associated_labels = {
                labels[key] for field in RECOUNT_DETAIL_FIELDS
                if (key := "local_recount_associated_" + field) in labels
            }
            associated_labels -= {
                labels["local_recount_required_" + field] for field in RECOUNT_DETAIL_FIELDS
            }
            assert not [row for row in metadata if row[0] in associated_labels]

            observation_keys = (
                ("event_at", "entered_at", "actor_id") if form == "statement"
                else ("f1_event_at", "f1_entered_at", "f1_actor_id")
            )
            values = (
                ("Not recorded", "Not recorded", "Not recorded") if kind == "blank"
                else ("2026-11-15 23:15:12.123456 HKT", "2026-11-16 00:00:00 HKT",
                      str(prior["actor_id"]))
            )
            for key, value in zip(observation_keys, values, strict=True):
                assert [labels[key], value] in metadata
            if kind == "blank" and form != "statement":
                assert [labels["revision_actor_id"], str(actor_id)] in metadata
                assert [labels["revision_event_at"], expected_required["event_at"]] in metadata
                assert [labels["revision_entered_at"], expected_required["entered_at"]] in metadata

        history_after_response = counter.get(source_path)
        assert history_after_response.status_code == 200, history_after_response.text
        history_after = history_after_response.json()["history"]
        assert [row["revision_id"] for row in history_after] == [
            row["revision_id"] for row in history_before
        ]
        for before, after in zip(history_before, history_after, strict=True):
            for key in ("candidate_votes", "invalid_papers", "scope_basis", "f2",
                        "event_at", "entered_at", "actor_id", "approved_at", "approved_by"):
                assert after.get(key) == before.get(key)
