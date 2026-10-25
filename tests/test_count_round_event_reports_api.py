"""Public box statements retain round-event provenance without station completion."""

import csv
from io import BytesIO, StringIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.tally_support import tally_setup
from tests.test_count_round_events_desktop import (
    complete_selected_round,
)
from tests.test_count_round_events_desktop import (
    database_url as database_url,
)
from tests.test_count_round_events_desktop import (
    private_active_pointer as private_active_pointer,
)


@pytest.mark.parametrize(
    (
        "locale",
        "title",
        "kind",
        "scope_label",
        "origin_label",
        "current_label",
        "status",
        "selected",
        "historical",
        "scalar_caption",
    ),
    [
        (
            "tc",
            "點票輪次工作事件",
            "輪次點票完成",
            "點票範圍編號",
            "事件來源點票版本記錄編號",
            "目前點票版本記錄編號",
            "已核准",
            "已明確選定",
            "歷史事件",
            "點票完成時間",
        ),
        (
            "sc",
            "点票轮次工作事件",
            "轮次点票完成",
            "点票范围编号",
            "事件来源点票版本记录编号",
            "当前点票版本记录编号",
            "已核准",
            "已明确选定",
            "历史事件",
            "点票完成时间",
        ),
        (
            "en",
            "Count round workflow events",
            "Round counting completed",
            "Counting scope ID",
            "Origin count revision record ID",
            "Current count revision record ID",
            "Approved",
            "Explicitly selected",
            "Historical occurrence",
            "Count completion time",
        ),
    ],
    ids=["tc", "sc", "en"],
)
def test_box_statement_exports_round_occurrences_with_exact_revision_and_time_provenance(
    admin: TestClient,
    database_url: str,
    locale: str,
    title: str,
    kind: str,
    scope_label: str,
    origin_label: str,
    current_label: str,
    status: str,
    selected: str,
    historical: str,
    scalar_caption: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        setup["clock"].value = setup["clock"].value.replace(microsecond=987654)
        saved = complete_selected_round(setup)
        api = setup["counter"]
        path = f"/api/workspace/stations/{setup['stations']['N1']['id']}/boxes/statement"
        response = api.get(path, params={"locale": locale})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["count_completion"] is None
        assert len(report["count_events"]) == 3
        preview = "\n".join(report["preview_lines"])
        assert title in preview
        assert scalar_caption + ":" not in preview
        assert (
            kind in preview and status in preview and selected in preview and historical in preview
        )
        csv_response = api.get(path + ".csv", params={"locale": locale})
        assert csv_response.status_code == 200, csv_response.text
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert [scope_label, str(setup["scope"]["id"])] in rows
        assert rows.count([scope_label, str(setup["scope"]["id"])]) == 3
        assert [origin_label, str(saved["submitted"]["revision_id"])] in rows
        assert [current_label, str(saved["approved"]["revision_id"])] in rows
        assert [origin_label, str(saved["first"]["revision_id"])] in rows
        assert [origin_label, str(saved["corrected"]["revision_id"])] in rows
        assert not any(row and row[0] == scalar_caption for row in rows)
        for precise_time in (
            "2026-11-15 23:18:12.123456 HKT",
            "2026-11-15 23:19:00.654321 HKT",
            "2026-11-16 00:00:00.987654 HKT",
        ):
            assert any(precise_time in row for row in rows)
        assert any("核對紙本 <original> & corrected\nprecise source time" in row for row in rows)
        pdf_response = api.get(path + ".pdf", params={"locale": locale})
        assert pdf_response.status_code == 200, pdf_response.text
        reader = PdfReader(BytesIO(pdf_response.content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert all(page.extract_text().strip() for page in reader.pages)
        for literal in (
            title,
            kind,
            origin_label,
            current_label,
            status,
            selected,
            historical,
            "2026-11-15 23:18:12.123456 HKT",
            "2026-11-15 23:19:00.654321 HKT",
        ):
            assert literal in text
