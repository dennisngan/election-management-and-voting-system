"""P(14) reports distinguish an exact saved revision from current station stock."""

import csv
from datetime import datetime
from io import BytesIO, StringIO

import pytest
from pypdf import PdfReader

from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


def test_selected_historical_report_does_not_mix_current_station_totals(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    original = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert original.status_code == 201
    changed = officer.put(
        path + f"/{original.json()['id']}",
        json=allocation_payload(
            setup["counter"]["id"],
            revision=1,
            serial_from="000002",
            serial_to="000005",
            reason="核對紙本派票範圍後更正",
        ),
    )
    assert changed.status_code == 200
    selected = officer.get(
        path + "/statement",
        params={"allocation_id": original.json()["id"], "revision": 1, "locale": "tc"},
    )
    assert selected.status_code == 200
    report = selected.json()
    assert report["title"] == "P(14) 發票櫃台選票派發紀錄"
    assert report["report_scope"] == "allocation_revision"
    assert report["allocation_id"] == original.json()["id"]
    assert report["revision"] == 1
    assert report["revision_state"] == "historical"
    assert report["items"] == [original.json()]
    assert report["availability"] is None
    assert report["scope"]["station"]["id"] == setup["station"]["id"]
    assert report["locale"] == "tc" and report["generation_timezone"] == "Asia/Hong_Kong"
    assert datetime.fromisoformat(report["generated_at"]).utcoffset() is not None
    current = officer.get(path + "/statement", params={"locale": "tc"})
    assert current.status_code == 200
    overview = current.json()
    assert overview["report_scope"] == "station_current"
    assert overview["allocation_id"] is None and overview["revision"] is None
    assert overview["revision_state"] == "current"
    assert overview["items"] == [changed.json()]
    assert overview["availability"][0]["allocated_quantity"] == 4
    assert overview["availability"][0]["available_quantity"] == 4
    assert [
        (row["serial_from"], row["serial_to"], row["quantity"])
        for row in overview["availability"][0]["ranges"]
    ] == [("000001", "000001", 1), ("000006", "000008", 3)]


def test_saved_revision_csv_and_preview_preserve_scope_counter_and_serials(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    saved = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert saved.status_code == 201
    allocation_id = saved.json()["id"]
    params = {"allocation_id": allocation_id, "revision": 1, "locale": "tc"}
    downloaded = officer.get(path + "/statement.csv", params=params)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/csv")
    assert f"p14-allocation-{allocation_id}-r1-tc.csv" in downloaded.headers["content-disposition"]
    assert downloaded.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(StringIO(downloaded.content.decode("utf-8-sig"))))
    assert rows[0] == ["P(14) 發票櫃台選票派發紀錄"]
    assert ["派票記錄編號", str(allocation_id)] in rows
    assert ["修訂版本", "1"] in rows
    assert ["發票櫃台", "C1 · 發票櫃台一"] in rows
    assert any(row[-3:] == ["000001", "000003", "3"] for row in rows)
    preview = officer.get(path + "/statement", params=params).json()["preview_lines"]
    assert preview[0] == "P(14) 發票櫃台選票派發紀錄"
    assert any("000001" in line and "000003" in line for line in preview)


@pytest.mark.parametrize(
    ("locale", "title", "counter_label"),
    [
        ("tc", "P(14) 發票櫃台選票派發紀錄", "發票櫃台"),
        ("sc", "P(14) 发票柜台选票分配记录", "发票柜台"),
        ("en", "P(14) Counter ballot allocations", "Issuance counter"),
    ],
)
def test_selected_revision_pdf_has_translated_context_and_exact_serials(
    allocation_setup: dict, locale: str, title: str, counter_label: str
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    saved = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert saved.status_code == 201
    allocation_id = saved.json()["id"]
    exported = officer.get(
        path + "/statement.pdf",
        params={"allocation_id": allocation_id, "revision": 1, "locale": locale},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/pdf"
    assert (
        f"p14-allocation-{allocation_id}-r1-{locale}.pdf" in exported.headers["content-disposition"]
    )
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(exported.content)).pages)
    for expected in (
        title,
        counter_label,
        "C1",
        "發票櫃台一",
        "普通系列 A",
        "000001",
        "000003",
        "2026-11-08 08:05:00 HKT",
        "Asia/Hong_Kong (UTC+08:00)",
    ):
        assert expected in text
