"""Localized constituency-result statements use the public result API."""

from collections.abc import Iterator
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import result_setup
from tests.test_constituency_tie_api import _save_tie_round, complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_statement_endpoint_reads_a_complete_public_result(
    admin: TestClient, database_url: str
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results/statement"
        statement = setup["clients"]["supervisor"].get(path)
        assert statement.status_code == 200, statement.text
        record = statement.json()["result"]
        assert record["complete"] is True and record["provisional"] is True
        assert record["tie_candidate_ids"] == [
            row["candidate_id"] for row in record["candidate_totals"]
        ]
        assert [row["quantity"] for row in record["candidate_totals"]] == [0, 0]
        assert len(record["contributions"]) == 2
        assert all(row["frozen_source_context"] for row in record["contributions"])
        labels = statement.json()["labels"]
        accounting_tables = [
            table
            for table in statement.json()["tables"]
            if table["title"] == labels["accounting_source"]
        ]
        accounting_rows = [row for table in accounting_tables for row in table["rows"][1:]]
        source_records = [
            source_record
            for contribution in record["contributions"]
            for source_record in contribution["frozen_source_context"]["accounting_basis"]
        ]
        assert source_records
        for source_record in source_records:
            expected_status = labels.get(source_record["status"], source_record["status"])
            assert any(
                row[1] == str(source_record["id"])
                and row[2] == str(source_record["revision"])
                and row[3] == expected_status
                for row in accounting_rows
            )
        for locale, title in (
            ("tc", "選區選舉結果報表"),
            ("sc", "选区选举结果报表"),
            ("en", "Constituency Election Results"),
        ):
            localized = setup["clients"]["supervisor"].get(path, params={"locale": locale})
            assert localized.status_code == 200
            assert localized.json()["title"] == title


def test_partial_result_statement_keeps_zero_distinct_from_missing(
    admin: TestClient, database_url: str
) -> None:
    with result_setup(admin, database_url) as setup:
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        source = setup["clients"]["supervisor"].get(path)
        statement = setup["clients"]["supervisor"].get(path + "/statement", params={"locale": "en"})
        assert source.status_code == statement.status_code == 200
        result = statement.json()["result"]
        assert result["complete"] is False
        assert result["pending"]
        assert any(row["quantity"] is None for row in result["candidate_totals"])
        assert any(row["code"] == "selected_count_missing" for row in result["pending"])
        assert statement.json()["locale"] == "en"


def test_tie_resolution_reason_and_history_are_in_both_exports(
    admin: TestClient, database_url: str
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(base).json()
        reason = "Supervisor reviewed the signed tie record and selected the recorded candidate."
        resolved = supervisor.post(
            base + "/tie-resolutions",
            json={
                "request_id": str(uuid4()),
                "expected_resolution_revision": 0,
                "basis_digest": before["basis_digest"],
                "candidate_id": before["tie_candidate_ids"][0],
                "reason": reason,
                "password": READY_PASSWORD,
            },
        )
        assert resolved.status_code == 200, resolved.text
        statement = supervisor.get(base + "/statement", params={"locale": "en"})
        assert statement.status_code == 200, statement.text
        report = statement.json()["result"]
        assert report["resolved_candidate_id"] == before["tie_candidate_ids"][0]
        assert report["resolution_history"][0]["reason"] == reason
        assert report["resolution_history"][0]["valid"] is True
        csv_report = supervisor.get(base + "/statement.csv", params={"locale": "en"})
        pdf_report = supervisor.get(base + "/statement.pdf", params={"locale": "en"})
        assert csv_report.status_code == pdf_report.status_code == 200
        assert reason in csv_report.content.decode("utf-8-sig")
        pdf_text = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(pdf_report.content)).pages
        )
        assert reason in pdf_text
        assert READY_PASSWORD not in csv_report.content.decode("utf-8-sig")
        assert READY_PASSWORD not in pdf_text
