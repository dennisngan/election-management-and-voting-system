"""Outage paper identities and late provenance linking through public APIs."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
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


def test_reconciliation_requires_exact_supervisor_review_and_invalidates_on_basis_changes(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter = setup["counter"]
        options, round_target, count_round = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        submitted = counter.post(
            round_target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
                "paper_record_id": paper["id"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["revision"] == 3
        outage_response = counter.get(outage_path)
        assert outage_response.status_code == 200, outage_response.text
        record = outage_response.json()["record"]
        paper_row = record["paper_records"][0]
        assert paper_row["status"] == "entered"

        supervisor = setup["clients"]["supervisor"]
        approve_path = outage_path + "/approve"

        def approval(*, request_id: str | None = None, **changes: object) -> dict:
            return {
                "request_id": request_id or str(uuid4()),
                "expected_revision": record["revision"],
                "expected_reconciliation_revision": 0,
                "paper_revisions": [{"paper_id": paper_row["id"], "revision": 1}],
                "password": READY_PASSWORD,
                "reason": "Supervisor matched the paper return to its count receipt.",
                **changes,
            }

        wrong_password = supervisor.post(
            approve_path,
            json=approval(password="Incorrect-Password-42!"),
        )
        assert wrong_password.status_code == 401, wrong_password.text
        blank_reason = supervisor.post(approve_path, json=approval(reason="   "))
        assert blank_reason.status_code == 422, blank_reason.text
        omitted_membership = supervisor.post(approve_path, json=approval(paper_revisions=[]))
        assert omitted_membership.status_code == 409, omitted_membership.text
        assert omitted_membership.json()["detail"]["code"] == ("outage_paper_revision_conflict")

        approved = supervisor.post(approve_path, json=approval())
        assert approved.status_code == 200, approved.text
        current = approved.json()["record"]
        assert current["reconciled"] is True
        assert current["reconciliation"]["valid"] is True

        stale_cas = supervisor.post(
            approve_path,
            json=approval(request_id=str(uuid4()), expected_reconciliation_revision=0),
        )
        assert stale_cas.status_code == 409, stale_cas.text
        assert stale_cas.json()["detail"]["code"] == ("outage_reconciliation_revision_conflict")

        successor = counter.put(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": current["revision"],
                "reference": current["reference"],
                "kind": current["kind"],
                "started_at": current["started_at"],
                "ended_at": current["ended_at"],
                "notes": "Supervisor rechecked the original outage interval.",
                "amendment_reason": "Corrected the outage note from the signed log.",
            },
        )
        assert successor.status_code == 200, successor.text
        after_outage_successor = counter.get(outage_path).json()["record"]
        assert after_outage_successor["revision"] == current["revision"] + 1
        assert after_outage_successor["reconciled"] is False
        assert after_outage_successor["reconciliation_history"][0]["valid"] is False

        reapproved = supervisor.post(
            approve_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": after_outage_successor["revision"],
                "expected_reconciliation_revision": 1,
                "paper_revisions": [{"paper_id": paper_row["id"], "revision": 1}],
                "password": READY_PASSWORD,
                "reason": "Supervisor reviewed the revised outage history and same paper receipt.",
            },
        )
        assert reapproved.status_code == 200, reapproved.text
        assert reapproved.json()["record"]["reconciliation"]["revision"] == 2
        assert reapproved.json()["record"]["reconciled"] is True

        second_paper = counter.post(
            outage_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": after_outage_successor["revision"],
                "paper_reference": "N1-PAPER-SECOND-" + uuid4().hex[:10],
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:36:00+08:00",
                "target": {
                    "scope_id": setup["scope"]["id"],
                    "round_id": count_round["id"],
                },
                "notes": "A second current paper return is awaiting entry.",
            },
        )
        assert second_paper.status_code == 201, second_paper.text
        after_paper_successor = counter.get(outage_path).json()["record"]
        assert len(after_paper_successor["paper_records"]) == 2
        assert after_paper_successor["paper_records"][1]["status"] == "pending"
        assert after_paper_successor["reconciled"] is False
        assert after_paper_successor["reconciliation_history"][0]["revision"] == 2
        assert after_paper_successor["reconciliation_history"][0]["valid"] is False


def test_paper_amendment_replay_stays_bound_to_its_original_outage(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, _, count_round = _count_draft(setup)
        first_path, paper = _create_outage_and_paper(setup, count_round["id"])
        other_path, _ = _create_outage_and_paper(setup, count_round["id"])
        paper_path = first_path + f"/paper-records/{paper['id']}"
        command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "expected_revision": 1,
            "original_event_at": "2026-11-15T23:34:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": count_round["id"]},
            "notes": "Corrected original paper time.",
            "amendment_reason": "Check against the signed count return.",
        }
        saved = setup["counter"].put(paper_path, json=command)
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 2
        replay = setup["counter"].put(paper_path, json=command)
        assert replay.status_code == 200, replay.text
        assert replay.json() == saved.json()

        wrong_parent = setup["counter"].put(
            other_path + f"/paper-records/{paper['id']}", json=command,
        )
        assert wrong_parent.status_code == 404, wrong_parent.text
        assert wrong_parent.json() == {"detail": {"code": "outage_paper_not_found"}}
        current = setup["counter"].get(first_path)
        assert current.status_code == 200, current.text
        original_paper = current.json()["record"]["paper_records"][0]
        assert original_paper["revision"] == 2
        assert original_paper["notes"] == saved.json()["notes"]


def test_count_paper_amendment_replay_requires_current_counting_role(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        _, _, count_round = _count_draft(setup)
        path, paper = _create_outage_and_paper(setup, count_round["id"])
        target = path + f"/paper-records/{paper['id']}"
        command = {
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "expected_revision": 1,
            "original_event_at": "2026-11-15T23:34:00+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": count_round["id"]},
            "notes": "Corrected paper time before role reassignment.",
            "amendment_reason": "Checked signed return.",
        }
        counter = setup["counter"]
        saved = counter.put(target, json=command)
        assert saved.status_code == 200, saved.text
        profile = counter.get("/api/auth/me")
        assert profile.status_code == 200, profile.text
        full_account = admin.get(f"/api/accounts/{profile.json()['id']}")
        assert full_account.status_code == 200, full_account.text
        account = full_account.json()
        changed = admin.put(
            f"/api/accounts/{account['id']}",
            json={
                "revision": account["revision"],
                "display_name": account["display_name"],
                "role": "polling_officer",
                "enabled": True,
                "station_ids": account["station_ids"],
            },
        )
        assert changed.status_code == 200, changed.text
        login = counter.post(
            "/api/auth/login",
            json={"username": account["username"], "password": READY_PASSWORD},
        )
        assert login.status_code == 200, login.text
        counter.headers["Authorization"] = "Bearer " + login.json()["token"]
        assert counter.get("/api/auth/me").json()["role"] == "polling_officer"
        forbidden = counter.put(target, json=command)
        assert forbidden.status_code == 403, forbidden.text
        assert forbidden.json() == {"detail": {"code": "counting_officer_required"}}
