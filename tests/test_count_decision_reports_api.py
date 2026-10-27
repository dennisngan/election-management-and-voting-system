"""Decision and correction context remains distinct in localized count statements."""

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


@pytest.mark.parametrize(
    ("locale", "accepted_status", "pending_status", "approved_heading"),
    [
        ("tc", "已接納", "差額待覆核", "批准時已審閱的實際差額決定"),
        ("sc", "已接纳", "差额待复核", "批准时已审阅的实际差额决定"),
        ("en", "Accepted", "Difference pending review", "Physical decision approved at review"),
    ],
)
def test_count_statement_keeps_live_decision_validity_separate_from_frozen_approval(
    admin: TestClient,
    database_url: str,
    locale: str,
    accepted_status: str,
    pending_status: str,
    approved_heading: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, rounds_path = setup["counter"], setup["rounds_path"]
        options = counter.get(rounds_path).json()
        f1_command = complete_f1_command(options, actual_counted_quantity=3)
        f1_command["candidate_votes"][0]["quantity"] = 3
        f1 = counter.post(rounds_path, json=f1_command)
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        target = rounds_path + f"/{round_id}"

        f2 = counter.put(target + "/f2", json=complete_f2_command(options))
        assert f2.status_code == 200, f2.text
        submitted = counter.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text

        decision_command = {
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
            "expected_decision_revision": 0,
            "password": READY_PASSWORD,
            "reason": "Checked the observed papers against the signed stock record.",
        }
        supervisor = setup["clients"]["supervisor"]
        decision = supervisor.post(
            target + "/physical-differences/stock/accept", json=decision_command
        )
        assert decision.status_code == 200, decision.text
        original_decision = decision.json()["physical_decisions"][0]

        approval = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approval.status_code == 200, approval.text
        assert approval.json()["revision"] == 4

        # A reasoned successor to the contributing P(18) makes the old count basis stale.
        p18 = setup["accounting"]["N1"]
        revised_p18 = setup["clients"]["bothcounting"].put(
            p18["path"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": p18["special_papers"]["id"],
                "special_paper_revision": p18["special_papers"]["revision"],
                "notes": "Rechecked the original accounting papers.",
                "amendment_reason": "Correct the recorded P(18) note after paper review.",
            },
        )
        assert revised_p18.status_code == 200, revised_p18.text
        assert revised_p18.json()["revision"] == 2

        base = f"{target}/revisions/4"
        report = None
        for form in ("f2", "f3", "f4", "count"):
            count_report = supervisor.get(base + f"/{form}", params={"locale": locale})
            assert count_report.status_code == 200, count_report.text
            form_report = count_report.json()
            if form == "count":
                report = form_report
            assert any(
                table["title"] == approved_heading + " · " + form_report["labels"]["source_stock"]
                for table in form_report["tables"]
            )
        assert report is not None
        record = report["record"]
        assert record["source_current"] is False
        live = next(row for row in record["physical_decisions"] if row["source"] == "stock")
        assert live["id"] == original_decision["id"]
        assert live["valid"] is False
        frozen = next(
            row for row in record["approved_physical_decisions"] if row["source"] == "stock"
        )
        assert frozen["id"] == original_decision["id"]
        assert frozen["valid"] is True
        assert frozen["reason"] == decision_command["reason"]
        assert frozen["reviewed_revision"] == 3
        assert frozen["expected_quantity"] == 5
        assert frozen["actual_quantity"] == 3
        assert frozen["difference_quantity"] == -2

        decision_table = next(
            table
            for table in report["tables"]
            if table["title"] == approved_heading + " · " + report["labels"]["source_stock"]
        )
        assert [
            report["labels"]["acceptance_reason"],
            decision_command["reason"],
        ] in decision_table["rows"]
        assert [report["labels"]["decision_validity"], report["labels"]["yes"]] in decision_table[
            "rows"
        ]
        live_decision_table = next(
            table
            for table in report["tables"]
            if table["title"]
            == report["labels"]["physical_decision_history"]
            + " · "
            + report["labels"]["source_stock"]
        )
        assert [report["labels"]["decision_validity"], report["labels"]["no"]] in (
            live_decision_table["rows"]
        )
        reviewed_comparison = next(
            table
            for table in report["tables"]
            if table["title"]
            == report["labels"]["physical_comparison_reviewed"]
            + " · "
            + report["labels"]["source_stock"]
        )
        assert [report["labels"]["comparison_status"], accepted_status] in reviewed_comparison[
            "rows"
        ]
        live_comparison = next(
            table
            for table in report["tables"]
            if table["title"]
            == report["labels"]["physical_comparisons"] + " · " + report["labels"]["source_stock"]
        )
        assert [report["labels"]["comparison_status"], pending_status] in live_comparison["rows"]

        f1_statement = supervisor.get(base + "/statement", params={"locale": locale})
        assert f1_statement.status_code == 200, f1_statement.text
        statement = f1_statement.json()
        assert READY_PASSWORD not in str(statement)
        assert any(
            table["title"].startswith(statement["labels"]["physical_decision_history"])
            for table in statement["tables"]
        )
        csv_report = supervisor.get(base + "/count.csv", params={"locale": locale})
        assert csv_report.status_code == 200, csv_report.text
        assert decision_command["reason"] in csv_report.content.decode("utf-8-sig")
        assert READY_PASSWORD not in csv_report.content.decode("utf-8-sig")
        pdf_report = supervisor.get(base + "/count.pdf", params={"locale": locale})
        assert pdf_report.status_code == 200, pdf_report.text
        pdf_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(pdf_report.content)).pages
        )
        assert decision_command["reason"] in pdf_text
        assert approved_heading in pdf_text
        assert READY_PASSWORD not in pdf_text
        f1_csv = supervisor.get(base + "/statement.csv", params={"locale": locale})
        assert f1_csv.status_code == 200, f1_csv.text
        assert decision_command["reason"] in f1_csv.content.decode("utf-8-sig")
        assert READY_PASSWORD not in f1_csv.content.decode("utf-8-sig")
