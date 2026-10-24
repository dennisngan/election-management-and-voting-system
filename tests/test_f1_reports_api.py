"""F1 draft statements retain exact observations and frozen scope provenance."""

import csv
from io import BytesIO, StringIO

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
