"""Localized exports preserve historical recount association and the current requirement."""

import csv
from collections.abc import Iterator
from datetime import timedelta
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.results_support import save_result_round
from tests.tally_support import complete_f1_command
from tests.test_constituency_tie_api import complete_tie_setup

FORMS = ("statement", "f2", "f3", "f4", "count")
TOKENS = {
    "tc": {
        "yes": "是", "no": "否", "not_recorded": "尚未記錄",
        "pending": "尚未完成批准及選取", "completed": "曾完成批准及選取",
        "historical": "先前指示；目前要求另列",
        "pending_label": "目前重新點票要求尚待完成",
    },
    "sc": {
        "yes": "是", "no": "否", "not_recorded": "尚未记录",
        "pending": "尚未完成批准及选取", "completed": "曾完成批准及选取",
        "historical": "先前指示；当前要求另列",
        "pending_label": "当前重新点票要求尚待完成",
    },
    "en": {
        "yes": "Yes", "no": "No", "not_recorded": "Not recorded",
        "pending": "Not yet approved and explicitly selected",
        "completed": "Previously approved and explicitly selected",
        "historical": "Earlier instruction; current requirement shown separately",
        "pending_label": "Current recount requirement pending",
    },
}


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def complete_required_round(setup: dict, blank: dict, selection_revision: int) -> dict:
    """Enter, submit, approve and select an instructed blank round through public APIs."""
    counter, supervisor = setup["clients"]["receiveronly"], setup["clients"]["supervisor"]
    path = setup["rounds_path"]
    options_response = counter.get(path)
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()
    target = f"{path}/{blank['id']}"
    command = complete_f1_command(
        options, expected_revision=1, actual_counted_quantity=10,
        event_at="2026-11-16T00:06:12.123456+08:00",
        notes="Observed first replacement: eight and two.",
    )
    for row, quantity in zip(command["candidate_votes"], [8, 2], strict=True):
        row["quantity"] = quantity
    f1_response = counter.put(target, json=command)
    assert f1_response.status_code == 200, f1_response.text
    f2_response = counter.put(target + "/f2", json=complete_f2_command(
        options, expected_revision=f1_response.json()["revision"],
        event_at="2026-11-16T00:07:17.654321+08:00",
    ))
    assert f2_response.status_code == 200, f2_response.text
    submitted = counter.post(target + "/submit", json={
        "request_id": str(uuid4()), "expected_revision": f2_response.json()["revision"],
        "scope_revision": setup["scope"]["revision"],
    })
    assert submitted.status_code == 200, submitted.text
    approved = supervisor.post(target + "/approve", json={
        "request_id": str(uuid4()), "expected_revision": submitted.json()["revision"],
        "scope_revision": setup["scope"]["revision"], "password": READY_PASSWORD,
    })
    assert approved.status_code == 200, approved.text
    selected = supervisor.post(target + "/select", json={
        "request_id": str(uuid4()), "expected_revision": approved.json()["revision"],
        "scope_revision": setup["scope"]["revision"],
        "expected_selection_revision": selection_revision, "password": READY_PASSWORD,
    })
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected"] is True and selected.json()["approval_valid"] is True
    assert selected.json()["selection"]["revision"] == selection_revision + 1
    return selected.json()


def test_localized_exports_keep_completed_association_separate_from_later_requirement(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        supervisor, counter = setup["clients"]["supervisor"], setup["clients"]["receiveronly"]
        rounds_path = setup["rounds_path"]
        source_path = f"{rounds_path}/{prior['id']}"
        original_response = counter.get(source_path)
        assert original_response.status_code == 200, original_response.text
        original_history = original_response.json()["history"]
        legacy = {}
        for locale in TOKENS:
            for form in FORMS:
                response = supervisor.get(
                    f"{source_path}/revisions/{prior['revision']}/{form}",
                    params={"locale": locale},
                )
                assert response.status_code == 200, response.text
                report = response.json()
                assert report["record"].get("required_recount") is None
                assert not any(key.startswith("local_recount_") for key in report["labels"])
                legacy[(locale, form)] = report

        scope = setup["scope"]
        station_id = setup["stations"]["N1"]["id"]
        actor_id = setup["accounts"]["supervisor"]["id"]
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope['id']}/recounts"
        )
        setup["clock"].value += timedelta(minutes=10)
        first_uuid = str(uuid4())
        first_reason = "FIRST RECOUNT: signed paper review requires a fresh tally."
        first_response = supervisor.post(recount_path, json={
            "request_id": first_uuid, "scope_revision": scope["revision"],
            "expected_selection_revision": prior["selection"]["revision"],
            "source_round_id": prior["id"], "source_round_revision": prior["revision"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": first_reason, "password": READY_PASSWORD,
        })
        assert first_response.status_code == 201, first_response.text
        first = first_response.json()["instruction"]
        completed = complete_required_round(
            setup, first_response.json()["round"], prior["selection"]["revision"]
        )
        assert completed["round_number"] == 2 and completed["revision"] == 5
        assert [row["quantity"] for row in completed["candidate_votes"]] == [8, 2]
        assert completed["scope_basis"] == prior["scope_basis"]
        completed_state_response = supervisor.get(recount_path)
        assert completed_state_response.status_code == 200, completed_state_response.text
        first_completed = completed_state_response.json()["latest_instruction"]
        assert first_completed["id"] == first["id"]
        assert first_completed["status"] == "completed"
        assert first_completed["current_satisfied"] is True
        assert first_completed["completion_selection_revision"] == 2
        assert first_completed["completed_at"] == "2026-11-15T16:10:00Z"
        replacement_path = f"{rounds_path}/{completed['id']}"
        completed_previews = {}
        for locale, token in TOKENS.items():
            for form in FORMS:
                response = supervisor.get(
                    f"{replacement_path}/revisions/{completed['revision']}/{form}",
                    params={"locale": locale},
                )
                assert response.status_code == 200, response.text
                report = response.json()
                record, labels, metadata = report["record"], report["labels"], report["metadata"]
                assert record["recount_pending"] is False
                assert record["contributes_to_result"] is True
                assert record["recount_instruction"]["id"] == record["required_recount"]["id"]
                assert record["recount_instruction"]["id"] == first["id"]
                assert labels["local_recount_pending"] == token["pending_label"]
                assert [labels["local_recount_pending"], token["no"]] in metadata
                assert [labels["local_recount_contributes_to_result"], token["yes"]] in metadata
                assert metadata.count([
                    labels["local_recount_required_request_id"], first_uuid
                ]) == 1
                associated_labels = {
                    value for key, value in labels.items()
                    if key.startswith("local_recount_associated_")
                    and key != "local_recount_associated_instruction"
                }
                assert not [row for row in metadata if row[0] in associated_labels]
                completed_previews[(locale, form)] = report

        setup["clock"].value += timedelta(minutes=10)
        second_uuid = str(uuid4())
        second_reason = "LATER RECOUNT: another paper review requires a new tally."
        second_response = supervisor.post(recount_path, json={
            "request_id": second_uuid, "scope_revision": scope["revision"],
            "expected_selection_revision": completed["selection"]["revision"],
            "source_round_id": completed["id"], "source_round_revision": completed["revision"],
            "event_at": "2026-11-16T00:15:42.654321+08:00",
            "reason": second_reason, "password": READY_PASSWORD,
        })
        assert second_response.status_code == 201, second_response.text
        second = second_response.json()["instruction"]
        assert second["new_round_number"] == 3
        state_response = supervisor.get(recount_path)
        assert state_response.status_code == 200, state_response.text
        state = state_response.json()
        historical = next(row for row in state["instructions"] if row["id"] == first["id"])
        assert state["latest_instruction"]["id"] == second["id"] and state["pending"] is True
        assert historical["status"] == "completed" and historical["current_satisfied"] is None
        assert historical["completed_at"] == first_completed["completed_at"]
        assert historical["completion_selection_id"] == first_completed["completion_selection_id"]

        for locale, token in TOKENS.items():
            for form in FORMS:
                base = f"{replacement_path}/revisions/{completed['revision']}/{form}"
                response = supervisor.get(base, params={"locale": locale})
                assert response.status_code == 200, response.text
                report = response.json()
                record, labels, metadata = report["record"], report["labels"], report["metadata"]
                assert record["recount_instruction"]["id"] == first["id"]
                assert record["required_recount"]["id"] == second["id"]
                assert record["recount_pending"] is True
                assert record["contributes_to_result"] is False
                assert record["is_current"] is True and record["selected"] is True
                assert record["scope_basis"] == completed["scope_basis"] == prior["scope_basis"]
                for key in ("candidate_votes", "invalid_papers", "f2", "event_at", "entered_at",
                            "actor_id", "notes", "approved_at", "approved_by"):
                    assert record[key] == completed[key]
                assert [row["quantity"] for row in record["candidate_votes"]] == [8, 2]
                assert labels["local_recount_state_pending"] == token["pending"]
                assert labels["local_recount_state_completed"] == token["completed"]
                assert labels["local_recount_historical_not_current"] == token["historical"]
                expected = {
                    "local_recount_pending": token["yes"],
                    "local_recount_contributes_to_result": token["no"],
                    "local_recount_associated_instruction": str(first["id"]),
                    "local_recount_required_instruction": str(second["id"]),
                    "local_recount_required_request_id": second_uuid,
                    "local_recount_required_source_round_id": str(completed["id"]),
                    "local_recount_required_source_round_revision": str(completed["revision"]),
                    "local_recount_required_source_round_revision_id": (
                        str(completed["revision_id"])
                    ),
                    "local_recount_required_new_round_id": str(second["new_round_id"]),
                    "local_recount_required_new_round_number": "3",
                    "local_recount_required_actor_id": str(actor_id),
                    "local_recount_required_reason": second_reason,
                    "local_recount_required_event_at": "2026-11-16 00:15:42.654321 HKT",
                    "local_recount_required_entered_at": "2026-11-16 00:20:00 HKT",
                    "local_recount_required_status": token["pending"],
                    "local_recount_required_completed_at": token["not_recorded"],
                    "local_recount_required_completion_selection_revision": token["not_recorded"],
                    "local_recount_required_current_satisfied": token["no"],
                    "local_recount_associated_request_id": first_uuid,
                    "local_recount_associated_source_round_id": str(prior["id"]),
                    "local_recount_associated_source_round_revision": str(prior["revision"]),
                    "local_recount_associated_source_round_revision_id": str(prior["revision_id"]),
                    "local_recount_associated_new_round_id": str(completed["id"]),
                    "local_recount_associated_new_round_number": "2",
                    "local_recount_associated_actor_id": str(actor_id),
                    "local_recount_associated_reason": first_reason,
                    "local_recount_associated_event_at": "2026-11-16 00:05:42.123456 HKT",
                    "local_recount_associated_entered_at": "2026-11-16 00:10:00 HKT",
                    "local_recount_associated_status": token["completed"],
                    "local_recount_associated_completed_at": "2026-11-16 00:10:00 HKT",
                    "local_recount_associated_completion_selection_revision": "2",
                    "local_recount_associated_current_satisfied": token["historical"],
                }
                # Both instructions preserve the same current scope revision identity.
                for prefix in ("required", "associated"):
                    expected[f"local_recount_{prefix}_scope_revision"] = str(scope["revision"])
                    expected[f"local_recount_{prefix}_scope_revision_id"] = (
                        str(scope["revision_id"])
                    )
                rows = [[labels[key], value] for key, value in expected.items()]
                for row in rows:
                    assert metadata.count(row) == 1, row
                before = completed_previews[(locale, form)]
                assert before["record"]["candidate_votes"] == record["candidate_votes"]
                recount_labels = {value for key, value in labels.items()
                                  if key.startswith("local_recount_")}
                assert not [row for row in legacy[(locale, form)]["metadata"]
                            if row[0] in recount_labels]
                observation_keys = (
                    ("event_at", "entered_at", "actor_id") if form == "statement"
                    else ("f1_event_at", "f1_entered_at", "f1_actor_id")
                )
                observation_values = (
                    "2026-11-16 00:06:12.123456 HKT", "2026-11-16 00:10:00 HKT",
                    str(setup["accounts"]["receiveronly"]["id"]),
                )
                observation_rows = [[labels[key], value] for key, value in zip(
                    observation_keys, observation_values, strict=True
                )]

                csv_response = supervisor.get(base + ".csv", params={"locale": locale})
                assert csv_response.status_code == 200, csv_response.text
                assert csv_response.content.startswith(b"\xef\xbb\xbf")
                csv_text = csv_response.content.decode("utf-8-sig")
                csv_rows = list(csv.reader(StringIO(csv_text)))
                for row in rows:
                    assert csv_rows.count(row) == 1, row
                for row in observation_rows:
                    assert row in csv_rows
                assert "local_recount_" not in csv_text and READY_PASSWORD not in csv_text

                pdf_response = supervisor.get(base + ".pdf", params={"locale": locale})
                assert pdf_response.status_code == 200, pdf_response.text
                assert pdf_response.content.startswith(b"%PDF-")
                pages = PdfReader(BytesIO(pdf_response.content)).pages
                assert len(pages) > 0
                page_texts = [page.extract_text() or "" for page in pages]
                assert all(text.strip() for text in page_texts)
                pdf_text = "\n".join(page_texts)
                normalized_pdf = "".join(pdf_text.split())
                for label, value in [*rows, *observation_rows]:
                    assert "".join(label.split()) in normalized_pdf
                    assert "".join(value.split()) in normalized_pdf
                assert "\ufffd" not in pdf_text
                assert "local_recount_" not in pdf_text and READY_PASSWORD not in pdf_text

        preserved_response = counter.get(source_path)
        assert preserved_response.status_code == 200, preserved_response.text
        preserved = preserved_response.json()
        assert [row["revision_id"] for row in preserved["history"]] == [
            row["revision_id"] for row in original_history
        ]
        for key in ("candidate_votes", "invalid_papers", "scope_basis", "f2", "event_at",
                    "entered_at", "actor_id", "notes", "approved_at", "approved_by"):
            assert preserved["record"][key] == prior[key]
        assert [row["quantity"] for row in preserved["record"]["candidate_votes"]] == [6, 4]
