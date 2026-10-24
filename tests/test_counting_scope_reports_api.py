"""Frozen received-box scope reports through authenticated MySQL-backed routes."""

import csv
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD, box_staff, event_command
from tests.counting_support import counting_setup
from tests.stock_support import stock_payload
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


@pytest.mark.parametrize(
    ("locale", "title", "partial", "missing", "stock_estimate", "observed"),
    [
        (
            "en",
            "Counting scope and received-box provenance",
            "Only some source boxes are selected; whole-station accounting estimates "
            "are not estimates for this subset.",
            "Not recorded",
            "Estimated box papers from stock",
            "Actual observed counted papers",
        ),
        (
            "tc",
            "點票範圍及已接收票箱來源",
            "只選取部分來源票箱；不把全站核算估計當作這些票箱的估計。",
            "尚未記錄",
            "庫存推算票箱選票數量",
            "票箱實際點算數量",
        ),
        (
            "sc",
            "点票范围及已接收票箱来源",
            "只选取部分来源票箱；不把全站核算估计当作这些票箱的估计。",
            "尚未记录",
            "库存推算票箱选票数量",
            "票箱实际点算数量",
        ),
    ],
)
def test_receiver_exports_submitted_scope_without_general_source_station_access(
    admin: TestClient,
    database_url: str,
    locale: str,
    title: str,
    partial: str,
    missing: str,
    stock_estimate: str,
    observed: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        path = setup["paths"]["n1_counting_scopes"]
        local, transferred = setup["boxes"]["local_n1"], setup["boxes"]["transferred_n2"]
        created = receiver.post(
            path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "北區 scope <01> & 保留",
                "event_at": "2026-11-15T23:10:00.123456+08:00",
                "box_revisions": [
                    {"box_id": box["id"], "revision": box["revision"]}
                    for box in (local, transferred)
                ],
                "accounting_revisions": [
                    {"station_id": setup["stations"][code]["id"], "revision": 1}
                    for code in ("N1", "N2")
                ],
                "notes": (
                    "Received local and transferred boxes.\n保留原始來源，不把混合點票歸於各票站。"
                ),
            },
        )
        assert created.status_code == 201, created.text
        scope_id = created.json()["id"]
        submitted = receiver.post(
            path + f"/{scope_id}/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["count_ready"] is True
        assert receiver.get(setup["paths"]["n2_accounting"]).status_code == 403
        target = path + f"/{scope_id}/revisions/1/statement"
        response = receiver.get(target, params={"locale": locale})
        assert response.status_code == 200
        report = response.json()
        assert report["station_id"] == setup["stations"]["N1"]["id"]
        assert report["scope_id"] == scope_id
        assert report["revision"] == 1 and report["locale"] == locale
        assert report["record"] == submitted.json()
        assert report["preview_lines"][0] == title
        assert report["metadata"]
        assert all(len(row) == 2 for row in report["metadata"])
        assert report["tables"]
        assert all(table["title"] and table["rows"] for table in report["tables"])
        preview = "\n".join(report["preview_lines"])
        for expected in (
            partial,
            "2026-11-15 23:10:00.123456 HKT",
            "北區 scope <01> & 保留",
            local["box_reference"],
            transferred["box_reference"],
            local["seal_reference"],
            transferred["seal_reference"],
            "保留原始來源，不把混合點票歸於各票站。",
        ):
            assert expected in preview
        assert stock_estimate + " · " + missing in report["preview_lines"]
        assert observed + " · " + missing in report["preview_lines"]
        assert len(report["record"]["accounting_basis"]) == 2
        assert report["record"]["estimated_box_from_stock_quantity"] is None
        assert report["record"]["estimated_box_from_turnout_quantity"] is None
        assert report["record"]["coverage"][1]["all_source_boxes_in_scope"] is False

        csv_response = receiver.get(target + ".csv", params={"locale": locale})
        assert csv_response.status_code == 200
        assert csv_response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert rows[0] == [title]
        assert [stock_estimate, missing] in rows
        assert [observed, missing] in rows
        assert any(partial in row for row in rows)
        assert csv_response.headers["content-type"].startswith("text/csv")
        pdf = receiver.get(target + ".pdf", params={"locale": locale})
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        pages = PdfReader(BytesIO(pdf.content)).pages
        assert pages
        text = "\n".join(page.extract_text() for page in pages)
        for expected in (
            title,
            "北區 scope <01> & 保留",
            local["box_reference"],
            transferred["box_reference"],
            partial,
            observed,
            missing,
        ):
            assert expected in text
        assert receiver.get(target, params={"locale": "unsupported"}).status_code == 422
        assert receiver.get(path + f"/{scope_id}/revisions/99/statement").status_code == 404


def scope_command(setup: dict, *, boxes: list[dict] | None = None, **changes: object) -> dict:
    selected = boxes if boxes is not None else [setup["boxes"]["local_n1"]]
    codes = [
        code
        for code in ("N1", "N2")
        if setup["stations"][code]["id"] in {box["origin_station_id"] for box in selected}
    ]
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "reference": "Public scope " + uuid4().hex[:8],
        "event_at": "2026-11-15T23:10:00+08:00",
        "box_revisions": [{"box_id": box["id"], "revision": box["revision"]} for box in selected],
        "accounting_revisions": [
            {"station_id": setup["stations"][code]["id"], "revision": 1} for code in codes
        ],
        **changes,
    }


def test_report_keeps_frozen_receipt_and_old_revision_after_reasoned_scope_correction(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        command = scope_command(setup)
        saved = receiver.post(path, json=command)
        assert saved.status_code == 201
        scope_id = saved.json()["id"]
        assert (
            receiver.post(
                path + f"/{scope_id}/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                },
            ).status_code
            == 200
        )
        target = path + f"/{scope_id}/revisions/1/statement"
        before = receiver.get(target, params={"locale": "en"})
        assert before.status_code == 200
        original = before.json()["record"]
        box = setup["boxes"]["local_n1"]
        corrected = receiver.put(
            setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
            json=event_command(
                box["revision"], "2026-11-15T22:46:00+08:00", reason="Corrected paper handover time"
            ),
        )
        assert corrected.status_code == 200
        stale = receiver.get(target, params={"locale": "en"})
        assert stale.status_code == 200
        record = stale.json()["record"]
        assert record["source_current"] is False and record["count_ready"] is False
        assert record["box_basis"] == original["box_basis"]
        assert record["accounting_basis"] == original["accounting_basis"]
        assert "2026-11-15 22:45:00 HKT" in "\n".join(stale.json()["preview_lines"])
        assert "Box or accounting sources changed; review this scope again." in "\n".join(
            stale.json()["preview_lines"]
        )
        amended = receiver.put(
            path + f"/{scope_id}",
            json={
                **command,
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "box_revisions": [{"box_id": box["id"], "revision": corrected.json()["revision"]}],
                "amendment_reason": "Use the corrected receipt; preserve the original scope.",
            },
        )
        assert amended.status_code == 200
        historical = receiver.get(target, params={"locale": "en"})
        assert historical.status_code == 200
        assert historical.json()["record"]["is_current"] is False
        assert historical.json()["record"]["box_basis"] == original["box_basis"]
        current = receiver.get(path + f"/{scope_id}/revisions/2/statement", params={"locale": "en"})
        assert current.status_code == 200
        assert current.json()["record"]["status"] == "draft"
        assert current.json()["record"]["source_current"] is True
        assert "2026-11-15 22:46:00 HKT" in "\n".join(current.json()["preview_lines"])
        assert current.json()["record"]["amendment_reason"] == (
            "Use the corrected receipt; preserve the original scope."
        )


def test_reports_preserve_permission_boundaries_and_missing_receipt_blockers(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        missing_box = setup["boxes"]["unreceived_n2"]
        saved = receiver.post(
            path,
            json=scope_command(
                setup,
                boxes=[missing_box],
                accounting_revisions=[],
            ),
        )
        assert saved.status_code == 201
        scope_id = saved.json()["id"]
        target = path + f"/{scope_id}/revisions/1/statement"
        report = receiver.get(target, params={"locale": "en"})
        assert report.status_code == 200
        assert report.json()["record"]["count_ready"] is False
        preview = "\n".join(report.json()["preview_lines"])
        assert "Actual box receipt is missing." in preview
        assert "Source-station P(18) accounting is not selected." in preview
        for extension in ("", ".csv", ".pdf"):
            denied = admin.get(target + extension)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "operational_role_required"
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [setup["stations"]["N3"]["id"]]
        ) as (other, _):
            assert other.get(target).status_code == 403
            own_station_target = target.replace(
                f"/stations/{setup['stations']['N1']['id']}/",
                f"/stations/{setup['stations']['N3']['id']}/",
            )
            assert other.get(own_station_target).status_code == 404
        assert receiver.get(setup["paths"]["n2_accounting"]).status_code == 403


def test_complete_source_box_coverage_adds_each_station_estimate_once(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        missing_box = setup["boxes"]["unreceived_n2"]
        departed = setup["clients"]["polling"].post(
            setup["paths"]["n2_boxes"] + f"/{missing_box['id']}/departure",
            json=event_command(1, "2026-11-15T23:00:00+08:00"),
        )
        assert departed.status_code == 201
        received = receiver.post(
            setup["paths"]["n1_boxes"] + f"/{missing_box['id']}/receipt",
            json=event_command(2, "2026-11-15T23:07:00+08:00"),
        )
        assert received.status_code == 201
        saved = receiver.post(
            path,
            json=scope_command(
                setup,
                boxes=[
                    setup["boxes"]["local_n1"],
                    setup["boxes"]["transferred_n2"],
                    received.json(),
                ],
            ),
        )
        assert saved.status_code == 201
        scope_id = saved.json()["id"]
        report = receiver.get(path + f"/{scope_id}/revisions/1/statement", params={"locale": "en"})
        assert report.status_code == 200
        record = report.json()["record"]
        assert len(record["box_basis"]) == 3
        assert len(record["accounting_basis"]) == 2
        assert record["estimated_box_from_stock_quantity"] == 10
        assert record["estimated_box_from_turnout_quantity"] is None
        assert all(row["all_source_boxes_in_scope"] for row in record["coverage"])
        assert "Estimated box papers from stock · 10" in report.json()["preview_lines"]
        assert "the same candidate total must not be attributed to every source station." in (
            "\n".join(report.json()["preview_lines"])
        )


def test_scope_export_preserves_large_whole_station_reserves_exactly(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        polling, receiver = setup["clients"]["polling"], setup["clients"]["receiveronly"]
        source = setup["accounting"]["N2"]
        base = source["path"].removesuffix("/accounting")
        large = 9007199254740993
        received = polling.post(
            base + "/stock",
            json=stock_payload(
                series="精確儲備 <A> & retained",
                event_at="2026-11-15T08:30:00+08:00",
                ordinary_quantity=0,
                replacement_quantity=large,
                tendered_quantity=0,
                ranges=[
                    {
                        "pool": "replacement",
                        "serial_from": "000000000000000001",
                        "serial_to": "009007199254740993",
                    }
                ],
            ),
        )
        assert received.status_code == 201
        quantities = {
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 0,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }
        special = polling.post(
            base + "/special-papers",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:00:00+08:00",
                "stock_snapshot_id": source["stock_snapshot"]["id"],
                "stock_snapshot_revision": 1,
                "series": [
                    {"series": series, **quantities}
                    for series in ("普通系列 A", "精確儲備 <A> & retained")
                ],
            },
        )
        assert special.status_code == 201, special.text
        counter = setup["clients"]["bothcounting"]
        amended = counter.put(
            source["path"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
                "amendment_reason": "Retain newly recorded exact reserve stock.",
            },
        )
        assert amended.status_code == 200, amended.text
        assert (
            counter.post(
                source["path"] + "/submit",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 2,
                },
            ).status_code
            == 200
        )
        approved = setup["clients"]["supervisor"].post(
            source["path"] + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200
        saved = receiver.post(
            setup["paths"]["n1_counting_scopes"],
            json=scope_command(
                setup,
                boxes=[setup["boxes"]["transferred_n2"]],
                accounting_revisions=[{"station_id": setup["stations"]["N2"]["id"], "revision": 2}],
            ),
        )
        assert saved.status_code == 201, saved.text
        target = setup["paths"]["n1_counting_scopes"] + (
            f"/{saved.json()['id']}/revisions/1/statement"
        )
        report = receiver.get(target, params={"locale": "en"})
        assert report.status_code == 200
        assert "Unused replacement reserve · 9007199254740993" in report.json()["preview_lines"]
        assert "Total papers received · 9007199254741003" in report.json()["preview_lines"]
        csv_response = receiver.get(target + ".csv", params={"locale": "en"})
        assert csv_response.status_code == 200
        assert b"9007199254740993" in csv_response.content
        assert b"9007199254741003" in csv_response.content
        pdf = receiver.get(target + ".pdf", params={"locale": "en"})
        assert pdf.status_code == 200
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "9007199254740993" in text and "9007199254741003" in text
        # Detailed P(18) serial chains remain in the associated accounting snapshot,
        # rather than multiplying repeated serial tables in the compact scope statement.
        assert "009007199254740993" not in text
