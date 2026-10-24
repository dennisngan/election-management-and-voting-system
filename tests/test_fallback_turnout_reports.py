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
from tests.turnout_support import (
    READY_PASSWORD,
    approve_period,
    submit_period,
    turnout_command,
    turnout_draft,
)


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


RECOVERY_WORDS = {
    "tc": {
        "reconciled": "恢復後核對的外部數字", "mixed": "外部數字及後備庫存推算",
        "provenance": "數字來源類別", "source_basis": "凍結來源基礎",
        "activation_id": "後備啟用記錄編號", "activation_revision": "後備啟用修訂版本",
        "activation_event_at": "後備啟用時間（香港時間）",
        "activation_cumulative_quantity": "啟用時確認累計人數",
        "stock_snapshot_id": "期末 P(12) 快照記錄編號",
        "stock_snapshot_revision": "期末 P(12) 快照修訂版本",
        "ordinary_issued_since_activation_quantity": "啟用後普通發票增量",
        "stock_derived_cumulative_quantity": "庫存推算期末累計人數",
        "recovered_cumulative_quantity": "恢復後外部累計人數",
        "reconciliation_difference": "外部與庫存推算差額",
        "recovery_id": "恢復記錄編號", "recovery_revision": "恢復修訂版本",
        "recovery_event_at": "恢復事件時間（香港時間）", "recovery_reason": "恢復核對原因",
        "recovery_approved_at": "恢復確認時間（香港時間）",
        "recovery_approved_by": "恢復確認主管編號", "coverage": "來源涵蓋時段",
        "normal": "外部提供", "fallback": "後備庫存", "reconciled_mode": "外部核對後",
        "hourly": "確認時計算的本時段人數", "cumulative": "確認時計算的結束累計",
    },
    "sc": {
        "reconciled": "恢复后核对的外部数字", "mixed": "外部数字及后备库存推算",
        "provenance": "数字来源类别", "source_basis": "冻结来源依据",
        "activation_id": "后备启用记录编号", "activation_revision": "后备启用修订版本",
        "activation_event_at": "后备启用时间（香港时间）",
        "activation_cumulative_quantity": "启用时确认累计人数",
        "stock_snapshot_id": "期末 P(12) 快照记录编号",
        "stock_snapshot_revision": "期末 P(12) 快照修订版本",
        "ordinary_issued_since_activation_quantity": "启用后普通发票增量",
        "stock_derived_cumulative_quantity": "库存推算期末累计人数",
        "recovered_cumulative_quantity": "恢复后外部累计人数",
        "reconciliation_difference": "外部与库存推算差额",
        "recovery_id": "恢复记录编号", "recovery_revision": "恢复修订版本",
        "recovery_event_at": "恢复事件时间（香港时间）", "recovery_reason": "恢复核对原因",
        "recovery_approved_at": "恢复确认时间（香港时间）",
        "recovery_approved_by": "恢复确认主管编号", "coverage": "来源覆盖时段",
        "normal": "外部提供", "fallback": "后备库存", "reconciled_mode": "外部核对后",
        "hourly": "确认时计算的本时段人数", "cumulative": "确认时计算的结束累计",
    },
    "en": {
        "reconciled": "Reconciled recovered external figures",
        "mixed": "External figures and fallback stock derivation",
        "provenance": "Figure provenance",
        "source_basis": "Frozen source basis", "activation_id": "Fallback activation ID",
        "activation_revision": "Fallback activation revision",
        "activation_event_at": "Fallback activation time (HKT)",
        "activation_cumulative_quantity": "Confirmed cumulative turnout at activation",
        "stock_snapshot_id": "Endpoint P(12) snapshot ID",
        "stock_snapshot_revision": "Endpoint P(12) snapshot revision",
        "ordinary_issued_since_activation_quantity": "Ordinary issuance since activation",
        "stock_derived_cumulative_quantity": "Stock-derived cumulative endpoint",
        "recovered_cumulative_quantity": "Recovered external cumulative turnout",
        "reconciliation_difference": "Recovered minus stock-derived difference",
        "recovery_id": "Recovery ID", "recovery_revision": "Recovery revision",
        "recovery_event_at": "Recovery event time (HKT)",
        "recovery_reason": "Recovery reconciliation reason",
        "recovery_approved_at": "Recovery approval time (HKT)",
        "recovery_approved_by": "Recovery approving Supervisor ID",
        "coverage": "Source coverage intervals",
        "normal": "External manual", "fallback": "Fallback stock",
        "reconciled_mode": "Reconciled external",
        "hourly": "Period turnout derived at approval",
        "cumulative": "Ending cumulative turnout derived at approval",
    },
}


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_recovery_reports_retain_historical_115_and_reconciled_116_with_visible_source_coverage(
    admin: TestClient, database_url: str, locale: str,
) -> None:
    words = RECOVERY_WORDS[locale]
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        activation, endpoint, original = (
            prepared["activation"], prepared["endpoint"], prepared["approved"],
        )
        officer, turnout_path = setup["officer"], setup["scope"]["path"]
        recovery_reason = "核對恢復的外部數字：116，庫存推算115。\n保留一人的差額及原始來源。"
        created = officer.post(setup["path"], json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 116,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "source_context": "Recovered manual register confirms 116 at noon.",
            "reason": recovery_reason,
        })
        assert created.status_code == 201
        recovery_id = created.json()["id"]
        target = setup["path"] + f"/{recovery_id}"
        submitted = officer.post(target + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200
        confirmed = setup["supervisor"].post(
            target + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        recovery = confirmed.json()
        assert recovery["reconciliation"]["difference"] == 1
        amended = officer.post(turnout_path + "/2/amend", json=turnout_draft(
            expected_revision=1, mode="recovery", fallback_recovery_id=recovery_id,
            fallback_recovery_revision=1, supplied_hourly=None, supplied_cumulative=None,
            event_at="2026-11-15T12:00:00+08:00",
            source_context="Recovered cumulative 116 replaces the stock-derived 115 endpoint.",
            amendment_reason=("Renew the review using the recovered figure, "
                              "without adding 115 again."),
        ))
        assert amended.status_code == 200 and amended.json()["revision"] == 2
        submitted = officer.post(turnout_path + "/2/submit", json=turnout_command(2))
        assert submitted.status_code == 200
        approved_response = setup["supervisor"].post(
            turnout_path + "/2/approve", json=turnout_command(2, password=READY_PASSWORD),
        )
        assert approved_response.status_code == 200
        approved = approved_response.json()
        assert approved["derived_hourly"] == 16 and approved["derived_cumulative_end"] == 116
        history_before = officer.get(turnout_path + "/2/history")
        assert history_before.status_code == 200
        assert history_before.json() == {"items": [original, approved]}
        turnout_before = officer.get(turnout_path)
        assert turnout_before.status_code == 200
        assert turnout_before.json()["approved_prefix"]["cumulative_end"] == 116
        stock_before = officer.get(setup["base"] + "/stock-snapshots")
        assert stock_before.status_code == 200
        recovery_before = officer.get(target)
        assert recovery_before.status_code == 200 and recovery_before.json() == recovery

        for suffix, revision_number, hourly, cumulative in (
            ("/statement", None, 16, 116), ("/2/statement", 1, 15, 115),
            ("/2/statement", 2, 16, 116),
        ):
            params = {"locale": locale}
            if revision_number is not None:
                params["revision"] = revision_number
            response = officer.get(turnout_path + suffix, params=params)
            # First new recovery-report request reaches external_reconciled label RED.
            # Later basis/coverage/CSV/PDF/immutable-readback assertions are unreached.
            assert response.status_code == 200
            report = response.json()
            item = next(row for row in report["items"] if row["period_index"] == 2)
            historical = revision_number == 1
            expected = original if historical else approved
            assert item["source_basis"] == expected["source_basis"]
            assert item["derived_hourly"] == hourly and item["derived_cumulative_end"] == cumulative
            assert item["provenance"] == ("mixed" if historical else "external_reconciled")
            if historical:
                assert report["revision_state"] == "historical"
                assert report["approved_prefix"] is None
                assert "recovery_id" not in item["source_basis"]
            elif revision_number is None:
                assert report["approved_prefix"]["cumulative_end"] == 116
            preview = "\n".join(report["preview_lines"])
            expected_rows = [
                [words["activation_id"], str(activation["id"])],
                [words["activation_revision"], "1"],
                [words["activation_event_at"], "2026-11-15 11:20:00 HKT"],
                [words["activation_cumulative_quantity"], "110"],
                [words["stock_snapshot_id"], str(endpoint["id"])],
                [words["stock_snapshot_revision"], "1"],
                [words["ordinary_issued_since_activation_quantity"], "5"],
                [words["stock_derived_cumulative_quantity"], "115"],
                [words["hourly"], str(hourly)], [words["cumulative"], str(cumulative)],
                [words["provenance"], words["mixed"] if historical else words["reconciled"]],
            ]
            if not historical:
                expected_rows += [
                    [words["recovered_cumulative_quantity"], "116"],
                    [words["reconciliation_difference"], "1"],
                    [words["recovery_id"], str(recovery_id)],
                    [words["recovery_revision"], "1"],
                    [words["recovery_event_at"], "2026-11-15 12:00:00 HKT"],
                    [words["recovery_reason"], recovery_reason],
                    [words["recovery_approved_at"], "2026-11-15 12:00:00 HKT"],
                    [words["recovery_approved_by"], str(setup["supervisor_account"]["id"])],
                ]
            coverage_rows = [
                [words["normal"], "2026-11-15 11:00:00 HKT", "2026-11-15 11:20:00 HKT",
                 "100", "110", "10"],
                [words["fallback"] if historical else words["reconciled_mode"],
                 "2026-11-15 11:20:00 HKT", "2026-11-15 12:00:00 HKT", "110",
                 "115" if historical else "116", "5" if historical else "6"],
            ]
            assert words["source_basis"] in preview and words["coverage"] in preview
            for row in expected_rows + coverage_rows:
                assert " · ".join(row) in preview
            csv_response = officer.get(turnout_path + suffix + ".csv", params=params)
            assert csv_response.status_code == 200
            assert csv_response.content.startswith(b"\xef\xbb\xbf")
            csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
            pdf_response = officer.get(turnout_path + suffix + ".pdf", params=params)
            assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF-")
            pdf_text = "".join("".join(page.extract_text().split())
                               for page in PdfReader(BytesIO(pdf_response.content)).pages)
            for row in expected_rows + coverage_rows:
                assert row in csv_rows
                assert "".join("".join(row).split()) in pdf_text
            if historical:
                assert words["recovery_id"] not in [cell for row in csv_rows for cell in row]
        assert officer.get(turnout_path + "/2/history").json() == history_before.json()
        assert officer.get(turnout_path).json() == turnout_before.json()
        assert officer.get(setup["base"] + "/stock-snapshots").json() == stock_before.json()
        assert officer.get(target).json() == recovery_before.json()
