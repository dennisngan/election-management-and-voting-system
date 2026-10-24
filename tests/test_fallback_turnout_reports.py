"""Saved mixed and fallback-stock P(15) figures retain translated provenance."""

import csv
from datetime import UTC, datetime
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import approve_period, submit_period


@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("tc", {
            "title": "P(15) 時段及累計投票人數報表", "provenance": "數字來源類別",
            "mixed": "外部數字及後備庫存推算", "fallback_stock": "後備庫存推算投票人數",
            "hourly": "確認時計算的本時段人數", "cumulative": "確認時計算的結束累計",
        }),
        ("sc", {
            "title": "P(15) 时段及累计投票人数报表", "provenance": "数字来源类别",
            "mixed": "外部数字及后备库存推算", "fallback_stock": "后备库存推算投票人数",
            "hourly": "确认时计算的本时段人数", "cumulative": "确认时计算的结束累计",
        }),
        ("en", {
            "title": "P(15) period and cumulative turnout", "provenance": "Figure provenance",
            "mixed": "External figures and fallback stock derivation",
            "fallback_stock": "Fallback stock-derived turnout",
            "hourly": "Period turnout derived at approval",
            "cumulative": "Ending cumulative turnout derived at approval",
        }),
    ],
)
def test_saved_mixed_and_fallback_periods_keep_values_and_provenance_in_all_report_formats(
    admin: TestClient, database_url: str, locale: str, words: dict[str, str],
) -> None:
    with fallback_setup(admin, database_url) as setup:
        mixed = approved_mixed_period(setup)
        officer, path, base = setup["officer"], setup["scope"]["path"], setup["base"]
        setup["clock"].value = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T13:00:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        endpoint = observed.json()
        assert endpoint["ordinary_issued_quantity"] == 115
        assert endpoint["ordinary_remaining_quantity"] == 85
        submitted = submit_period(
            officer, path, 3, mode="fallback",
            fallback_activation_id=mixed["activation"]["id"], fallback_activation_revision=1,
            stock_snapshot_id=endpoint["id"], stock_snapshot_revision=1,
            event_at="2026-11-15T13:00:00+08:00", supplied_hourly=None,
            supplied_cumulative=None, source_context="Ordinary-stock fallback from noon to 13:00.",
        )
        assert submitted["provenance"] == "fallback_stock"
        fallback = approve_period(setup["supervisor"], path, 3)
        assert fallback["derived_hourly"] == 0 and fallback["derived_cumulative_end"] == 115
        before = officer.get(path)
        assert before.status_code == 200
        assert before.json()["approved_prefix"]["cumulative_end"] == 115
        source_before = officer.get(base + "/stock-snapshots")
        assert source_before.status_code == 200
        special_before = officer.get(base + "/special-papers")
        assert special_before.status_code == 200
        histories = {index: officer.get(path + f"/{index}/history").json() for index in (2, 3)}

        for suffix, expected_periods in (("/statement", (2, 3)),
                                         ("/2/statement", (2,)), ("/3/statement", (3,))):
            params = {"locale": locale}
            if suffix != "/statement":
                params["revision"] = 1
            response = officer.get(path + suffix, params=params)
            # First new report request reaches the missing mixed-provenance label RED.
            # Later format/value and immutable-readback assertions remain unreached in RED.
            assert response.status_code == 200
            report = response.json()
            assert report["title"] == words["title"] and report["locale"] == locale
            if suffix == "/statement":
                assert report["approved_prefix"]["cumulative_end"] == 115
            items = {row["period_index"]: row for row in report["items"]}
            preview = "\n".join(report["preview_lines"])
            csv_response = officer.get(path + suffix + ".csv", params=params)
            assert csv_response.status_code == 200
            assert csv_response.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
            pdf_response = officer.get(path + suffix + ".pdf", params=params)
            assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF-")
            pdf = PdfReader(BytesIO(pdf_response.content))
            pdf_text = "".join("".join(page.extract_text().split()) for page in pdf.pages)
            assert "".join(words["title"].split()) in pdf_text
            for index in expected_periods:
                provenance, hourly = ("mixed", 15) if index == 2 else ("fallback_stock", 0)
                item = items[index]
                assert item["provenance"] == provenance
                assert item["approval_valid"] is True and item["review_required"] is False
                assert item["derived_hourly"] == hourly
                assert item["derived_cumulative_end"] == 115
                assert item["supplied_hourly"] is None and item["supplied_cumulative"] is None
                expected_source = mixed["approved"] if index == 2 else fallback
                assert item["source_basis"] == expected_source["source_basis"]
                assert words["provenance"] + " · " + words[provenance] in preview
                for label, value in ((words["provenance"], words[provenance]),
                                     (words["hourly"], str(hourly)),
                                     (words["cumulative"], "115")):
                    assert [label, value] in rows
                    assert "".join((label + value).split()) in pdf_text
        after = officer.get(path)
        assert after.status_code == 200 and after.json() == before.json()
        for index in (2, 3):
            history = officer.get(path + f"/{index}/history")
            assert history.status_code == 200 and history.json() == histories[index]
        assert officer.get(base + "/stock-snapshots").json() == source_before.json()
        assert officer.get(base + "/special-papers").json() == special_before.json()
