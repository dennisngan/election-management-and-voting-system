"""Existing count reports identify a wide instruction without changing observations."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup

FORMS = ("statement", "f2", "f3", "f4", "count")
LOCALES = ("en", "tc", "sc")
REQUIRED_PARENT_ID_LABEL = "Current required instruction · Constituency-wide instruction ID"
FROZEN_OBSERVATIONS = (
    "candidate_votes", "invalid_papers", "actual_counted_quantity", "questionable_quantity",
    "scope_basis", "f2", "event_at", "entered_at", "actor_id", "notes", "approved_at",
    "approved_by",
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_count_previews_preserve_original_observations_and_show_the_wide_parent(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor = setup["clients"]["supervisor"]
        rounds_path = setup["rounds_path"]
        source_path = saved["round_path"]
        history_response = supervisor.get(source_path)
        assert history_response.status_code == 200, history_response.text
        original_history = history_response.json()["history"]
        assert [row["quantity"] for row in prior["candidate_votes"]] == [6, 4]
        assert [row["quantity"] for row in setup["n3_round"]["selected"]["candidate_votes"]] == [
            0, 0,
        ]

        legacy = {}
        for locale in LOCALES:
            for form in FORMS:
                response = supervisor.get(
                    f"{source_path}/revisions/{prior['revision']}/{form}",
                    params={"locale": locale},
                )
                assert response.status_code == 200, response.text
                report = response.json()
                assert report["record"].get("required_recount") is None
                assert report["record"].get("recount_instruction") is None
                legacy[(locale, form)] = report

        constituency_id = setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        assert options["can_instruct"] is True
        scope_ids = [setup["scope"]["id"], setup["n3_scope"]["id"]]
        assert [row["scope_id"] for row in options["scope_sources"]] == scope_ids
        request_id = str(uuid4())
        actor_id = setup["accounts"]["supervisor"]["id"]
        reason = "Repeat every North scope; retain the original six/four and observed zero."
        setup["clock"].value += timedelta(minutes=10)
        created = supervisor.post(target, json={
            "request_id": request_id, "basis_digest": options["basis_digest"],
            "scope_sources": options["scope_sources"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": reason, "password": READY_PASSWORD,
        })
        assert created.status_code == 201, created.text
        receipt = created.json()
        parent = receipt["instruction"]
        assert parent["id"] > 0
        assert len(receipt["members"]) == 2
        expected_parent = {
            "id": parent["id"], "request_id": request_id,
            "constituency_id": constituency_id, "actor_id": actor_id, "reason": reason,
            "event_at": "2026-11-15T16:05:42.123456Z",
            "entered_at": "2026-11-15T16:10:00Z",
            "member_count": 2, "scope_ids": scope_ids,
        }
        for field in ("request_id", "constituency_id", "actor_id", "reason", "event_at",
                      "entered_at", "member_count"):
            assert parent[field] == expected_parent[field]
        assert [row["scope_id"] for row in parent["members"]] == scope_ids
        local, blank = receipt["members"][0]["instruction"], receipt["members"][0]["round"]
        assert local["scope_id"] == setup["scope"]["id"]
        assert local["source_round_id"] == prior["id"]
        assert local["new_round_id"] == blank["id"]

        reports = {}
        # Establish all existing routes and their unchanged observations before the new key.
        for locale in LOCALES:
            for kind, round_id, revision in (
                ("source", prior["id"], prior["revision"]), ("blank", blank["id"], 1),
            ):
                for form in FORMS:
                    response = supervisor.get(
                        f"{rounds_path}/{round_id}/revisions/{revision}/{form}",
                        params={"locale": locale},
                    )
                    assert response.status_code == 200, response.text
                    report = response.json()
                    assert report["round_id"] == round_id and report["revision"] == revision
                    assert report["locale"] == locale
                    record = report["record"]
                    assert record["required_recount"]["id"] == local["id"]
                    assert record["recount_pending"] is True
                    assert record["contributes_to_result"] is False
                    assert record["scope_basis"] == prior["scope_basis"]
                    if kind == "source":
                        assert record["recount_instruction"] is None
                        assert {key: record[key] for key in FROZEN_OBSERVATIONS} == {
                            key: prior[key] for key in FROZEN_OBSERVATIONS
                        }
                    else:
                        assert record["recount_instruction"]["id"] == local["id"]
                        assert record["revision_actor_id"] == actor_id
                        assert record["revision_event_at"] == expected_parent["event_at"]
                        assert record["revision_entered_at"] == expected_parent["entered_at"]
                        assert all(record[key] is None for key in (
                            "event_at", "entered_at", "actor_id", "actual_counted_quantity",
                            "questionable_quantity", "f2",
                        ))
                        assert all(row["quantity"] is None
                                   for key in ("candidate_votes", "invalid_papers")
                                   for row in record[key])
                    reports[(locale, kind, form)] = report

        # Genuine first RED: the current required instruction lacks its wide parent key.
        first = reports[("en", "source", "statement")]
        assert first["record"]["required_recount"]["constituency_recount"] == expected_parent
        for (_, kind, _), report in reports.items():
            record = report["record"]
            assert record["required_recount"]["constituency_recount"] == expected_parent
            if kind == "blank":
                assert record["recount_instruction"]["constituency_recount"] == expected_parent

        for member, source in zip(receipt["members"], options["scope_sources"], strict=True):
            assert member["instruction"]["constituency_recount"] == expected_parent
            assert member["round"]["required_recount"]["constituency_recount"] == expected_parent
            assert member["round"]["recount_instruction"]["constituency_recount"] == expected_parent
            assert all(row["quantity"] is None for row in member["round"]["candidate_votes"])
            assert member["round"]["f2"] is None
            path = (
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}/recounts"
            )
            response = supervisor.get(path)
            assert response.status_code == 200, response.text
            state = response.json()
            assert len(state["instructions"]) == 1
            assert state["instructions"][0]["constituency_recount"] == expected_parent
            assert state["latest_instruction"]["constituency_recount"] == expected_parent

        # Anchor the new public label in Root's recorded English wording, then use
        # that same key across locales without inventing an official Chinese label.
        id_keys = [key for key, value in first["labels"].items()
                   if value == REQUIRED_PARENT_ID_LABEL]
        assert len(id_keys) == 1
        id_key = id_keys[0]
        for (locale, _, form), report in reports.items():
            label = report["labels"][id_key]
            assert isinstance(label, str) and label and label != id_key
            if locale == "en":
                assert label == REQUIRED_PARENT_ID_LABEL
            else:
                assert label != REQUIRED_PARENT_ID_LABEL
                assert any("\u4e00" <= character <= "\u9fff" for character in label)
            row = [label, str(parent["id"])]
            assert report["metadata"].count(row) == 1
            assert " · ".join(row) in report["preview_lines"]
            assert not [old for old in legacy[(locale, form)]["metadata"] if old[0] == label]

        preserved_response = supervisor.get(source_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == [
            row["revision_id"] for row in original_history
        ]
        for before, after in zip(original_history, preserved["history"], strict=True):
            assert {key: after.get(key) for key in FROZEN_OBSERVATIONS} == {
                key: before.get(key) for key in FROZEN_OBSERVATIONS
            }
        zero_response = supervisor.get(setup["n3_round"]["round_path"])
        assert zero_response.status_code == 200, zero_response.text
        zero = zero_response.json()["record"]
        assert {key: zero[key] for key in FROZEN_OBSERVATIONS} == {
            key: setup["n3_round"]["selected"][key] for key in FROZEN_OBSERVATIONS
        }
