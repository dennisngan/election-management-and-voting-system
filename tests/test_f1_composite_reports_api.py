"""F1 statement compatibility for composite count-round revisions."""

import csv
from io import BytesIO, StringIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_f1_statement_on_incomplete_f2_revision_uses_original_f1_observation(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1_command = complete_f1_command(
            options,
            questionable_quantity=3,
            actual_counted_quantity=5,
            notes="Original F1 observation note",
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        f1_response = client.post(path, json=f1_command)
        assert f1_response.status_code == 201, f1_response.text
        f1 = f1_response.json()

        f2_command = complete_f2_command(
            options,
            determination_started_at="2026-11-15T23:18:12.123456+08:00",
            accepted_votes=[],
            rejected_papers=[],
            notes="F2 determination remains incomplete",
        )
        f2_response = client.put(path + f"/{f1['id']}/f2", json=f2_command)
        assert f2_response.status_code == 200, f2_response.text
        composite = f2_response.json()
        assert composite["revision"] == 2 and composite["f2_complete"] is False
        assert composite["status"] == "draft"

        statement_path = path + f"/{f1['id']}/revisions/2/statement"
        response = client.get(statement_path, params={"locale": "en"})
        assert response.status_code == 200, response.text
        report = response.json()
        record = report["record"]
        assert record["status"] == "draft"
        assert record["f1_complete"] is True
        assert record["event_at"] == f1["event_at"]
        assert record["entered_at"] == f1["entered_at"]
        assert record["actor_id"] == f1["actor_id"]
        assert record["notes"] == "Original F1 observation note"
        assert record["amendment_reason"] == f1["amendment_reason"]
        assert record["revision_notes"] == "F2 determination remains incomplete"

        preview = "\n".join(report["preview_lines"])
        assert "Initial valid votes · 2" in preview
        assert "F2 candidate quantity unobserved" not in preview
        assert "F2 invalid-reason quantity unobserved" not in preview
        assert "Original F1 observation note" in preview
        assert "F2 determination remains incomplete" not in preview
        assert ["Record status", "Draft"] in report["tables"][0]["rows"]
        assert [
            "Report basis",
            "This section shows the F1 observation portion of the count record.",
        ] in report["tables"][0]["rows"]

        csv_response = client.get(statement_path + ".csv", params={"locale": "en"})
        assert csv_response.status_code == 200
        csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert ["Record status", "Draft"] in csv_rows
        assert [
            "Report basis",
            "This section shows the F1 observation portion of the count record.",
        ] in csv_rows
        assert ["Notes", "Original F1 observation note"] in csv_rows
        assert ["Notes", "F2 determination remains incomplete"] not in csv_rows

        pdf_response = client.get(statement_path + ".pdf", params={"locale": "en"})
        assert pdf_response.status_code == 200
        pdf_text = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(pdf_response.content)).pages
        )
        assert "Record status" in pdf_text and "Draft" in pdf_text
        assert "F1 observation portion of the count record" in pdf_text
        assert "Original F1 observation note" in pdf_text
        assert "F2 determination remains incomplete" not in pdf_text
