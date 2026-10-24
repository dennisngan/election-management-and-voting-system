"""Selected special-paper PDFs retain exact stock categories and frozen source context."""

import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


@pytest.mark.parametrize(
    ("locale", "title", "historical", "current", "quantity_labels"),
    [
        pytest.param("en", "Special ballot stock accounting", "Historical revision",
                     "Current revision", [
            "Total papers received", "Stock-derived ordinary issuance",
            "Replacement papers issued",
            "Surrendered/cancelled spoilt originals (paired with replacements; not deducted twice)",
            "Tendered papers issued", "Retrieved unused papers refused by electors",
            "Retrieved unused papers found within station",
            "Retrieved unused papers held pending elector's return",
            "Retrieved-unused papers total",
            "Never-issued ordinary papers remaining", "Unused replacement reserve",
            "Unused tendered reserve", "Never-issued stock total",
            "Estimated box papers from stock",
        ], id="en"),
        pytest.param("tc", "補發、重複及未用選票核算", "歷史版本", "目前版本", [
            "接收選票總數", "庫存推算普通發票數量", "補發選票數量",
            "已收回並註銷的損壞原票（與補發配對，不重複扣減）", "重複選票發出數量",
            "已收回未用選票：選民拒絕接受", "已收回未用選票：在站內發現",
            "已收回未用選票：保留待選民返回", "已收回未用選票合計", "從未發出普通選票餘量",
            "未使用補發選票儲備", "未使用重複選票儲備", "從未發出選票合計",
            "庫存推算票箱選票數量",
        ], id="tc"),
        pytest.param("sc", "补发、重复及未用选票核算", "历史版本", "当前版本", [
            "接收选票总数", "库存推算普通发票数量", "补发选票数量",
            "已收回并注销的损坏原票（与补发配对，不重复扣减）", "重复选票发出数量",
            "已收回未用选票：选民拒绝接受", "已收回未用选票：在站内发现",
            "已收回未用选票：保留待选民返回", "已收回未用选票合计", "从未发出普通选票余量",
            "未使用补发选票储备", "未使用重复选票储备", "从未发出选票合计",
            "库存推算票箱选票数量",
        ], id="sc"),
    ],
)
def test_selected_pdf_preserves_fourteen_category_totals_and_historical_source_context(
    admin: TestClient, database_url: str, tmp_path: Path, locale: str, title: str,
    historical: str, current: str, quantity_labels: list[str],
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        reason = "核對紙本數量：補發三張，尋回零張。\n第二行：保留原始觀察時間及來源版本。"
        corrected = officer.put(target, json={
            **setup["command"], "request_id": str(uuid4()), "revision": 1,
            "reason": reason,
            "series": [{
                **setup["entered_series"], "replacement_issued_quantity": 3,
                "spoilt_original_quantity": 3, "retrieved_found_quantity": 0,
            }],
        })
        assert corrected.status_code == 200
        second = corrected.json()
        params = {"snapshot_id": first["id"], "revision": 1, "locale": locale}
        response = officer.get(path + "/statement.pdf", params=params)
        # First PDF behavior assertion. Later PDF/artifact/readback checks are unreached in RED.
        assert response.status_code == 200
        for revision, exported, state_label, quantities in (
            (1, response, historical, (15, 5, 2, 2, 1, 1, 1, 1, 3, 5, 1, 1, 7, 2)),
            (2, officer.get(path + "/statement.pdf", params={**params, "revision": 2}),
             current, (15, 5, 3, 3, 1, 1, 0, 1, 2, 5, 0, 1, 6, 3)),
        ):
            assert exported.status_code == 200
            assert exported.headers["content-type"] == "application/pdf"
            assert exported.content.startswith(b"%PDF-")
            pdf_path = tmp_path / f"special-papers-{first['id']}-r{revision}-{locale}.pdf"
            pdf_path.write_bytes(exported.content)
            document = PdfReader(BytesIO(exported.content))
            assert document.pages
            page_texts = []
            station_code = first["scope"]["station"]["code"]
            for number, page in enumerate(document.pages, 1):
                assert abs(float(page.mediabox.width) - 841.8898) < 0.1
                assert abs(float(page.mediabox.height) - 595.2756) < 0.1
                text = page.extract_text()
                page_texts.append(text)
                pdf_path.with_suffix(f".page-{number}.txt").write_text(text)
                body = [
                    line for line in text.splitlines()
                    if line.strip() and not line.startswith(station_code + " · ")
                    and not re.fullmatch(r"(?:Page|頁|页)\s*\d+", line.strip())
                ]
                assert body, f"Report page {number} contains only a scope/page footer"
                assert "\ufffd" not in text and "\x00" not in text
                fonts = page["/Resources"]["/Font"].get_object().values()
                assert any(
                    "/ToUnicode" in font.get_object()
                    and "/FontDescriptor" in font.get_object()
                    and "/FontFile2" in font.get_object()["/FontDescriptor"]
                    for font in fonts
                ), "The report page has no embedded Unicode report font"
            text = "\n".join(page_texts)
            compact = "".join(text.split())
            for expected in (
                title, state_label, first["scope"]["election"]["name"],
                first["scope"]["constituency"]["code"],
                first["scope"]["constituency"]["name"], station_code,
                first["scope"]["station"]["name"], "普通系列 A",
                "000011", "000013", "000014", "000015",
                "2026-11-15 09:45:17.123456 HKT", "2026-11-15 09:30:17.123456 HKT",
                "Asia/Hong_Kong (UTC+08:00)",
            ):
                assert "".join(expected.split()) in compact
            for label, quantity in zip(quantity_labels, quantities, strict=True):
                assert "".join((label + str(quantity)).split()) in compact, (label, quantity)
            if revision == 1:
                assert "".join(reason.split()) not in compact
            else:
                assert all("".join(line.split()) in compact for line in reason.splitlines())
            selected = officer.get(path + "/statement", params={**params, "revision": revision})
            assert selected.status_code == 200
            assert selected.json()["items"] == [first if revision == 1 else second]
            assert selected.json().get("availability") is None
        retained = officer.get(target)
        assert retained.status_code == 200 and retained.json() == second
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [first, second]
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
