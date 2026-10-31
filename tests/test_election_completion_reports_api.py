"""Immutable completion-event reports retain the exact finalized source facts."""

import csv
import os
import re
from collections.abc import Iterator
from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pypdf import PdfReader

from election.server.app import create_app
from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_staff
from tests.complaint_support import complaint_payload, station_categories
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _csv_rows(response: Response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].partition(";")[0] == "text/csv"
    assert response.headers["content-disposition"].lower().startswith("attachment;")
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))


def _has_pair(rows: list[list[str]], label: str, value: object) -> bool:
    return any(
        row[index:index + 2] == [label, str(value)]
        for row in rows for index in range(len(row) - 1)
    )


def test_original_completion_csv_keeps_finalized_facts_after_reopening_and_complaint_edit(
    admin: TestClient, database_url: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        officer = setup["clients"]["polling"]
        election_id = setup["election"]["id"]
        station_id = setup["stations"]["N1"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        complaints_path = f"/api/workspace/stations/{station_id}/complaints"
        category = station_categories(officer, station_id)[0]
        case_reference = "completion-csv-" + uuid4().hex[:12]
        created = officer.post(complaints_path, json=complaint_payload(
            category, case_reference=case_reference,
        ))
        assert created.status_code == 201, created.text
        complaint = created.json()
        assert complaint["work_status"] == "in_progress" and complaint["completed_at"] is None
        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        reviewed = assessment_response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        event = original["event"]
        assert event["kind"] == "finalization"
        assert {
            "station_id": station_id, "records": [complaint],
        } in event["outcome"]["sources"]["complaints"]
        results = event["outcome"]["results"]
        assert [[row["quantity"] for row in result["candidate_totals"]]
                for result in results] == [[6, 4], [4, 1]]
        report_path = base + f"/completion/history/{event['id']}/statement.csv"
        # First meaningful RED is the real missing report route returning404.
        before = _csv_rows(supervisor.get(report_path, params={"locale": "en"}))
        for label, value in (
            ("Election ID", election_id), ("Election", original["election"]["name"]),
            ("Event ID", event["id"]), ("Status", "Finalized"),
            ("Revision", event["election_revision"]), ("Basis digest", event["basis_digest"]),
            ("Actor ID", event["actor_id"]),
        ):
            assert _has_pair(before, label, value), (label, value, before)
        for result in results:
            for candidate in result["candidate_totals"]:
                assert any(
                    str(candidate["candidate_id"]) in row and candidate["name"] in row
                    and str(candidate["quantity"]) in row for row in before
                ), (candidate, before)
        assert any(case_reference in row and "In progress" in row for row in before), before
        generated_before = [row for row in before if row and row[0] == "Generated at"]
        assert len(generated_before) == 1 and len(generated_before[0]) == 2
        assert generated_before[0][1].endswith(" HKT")
        frozen_rows = [row for row in before if not row or row[0] != "Generated at"]
        reopened = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": event["id"],
            "reason": "Review later complaint progress without replacing the signed outcome.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened.status_code == 201, reopened.text
        assert reopened.json()["election"]["status"] == "active"
        updated = officer.put(f"{complaints_path}/{complaint['id']}", json=complaint_payload(
            category, case_reference=case_reference, expected_revision=complaint["revision"],
            work_status="completed", completed_at="2026-11-15T09:00:00+08:00",
            description="Progress recorded only after the election was reopened.",
        ))
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == complaint["revision"] + 1
        assert updated.json()["work_status"] == "completed"
        current = officer.get(f"{complaints_path}/{complaint['id']}")
        assert current.status_code == 200 and current.json() == updated.json()
        # Approved controlled fixture time; no sleep or production time-control route.
        setup["clock"].value += timedelta(minutes=1)
        after = _csv_rows(supervisor.get(report_path, params={"locale": "en"}))
        generated_after = [row for row in after if row and row[0] == "Generated at"]
        assert len(generated_after) == 1 and len(generated_after[0]) == 2
        assert generated_after[0][1].endswith(" HKT")
        assert generated_after != generated_before
        assert [row for row in after if not row or row[0] != "Generated at"] == frozen_rows
        history = supervisor.get(base + "/completion/history")
        assert history.status_code == 200, history.text
        retained = next(row for row in history.json()["events"] if row["id"] == event["id"])
        assert retained == event


def _pdf_has_cells(text: str, cells: list[object]) -> bool:
    # Source-cell semantics tolerate CJK and long-digest wrapping without page geometry.
    patterns = [r"\s*".join(re.escape(char) for char in str(cell) if not char.isspace())
                for cell in cells]
    return re.search(r"(?<!\S)" + r"\s+".join(patterns) + r"(?=\s|$)", text) is not None


@pytest.mark.parametrize(("locale", "words"), [
    ("en", {
        "title": "Preserved election completion statement",
        "election_id": "Election ID", "election": "Election", "event_id": "Event ID",
        "kind": "Event", "finalization": "Finalization", "status": "Status",
        "finalized": "Finalized", "revision": "Revision", "basis": "Basis digest",
        "actor": "Actor ID", "in_progress": "In progress", "completed": "Completed",
        "not_recorded": "Not recorded",
    }),
    ("tc", {
        "title": "已保留選舉完成確認報表",
        "election_id": "選舉編號", "election": "選舉", "event_id": "事件編號",
        "kind": "事件", "finalization": "完成確認", "status": "狀態",
        "finalized": "已定案", "revision": "修訂", "basis": "基礎摘要",
        "actor": "帳戶編號", "in_progress": "處理中", "completed": "已完成",
        "not_recorded": "未有資料",
    }),
    ("sc", {
        "title": "已保留选举完成确认报表",
        "election_id": "选举编号", "election": "选举", "event_id": "事件编号",
        "kind": "事件", "finalization": "完成确认", "status": "状态",
        "finalized": "已定案", "revision": "修订", "basis": "基础摘要",
        "actor": "账户编号", "in_progress": "处理中", "completed": "已完成",
        "not_recorded": "未有资料",
    }),
])
def test_original_completion_pdf_preserves_finalized_facts_after_reopening_in_each_locale(
    admin: TestClient, database_url: str, tmp_path: Path, locale: str, words: dict[str, str],
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        officer = setup["clients"]["polling"]
        election_id = setup["election"]["id"]
        station_id = setup["stations"]["N1"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        complaints_path = f"/api/workspace/stations/{station_id}/complaints"
        category = station_categories(officer, station_id)[0]
        case_reference = "completion-pdf-" + uuid4().hex[:12]
        created = officer.post(complaints_path, json=complaint_payload(
            category, case_reference=case_reference,
        ))
        assert created.status_code == 201, created.text
        complaint = created.json()
        assert complaint["work_status"] == "in_progress" and complaint["completed_at"] is None
        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        reviewed = assessment_response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        event = original["event"]
        assert event["kind"] == "finalization" and original["election"]["status"] == "finalized"
        assert {"station_id": station_id, "records": [complaint]} in (
            event["outcome"]["sources"]["complaints"]
        )
        assert [[row["quantity"] for row in result["candidate_totals"]]
                for result in event["outcome"]["results"]] == [[6, 4], [4, 1]]
        reopened = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": event["id"],
            "reason": "Review newer complaint progress while preserving the original PDF facts.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened.status_code == 201, reopened.text
        assert reopened.json()["election"]["status"] == "active"
        updated = officer.put(f"{complaints_path}/{complaint['id']}", json=complaint_payload(
            category, case_reference=case_reference, expected_revision=complaint["revision"],
            work_status="completed", completed_at="2026-11-15T09:00:00+08:00",
            description="only-current-after-reopen",
        ))
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == complaint["revision"] + 1
        assert updated.json()["work_status"] == "completed"
        current = officer.get(f"{complaints_path}/{complaint['id']}")
        assert current.status_code == 200 and current.json() == updated.json()
        setup["clock"].value += timedelta(minutes=1)
        report_path = base + f"/completion/history/{event['id']}/statement.pdf"
        response = supervisor.get(report_path, params={"locale": locale})
        # Preserve the exact delivered body before EVERY report assertion or parsing step.
        # On RED this nominal .pdf file contains the actual404 body, not a generated PDF.
        saved_pdf = tmp_path / f"completion-event-{event['id']}-{locale}.pdf"
        descriptor = os.open(saved_pdf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(response.content)
            output.flush()
            os.fsync(output.fileno())
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].partition(";")[0] == "application/pdf"
        assert response.headers["content-disposition"].lower().startswith("attachment;")
        assert response.content.startswith(b"%PDF-")
        pages = PdfReader(BytesIO(response.content)).pages
        texts = [page.extract_text() or "" for page in pages]
        assert texts and all(text.strip() for text in texts)
        text = "\n".join(texts)
        assert "\ufffd" not in text
        compact = "".join(text.split())
        assert "".join(words["title"].split()) in compact
        for label, value in (
            (words["election_id"], election_id),
            (words["election"], original["election"]["name"]),
            (words["event_id"], event["id"]), (words["kind"], words["finalization"]),
            (words["status"], words["finalized"]),
            (words["revision"], event["election_revision"]),
            (words["basis"], event["basis_digest"]), (words["actor"], event["actor_id"]),
        ):
            assert _pdf_has_cells(text, [label, value]), (label, value, saved_pdf)
        for result in event["outcome"]["results"]:
            for candidate in result["candidate_totals"]:
                assert _pdf_has_cells(text, [
                    candidate["candidate_id"], candidate["name"], candidate["quantity"],
                ]), (candidate, saved_pdf)
        assert _pdf_has_cells(text, [
            station_id, complaint["id"], case_reference, complaint["revision"],
            words["in_progress"], words["not_recorded"],
        ]), saved_pdf
        assert not _pdf_has_cells(text, [
            station_id, complaint["id"], case_reference, updated.json()["revision"],
            words["completed"],
        ]), saved_pdf
        assert "only-current-after-reopen" not in text
        assert "HKT" in text


@pytest.mark.parametrize(("principal", "expected_status", "expected_code"), [
    ("anonymous", 401, "session_expired"),
    ("polling_officer", 403, "supervisor_required"),
    ("partial_supervisor", 403, "full_election_access_required"),
])
def test_completion_csv_rechecks_authentication_role_and_whole_election_coverage(
    admin: TestClient, database_url: str, principal: str,
    expected_status: int, expected_code: str,
) -> None:
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        station_ids = {row["id"] for row in setup["stations"].values()}
        assert len(station_ids) == 4
        base = f"/api/workspace/elections/{election_id}"
        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        reviewed = assessment_response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        event = original["event"]
        assert event["kind"] == "finalization"
        history_path = base + "/completion/history"
        before_response = supervisor.get(history_path)
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["events"] == [event]
        report_path = base + f"/completion/history/{event['id']}/statement.csv"
        if principal == "anonymous":
            # A real app/client without an Authorization header, under the fixture's clock.
            with TestClient(
                create_app(database_url, now=setup["clock"]), base_url="https://testserver",
            ) as anonymous:
                denied = anonymous.get(report_path, params={"locale": "en"})
        elif principal == "polling_officer":
            denied = setup["clients"]["polling"].get(report_path, params={"locale": "en"})
        else:
            # A genuine fresh role account/session assigned one of the required four stations.
            with box_staff(
                admin, database_url, setup["clock"], "supervisor", [setup["stations"]["N1"]["id"]],
            ) as (partial, _):
                denied = partial.get(report_path, params={"locale": "en"})
        assert denied.status_code == expected_status, denied.text
        assert denied.json() == {"detail": {"code": expected_code}}
        # Denial must not prevent the full Supervisor from reading the real original event.
        allowed = _csv_rows(supervisor.get(report_path, params={"locale": "en"}))
        assert _has_pair(allowed, "Event ID", event["id"])
        assert _has_pair(allowed, "Status", "Finalized")
        assert _has_pair(allowed, "Basis digest", event["basis_digest"])
        after_response = supervisor.get(history_path)
        assert after_response.status_code == 200, after_response.text
        assert after_response.json() == before
        original_outcome = supervisor.get(
            base + f"/request-outcomes/{original['request_id']}",
            params={"workflow": "election_completion"},
        )
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json() == {
            "request_id": original["request_id"], "workflow": "election_completion",
            "status": "committed", "record": original,
        }


def test_completion_csv_keeps_frozen_source_ids_and_accepted_difference_after_count_amendment(
    admin: TestClient, database_url: str, tmp_path: Path,
) -> None:
    from tests.outcomes_support import complete_f2_command
    from tests.tally_support import complete_f1_command

    def preserve(name: str, body: bytes) -> None:
        descriptor = os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())

    def require_source(
        rows: list[list[str]], identity: tuple[tuple[str, object], ...],
        facts: tuple[tuple[str, object], ...],
    ) -> None:
        # Existing CSV convention separates logical tables by blank rows.
        # Match semantic pairs in ONE source table, without fixed title/order/geometry.
        blocks: list[list[list[str]]] = [[]]
        for row in rows:
            if not row:
                blocks.append([])
            else:
                blocks[-1].append(row)
        assert any(
            all(_has_pair(block, label, value) for label, value in (*identity, *facts))
            for block in blocks
        ), (identity, facts, rows)

    with reviewed_election_setup(
        admin, database_url, n1_quantities=(5, 3), n1_selected=False,
    ) as setup:
        supervisor = setup["clients"]["supervisor"]
        counter = setup["clients"]["receiveronly"]
        station_id = setup["stations"]["N1"]["id"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        n1 = setup["n1_round"]
        target, submitted = n1["round_path"], n1["submitted"]
        scope_id = setup["scope"]["id"]
        scope_revision = n1["options"]["scope"]["revision"]
        stock = next(row for row in submitted["physical_comparisons"] if row["source"] == "stock")
        assert (
            stock["expected_quantity"], stock["actual_quantity"], stock["difference_quantity"]
        ) == (10, 8, -2)
        reason = "Signed paper review confirms eight papers; retain the accepted stock difference."
        accepted = supervisor.post(target + "/physical-differences/stock/accept", json={
            "request_id": str(uuid4()), "expected_revision": submitted["revision"],
            "scope_revision": scope_revision, "expected_decision_revision": 0,
            "reason": reason, "password": BOX_READY_PASSWORD,
        })
        assert accepted.status_code == 200, accepted.text
        decision = next(
            row for row in accepted.json()["physical_decisions"] if row["source"] == "stock"
        )
        assert decision["id"] > 0 and decision["reason"] == reason
        assert decision["reviewed_revision_id"] == submitted["revision_id"]
        assert decision["difference_quantity"] == -2 and decision["valid"] is True
        approved = supervisor.post(target + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": submitted["revision"],
            "scope_revision": scope_revision, "password": BOX_READY_PASSWORD,
        })
        assert approved.status_code == 200, approved.text
        selected_response = supervisor.post(target + "/select", json={
            "request_id": str(uuid4()), "expected_revision": approved.json()["revision"],
            "scope_revision": scope_revision, "expected_selection_revision": 0,
            "password": BOX_READY_PASSWORD,
        })
        assert selected_response.status_code == 200, selected_response.text
        selected = selected_response.json()
        assert selected["selected"] is True and selected["approval_valid"] is True
        assert selected["approved_physical_decisions"] == [decision]
        assert selected["reviewed_revision_id"] == submitted["revision_id"]
        assert selected["scope_basis"] == setup["scope"]
        turnout = next(
            row for row in selected["physical_comparisons"] if row["source"] == "turnout"
        )
        assert turnout["available"] is False and turnout["status"] == "unavailable"
        assert turnout["expected_quantity"] is None and turnout["difference_quantity"] is None
        assert turnout["actual_quantity"] == 8

        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        reviewed = assessment_response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        event = original["event"]
        preserve("canonical-original-finalization.json", finalized.content)
        sources = event["outcome"]["sources"]
        assert sources == reviewed["sources"]
        frozen_count = next(
            row["record"] for row in sources["selected_counts"] if row["scope_id"] == scope_id
        )
        assert frozen_count == selected
        assert frozen_count["approved_physical_decisions"] == [decision]
        for source in sources["polling_completion"]:
            record = source["record"]
            assert record["id"] > 0 and record["status"] == "approved"
            assert record["approved_by"] == setup["accounts"]["supervisor"]["id"]
        for source in sources["accounting"]:
            record = source["record"]
            assert record["id"] > 0 and record["status"] == "approved"
            assert record["source_current"] is True and record["approval_valid"] is True
        assert next(
            row["record"] for row in sources["accounting"] if row["station_id"] == station_id
        ) == setup["accounting"]["N1"]["record"]
        report_path = base + f"/completion/history/{event['id']}/statement.csv"
        before_response = supervisor.get(report_path, params={"locale": "en"})
        preserve("original-before-current-count-amendment.csv", before_response.content)

        reopened = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": event["id"],
            "reason": "Correct the later current tally while retaining the signed first outcome.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened.status_code == 201, reopened.text
        options_response = counter.get(setup["rounds_path"])
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        amended_command = complete_f1_command(
            options, expected_revision=selected["revision"], actual_counted_quantity=10,
            discard_f2=True,
            amendment_reason="Later current-only correction from the reviewed paper tally.",
        )
        for row, quantity in zip(amended_command["candidate_votes"], [7, 3], strict=True):
            row["quantity"] = quantity
        amended = counter.post(target + "/amend-f1", json=amended_command)
        assert amended.status_code == 200, amended.text
        f2 = counter.put(target + "/f2", json=complete_f2_command(
            options, expected_revision=amended.json()["revision"],
        ))
        assert f2.status_code == 200, f2.text
        submitted_again = counter.post(target + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": f2.json()["revision"],
            "scope_revision": scope_revision,
        })
        assert submitted_again.status_code == 200, submitted_again.text
        approved_again = supervisor.post(target + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": submitted_again.json()["revision"],
            "scope_revision": scope_revision, "password": BOX_READY_PASSWORD,
        })
        assert approved_again.status_code == 200, approved_again.text
        selected_again = supervisor.post(target + "/select", json={
            "request_id": str(uuid4()), "expected_revision": approved_again.json()["revision"],
            "scope_revision": scope_revision,
            "expected_selection_revision": selected["selection"]["revision"],
            "password": BOX_READY_PASSWORD,
        })
        assert selected_again.status_code == 200, selected_again.text
        current = selected_again.json()
        preserve("canonical-new-current-count.json", selected_again.content)
        assert current["id"] == frozen_count["id"]
        assert current["revision_id"] != frozen_count["revision_id"]
        assert current["reviewed_revision_id"] != frozen_count["reviewed_revision_id"]
        assert current["selection"]["id"] != frozen_count["selection"]["id"]
        assert current["actual_counted_quantity"] == 10
        assert [row["quantity"] for row in current["final_candidate_votes"]] == [7, 3]
        assert current["approved_physical_decisions"] == []
        assert current["selected"] is True and current["approval_valid"] is True
        after_response = supervisor.get(report_path, params={"locale": "en"})
        preserve("original-after-current-count-amendment.csv", after_response.content)
        history_response = supervisor.get(base + "/completion/history")
        preserve("history-after-current-count-amendment.json", history_response.content)
        assert history_response.status_code == 200, history_response.text
        assert next(
            row for row in history_response.json()["events"] if row["id"] == event["id"]
        ) == event

        before = _csv_rows(before_response)
        after = _csv_rows(after_response)
        assert [row for row in after if not row or row[0] != "Generated at"] == [
            row for row in before if not row or row[0] != "Generated at"
        ]
        # First expected RED: the report has results/complaints but no real source provenance.
        for rows in (before, after):
            for source in sources["polling_completion"]:
                record = source["record"]
                require_source(rows, (
                    ("Source", "Polling completion"), ("Station ID", source["station_id"]),
                ), (
                    ("Record ID", record["id"]), ("Revision", record["revision"]),
                    ("Status", "Approved"), ("Approved by supervisor ID", record["approved_by"]),
                ))
            for source in sources["accounting"]:
                record = source["record"]
                require_source(rows, (
                    ("Source", "P(18) accounting"), ("Station ID", source["station_id"]),
                ), (
                    ("P(18) record ID", record["id"]), ("P(18) revision", record["revision"]),
                    ("P(18) status", "Approved"),
                    ("Source current at finalization", "Yes"),
                    ("Approval valid at finalization", "Yes"),
                    ("Approved by supervisor ID", record["approved_by"]),
                ))
            count_identity = (
                ("Source", "Selected approved count"), ("Station ID", station_id),
                ("Counting scope ID", scope_id), ("Round ID", frozen_count["id"]),
            )
            require_source(rows, count_identity, (
                ("Scope revision", frozen_count["scope_revision"]),
                ("Revision", frozen_count["revision"]),
                ("Revision record ID", frozen_count["revision_id"]),
                ("Count revision reviewed", frozen_count["reviewed_revision"]),
                ("Count revision record reviewed", frozen_count["reviewed_revision_id"]),
                ("Approval valid at finalization", "Yes"),
                ("Approved by supervisor ID", frozen_count["approved_by"]),
                ("Selection ID", frozen_count["selection"]["id"]),
                ("Selection record revision", frozen_count["selection"]["revision"]),
                ("Selected at finalization", "Yes"), ("Actual observed quantity", 8),
            ))
            for box in frozen_count["scope_basis"]["box_basis"]:
                require_source(rows, (
                    ("Source", "Frozen box basis"), ("Counting scope ID", scope_id),
                    ("Box record ID", box["id"]),
                ), (
                    ("Revision", box["revision"]),
                    ("Origin station ID", box["origin_station_id"]),
                    ("Destination station ID", box["destination_station_id"]),
                ))
            pinned_accounting = frozen_count["scope_basis"]["accounting_basis"]
            assert any(record["station_id"] != station_id for record in pinned_accounting)
            for record in pinned_accounting:
                require_source(rows, (
                    ("Source", "Counting scope accounting basis"),
                    ("Counting scope ID", scope_id), ("P(18) record ID", record["id"]),
                ), (
                    ("Counting station ID", station_id),
                    ("Accounting source station ID", record["station_id"]),
                    ("P(18) revision", record["revision"]),
                ))
            require_source(rows, (
                ("Source", "Physical decision approved at review"),
                ("Counting scope ID", scope_id), ("Round ID", frozen_count["id"]),
                ("Decision ID", decision["id"]),
            ), (
                ("Comparison source", "Stock-derived estimate"),
                ("Decision revision", decision["revision"]),
                ("Count revision record reviewed", decision["reviewed_revision_id"]),
                ("Reviewing supervisor ID", decision["actor_id"]),
                ("Reason for accepting the difference", reason),
                ("Frozen expected quantity", 10), ("Actual observed quantity", 8),
                ("Actual minus expected difference", -2),
            ))
            require_source(rows, (
                ("Source", "Physical comparison"), ("Counting scope ID", scope_id),
                ("Round ID", frozen_count["id"]),
                ("Comparison source", "Approved-turnout-derived estimate"),
            ), (
                ("Comparison data available", "No"),
                ("Comparison status", "Unavailable; source quantity was not recorded"),
                ("Frozen expected quantity", "Not recorded"),
                ("Actual observed quantity", 8),
                ("Actual minus expected difference", "Not recorded"),
            ))
            for result in event["outcome"]["results"]:
                for candidate in result["candidate_totals"]:
                    assert any(
                        row[:3] == [str(candidate["candidate_id"]), candidate["name"],
                                    str(candidate["quantity"])] for row in rows
                    ), (candidate, rows)
        assert BOX_READY_PASSWORD not in after_response.content.decode("utf-8-sig")
        assert original["request_id"] not in after_response.content.decode("utf-8-sig")
