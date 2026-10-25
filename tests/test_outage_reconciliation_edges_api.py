"""Outage paper identities and late provenance linking through public APIs."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def _count_draft(setup: dict) -> tuple[dict, str, dict]:
    counter, rounds_path = setup["counter"], setup["rounds_path"]
    options = counter.get(rounds_path).json()
    f1 = complete_f1_command(options, actual_counted_quantity=5)
    f1["candidate_votes"][0]["quantity"] = 5
    created = counter.post(rounds_path, json=f1)
    assert created.status_code == 201, created.text
    target = rounds_path + f"/{created.json()['id']}"
    f2 = counter.put(target + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    return options, target, created.json()


def _create_outage_and_paper(setup: dict, round_id: int) -> tuple[str, dict]:
    counter = setup["counter"]
    station_id = setup["stations"]["N1"]["id"]
    outage_path = f"/api/workspace/stations/{station_id}/outages"
    outage = counter.post(
        outage_path,
        json={
            "request_id": str(uuid4()),
            "reference": "N1 network outage " + uuid4().hex[:10],
            "kind": "network",
            "started_at": "2026-11-15T23:15:00+08:00",
            "ended_at": "2026-11-15T23:40:00+08:00",
            "notes": "Staff used the signed paper count return during the outage.",
        },
    )
    assert outage.status_code == 201, outage.text
    outage_record_path = outage_path + f"/{outage.json()['id']}"
    paper = counter.post(
        outage_record_path + "/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": "N1-PAPER-" + uuid4().hex[:12],
            "workflow": "count",
            "action": "submit",
            "original_event_at": "2026-11-15T23:35:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
            "notes": "Paper count return signed by the Counting Officer.",
        },
    )
    assert paper.status_code == 201, paper.text
    assert paper.json()["status"] == "pending"
    return outage_record_path, paper.json()


def test_late_paper_link_replays_original_count_receipt_without_second_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter = setup["counter"]
        options, target, count_round = _count_draft(setup)
        request_id = str(uuid4())
        original_submission = {
            "request_id": request_id,
            "expected_revision": 2,
            "scope_revision": options["scope"]["revision"],
        }
        submitted = counter.post(target + "/submit", json=original_submission)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["revision"] == 3
        original_receipt = submitted.json()

        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        linked = counter.post(
            target + "/submit",
            json={**original_submission, "paper_record_id": paper["id"]},
        )
        assert linked.status_code == 200, linked.text
        assert linked.json() == original_receipt

        history = counter.get(target)
        assert history.status_code == 200, history.text
        assert [row["revision"] for row in history.json()["history"]] == [3, 2, 1]
        record = counter.get(outage_path).json()["record"]
        assert len(record["paper_records"]) == 1
        entered = record["paper_records"][0]
        assert entered["status"] == "entered"
        assert entered["reentry"]["request_id"] == request_id
        assert entered["reentry"]["record"] == original_receipt


def test_paper_reference_identity_is_trimmed_case_sensitive_and_request_bound(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, _, count_round = _count_draft(setup)
        counter = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = counter.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "N1 identity test " + uuid4().hex[:10],
                "kind": "network",
                "started_at": "2026-11-15T23:15:00+08:00",
                "ended_at": "2026-11-15T23:40:00+08:00",
                "notes": "Paper-reference identity check.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_record_path = outage_path + f"/{outage.json()['id']}"
        base = {
            "expected_outage_revision": 1,
            "workflow": "count",
            "action": "submit",
            "original_event_at": "2026-11-15T23:35:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": count_round["id"]},
            "notes": "Paper return for the identity test.",
        }
        first_request = str(uuid4())
        first = counter.post(
            outage_record_path + "/paper-records",
            json={**base, "request_id": first_request, "paper_reference": "  Exact-Paper-Ref  "},
        )
        assert first.status_code == 201, first.text
        assert first.json()["paper_reference"] == "Exact-Paper-Ref"

        duplicate = counter.post(
            outage_record_path + "/paper-records",
            json={**base, "request_id": str(uuid4()), "paper_reference": "Exact-Paper-Ref"},
        )
        assert duplicate.status_code == 409, duplicate.text

        case_variant = counter.post(
            outage_record_path + "/paper-records",
            json={**base, "request_id": str(uuid4()), "paper_reference": "exact-paper-ref"},
        )
        assert case_variant.status_code == 201, case_variant.text
        assert case_variant.json()["paper_reference"] == "exact-paper-ref"

        changed_identity = counter.post(
            outage_record_path + "/paper-records",
            json={**base, "request_id": first_request, "paper_reference": "Different-Ref"},
        )
        assert changed_identity.status_code == 409, changed_identity.text
        assert changed_identity.json()["detail"]["code"] == "request_conflict"
        replay = counter.post(
            outage_record_path + "/paper-records",
            json={**base, "request_id": first_request, "paper_reference": "Exact-Paper-Ref"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        current = counter.get(outage_record_path)
        assert current.status_code == 200, current.text
        records = current.json()["record"]["paper_records"]
        assert [row["paper_reference"] for row in records] == [
            "Exact-Paper-Ref",
            "exact-paper-ref",
        ]
