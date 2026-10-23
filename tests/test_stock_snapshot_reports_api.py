"""P(12) statements retain an exact saved stock snapshot and its provenance."""

import csv
from datetime import datetime
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.stock_support import stock_payload
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


def test_selected_p12_statement_keeps_original_snapshot_after_reasoned_correction(
    admin: TestClient, database_url: str,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        path = base + "/stock-snapshots"
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": counter["id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        assert original["complete"] is True and original["provenance"] == "stock_derived"
        assert original["ordinary_allocated_quantity"] == 6
        assert original["ordinary_returned_quantity"] == 0
        assert original["ordinary_net_allocated_quantity"] == 6
        assert original["ordinary_remaining_quantity"] == 3
        assert original["ordinary_issued_quantity"] == 3
        assert original["actor_id"] == account["id"]
        assert original["receipt_basis"] == [{"receipt_id": receipt.json()["id"], "revision": 1}]
        assert original["allocation_basis"] == [
            {"allocation_id": allocation.json()["id"], "revision": 1}
        ]
        assert original["return_basis"] == []

        params = {"snapshot_id": original["id"], "revision": 1, "locale": "tc"}
        response = officer.get(path + "/statement", params=params)
        assert response.status_code == 200
        report = response.json()
        assert report["report_scope"] == "snapshot_revision"
        assert report["snapshot_id"] == original["id"] and report["revision"] == 1
        assert report["revision_state"] == "current"
        assert report["items"] == [original]
        assert report["availability"] is None
        assert report["scope"] == options.json()["scope"]
        assert report["locale"] == "tc" and report["title"].startswith("P(12)")
        assert report["labels"]["counter"] == "發票櫃台"
        assert report["generation_timezone"] == "Asia/Hong_Kong"
        assert datetime.fromisoformat(report["generated_at"]).utcoffset() is not None
        preview = "\n".join(report["preview_lines"])
        for expected in (
            report["title"], "發票櫃台", "普通系列 A", "000004", "000006",
            "2026-11-15 09:30:17.123456 HKT", "Asia/Hong_Kong", "並非已核實選民人數",
        ):
            assert expected in preview

        correction = officer.put(
            path + f"/{original['id']}",
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": 1,
                "reason": "核對紙本櫃台結餘，第4號已發出",
                "counters": [
                    {
                        "counter_id": counter["id"],
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000005",
                                "serial_to": "000006",
                            }
                        ],
                    }
                ],
            },
        )
        assert correction.status_code == 200
        assert correction.json()["revision"] == 2
        assert correction.json()["ordinary_issued_quantity"] == 4
        historical = officer.get(path + "/statement", params=params)
        assert historical.status_code == 200
        frozen = historical.json()
        assert frozen["report_scope"] == "snapshot_revision"
        assert frozen["revision_state"] == "historical" and frozen["revision"] == 1
        assert frozen["items"] == [original]
        assert frozen["availability"] is None
        assert frozen["items"][0]["ordinary_remaining_quantity"] == 3
        assert frozen["items"][0]["ordinary_issued_quantity"] == 3
        assert frozen["items"][0]["provenance"] == "stock_derived"


@pytest.mark.parametrize(
    ("locale", "labels"),
    [
        pytest.param(
            "tc",
            {
                "title": "P(12) 發票櫃台結餘及發票紀錄",
                "snapshot_id": "快照記錄編號",
                "revision": "修訂版本",
                "report_scope": "報表基準",
                "snapshot_revision": "所選已儲存快照版本",
                "counter": "發票櫃台",
                "allocated": "普通選票派發總量",
                "remaining": "剩餘普通選票數量",
                "issued": "庫存推算普通發票數量",
                "reason": "修正原因",
                "disclaimer": "並非已核實選民人數",
            },
            id="tc",
        ),
        pytest.param(
            "sc",
            {
                "title": "P(12) 发票柜台结余及发票记录",
                "snapshot_id": "快照记录编号",
                "revision": "修订版本",
                "report_scope": "报表依据",
                "snapshot_revision": "所选已保存快照版本",
                "counter": "发票柜台",
                "allocated": "普通选票派发总量",
                "remaining": "剩余普通选票数量",
                "issued": "库存推算普通发票数量",
                "reason": "修正原因",
                "disclaimer": "并非已核实选民人数",
            },
            id="sc",
        ),
        pytest.param(
            "en",
            {
                "title": "P(12) Counter remaining stock and issuance",
                "snapshot_id": "Snapshot ID",
                "revision": "Revision",
                "report_scope": "Report basis",
                "snapshot_revision": "Selected saved snapshot revision",
                "counter": "Issuance counter",
                "allocated": "Gross ordinary allocations",
                "remaining": "Ordinary papers remaining",
                "issued": "Stock-derived ordinary issuance",
                "reason": "Correction reason",
                "disclaimer": "not verified elector counts",
            },
            id="en",
        ),
    ],
)
def test_selected_snapshot_csv_preserves_translated_scope_ranges_and_multiline_reason(
    admin: TestClient, database_url: str, locale: str, labels: dict[str, str],
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        path = base + "/stock-snapshots"
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": counter["id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        reason = "核對紙本結餘：第4至6號仍未發出。\n第二行：保留此原因作報表核對。"
        corrected = officer.put(
            path + f"/{original['id']}",
            json={**command, "request_id": str(uuid4()), "revision": 1, "reason": reason},
        )
        assert corrected.status_code == 200
        saved = corrected.json()
        assert saved["revision"] == 2 and saved["reason"] == reason
        assert saved["ordinary_allocated_quantity"] == 6
        assert saved["ordinary_remaining_quantity"] == 3
        assert saved["ordinary_issued_quantity"] == 3
        assert saved["event_at"] == "2026-11-15T01:30:17.123456Z"

        response = officer.get(
            path + "/statement.csv",
            params={"snapshot_id": saved["id"], "revision": 2, "locale": locale},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert (
            f"p12-snapshot-{saved['id']}-r2-{locale}.csv"
            in response.headers["content-disposition"]
        )
        assert response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0] == [labels["title"]]
        assert [labels["snapshot_id"], str(saved["id"])] in rows
        assert [labels["revision"], "2"] in rows
        assert [labels["report_scope"], labels["snapshot_revision"]] in rows
        assert [labels["counter"], counter["code"] + " · " + counter["name"]] in rows
        assert [labels["allocated"], "6"] in rows
        assert [labels["remaining"], "3"] in rows
        assert [labels["issued"], "3"] in rows
        assert [labels["reason"], reason] in rows
        assert any(
            all(value in row for value in ("普通系列 A", "000004", "000006", "3"))
            for row in rows
        )
        cells = [cell for row in rows for cell in row]
        assert scope["election"]["name"] in cells
        assert "2026-11-15 09:30:17.123456 HKT" in cells
        assert "Asia/Hong_Kong (UTC+08:00)" in cells
        assert any(labels["disclaimer"] in cell for cell in cells)
        assert not any(cell.lstrip().startswith(("{", "[")) for cell in cells)
        assert not any("000007" in cell or "000008" in cell for cell in cells)


@pytest.mark.parametrize(
    ("locale", "labels"),
    [
        pytest.param(
            "tc",
            {
                "title": "P(12) 發票櫃台結餘及發票紀錄",
                "snapshot_id": "快照記錄編號",
                "revision": "修訂版本",
                "report_scope": "報表基準",
                "snapshot_revision": "所選已儲存快照版本",
                "counter": "發票櫃台",
                "allocated": "普通選票派發總量",
                "returned": "未發出普通選票退回總量",
                "net_allocated": "普通選票淨派發量",
                "remaining": "剩餘普通選票數量",
                "issued": "庫存推算普通發票數量",
                "reason": "修正原因",
                "complete": "完整",
                "provenance": "庫存推算",
                "receipt_basis": "原接收記錄基礎",
                "allocation_basis": "原派發記錄基礎",
                "receipt_id": "接收記錄編號",
                "allocation_id": "派發記錄編號",
                "disclaimer": "並非已核實選民人數",
            },
            id="tc",
        ),
        pytest.param(
            "sc",
            {
                "title": "P(12) 发票柜台结余及发票记录",
                "snapshot_id": "快照记录编号",
                "revision": "修订版本",
                "report_scope": "报表依据",
                "snapshot_revision": "所选已保存快照版本",
                "counter": "发票柜台",
                "allocated": "普通选票派发总量",
                "returned": "未发出普通选票退回总量",
                "net_allocated": "普通选票净派发量",
                "remaining": "剩余普通选票数量",
                "issued": "库存推算普通发票数量",
                "reason": "修正原因",
                "complete": "完整",
                "provenance": "库存推算",
                "receipt_basis": "原接收记录依据",
                "allocation_basis": "原派发记录依据",
                "receipt_id": "接收记录编号",
                "allocation_id": "派发记录编号",
                "disclaimer": "并非已核实选民人数",
            },
            id="sc",
        ),
        pytest.param(
            "en",
            {
                "title": "P(12) Counter remaining stock and issuance",
                "snapshot_id": "Snapshot ID",
                "revision": "Revision",
                "report_scope": "Report basis",
                "snapshot_revision": "Selected saved snapshot revision",
                "counter": "Issuance counter",
                "allocated": "Gross ordinary allocations",
                "returned": "Unissued ordinary stock returned",
                "net_allocated": "Net ordinary allocations",
                "remaining": "Ordinary papers remaining",
                "issued": "Stock-derived ordinary issuance",
                "reason": "Correction reason",
                "complete": "Complete",
                "provenance": "Stock-derived",
                "receipt_basis": "Original receipt basis",
                "allocation_basis": "Original allocation basis",
                "receipt_id": "Receipt ID",
                "allocation_id": "Allocation ID",
                "disclaimer": "not verified elector counts",
            },
            id="en",
        ),
    ],
)
def test_selected_snapshot_pdf_keeps_translated_frozen_basis_and_unicode_text(
    admin: TestClient, database_url: str, locale: str, labels: dict[str, str],
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        receipt = officer.post(base + "/stock", json=stock_payload())
        assert receipt.status_code == 201
        options = officer.get(base + "/allocations")
        assert options.status_code == 200
        counter = next(row for row in options.json()["counters"] if row["code"] == "C1")
        allocation = officer.post(
            base + "/allocations",
            json={
                "request_id": str(uuid4()),
                "counter_id": counter["id"],
                "series": "普通系列 A",
                "serial_from": "000001",
                "serial_to": "000006",
                "event_at": "2026-11-15T09:00:00+08:00",
            },
        )
        assert allocation.status_code == 201
        path = base + "/stock-snapshots"
        command = {
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": counter["id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        original = created.json()
        reason = "核對紙本結餘：第4至6號仍未發出。\n第二行：保留此原因作報表核對。"
        corrected = officer.put(
            path + f"/{original['id']}",
            json={**command, "request_id": str(uuid4()), "revision": 1, "reason": reason},
        )
        assert corrected.status_code == 200
        saved = corrected.json()
        assert saved["revision"] == 2 and saved["reason"] == reason
        assert saved["ordinary_allocated_quantity"] == 6
        assert saved["ordinary_remaining_quantity"] == 3
        assert saved["ordinary_issued_quantity"] == 3
        assert saved["event_at"] == "2026-11-15T01:30:17.123456Z"
        assert saved["receipt_basis"] == [{"receipt_id": receipt.json()["id"], "revision": 1}]
        assert saved["allocation_basis"] == [
            {"allocation_id": allocation.json()["id"], "revision": 1}
        ]
        assert saved["return_basis"] == []

        response = officer.get(
            path + "/statement.pdf",
            params={"snapshot_id": saved["id"], "revision": 2, "locale": locale},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="p12-snapshot-{saved["id"]}-r2-{locale}.pdf"'
        )
        assert response.content.startswith(b"%PDF-")
        document = PdfReader(BytesIO(response.content))
        assert len(document.pages) >= 1
        text = "\n".join(page.extract_text() for page in document.pages)
        compact = "".join(text.split())
        for expected in (
            labels["title"], labels["snapshot_id"], str(saved["id"]), labels["revision"],
            labels["report_scope"], labels["snapshot_revision"], labels["counter"],
            labels["allocated"], labels["returned"], labels["net_allocated"],
            labels["remaining"], labels["issued"], labels["reason"], labels["complete"],
            labels["provenance"], labels["receipt_basis"], labels["allocation_basis"],
            labels["receipt_id"], str(receipt.json()["id"]),
            labels["allocation_id"], str(allocation.json()["id"]),
            scope["election"]["name"], options.json()["scope"]["constituency"]["code"],
            options.json()["scope"]["constituency"]["name"],
            options.json()["scope"]["station"]["code"],
            options.json()["scope"]["station"]["name"], counter["code"], counter["name"],
            "普通系列 A", "000001", "000003", "000004", "000006",
            "2026-11-15 09:30:17.123456 HKT", "2026-11-15 12:00:00 HKT",
            "Asia/Hong_Kong (UTC+08:00)", str(account["id"]),
            *reason.splitlines(), labels["disclaimer"],
        ):
            assert "".join(expected.split()) in compact
        values = compact.replace("·", "").replace(":", "")
        for key, value in (("allocated", 6), ("returned", 0), ("net_allocated", 6),
                           ("remaining", 3), ("issued", 3), ("revision", 2)):
            assert "".join((labels[key] + str(value)).split()) in values
        for key, identity in (("receipt_id", receipt.json()["id"]),
                              ("allocation_id", allocation.json()["id"])):
            expected_basis = labels[key] + labels["revision"] + str(identity) + "1"
            assert "".join(expected_basis.split()) in values
        assert "000007" not in text and "000008" not in text
        assert not any(line.lstrip().startswith(("{", "[")) for line in text.splitlines())
        assert "\ufffd" not in text and "\x00" not in text
        for page in document.pages:
            fonts = page["/Resources"]["/Font"].get_object().values()
            assert any(
                "/ToUnicode" in font.get_object()
                and "/FontDescriptor" in font.get_object()
                and "/FontFile2" in font.get_object()["/FontDescriptor"]
                for font in fonts
            )
