"""Application-outage report reads use the normal assigned-station API boundary."""

import csv
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
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
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    with turnout_staff(admin, database_url, TurnoutClock(), [station_id]) as (officer, _):
        response = officer.get(f"/api/workspace/stations/{station_id}/outages/2147483647/statement")

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "outage_not_found"


def test_outage_reports_preserve_localized_receipts_and_invalidated_reconciliation(
    admin: TestClient,
    database_url: str,
    tmp_path: Path,
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
        before_statement = officer.get(outage_record_path + "/statement")
        assert before_statement.status_code == 200, before_statement.text
        reviewed_report_basis = before_statement.json().get("basis_digest", "")


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

        # A new paper invalidates the newest decision; it does not create a successor.
        current_response = officer.get(outage_record_path)
        assert current_response.status_code == 200, current_response.text
        current = current_response.json()["record"]
        assert current["reconciled"] is False
        assert len(current["reconciliation_history"]) == 1
        decision = current["reconciliation_history"][0]
        assert decision["revision"] == old_decision_revision
        assert decision["is_current"] is True
        assert decision["valid"] is False
        assert [entry["paper_id"] for entry in decision["basis"]["paper_entries"]] == [paper_id]
        assert [entry["request_id"] for entry in decision["basis"]["paper_entries"]] == [
            submission_request_id
        ]

        statement_path = outage_record_path + "/statement"
        for extension in ("", ".csv", ".pdf"):
            stale_export = officer.get(
                statement_path + extension,
                params={"locale": "en", "expected_basis": reviewed_report_basis},
            )
            assert stale_export.status_code == 409, stale_export.text
            assert stale_export.json()["detail"]["code"] == "outage_revision_conflict"

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
            row[1] == pending_reference and row[7] == "Pending re-entry" for row in paper_rows[1:]
        )
        assert any(row[-1] == submission_request_id for row in paper_rows[1:])
        reconciliation_rows = en_sections["Reconciliation decision history"]
        assert any(
            row[0] == str(old_decision_revision) and row[1] == "Yes" and row[2] == "Needs review"
            for row in reconciliation_rows[1:]
        )

        csv_response = officer.get(statement_path + ".csv", params={"locale": "en"})
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
        (tmp_path / "outage-report-en.pdf").write_bytes(pdf_response.content)
        (tmp_path / "outage-report-en.csv").write_bytes(csv_response.content)
        (tmp_path / "expected-references.txt").write_text(
            "\n".join((outage_reference, paper_reference, pending_reference, submission_request_id))
        )
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


def _link_original_count_receipt(setup: dict) -> dict:
    officer = setup["counter"]
    rounds_path = setup["rounds_path"]
    options = officer.get(rounds_path).json()
    initial = officer.post(rounds_path, json=complete_f1_command(options))
    assert initial.status_code == 201, initial.text
    round_path = rounds_path + f"/{initial.json()['id']}"
    f2 = officer.put(round_path + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    setup["clock"].value = datetime(2026, 11, 15, 16, 0, 0, 123456, tzinfo=UTC)
    original_request_id = str(uuid4())
    submitted = officer.post(
        round_path + "/submit",
        json={
            "request_id": original_request_id,
            "expected_revision": f2.json()["revision"],
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    original_record = submitted.json()
    station_id = setup["stations"]["N1"]["id"]
    outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{original_request_id}"
    original_outcome = officer.get(outcome_path, params={"workflow": "count"})
    assert original_outcome.status_code == 200, original_outcome.text

    setup["clock"].value = datetime(2026, 11, 15, 16, 30, 0, 234567, tzinfo=UTC)
    outage_path = f"/api/workspace/stations/{station_id}/outages"
    outage = officer.post(
        outage_path,
        json={
            "request_id": str(uuid4()),
            "reference": "LATER-LINK-" + uuid4().hex[:10],
            "kind": "network",
            "started_at": "2026-11-15T23:00:00+08:00",
            "ended_at": "2026-11-15T23:30:00+08:00",
            "notes": "The count was committed before its paper reference was registered.",
        },
    )
    assert outage.status_code == 201, outage.text
    record_path = outage_path + f"/{outage.json()['id']}"
    paper = officer.post(
        record_path + "/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": "LATER-COUNT-" + uuid4().hex[:10],
            "workflow": "count",
            "action": "submit",
            "original_event_at": "2026-11-15T23:25:33.123456+08:00",
            "target": {"scope_id": setup["scope"]["id"], "round_id": original_record["id"]},
            "notes": "Preserve the signed original return beside its existing receipt.",
        },
    )
    assert paper.status_code == 201, paper.text
    paper_path = record_path + f"/paper-records/{paper.json()['id']}"
    checked = officer.get(paper_path + "/receipt", params={"request_id": original_request_id})
    assert checked.status_code == 200, checked.text
    link_request_id = str(uuid4())
    reason = "Compared the signed original return with the committed count."
    setup["clock"].value = datetime(2026, 11, 15, 16, 45, 0, 345678, tzinfo=UTC)
    linked = officer.post(
        paper_path + "/link-receipt",
        json={
            "request_id": link_request_id,
            "expected_outage_revision": 1,
            "expected_paper_revision": 1,
            "original_request_id": original_request_id,
            "expected_receipt_digest": checked.json()["receipt_digest"],
            "reason": reason,
        },
    )
    assert linked.status_code == 200, linked.text
    reentry = linked.json()["reentry"]
    assert reentry["request_id"] == original_request_id
    assert reentry["record"] == original_record
    assert reentry["link"] == {
        "request_id": link_request_id,
        "reason": reason,
        "actor_id": original_record["actor_id"],
        "linked_at": "2026-11-15T16:45:00.345678Z",
        "receipt_digest": checked.json()["receipt_digest"],
    }
    outcome_after = officer.get(outcome_path, params={"workflow": "count"})
    assert outcome_after.status_code == 200, outcome_after.text
    assert outcome_after.json() == original_outcome.json()
    return {
        "record_path": record_path,
        "original_request_id": original_request_id,
        "original_record": original_record,
        "link": reentry["link"],
    }


def test_outage_preview_separates_later_link_metadata_from_the_original_receipt(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        linked = _link_original_count_receipt(setup)
        statement = setup["counter"].get(
            linked["record_path"] + "/statement", params={"locale": "en"},
        )
        assert statement.status_code == 200, statement.text
        rows = next(
            section["rows"] for section in statement.json()["sections"]
            if section["title"] == "Immutable receipt details"
        )
        assert ["Re-entry request ID", linked["original_request_id"]] in rows
        assert ["Original business record status", "Submitted"] in rows
        assert ["Later receipt link request ID", linked["link"]["request_id"]] in rows
        assert ["Later receipt link reason", linked["link"]["reason"]] in rows
        assert ["Later receipt link account ID", str(linked["link"]["actor_id"])] in rows
        assert [
            "Later receipt link time (Hong Kong time)", "2026-11-16 00:45:00.345678 HKT",
        ] in rows
        assert ["Linked original receipt fingerprint", linked["link"]["receipt_digest"]] in rows
