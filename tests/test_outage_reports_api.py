"""Application-outage report reads use the normal assigned-station API boundary."""

import csv
from datetime import UTC, datetime
from io import BytesIO, StringIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_turnout_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_turnout_api import database_url as database_url
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


def test_missing_outage_statement_returns_the_assigned_api_not_found_dto(
    admin: TestClient, database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    with turnout_staff(admin, database_url, TurnoutClock(), [station_id]) as (officer, _):
        response = officer.get(
            f"/api/workspace/stations/{station_id}/outages/2147483647/statement"
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "outage_not_found"


def test_outage_reports_preserve_localized_receipts_and_invalidated_reconciliation(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        officer = setup["counter"]
        supervisor = setup["clients"]["supervisor"]
        supervisor_account = setup["accounts"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options = officer.get(rounds_path).json()

        initial = officer.post(rounds_path, json=complete_f1_command(options))
        assert initial.status_code == 201, initial.text
        round_id = initial.json()["id"]
        round_path = f"{rounds_path}/{round_id}"
        f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text

        setup["clock"].value = datetime(2026, 11, 15, 16, 0, 0, 654321, tzinfo=UTC)
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage_reference = "N1-OUTAGE-" + uuid4().hex[:8]
        outage = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": outage_reference,
                "kind": "network",
                "started_at": "2026-11-15T23:00:01.123456+08:00",
                "ended_at": "2026-11-15T23:30:02.654321+08:00",
                "notes": "Application connectivity was interrupted; signed paper was retained.",
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_record_path = f"{outage_path}/{outage_id}"
        paper_reference = "N1-PAPER-" + uuid4().hex[:8]
        paper = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": paper_reference,
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:25:33.123456+08:00",
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Signed count form retained during the interruption.",
            },
        )
        assert paper.status_code == 201, paper.text
        paper_id = paper.json()["id"]
        submission_request_id = str(uuid4())
        submitted = officer.post(
            round_path + "/submit",
            json={
                "request_id": submission_request_id,
                "expected_revision": f2.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "paper_record_id": paper_id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["candidate_votes"][0]["quantity"] == 0

        reconciled = supervisor.post(
            outage_record_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "expected_reconciliation_revision": 0,
                "paper_revisions": [{"paper_id": paper_id, "revision": 1}],
                "password": READY_PASSWORD,
                "reason": "Supervisor compared the signed zero count and server receipt.",
            },
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["record"]["reconciled"] is True
        old_decision_revision = reconciled.json()["record"]["reconciliation"]["revision"]

        pending_reference = "N1-PENDING-" + uuid4().hex[:8]
        pending = officer.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": reconciled.json()["record"]["revision"],
                "paper_reference": pending_reference,
                "workflow": "count",
                "action": "submit",
                "original_event_at": "2026-11-15T23:28:17.000001+08:00",
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Second sheet remains pending after the earlier reconciliation.",
            },
        )
        assert pending.status_code == 201, pending.text

        statement_path = outage_record_path + "/statement"
        localized_titles = {
            "tc": "應用程式連線中斷及紙本核對報表",
            "sc": "应用程序连接中断及纸本核对报表",
            "en": "Application connectivity outage and paper reconciliation statement",
        }
        localized_receipt_values = {
            "tc": {
                "section": "不可變更收據內容",
                "status_field": "原始業務記錄狀態",
                "submitted": "已提交",
                "round_field": "點票輪次",
                "record_id_field": "原始業務記錄編號",
            },
            "sc": {
                "section": "不可变更收据内容",
                "status_field": "原始业务记录状态",
                "submitted": "已提交",
                "round_field": "点票轮次",
                "record_id_field": "原始业务记录编号",
            },
            "en": {
                "section": "Immutable receipt details",
                "status_field": "Original business record status",
                "submitted": "Submitted",
                "round_field": "Round number",
                "record_id_field": "Original business record ID",
            },
        }
        reports = {}
        for locale, title in localized_titles.items():
            response = officer.get(statement_path, params={"locale": locale})
            assert response.status_code == 200, response.text
            report = response.json()
            reports[locale] = report
            assert report["title"] == title
            assert report["generation_timezone"] == "Asia/Hong_Kong"
            assert report["outage_id"] == outage_id and report["revision"] == 1
            assert READY_PASSWORD not in response.text
            assert "password" not in response.text.lower()
            assert "2026-11-15 23:00:01.123456 HKT" in response.text
            assert "2026-11-15 23:25:33.123456 HKT" in response.text
            assert "2026-11-16 00:00:00.654321 HKT" in response.text
            assert "N1-OUTAGE-" in response.text
            assert "N1-PAPER-" in response.text
            assert "N1-PENDING-" in response.text
            assert submission_request_id in response.text
            assert str(submitted.json()["id"]) in response.text
            assert str(submitted.json()["revision"]) in response.text
            assert str(supervisor_account["id"]) in response.text
            assert "0" in response.text
            assert str(old_decision_revision) in response.text
            assert "Supervisor compared" in response.text
            assert all(
                isinstance(section["rows"], list)
                and all(all(isinstance(cell, str) for cell in row) for row in section["rows"])
                for section in report["sections"]
            )
            assert "record" not in report and "history" not in report
            receipt_contract = localized_receipt_values[locale]
            receipt_rows = next(
                section["rows"]
                for section in report["sections"]
                if section["title"] == receipt_contract["section"]
            )
            assert [receipt_contract["status_field"], receipt_contract["submitted"]] in receipt_rows
            assert [
                receipt_contract["round_field"],
                str(submitted.json()["round_number"]),
            ] in receipt_rows
            assert [
                receipt_contract["record_id_field"],
                str(submitted.json()["id"]),
            ] in receipt_rows

        en_sections = {section["title"]: section["rows"] for section in reports["en"]["sections"]}
        paper_rows = en_sections["Paper references and re-entry status"]
        assert any(row[1] == paper_reference and row[7] == "Re-entered" for row in paper_rows[1:])
        assert any(
            row[1] == pending_reference and row[7] == "Pending re-entry"
            for row in paper_rows[1:]
        )
        assert any(row[-1] == submission_request_id for row in paper_rows[1:])
        reconciliation_rows = en_sections["Reconciliation decision history"]
        assert any(
            row[0] == str(old_decision_revision)
            and row[1] == "No"
            and row[2] == "Needs review"
            for row in reconciliation_rows[1:]
        )

        csv_response = officer.get(
            statement_path + ".csv", params={"locale": "en"}
        )
        assert csv_response.status_code == 200, csv_response.text
        assert csv_response.headers["content-type"].startswith("text/csv")
        csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        csv_text = "\n".join(" · ".join(row) for row in csv_rows)
        for expected in (
            outage_reference,
            paper_reference,
            pending_reference,
            submission_request_id,
            "2026-11-15 23:25:33.123456 HKT",
            "Questionable papers",
            "Not applicable",
            "0",
            "Supervisor compared the signed zero count",
        ):
            assert expected in csv_text
        assert READY_PASSWORD not in csv_text and "password" not in csv_text.lower()

        pdf_response = officer.get(statement_path + ".pdf", params={"locale": "en"})
        assert pdf_response.status_code == 200, pdf_response.text
        assert pdf_response.headers["content-type"] == "application/pdf"
        pdf = PdfReader(BytesIO(pdf_response.content))
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        assert page_texts and all(page_texts)
        pdf_text = " ".join(" ".join(text.split()) for text in page_texts)
        for expected in (
            outage_reference,
            paper_reference,
            pending_reference,
            submission_request_id,
            "2026-11-15 23:25:33.123456 HKT",
            "2026-11-16 00:00:00.654321 HKT",
            "Supervisor compared the signed zero count",
        ):
            assert expected in pdf_text
        assert READY_PASSWORD not in pdf_text and "password" not in pdf_text.lower()

        unassigned_station = setup["stations"]["N2"]["id"]
        forbidden = officer.get(
            f"/api/workspace/stations/{unassigned_station}/outages/{outage_id}/statement"
        )
        assert forbidden.status_code == 403, forbidden.text
        assert forbidden.json()["detail"]["code"] == "station_access_denied"
