"""Long frozen P(12) bases paginate without footer-only pages or orphan headings."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.stock_support import stock_payload
from tests.test_stock_snapshot_quantity_api import allocate_large_series
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture
def long_snapshot_basis(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    election_id = scope["election"]["id"]
    renamed = admin.put(
        f"/api/elections/{election_id}",
        json={"name": "票站流程驗證 Polling workflow 2025", "revision": 1},
    )
    assert renamed.status_code == 200
    constituencies = admin.get(f"/api/elections/{election_id}/constituencies")
    assert constituencies.status_code == 200
    constituency = next(row for row in constituencies.json()["items"] if row["code"] == "N")
    changed = admin.put(
        f"/api/elections/{election_id}/constituencies/{constituency['id']}",
        json={"code": "N", "name": "北區 North", "revision": constituency["revision"]},
    )
    assert changed.status_code == 200
    station_id = scope["stations"][0]["id"]
    station_path = (
        f"/api/elections/{election_id}/constituencies/{constituency['id']}/stations/{station_id}"
    )
    changed = admin.put(station_path, json={
        "code": "N1", "name": "北區 North 接收點票站", "revision": 1,
        "counting_mode": "local", "destination_station_id": None,
    })
    assert changed.status_code == 200
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload(
            series="北區選票系列 A", ordinary_quantity=7,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000007"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ))
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter_id = options.json()["counters"][0]["id"]
        allocations = []
        for start, end in (("000001", "000005"), ("000006", "000006")):
            allocated = officer.post(base + "/allocations", json={
                "request_id": str(uuid4()), "counter_id": counter_id,
                "series": "北區選票系列 A", "serial_from": start, "serial_to": end,
                "event_at": "2026-11-15T09:00:00+08:00",
            })
            assert allocated.status_code == 201
            allocations.append(allocated.json())
        returned = officer.post(base + "/stock-returns", json={
            "request_id": str(uuid4()), "counter_id": counter_id,
            "series": "北區選票系列 A", "serial_from": "000005", "serial_to": "000005",
            "event_at": "2026-11-15T09:15:00+08:00",
        })
        assert returned.status_code == 201
        allocate_large_series(officer, base, [(counter_id, 20)])
        command = {
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{"counter_id": counter_id, "ranges": []}],
        }
        path = base + "/stock-snapshots"
        saved = officer.post(path, json=command)
        assert saved.status_code == 201
        original = saved.json()
        corrected = officer.put(path + f"/{original['id']}", json={
            **command, "request_id": str(uuid4()), "revision": 1,
            "reason": "One remaining paper confirmed during recount.\n"
                      "Preserve the exact aggregate and original observation time.",
            "counters": [{"counter_id": counter_id, "ranges": [{
                "series": "Aggregate stock series 01", "serial_from": "1", "serial_to": "1",
            }]}],
        })
        assert corrected.status_code == 200
        yield {
            "officer": officer, "path": path, "original": original,
            "corrected": corrected.json(), "receipt": receipt.json(),
            "first_allocation": allocations[0], "return": returned.json(),
        }


def page_spans(page: Any) -> list[tuple[str, float, float]]:
    spans: list[tuple[str, float, float]] = []

    def record(text: str, cm: list[float], tm: list[float], font: Any, size: float) -> None:
        if text.strip():
            spans.append((
                " ".join(text.split()),
                tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
            ))

    page.extract_text(visitor_text=record)
    return spans


@pytest.mark.parametrize(("locale", "labels"), [
    ("tc", {
        "page": "頁", "summary": "此版本的全站合計", "field": "項目", "value": "內容",
        "report_scope": "報表基準", "counter": "發票櫃台",
        "remaining": "已填報的剩餘普通選票範圍", "issued": "按庫存推算的已發出普通選票範圍",
        "series": "選票系列", "from": "起始編號", "to": "結束編號", "quantity": "數量",
        "receipt": "原接收記錄基礎", "allocation": "原派發記錄基礎",
        "return": "原未發出選票退回記錄基礎", "receipt_id": "接收記錄編號",
        "allocation_id": "派發記錄編號", "return_id": "退回記錄編號", "revision": "修訂版本",
    }),
    ("sc", {
        "page": "页", "summary": "此版本的全站合计", "field": "项目", "value": "内容",
        "report_scope": "报表依据", "counter": "发票柜台",
        "remaining": "已填报的剩余普通选票范围", "issued": "按库存推算的已发出普通选票范围",
        "series": "选票系列", "from": "起始编号", "to": "结束编号", "quantity": "数量",
        "receipt": "原接收记录依据", "allocation": "原派发记录依据",
        "return": "原未发出选票退回记录依据", "receipt_id": "接收记录编号",
        "allocation_id": "派发记录编号", "return_id": "退回记录编号", "revision": "修订版本",
    }),
    ("en", {
        "page": "Page", "summary": "Station totals at this revision", "field": "Field",
        "value": "Value", "report_scope": "Report basis", "counter": "Issuance counter",
        "remaining": "Reported remaining ordinary ranges",
        "issued": "Stock-derived issued ordinary ranges",
        "series": "Ballot series", "from": "Serial from", "to": "Serial to", "quantity": "Quantity",
        "receipt": "Original receipt basis", "allocation": "Original allocation basis",
        "return": "Original unissued-return basis", "receipt_id": "Receipt ID",
        "allocation_id": "Allocation ID", "return_id": "Return ID", "revision": "Revision",
    }),
])
def test_long_basis_pages_have_body_and_keep_headings_with_header_and_first_data(
    long_snapshot_basis: dict, locale: str, labels: dict[str, str], tmp_path: Path,
) -> None:
    setup = long_snapshot_basis
    officer, path = setup["officer"], setup["path"]
    original, corrected = setup["original"], setup["corrected"]
    assert original["ordinary_issued_quantity"] == 19999999999999999985
    assert corrected["ordinary_issued_quantity"] == 19999999999999999984
    assert corrected["ordinary_remaining_quantity"] == 1
    assert len(corrected["receipt_basis"]) == 21 and len(corrected["allocation_basis"]) == 22
    target = path + f"/{original['id']}"
    history = officer.get(target + "/history")
    assert history.status_code == 200 and history.json()["items"] == [original, corrected]
    params = {"locale": locale, "snapshot_id": original["id"], "revision": 2}
    projection = officer.get(path + "/statement", params=params)
    assert projection.status_code == 200 and projection.json()["items"] == [corrected]
    exported = officer.get(path + "/statement.pdf", params=params)
    assert exported.status_code == 200
    (tmp_path / f"long-basis-{locale}.pdf").write_bytes(exported.content)
    document = PdfReader(BytesIO(exported.content))
    pages = [page_spans(page) for page in document.pages]
    for index, spans in enumerate(pages, 1):
        footer_y = next(y for text, _, y in spans if text == f"{labels['page']} {index}")
        assert any(y > footer_y + 12 for _, _, y in spans), {
            "footer_only_page": index, "locale": locale,
            "text": document.pages[index - 1].extract_text(),
        }

    def section(title: str, headers: tuple[str, ...], first_data: str) -> None:
        found = [spans for spans in pages if any(text == title for text, _, _ in spans)]
        assert len(found) == 1, {"heading": title, "matching_pages": len(found)}
        spans = found[0]
        heading_y = next(y for text, _, y in spans if text == title)
        for expected in (*headers, first_data):
            assert any(text == expected and y < heading_y for text, _, y in spans), {
                "heading": title, "missing_below_heading": expected,
            }

    section(labels["summary"], (labels["field"], labels["value"]), labels["report_scope"])
    range_headers = tuple(labels[key] for key in ("series", "from", "to", "quantity"))
    prefix = labels["counter"] + " · C1 · 發票櫃台 · "
    section(prefix + labels["remaining"], range_headers, "Aggregate stock series 01")
    section(prefix + labels["issued"], range_headers, "北區選票系列 A")
    for kind, first in (
        ("receipt", setup["receipt"]["id"]),
        ("allocation", setup["first_allocation"]["id"]),
        ("return", setup["return"]["id"]),
    ):
        section(labels[kind], (labels[kind + "_id"], labels["revision"]), str(first))
    text = "\n".join(page.extract_text() for page in document.pages)
    for quantity in ("19999999999999999986", "19999999999999999985", "19999999999999999984"):
        assert quantity in text

    def exact_issued_quantity(series: str, expected: str) -> bool:
        for spans in pages:
            for series_text, _, series_y in spans:
                if series_text != series:
                    continue
                headers = [
                    x for cell, x, y in spans if cell == labels["quantity"] and y > series_y
                ]
                if headers and any(
                    cell == expected and abs(y - series_y) < 0.5 and x >= headers[-1] - 0.5
                    for cell, x, y in spans
                ):
                    return True
        return False

    for number in range(1, 21):
        series = f"Aggregate stock series {number:02d}"
        expected = "999999999999999998" if number == 1 else "999999999999999999"
        assert exact_issued_quantity(series, expected), {
            "series": series, "missing_exact_issued_quantity": expected,
        }
    assert officer.get(target, params={"revision": 1}).json() == original
    assert officer.get(target + "/history").json()["items"] == [original, corrected]
