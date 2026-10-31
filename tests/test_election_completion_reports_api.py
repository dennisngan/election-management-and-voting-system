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
