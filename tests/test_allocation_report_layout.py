"""P(14) pagination and selected provenance cross the public real-MySQL API."""

import csv
import json
import os
from collections.abc import Iterator
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.lifecycle_support import lifecycle_database_url
from tests.stock_support import stock_payload
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def save_evidence(name: str, report: dict, pdf: bytes, csv_content: bytes) -> None:
    destination = os.getenv("ELECTION_ALLOCATION_REPORT_LAYOUT_DIRECTORY")
    if destination is None:
        return
    allowed = Path(__file__).resolve().parents[1] / "docs/evidence/ticket-08/reports"
    assert Path(destination).resolve() == allowed.resolve()
    allowed.mkdir(parents=True, exist_ok=True)
    (allowed / f"{name}.pdf").write_bytes(pdf)
    (allowed / f"{name}.csv").write_bytes(csv_content)
    (allowed / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


@pytest.mark.parametrize(
    ("locale", "title", "empty_message", "stock_heading", "page_label"),
    [
        (
            "tc",
            "P(14) 發票櫃台選票派發紀錄",
            "尚無已儲存派票記錄。",
            "目前本站庫存",
            "頁",
        ),
        (
            "sc",
            "P(14) 发票柜台选票分配记录",
            "尚无已保存分配记录。",
            "当前本站库存",
            "页",
        ),
        (
            "en",
            "P(14) Counter ballot allocations",
            "No saved allocations yet.",
            "Current station stock",
            "Page",
        ),
    ],
)
def test_current_report_distinguishes_no_allocations_from_zero_remaining_stock(
    allocation_setup: dict,
    tmp_path: Path,
    locale: str,
    title: str,
    empty_message: str,
    stock_heading: str,
    page_label: str,
) -> None:
    setup = allocation_setup
    path, officer = setup["base"] + "/allocations/statement", setup["officer"]
    params = {"locale": locale}
    projection = officer.get(path, params=params)
    assert projection.status_code == 200
    report = projection.json()
    assert report["items"] == []
    assert report["report_scope"] == "station_current"
    assert report["title"] == title
    assert report["availability"][0]["ordinary_received_quantity"] == 8
    assert report["availability"][0]["allocated_quantity"] == 0
    assert report["availability"][0]["available_quantity"] == 8
    assert report["availability"][0]["replacement_quantity"] == 1
    assert report["availability"][0]["tendered_quantity"] == 1
    assert empty_message in report["preview_lines"]
    exported_csv = officer.get(path + ".csv", params=params)
    assert exported_csv.status_code == 200
    rows = list(csv.reader(StringIO(exported_csv.content.decode("utf-8-sig"))))
    assert [empty_message] in rows
    assert ["普通系列 A", "8", "0", "8", "1", "1"] in rows
    assert ["000001", "000008", "8", str(setup["receipt"]["id"]), "1"] in rows
    exported_pdf = officer.get(path + ".pdf", params=params)
    assert exported_pdf.status_code == 200
    reader = PdfReader(BytesIO(exported_pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for expected in (title, empty_message, stock_heading, "000001", "000008"):
        assert expected in text
    for index, page in enumerate(reader.pages, start=1):
        assert f"{page_label} {index}" in page.extract_text()
    name = f"p14-empty-current-{locale}"
    (tmp_path / f"{name}.pdf").write_bytes(exported_pdf.content)
    save_evidence(name, report, exported_pdf.content, exported_csv.content)


@pytest.fixture
def long_allocation_setup(allocation_setup: dict, admin: TestClient) -> dict:
    setup = allocation_setup
    long_counter = "Counter始\n" + "櫃" * 142 + "\nCounter終"
    long_series = "Series始\n" + "票" * 48 + "\nSeries終"
    long_reason = "REASON始\n" + "述" * 984 + "\nREASON終"
    assert (len(long_counter), len(long_series), len(long_reason)) == (160, 64, 1000)
    counter_path = setup["counter_base"] + f"/{setup['counter']['id']}"
    counter = admin.put(counter_path, json={"code": "C1", "name": long_counter, "revision": 1})
    assert counter.status_code == 200
    officer, path = setup["officer"], setup["base"] + "/allocations"
    receipt_path = setup["base"] + f"/stock/{setup['receipt']['id']}"
    receipt = officer.put(
        receipt_path,
        json=stock_payload(
            revision=1,
            reason="依紙本交接單修訂完整十八位數系列",
            series=long_series,
            ranges=[
                {
                    "pool": "ordinary",
                    "serial_from": "100000000000000000",
                    "serial_to": "999999999999999999",
                }
            ],
            ordinary_quantity=900000000000000000,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert receipt.status_code == 200
    created = officer.post(
        path,
        json=allocation_payload(
            setup["counter"]["id"],
            series=long_series,
            serial_from="100000000000000000",
            serial_to="999999999999999998",
        ),
    )
    assert created.status_code == 201
    target = path + f"/{created.json()['id']}"
    amended = officer.put(
        target,
        json=allocation_payload(
            setup["counter"]["id"],
            revision=1,
            series=long_series,
            serial_from="100000000000000001",
            serial_to="999999999999999999",
            reason=long_reason,
        ),
    )
    assert amended.status_code == 200
    historical = amended.json()
    renamed = admin.put(
        counter_path, json={"code": "C1", "name": "CURRENT_COUNTER_ONLY", "revision": 2}
    )
    assert renamed.status_code == 200
    current = officer.put(
        target,
        json=allocation_payload(
            setup["counter"]["id"],
            revision=2,
            series=long_series,
            serial_from="100000000000000002",
            serial_to="999999999999999999",
            reason="CURRENT_REASON_ONLY",
        ),
    )
    assert current.status_code == 200
    changed_receipt = officer.put(
        receipt_path,
        json=stock_payload(
            revision=2,
            reason="只更正目前未派發的選票，不改動已派票範圍",
            series=long_series,
            ranges=[
                {
                    "pool": "ordinary",
                    "serial_from": "100000000000000001",
                    "serial_to": "999999999999999999",
                }
            ],
            ordinary_quantity=899999999999999999,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert changed_receipt.status_code == 200
    return {
        **setup,
        "path": path,
        "historical": historical,
        "current": current.json(),
        "long_counter": long_counter,
        "long_series": long_series,
        "long_reason": long_reason,
    }


@pytest.mark.parametrize(
    ("locale", "title", "history_state", "stock_heading", "page_label"),
    [
        (
            "tc",
            "P(14) 發票櫃台選票派發紀錄",
            "歷史版本",
            "目前本站庫存",
            "頁",
        ),
        (
            "sc",
            "P(14) 发票柜台选票分配记录",
            "历史版本",
            "当前本站库存",
            "页",
        ),
        (
            "en",
            "P(14) Counter ballot allocations",
            "Historical revision",
            "Current station stock",
            "Page",
        ),
    ],
)
def test_long_selected_history_keeps_frozen_context_and_exact_eighteen_digit_values(
    long_allocation_setup: dict,
    tmp_path: Path,
    locale: str,
    title: str,
    history_state: str,
    stock_heading: str,
    page_label: str,
) -> None:
    setup = long_allocation_setup
    officer, path = setup["officer"], setup["path"] + "/statement"
    params = {"locale": locale, "allocation_id": setup["historical"]["id"], "revision": 2}
    selected = officer.get(path, params=params)
    assert selected.status_code == 200
    report = selected.json()
    assert report["items"] == [setup["historical"]]
    assert report["revision_state"] == "historical" and report["availability"] is None
    assert report["items"][0]["counter"]["name"] == setup["long_counter"]
    assert report["items"][0]["receipt_basis"] == [
        {
            "receipt_id": setup["receipt"]["id"],
            "revision": 2,
            "range_line": 0,
        }
    ]
    current = officer.get(path, params={"locale": locale}).json()
    assert current["items"] == [setup["current"]]
    assert current["availability"][0]["ordinary_received_quantity"] == 899999999999999999
    assert current["availability"][0]["allocated_quantity"] == 899999999999999998
    assert current["availability"][0]["available_quantity"] == 1
    assert current["availability"][0]["ranges"][0]["receipt_revision"] == 3
    exported_csv = officer.get(path + ".csv", params=params)
    assert exported_csv.status_code == 200
    rows = list(csv.reader(StringIO(exported_csv.content.decode("utf-8-sig"))))
    values = [cell for row in rows for cell in row]
    for expected in (
        "C1 · " + setup["long_counter"],
        setup["long_series"],
        setup["long_reason"],
        "100000000000000001",
        "999999999999999999",
        "899999999999999999",
        history_state,
    ):
        assert expected in values
    assert "CURRENT_COUNTER_ONLY" not in values and "CURRENT_REASON_ONLY" not in values
    assert stock_heading not in values
    exported_pdf = officer.get(path + ".pdf", params=params)
    assert exported_pdf.status_code == 200
    reader = PdfReader(BytesIO(exported_pdf.content))
    texts = [page.extract_text() for page in reader.pages]
    text = "\n".join(texts)
    compact = "".join(text.split())
    assert len(reader.pages) > 1
    for expected in (
        title,
        history_state,
        "Counter始",
        "Counter終",
        "Series始",
        "Series終",
        "REASON始",
        "REASON終",
        "100000000000000001",
        "999999999999999999",
        "899999999999999999",
    ):
        assert "".join(expected.split()) in compact
    assert compact.count("述") == 984
    assert "CURRENT_COUNTER_ONLY" not in compact and "CURRENT_REASON_ONLY" not in compact
    assert stock_heading not in text
    for index, page_text in enumerate(texts, start=1):
        assert f"{page_label} {index}" in page_text
    name = f"p14-long-historical-{locale}"
    (tmp_path / f"{name}.pdf").write_bytes(exported_pdf.content)
    save_evidence(name, report, exported_pdf.content, exported_csv.content)
