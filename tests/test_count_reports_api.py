"""Selected-revision F2/F3/F4/count reports use the frozen count projection."""

import csv
from io import BytesIO, StringIO
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
    ("locale", "not_applicable"),
    [
        ("tc", "不適用"),
        ("sc", "不适用"),
        ("en", "Not applicable"),
    ],
)
def test_zero_questionable_count_reports_determination_start_not_applicable(
    admin: TestClient,
    database_url: str,
    locale: str,
    not_applicable: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = client.post(
            path,
            json=complete_f1_command(
                options,
                questionable_quantity=0,
                actual_counted_quantity=0,
            ),
        )
        assert f1.status_code == 201, f1.text
        f2 = client.put(
            path + f"/{f1.json()['id']}/f2",
            json=complete_f2_command(options, determination_started_at=None),
        )
        assert f2.status_code == 200, f2.text
        record = f2.json()
        assert record["f2_complete"] is True
        assert record["f2"]["determination_started_at"] is None

        report = client.get(
            path + f"/{f1.json()['id']}/revisions/2/f2",
            params={"locale": locale},
        )
        assert report.status_code == 200, report.text
        section = next(
            table for table in report.json()["tables"]
            if table["title"] == report.json()["labels"]["f2_section"]
        )
        assert [report.json()["labels"]["determination_started_at"], not_applicable] in section[
            "rows"
        ]


def test_f1_only_report_exposes_unobserved_f2_and_frozen_physical_comparisons(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=3,
        )
        command["candidate_votes"][0]["quantity"] = 3
        saved = client.post(path, json=command)
        assert saved.status_code == 201, saved.text

        statement_path = (
            path + f"/{saved.json()['id']}/revisions/1/statement"
        )
        response = client.get(statement_path, params={"locale": "en"})
        assert response.status_code == 200, response.text
        record = response.json()["record"]
        assert record["f2"] is None
        assert record["f2_complete"] is False
        assert record["count_inputs_complete"] is False
        assert record["count_complete"] is False
        comparisons = {row["source"]: row for row in record["physical_comparisons"]}
        assert comparisons["stock"]["expected_quantity"] == 5
        assert comparisons["stock"]["actual_quantity"] == 3
        assert comparisons["stock"]["difference_quantity"] == -2
        assert comparisons["stock"]["status"] == "pending"
        assert comparisons["turnout"]["expected_quantity"] is None
        assert comparisons["turnout"]["difference_quantity"] is None
        assert comparisons["turnout"]["status"] == "unavailable"


def test_count_report_route_reads_the_exact_composite_revision(
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
            notes="Original F1 observations",
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text

        f2_command = complete_f2_command(
            options,
            determination_started_at="2026-11-15T23:18:12.123456+08:00",
            notes="Completed F2 observations",
        )
        f2_command["accepted_votes"][0]["quantity"] = 2
        f2_reason = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        rejected = next(
            row for row in f2_command["rejected_papers"] if row["reason_id"] == f2_reason["id"]
        )
        rejected["quantity"] = 1
        f2 = client.put(path + f"/{f1.json()['id']}/f2", json=f2_command)
        assert f2.status_code == 200, f2.text
        assert f2.json()["revision"] == 2

        report_path = path + f"/{f1.json()['id']}/revisions/2/count"
        response = client.get(report_path, params={"locale": "en"})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["form"] == "count"
        assert report["revision"] == 2
        assert report["record"]["revision"] == 2
        assert report["record"]["status"] == "draft"
        assert report["record"]["f1_complete"] is True
        assert report["record"]["f2_complete"] is True
        assert report["record"]["final_candidate_votes"][0]["quantity"] == 4
        assert report["record"]["final_invalid_quantity"] == 1
        assert report["record"]["actual_counted_quantity"] == 5
        assert report["record"]["physical_comparisons"] == f2.json()["physical_comparisons"]
        assert report["record"]["f1_metadata"]["notes"] == "Original F1 observations"

        f2_report = client.get(
            path + f"/{f1.json()['id']}/revisions/2/f2", params={"locale": "en"}
        )
        assert f2_report.status_code == 200, f2_report.text
        assert f2_report.json()["record"] == report["record"]
        assert "F2 Questionable Paper Determination" in f2_report.json()["preview_lines"]
        assert "Completed F2 observations" in "\n".join(f2_report.json()["preview_lines"])
        f2_section = next(
            table
            for table in f2_report.json()["tables"]
            if table["title"] == "F2 Questionable Paper Determination"
        )
        assert ["Accepted questionable papers total", "2"] in f2_section["rows"]
        assert ["Rejected questionable papers total", "1"] in f2_section["rows"]

        f3_report = client.get(
            path + f"/{f1.json()['id']}/revisions/2/f3", params={"locale": "en"}
        )
        assert f3_report.status_code == 200, f3_report.text
        f3_text = "\n".join(f3_report.json()["preview_lines"])
        assert "F1 clearly invalid classification · gc-f1-a" in f3_text
        assert "F2 questionable-paper determination · gc-f2-k" in f3_text
        assert "Endorsed with the words “重複” and “TENDERED”" in f3_text
        assert "Void for uncertainty" in f3_text

        f4_report = client.get(
            path + f"/{f1.json()['id']}/revisions/2/f4", params={"locale": "en"}
        )
        assert f4_report.status_code == 200, f4_report.text
        f4_text = "\n".join(f4_report.json()["preview_lines"])
        assert "F1 initial valid votes · 2" in f4_text
        assert "Accepted questionable votes · 2" in f4_text
        assert "F4 final candidate votes · 4" in f4_text

        for locale in ("tc", "sc", "en"):
            for form in ("f2", "f3", "f4", "count"):
                localized = client.get(
                    path + f"/{f1.json()['id']}/revisions/2/{form}",
                    params={"locale": locale},
                )
                assert localized.status_code == 200, localized.text
                localized_report = localized.json()
                assert localized_report["locale"] == locale
                assert localized_report["title"] == localized_report["labels"][f"title_{form}"]
                assert localized_report["record"]["revision"] == 2
                if form in ("f2", "f3", "count"):
                    localized_text = "\n".join(localized_report["preview_lines"])
                    expected_label = f2_reason["label_" + locale]
                    assert expected_label in localized_text

        for form in ("f2", "f3", "f4", "count"):
            csv_response = client.get(
                path + f"/{f1.json()['id']}/revisions/2/{form}.csv",
                params={"locale": "en"},
            )
            assert csv_response.status_code == 200, csv_response.text
            assert csv_response.content.startswith(b"\xef\xbb\xbf")
            csv_rows = list(
                csv.reader(StringIO(csv_response.content.decode("utf-8-sig")))
            )
            if form in ("f2", "count"):
                assert ["Accepted questionable papers total", "2"] in csv_rows
                assert ["Rejected questionable papers total", "1"] in csv_rows
            pdf_response = client.get(
                path + f"/{f1.json()['id']}/revisions/2/{form}.pdf",
                params={"locale": "en"},
            )
            assert pdf_response.status_code == 200, pdf_response.text
            pdf_text = "\n".join(
                page.extract_text() for page in PdfReader(BytesIO(pdf_response.content)).pages
            )
            if form in ("f2", "f3", "count"):
                assert b"Void for uncertainty" in csv_response.content
                assert "Void for uncertainty" in pdf_text
            if form in ("f2", "count"):
                assert "Accepted questionable papers total" in pdf_text
                assert "Rejected questionable papers total" in pdf_text
            if form == "f4":
                assert "F4 final candidate votes" in pdf_text


def test_count_report_route_is_available_for_the_selected_revision(
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
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text
        f2 = client.put(
            path + f"/{f1.json()['id']}/f2",
            json=complete_f2_command(options, accepted_votes=[], rejected_papers=[]),
        )
        assert f2.status_code == 200, f2.text
        report_path = path + f"/{f1.json()['id']}/revisions/2/count"
        response = client.get(report_path, params={"locale": "en"})
        assert response.status_code == 200, response.text
        record = response.json()["record"]
        assert record["f2_complete"] is False
        assert record["f2"]["determination_started_at"] is None
        assert all(row["quantity"] is None for row in record["f2"]["accepted_votes"])
        assert all(row["quantity"] is None for row in record["f2"]["rejected_papers"])
        preview = "\n".join(response.json()["preview_lines"])
        assert "Candidate acceptance quantity is unobserved" in preview
        assert "Rejected-reason quantity is unobserved" in preview
        assert [
            response.json()["labels"]["determination_started_at"],
            response.json()["labels"]["not_recorded"],
        ] in next(
            table for table in response.json()["tables"]
            if table["title"] == response.json()["labels"]["f2_section"]
        )["rows"]


def test_count_report_preserves_submitted_approved_and_selected_revision_state(
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
            notes="Original count source figures",
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text

        f2_command = complete_f2_command(
            options,
            determination_started_at="2026-11-15T23:18:12.123456+08:00",
        )
        f2_command["accepted_votes"][0]["quantity"] = 2
        uncertainty = next(
            row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k"
        )
        next(
            row for row in f2_command["rejected_papers"]
            if row["reason_id"] == uncertainty["id"]
        )["quantity"] = 1
        f2 = client.put(path + f"/{f1.json()['id']}/f2", json=f2_command)
        assert f2.status_code == 200, f2.text

        round_id = f1.json()["id"]
        workflow_path = path + f"/{round_id}"
        scope_revision = setup["scope"]["revision"]
        submitted = client.post(
            workflow_path + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": scope_revision,
            },
        )
        assert submitted.status_code == 200, submitted.text
        supervisor = setup["clients"]["supervisor"]
        approved = supervisor.post(
            workflow_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": scope_revision,
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        selected = supervisor.post(
            workflow_path + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "scope_revision": scope_revision,
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert selected.status_code == 200, selected.text

        report_path = path + f"/{round_id}/revisions/4/count"
        response = supervisor.get(report_path, params={"locale": "en"})
        assert response.status_code == 200, response.text
        report = response.json()
        record = report["record"]
        assert record["status"] == "approved"
        assert record["approval_valid"] is True
        assert record["selected"] is True
        assert record["selection_valid"] is True
        assert record["selection"]["round_revision"] == 4
        assert record["selection"]["round_revision_id"] == record["revision_id"]
        assert record["reviewed_revision"] == 3
        assert record["completed_at"] == submitted.json()["completed_at"]
        assert record["f1_metadata"]["notes"] == "Original count source figures"
        preview = "\n".join(report["preview_lines"])
        assert "Count record status · Approved" in preview
        assert "No approved result has been explicitly selected" not in preview


def test_every_count_report_preserves_f1_f2_timing_and_origin_metadata(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        f1_command = complete_f1_command(
            options,
            event_at="2026-11-15T23:15:12.123456+08:00",
            questionable_quantity=3,
            actual_counted_quantity=5,
            notes="Original F1 observation notes",
            amendment_reason="Original F1 amendment context",
        )
        f1_command["candidate_votes"][0]["quantity"] = 2
        f1 = counter.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        round_path = path + f"/{round_id}"

        f2_command = complete_f2_command(
            options,
            event_at="2026-11-15T23:20:17.654321+08:00",
            determination_started_at="2026-11-15T23:19:00.654321+08:00",
            notes="Initial F2 observation notes",
        )
        f2_command["accepted_votes"][0]["quantity"] = 2
        uncertainty = next(
            row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k"
        )
        next(
            row for row in f2_command["rejected_papers"]
            if row["reason_id"] == uncertainty["id"]
        )["quantity"] = 1
        first_f2 = counter.put(round_path + "/f2", json=f2_command)
        assert first_f2.status_code == 200, first_f2.text
        assert first_f2.json()["revision"] == 2

        amended_f2 = complete_f2_command(
            options,
            expected_revision=2,
            event_at="2026-11-15T23:21:17.654321+08:00",
            determination_started_at="2026-11-15T23:18:30.123456+08:00",
            notes="Current F2 observation notes",
            amendment_reason="Corrected from the signed determination log",
        )
        amended_f2["accepted_votes"][0]["quantity"] = 2
        next(
            row for row in amended_f2["rejected_papers"]
            if row["reason_id"] == uncertainty["id"]
        )["quantity"] = 1
        saved_f2 = counter.put(round_path + "/f2", json=amended_f2)
        assert saved_f2.status_code == 200, saved_f2.text
        assert saved_f2.json()["revision"] == 3

        scope_revision = setup["scope"]["revision"]
        submitted = counter.post(
            round_path + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 3,
                "scope_revision": scope_revision,
            },
        )
        assert submitted.status_code == 200, submitted.text
        supervisor = setup["clients"]["supervisor"]
        approved = supervisor.post(
            round_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 4,
                "scope_revision": scope_revision,
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        selected = supervisor.post(
            round_path + "/select",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 5,
                "scope_revision": scope_revision,
                "expected_selection_revision": 0,
                "password": READY_PASSWORD,
            },
        )
        assert selected.status_code == 200, selected.text

        revision_path = path + f"/{round_id}/revisions/5"
        expected_event_at = "2026-11-15 23:21:17.654321 HKT"
        expected_start_at = "2026-11-15 23:18:30.123456 HKT"
        for locale in ("tc", "sc", "en"):
            for form in ("f2", "f3", "f4", "count"):
                response = supervisor.get(
                    revision_path + f"/{form}", params={"locale": locale}
                )
                assert response.status_code == 200, response.text
                report = response.json()
                record, labels = report["record"], report["labels"]
                assert record["status"] == "approved"
                assert record["selected"] is True
                assert record["selection"]["round_revision"] == 5

                metadata = report["metadata"]
                assert [labels["f1_event_at"], "2026-11-15 23:15:12.123456 HKT"] in metadata
                assert [labels["f1_notes"], "Original F1 observation notes"] in metadata
                assert [labels["f1_amendment_reason"], "Original F1 amendment context"] in metadata
                assert any(
                    row[0] == labels["f1_entered_at"] and row[1] != labels["not_recorded"]
                    for row in metadata
                )
                assert any(
                    row[0] == labels["f1_actor_id"] and row[1] != labels["not_recorded"]
                    for row in metadata
                )

                event_title = {
                    "tc": "F2 判定事件紀錄",
                    "sc": "F2 判定事件记录",
                    "en": "F2 Determination Event Record",
                }[locale]
                expected_f2_title = (
                    event_title if form in ("f3", "f4") else labels["f2_section"]
                )
                f2_sections = [
                    table for table in report["tables"]
                    if table["title"] == expected_f2_title
                ]
                assert len(f2_sections) == 1, (
                    f"{locale}/{form}: expected one F2 metadata section, got "
                    f"{[table['title'] for table in report['tables']]}"
                )
                f2_rows = f2_sections[0]["rows"]
                assert [labels["f2_event_at"], expected_event_at] in f2_rows
                assert [labels["f2_notes"], "Current F2 observation notes"] in f2_rows
                assert [
                    labels["f2_amendment_reason"],
                    "Corrected from the signed determination log",
                ] in f2_rows
                assert any(
                    row[0] == labels["f2_entered_at"] and row[1] != labels["not_recorded"]
                    for row in f2_rows
                )
                assert [labels["f2_actor_id"], str(record["f2"]["actor_id"])] in f2_rows
                assert [labels["determination_started_at"], expected_start_at] in f2_rows

                if form in ("f3", "f4"):
                    assert not any(
                        table["title"] == labels["f2_section"] for table in report["tables"]
                    )
                    assert not any(
                        row[0] in {
                            labels["accepted_questionable_quantity"],
                            labels["rejected_questionable_quantity"],
                        }
                        for row in f2_rows
                    )

                origin_sections = [
                    table for table in report["tables"]
                    if table["title"] == labels["determination_event"]
                ]
                assert len(origin_sections) == 1
                assert [labels["origin_revision"], "3"] in origin_sections[0]["rows"]
                assert [labels["f2_event_at"], expected_start_at] in origin_sections[0]["rows"]

                csv_response = supervisor.get(
                    revision_path + f"/{form}.csv", params={"locale": locale}
                )
                assert csv_response.status_code == 200, csv_response.text
                csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
                assert [labels["f2_event_at"], expected_event_at] in csv_rows
                assert [labels["f2_notes"], "Current F2 observation notes"] in csv_rows
                assert [
                    labels["f2_amendment_reason"],
                    "Corrected from the signed determination log",
                ] in csv_rows
                assert [labels["determination_started_at"], expected_start_at] in csv_rows
                assert [labels["origin_revision"], "3"] in csv_rows

                pdf_response = supervisor.get(
                    revision_path + f"/{form}.pdf", params={"locale": locale}
                )
                assert pdf_response.status_code == 200, pdf_response.text
                pdf_text = "\n".join(
                    page.extract_text()
                    for page in PdfReader(BytesIO(pdf_response.content)).pages
                )
                assert labels["f2_event_at"] in pdf_text
                assert expected_event_at in pdf_text
                assert labels["f2_notes"] in pdf_text
                assert "Current F2 observation notes" in pdf_text
                assert labels["f2_amendment_reason"] in pdf_text
                assert "Corrected from the signed determination log" in pdf_text
                assert labels["determination_started_at"] in pdf_text
                assert expected_start_at in pdf_text
                assert labels["origin_revision"] in pdf_text
