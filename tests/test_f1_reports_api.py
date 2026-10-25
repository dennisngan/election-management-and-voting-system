"""F1 draft statements retain exact observations and frozen scope provenance."""

import csv
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


@pytest.mark.parametrize(
    ("locale", "title"),
    [
        ("en", "F1 initial tally"),
        ("tc", "F1 初步點票"),
        ("sc", "F1 初步点票"),
    ],
)
def test_f1_exports_exact_initial_observations_with_scope_round_and_reason_provenance(
    admin: TestClient,
    database_url: str,
    locale: str,
    title: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        saved = client.post(
            path,
            json=complete_f1_command(
                options,
                questionable_quantity=3,
                actual_counted_quantity=3,
                notes="F1 核對第一行。\n第二行：保留問題選票及原始來源。",
            ),
        )
        assert saved.status_code == 201, saved.text
        record = saved.json()
        target = path + f"/{record['id']}/revisions/1/statement"
        response = client.get(target, params={"locale": locale})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["record"] == record
        assert report["scope_id"] == setup["scope"]["id"]
        assert report["round_id"] == record["id"] and report["revision"] == 1
        assert report["locale"] == locale and report["preview_lines"][0] == title
        preview = "\n".join(report["preview_lines"])
        for expected in (
            setup["scope"]["reference"],
            setup["boxes"]["local_n1"]["box_reference"],
            "2026-11-15 23:15:12.123456 HKT",
            "F1 核對第一行。",
            "第二行：保留問題選票及原始來源。",
            "Endorsed with the words “重複” and “TENDERED”",
            "gc-f1-a",
        ):
            assert expected in preview
        assert report["record"]["questionable_quantity"] == 3
        assert report["record"]["actual_counted_quantity"] == 3
        assert report["record"]["initial_valid_quantity"] == 0
        assert report["record"]["clearly_invalid_quantity"] == 0
        csv_response = client.get(target + ".csv", params={"locale": locale})
        assert csv_response.status_code == 200
        assert csv_response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert rows[0] == [title]
        assert [report["labels"]["questionable_quantity"], "3"] in rows
        assert [report["labels"]["initial_valid_quantity"], "0"] in rows
        pdf = client.get(target + ".pdf", params={"locale": locale})
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        pages = PdfReader(BytesIO(pdf.content)).pages
        assert pages
        text = "\n".join(page.extract_text() for page in pages)
        for expected in (
            title,
            setup["scope"]["reference"],
            "gc-f1-a",
            "2026-11-15 23:15:12.123456 HKT",
            "F1 核對第一行。",
        ):
            assert expected in text
        assert client.get(target, params={"locale": "unsupported"}).status_code == 422
        assert admin.get(target).status_code == 403


def test_f1_report_distinguishes_missing_zero_and_exact_twenty_digit_observations(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        saved = client.post(
            path,
            json=complete_f1_command(
                options,
                questionable_quantity=None,
                actual_counted_quantity=None,
            ),
        )
        assert saved.status_code == 201
        round_id = saved.json()["id"]
        target = path + f"/{round_id}/revisions/1/statement"
        report = client.get(target, params={"locale": "en"}).json()
        assert report["record"]["initial_valid_quantity"] == 0
        assert report["record"]["actual_counted_quantity"] is None
        assert "Initial valid votes · 0" in report["preview_lines"]
        assert "Actual counted papers · Not recorded" in report["preview_lines"]
        csv_response = client.get(target + ".csv", params={"locale": "en"})
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert ["Initial valid votes", "0"] in rows
        assert ["Actual counted papers", "Not recorded"] in rows
        pdf = client.get(target + ".pdf", params={"locale": "en"})
        assert pdf.status_code == 200
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "Actual counted papers" in text and "Not recorded" in text
        huge = 19999999999999999989
        command = complete_f1_command(
            options,
            expected_revision=1,
            questionable_quantity=3,
            actual_counted_quantity=19999999999999999992,
        )
        command["candidate_votes"][0]["quantity"] = huge
        amended = client.put(path + f"/{round_id}", json=command)
        assert amended.status_code == 200, amended.text
        assert amended.json()["f1_complete"] is True
        target = path + f"/{round_id}/revisions/2/statement"
        current = client.get(target, params={"locale": "en"}).json()
        assert "Initial valid votes · 19999999999999999989" in current["preview_lines"]
        assert "Actual counted papers · 19999999999999999992" in current["preview_lines"]
        assert current["record"]["initial_accounted_quantity"] == 19999999999999999992
        csv_response = client.get(target + ".csv", params={"locale": "en"})
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert ["Initial valid votes", "19999999999999999989"] in rows
        assert ["Actual counted papers", "19999999999999999992"] in rows
        pdf = client.get(target + ".pdf", params={"locale": "en"})
        assert pdf.status_code == 200
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "19999999999999999989" in text and "19999999999999999992" in text
        historical = client.get(path + f"/{round_id}/revisions/1/statement").json()
        assert historical["record"]["is_current"] is False
        assert historical["record"]["actual_counted_quantity"] is None


def test_reason_display_edits_preserve_frozen_f1_wording_and_reject_stale_catalog_input(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        reason = options["invalid_reasons"][0]
        command = complete_f1_command(options)
        saved = client.post(path, json=command)
        assert saved.status_code == 201
        round_id = saved.json()["id"]
        target = path + f"/{round_id}/revisions/1/statement"
        catalog_target = (
            f"/api/elections/{setup['election']['id']}/invalid-ballot-reasons/{reason['id']}"
        )
        changed = admin.put(
            catalog_target,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "label_en": "Reviewed project display label",
                "label_tc": "已核對的專案顯示標籤",
                "label_sc": "已核对的项目显示标签",
                "enabled": True,
                "explanation_required": False,
            },
        )
        assert changed.status_code == 200, changed.text
        before = client.get(target, params={"locale": "en"}).json()
        frozen = before["record"]["invalid_papers"][0]
        assert frozen["label_en"] == reason["label_en"]
        assert frozen["reason_revision"] == 1
        assert frozen["source_english"] == reason["source_english"]
        assert "Reviewed project display label" not in "\n".join(before["preview_lines"])
        command.update(request_id=str(uuid4()), expected_revision=1)
        conflict = client.put(path + f"/{round_id}", json=command)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "invalid_reason_revision_conflict"
        assert client.get(path + f"/{round_id}").json()["record"]["revision"] == 1
        current_options = client.get(path).json()
        amended = client.put(
            path + f"/{round_id}",
            json=complete_f1_command(
                current_options,
                expected_revision=1,
            ),
        )
        assert amended.status_code == 200, amended.text
        current = client.get(path + f"/{round_id}/revisions/2/statement", params={"locale": "en"})
        assert current.status_code == 200
        current_reason = current.json()["record"]["invalid_papers"][0]
        assert current_reason["label_en"] == "Reviewed project display label"
        assert current_reason["reason_revision"] == 2
        assert current_reason["source_english"] == reason["source_english"]
        old_csv = client.get(target + ".csv", params={"locale": "en"})
        assert b"Reviewed project display label" not in old_csv.content
        old_pdf = client.get(target + ".pdf", params={"locale": "en"})
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(old_pdf.content)).pages)
        assert "Reviewed project display label" not in text
        assert reason["source_english"] in text
