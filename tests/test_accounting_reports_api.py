"""P(18) exports retain frozen accounting and explicit missing observed figures."""

import csv
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.special_paper_support import special_paper_setup
from tests.test_accounting_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_accounting_api import database_url as database_url
from tests.turnout_support import READY_PASSWORD, turnout_command, turnout_draft, turnout_staff


@pytest.mark.parametrize(
    ("locale", "title", "observed", "missing", "turnout_estimate"),
    [
        ("en", "P(18) stock accounting and box-paper estimates",
         "Actual observed counted papers", "Not recorded",
         "Estimated box papers from approved turnout"),
        ("tc", "P(18) 選票核算及票箱選票估計", "票箱實際點算數量", "尚未記錄",
         "有效確認投票人數推算票箱選票數量"),
        ("sc", "P(18) 选票核算及票箱选票估计", "票箱实际点算数量", "尚未记录",
         "有效确认投票人数推算票箱选票数量"),
    ],
)
def test_counting_officer_exports_exact_saved_accounting_in_three_languages(
    admin: TestClient, database_url: str, locale: str, title: str,
    observed: str, missing: str, turnout_estimate: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special_response = setup["officer"].post(setup["path"], json=setup["command"])
        assert special_response.status_code == 201
        special = special_response.json()
        station_id = special["station_id"]
        with turnout_staff(admin, database_url, setup["clock"], [station_id],
                           "counting_officer") as (counter, _):
            path = setup["base"] + "/accounting"
            notes = "紙本核對 / paper <reconciliation> & retained\n第二行 — exact source"
            saved = counter.put(path, json={
                "request_id": str(uuid4()), "expected_revision": 0,
                "special_paper_id": special["id"], "special_paper_revision": 1,
                "turnout_period_index": 1, "turnout_revision": 1, "notes": notes,
            })
            assert saved.status_code == 200
            record = saved.json()
            target = path + "/revisions/1/statement"
            params = {"locale": locale}
            response = counter.get(target, params=params)
            # Intended report RED: the core accounting journey exists before this route.
            assert response.status_code == 200
            report = response.json()
            assert report["record"] == record
            assert report["station_id"] == station_id
            assert report["revision"] == 1 and report["locale"] == locale
            assert report["title"] == title
            assert report["preview_lines"][0] == title
            assert observed + " · " + missing in report["preview_lines"]
            assert turnout_estimate + " · " + missing in report["preview_lines"]
            preview = "\n".join(report["preview_lines"])
            for expected in ("000001", "000010", "000011", "000013", "000014", "000015",
                             "2026-11-15 09:30:17.123456 HKT", notes,
                             special["scope"]["station"]["name"], "普通系列 A"):
                assert expected in preview

            exported = counter.get(target + ".csv", params=params)
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("text/csv")
            assert exported.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
            assert rows[0] == [title]
            assert [observed, missing] in rows
            assert [turnout_estimate, missing] in rows
            assert any(notes in row for row in rows)
            assert any("000011" in row and "000013" in row for row in rows)

            pdf = counter.get(target + ".pdf", params=params)
            assert pdf.status_code == 200
            assert pdf.headers["content-type"] == "application/pdf"
            assert pdf.content.startswith(b"%PDF-")
            pages = PdfReader(BytesIO(pdf.content)).pages
            assert pages
            text = "\n".join(page.extract_text() for page in pages)
            assert title in text and observed in text and missing in text
            assert "paper <reconciliation> & retained" in text
            assert "000011" in text and "000013" in text
            assert counter.get(path).json()["record"] == record
            missing_revision = counter.get(path + "/revisions/99/statement", params=params)
            assert missing_revision.status_code == 404
            assert counter.get(target, params={"locale": "xx"}).status_code == 422

        with turnout_staff(admin, database_url, setup["clock"], [],
                           "counting_officer") as (unassigned, _):
            for suffix in ("", ".csv", ".pdf"):
                assert unassigned.get(target + suffix, params=params).status_code == 403


def test_historical_statement_preserves_approved_figures_after_sources_are_corrected(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        special_response = setup["officer"].post(setup["path"], json=setup["command"])
        assert special_response.status_code == 201
        special = special_response.json()
        station_id = special["station_id"]
        with (
            turnout_staff(admin, database_url, setup["clock"], [station_id],
                          "counting_officer") as (counter, _),
            turnout_staff(admin, database_url, setup["clock"], [station_id],
                          "supervisor") as (supervisor, _),
        ):
            path = setup["base"] + "/accounting"
            command = {
                "request_id": str(uuid4()), "expected_revision": 0,
                "special_paper_id": special["id"], "special_paper_revision": 1,
                "notes": "Original saved accounting before paper correction.",
            }
            saved = counter.put(path, json=command)
            assert saved.status_code == 200
            assert counter.post(path + "/submit", json={
                "request_id": str(uuid4()), "expected_revision": 1,
            }).status_code == 200
            approved = supervisor.post(path + "/approve", json={
                "request_id": str(uuid4()), "expected_revision": 1, "password": READY_PASSWORD,
            })
            assert approved.status_code == 200
            original = approved.json()
            assert original["approval_valid"] is True
            target = path + "/revisions/1/statement"
            before = counter.get(target, params={"locale": "en"})
            assert before.status_code == 200
            assert before.json()["record"]["summary"]["estimated_box_from_stock_quantity"] == 2

            corrected = setup["officer"].put(setup["path"] + f"/{special['id']}", json={
                **setup["command"], "request_id": str(uuid4()), "revision": 1,
                "reason": "One found paper was not part of the retrieved-unused set.",
                "series": [{**setup["entered_series"], "retrieved_found_quantity": 0}],
            })
            assert corrected.status_code == 200
            stale_report = counter.get(target, params={"locale": "en"})
            assert stale_report.status_code == 200
            stale = stale_report.json()["record"]
            assert stale["source_current"] is False and stale["approval_valid"] is False
            assert stale["summary"] == original["summary"]
            assert stale["status"] == "approved" and stale["approved_by"] == original["approved_by"]
            amended = counter.put(path, json={
                **command, "request_id": str(uuid4()), "expected_revision": 1,
                "special_paper_revision": 2, "notes": "New accounting after paper correction.",
                "amendment_reason": "Use the corrected retrieved-unused source.",
            })
            assert amended.status_code == 200
            assert amended.json()["summary"]["estimated_box_from_stock_quantity"] == 3
            historical_response = counter.get(target, params={"locale": "en"})
            assert historical_response.status_code == 200
            historical = historical_response.json()
            assert historical["revision_state"] == "historical"
            assert historical["record"] == stale
            for suffix in ("", ".csv", ".pdf"):
                exported = counter.get(target + suffix, params={"locale": "en"})
                assert exported.status_code == 200
                if suffix == ".pdf":
                    text = "\n".join(page.extract_text()
                                     for page in PdfReader(BytesIO(exported.content)).pages)
                else:
                    text = exported.text
                assert command["notes"] in text
                assert "New accounting after paper correction." not in text
            current = counter.get(path + "/revisions/2/statement", params={"locale": "en"})
            assert current.status_code == 200 and current.json()["revision_state"] == "current"
            assert current.json()["record"]["status"] == "draft"


@pytest.mark.parametrize("recovered", [False, True], ids=["fallback-115", "recovered-116"])
def test_statement_keeps_approved_fallback_and_recovery_provenance_separate_from_stock(
    admin: TestClient, database_url: str, recovered: bool,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        officer, supervisor = setup["officer"], setup["supervisor"]
        turnout_path = setup["scope"]["path"]
        revision, expected_turnout = 1, 115
        if recovered:
            activation, endpoint = prepared["activation"], prepared["endpoint"]
            created = officer.post(setup["path"], json={
                "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
                "activation_id": activation["id"], "activation_revision": 1,
                "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 116,
                "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
                "source_context": "Recovered supplied register confirms 116 at noon.",
                "reason": "Replace the fallback estimate with the recovered external figure.",
            })
            assert created.status_code == 201
            target = setup["path"] + f"/{created.json()['id']}"
            assert officer.post(target + "/submit", json=turnout_command(1)).status_code == 200
            assert supervisor.post(target + "/approve", json=turnout_command(
                1, password=READY_PASSWORD,
            )).status_code == 200
            amended = officer.post(turnout_path + "/2/amend", json=turnout_draft(
                expected_revision=1, mode="recovery", fallback_recovery_id=created.json()["id"],
                fallback_recovery_revision=1, event_at="2026-11-15T12:00:00+08:00",
                source_context="The noon recovered total replaces the former 115 estimate.",
                amendment_reason="Use 116 without adding the former 115.",
            ))
            assert amended.status_code == 200
            assert officer.post(turnout_path + "/2/submit",
                                json=turnout_command(2)).status_code == 200
            approved = supervisor.post(turnout_path + "/2/approve", json=turnout_command(
                2, password=READY_PASSWORD,
            ))
            assert approved.status_code == 200
            revision, expected_turnout = 2, 116
        specials = officer.get(setup["base"] + "/special-papers")
        assert specials.status_code == 200
        special = specials.json()["latest"]
        station_id = special["station_id"]
        with turnout_staff(admin, database_url, setup["clock"], [station_id],
                           "counting_officer") as (counter, _):
            path = setup["base"] + "/accounting"
            saved = counter.put(path, json={
                "request_id": str(uuid4()), "expected_revision": 0,
                "special_paper_id": special["id"], "special_paper_revision": 1,
                "turnout_period_index": 2, "turnout_revision": revision,
            })
            assert saved.status_code == 200
            assert saved.json()["summary"]["estimated_box_from_stock_quantity"] == 115
            assert (
                saved.json()["summary"]["estimated_box_from_turnout_quantity"] == expected_turnout
            )
            target = path + "/revisions/1/statement"
            statement = counter.get(target, params={"locale": "en"})
            assert statement.status_code == 200
            report = statement.json()
            assert report["record"]["turnout"]["record"]["provenance"] == (
                "external_reconciled" if recovered else "mixed"
            )
            csv_response = counter.get(target + ".csv", params={"locale": "en"})
            assert csv_response.status_code == 200
            rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
            assert ["Estimated box papers from stock", "115"] in rows
            assert ["Estimated box papers from approved turnout", str(expected_turnout)] in rows
            assert ["Stock-derived cumulative endpoint", "115"] in rows
            assert any("000111" in row and "000200" in row for row in rows)
            assert any("000116" in row and "000200" in row for row in rows)
            if recovered:
                assert ["Recovered external cumulative turnout", "116"] in rows
                assert ["Recovered minus stock-derived difference", "1"] in rows
            pdf = counter.get(target + ".pdf", params={"locale": "en"})
            assert pdf.status_code == 200
            text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
            assert "Stock-derived cumulative endpoint" in text and "115" in text
            assert "2026-11-15 11:20:00 HKT" in text
            assert "000111" in text and "000116" in text
            if recovered:
                assert "Recovered external cumulative turnout" in text and "116" in text
