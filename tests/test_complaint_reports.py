"""Saved P(19) reports retain frozen received-cohort case revisions."""

import csv
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Election
from election.server.db import make_engine
from tests.complaint_period_support import READY_PASSWORD, complaint_period_scope, period_command
from tests.complaint_support import (
    ComplaintClock,
    category_edit,
    complaint_payload,
    complaint_staff,
    station_categories,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_station_statement_distinguishes_saved_zero_from_missing_periods(
    admin: TestClient, database_url: str
) -> None:
    scope = complaint_period_scope(admin)
    station_id, path = scope["station"]["id"], scope["path"]
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station_id]
    ) as (po, _):
        assert po.put(path + "/1", json=period_command()).status_code == 200
        response = po.get(path + "/statement?locale=en")
        assert response.status_code == 200
        report = response.json()
        assert report["report_scope"] == "station_current"
        assert report["scope"]["station"]["id"] == station_id
        assert report["summary"] == {"required": 3, "approved_current": 0, "missing": 2}
        assert report["saved_period_count"] == 1
        assert report["items"][0]["total_received"] == 0
        assert report["items"][0]["members"] == []
        assert report["outside_coverage_case_count"] == 0
        assert report["preview_lines"]


@pytest.fixture
def report_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope = complaint_period_scope(admin)
    sid, path = scope["station"]["id"], scope["path"]
    clock = ComplaintClock(datetime(2026, 11, 15, 16, 0, 0, 654321, tzinfo=UTC))
    with (
        complaint_staff(admin, database_url, clock, "polling_officer", [sid]) as (po, actor),
        complaint_staff(admin, database_url, clock, "supervisor", [sid]) as (sv, reviewer),
    ):
        category = station_categories(po, sid)[0]
        first = po.post(
            scope["case_path"],
            json=complaint_payload(
                category,
                case_reference="000001 <原樣> & retained",
                received_at="2026-11-15T08:15:00.123456+08:00",
                work_status="completed",
                completed_at="2026-11-15T11:00:00.500000+08:00",
            ),
        )
        assert first.status_code == 201
        boundary = po.post(
            scope["case_path"],
            json=complaint_payload(
                category,
                case_reference="second-period",
                received_at="2026-11-15T08:30:00+08:00",
            ),
        )
        assert boundary.status_code == 201
        assert (
            po.post(
                scope["case_path"],
                json=complaint_payload(
                    category,
                    case_reference="outside",
                    received_at="2026-11-15T07:29:59+08:00",
                ),
            ).status_code
            == 201
        )
        assert po.put(path + "/1", json=period_command()).status_code == 200
        assert po.post(path + "/1/submit", json=period_command(1)).status_code == 200
        approved = sv.post(path + "/1/approve", json=period_command(1, password=READY_PASSWORD))
        assert approved.status_code == 200
        assert po.put(path + "/2", json=period_command()).status_code == 200
        yield {
            "scope": scope,
            "po": po,
            "sv": sv,
            "actor": actor,
            "reviewer": reviewer,
            "clock": clock,
            "category": category,
            "first": first.json(),
            "approved": approved.json(),
            "path": path,
            "sid": sid,
        }


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_all_formats_retain_frozen_cohort_metadata_and_fractional_times(
    report_setup: dict, locale: str
) -> None:
    po, path = report_setup["po"], report_setup["path"]
    for scope in ("/statement", "/1/statement?revision=1"):
        query = "&" if "?" in scope else "?"
        endpoint = scope.split("?")[0]
        params = scope[len(endpoint) :]
        response = po.get(path + scope + query + "locale=" + locale)
        assert response.status_code == 200
        report = response.json()
        labels = report["labels"]
        assert report["generated_at"] == "2026-11-15T16:00:00.654321Z"
        row = report["items"][0]
        assert row["total_received"] == row["total_completed"] == 1
        assert row["total_in_progress"] == 0
        assert row["members"][0]["case_revision_id"] == report_setup["first"]["revision_id"]
        assert row["group_counts"][0]["verified_source"] is True
        assert row["group_counts"][0]["source_english"] == "Polling arrangements"
        assert row["approved_by"] == report_setup["reviewer"]["id"]
        text = "\n".join(report["preview_lines"])
        assert "2026-11-15 08:15:00.123456 HKT" in text
        assert "2026-11-16 00:00:00.654321 HKT" in text
        assert report_setup["first"]["case_reference"] in text
        csv_response = po.get(path + endpoint + ".csv" + params + query + "locale=" + locale)
        assert csv_response.status_code == 200
        assert csv_response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        assert [labels["case_reference"], report_setup["first"]["case_reference"]] in rows
        assert [labels["category_revision"], "1"] in rows
        pdf = po.get(path + endpoint + ".pdf" + params + query + "locale=" + locale)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        pages = PdfReader(BytesIO(pdf.content)).pages
        extracted = "\n".join(page.extract_text() for page in pages)
        assert report["title"] in extracted
        assert report_setup["first"]["case_reference"] in extracted
        assert "08:15:00.123456 HKT" in extracted
        note = labels["coverage_legend" if scope == "/statement" else "period_legend"]
        assert "".join(note.split()) in "".join(extracted.split())


def test_current_report_marks_stale_basis_but_never_replaces_frozen_case_content(
    report_setup: dict,
) -> None:
    po, path = report_setup["po"], report_setup["path"]
    case = report_setup["first"]
    changed = po.post(
        report_setup["scope"]["case_path"] + f"/{case['id']}/amend",
        json=complaint_payload(
            report_setup["category"],
            expected_revision=1,
            case_reference="changed-reference",
            work_status="in_progress",
            reason="核對後改回處理中",
        ),
    )
    assert changed.status_code == 200
    report = po.get(path + "/statement?locale=en").json()
    assert report["summary"] == {"required": 3, "missing": 1, "approved_current": 0}
    assert report["outside_coverage_case_count"] == 1
    first = report["items"][0]
    assert first["status"] == "approved" and first["review_required"]
    assert not first["basis_current"] and not first["approval_valid"]
    assert first["approved_by"] == report_setup["approved"]["approved_by"]
    assert first["members"][0]["work_status"] == "completed"
    assert first["members"][0]["case_reference"] == case["case_reference"]
    assert first["members"][0]["revision"] == 1
    assert first["total_completed"] == 1


def test_catalog_rename_and_period_amendment_preserve_historical_labels_and_approvals(
    admin: TestClient,
    report_setup: dict,
) -> None:
    po, path, category = report_setup["po"], report_setup["path"], report_setup["category"]
    renamed = admin.put(
        f"/api/elections/{report_setup['scope']['election']['id']}/complaint-categories/{category['id']}",
        json=category_edit(category, label_tc="新分類名稱", label_en="Renamed category"),
    )
    assert renamed.status_code == 200
    before = po.get(path + "/1/statement?revision=1&locale=en").json()
    assert before["items"][0]["group_counts"][0]["label_en"] == "Polling arrangements"
    assert before["items"][0]["approval_valid"]
    amended = po.post(path + "/1/amend", json=period_command(1, reason="重新核對統計基礎"))
    assert amended.status_code == 200
    historical = po.get(path + "/1/statement?revision=1&locale=tc").json()
    assert historical["revision_state"] == "historical"
    assert historical["summary"] is historical["period_count"] is None
    assert historical["saved_period_count"] is historical["outside_coverage_case_count"] is None
    assert historical["schedule"] == {
        "revision": 2,
        "period_start_at": "2026-11-14T23:30:00Z",
        "period_end_at": "2026-11-15T00:30:00Z",
    }
    row = historical["items"][0]
    assert row["status"] == "approved" and not row["is_latest_revision"]
    assert not row["approval_valid"]
    assert row["approved_at"] == report_setup["approved"]["approved_at"]
    assert row["approved_by"] == report_setup["approved"]["approved_by"]
    assert row["members"][0]["category_label_tc"] == "投票安排"
    assert historical["labels"]["approved_current"] not in "\n".join(historical["preview_lines"])


def test_station_report_collects_saved_periods_beyond_first_page(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin, reporting_interval_minutes=1)
    sid, path = scope["station"]["id"], scope["path"]
    with complaint_staff(admin, database_url, ComplaintClock(), "polling_officer", [sid]) as (
        po,
        _,
    ):
        for index in (1, 107):
            assert po.put(f"{path}/{index}", json=period_command()).status_code == 200
        assert po.get(path).json()["items"][-1]["period_index"] == 100
        report = po.get(path + "/statement?locale=en").json()
        assert report["period_count"] == 160
        assert report["saved_period_count"] == 2
        assert report["summary"]["missing"] == 158
        assert [row["period_index"] for row in report["items"]] == [1, 107]


def test_extreme_schedule_report_remains_bounded_without_materializing_missing_periods(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [scope["station"]["id"]]
    ) as (po, _):
        response = po.get(scope["path"] + "/statement?locale=en")
        assert response.status_code == 200
        report = response.json()
        assert report["summary"] == {
            "required": 4733542080,
            "missing": 4733542080,
            "approved_current": 0,
        }
        assert report["items"] == []
        assert len(response.content) < 30000
        last = 4733542080
        assert po.put(f"{scope['path']}/{last}", json=period_command()).status_code == 200
        saved = po.get(scope["path"] + "/statement?locale=en").json()
        assert [item["period_index"] for item in saved["items"]] == [last]
        assert saved["summary"]["missing"] == last - 1
        assert "10000-01-01 07:59:59.999999 HKT" in "\n".join(report["preview_lines"])


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_assigned_operational_roles_can_read_both_scopes_but_other_station_is_forbidden(
    admin: TestClient,
    database_url: str,
    report_setup: dict,
    role: str,
) -> None:
    with complaint_staff(
        admin, database_url, report_setup["clock"], role, [report_setup["sid"]]
    ) as (client, _):
        for suffix in (
            "/statement",
            "/statement.csv",
            "/statement.pdf",
            "/1/statement?revision=1",
            "/1/statement.csv?revision=1",
            "/1/statement.pdf?revision=1",
        ):
            assert client.get(report_setup["path"] + suffix).status_code == 200
            other = report_setup["scope"]["N2"]["id"]
            assert (
                client.get(
                    f"/api/workspace/stations/{other}/complaint-periods" + suffix
                ).status_code
                == 403
            )


def test_anonymous_temporary_and_administrator_have_no_operational_report_override(
    admin: TestClient,
    database_url: str,
    report_setup: dict,
) -> None:
    path = report_setup["path"]
    with (
        TestClient(create_app(database_url), base_url="https://testserver") as anonymous,
        complaint_staff(
            admin,
            database_url,
            report_setup["clock"],
            "polling_officer",
            [report_setup["sid"]],
            ready=False,
        ) as (temporary, _),
    ):
        for suffix in (
            "/statement",
            "/statement.csv",
            "/statement.pdf",
            "/1/statement?revision=1",
            "/1/statement.csv?revision=1",
            "/1/statement.pdf?revision=1",
        ):
            assert anonymous.get(path + suffix).status_code == 401
            assert temporary.get(path + suffix).status_code == 403
            assert admin.get(path + suffix).status_code == 403


def test_revision_and_locale_validation_never_silently_selects_latest(report_setup: dict) -> None:
    po, path = report_setup["po"], report_setup["path"]
    for suffix in ("/1/statement", "/1/statement?revision=0", "/statement?locale=xx"):
        assert po.get(path + suffix).status_code == 422
    assert po.get(path + "/1/statement?revision=99").status_code == 404
    assert po.get(path + "/99/statement?revision=1").status_code == 404


def test_unsupported_frozen_reference_preserved_in_json_csv_but_pdf_returns_clear_error(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = complaint_period_scope(admin)
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [scope["station"]["id"]]
    ) as (po, _):
        reference = "原始投訴 \U0001f600 =SUM(A1:A2)"
        category = station_categories(po, scope["station"]["id"])[0]
        assert (
            po.post(
                scope["case_path"], json=complaint_payload(category, case_reference=reference)
            ).status_code
            == 201
        )
        assert po.put(scope["path"] + "/1", json=period_command()).status_code == 200
        for endpoint in ("/statement", "/1/statement?revision=1"):
            query = "&" if "?" in endpoint else "?"
            report = po.get(scope["path"] + endpoint + query + "locale=en").json()
            assert report["items"][0]["members"][0]["case_reference"] == reference
            base, _, params = endpoint.partition("?")
            params = "?" + params if params else ""
            csv_response = po.get(scope["path"] + base + ".csv" + params)
            assert reference in csv_response.content.decode("utf-8-sig")
            pdf = po.get(scope["path"] + base + ".pdf" + params)
            assert pdf.status_code == 422
            assert pdf.json()["detail"]["code"] == "report_glyph_unavailable"


def test_retained_finalized_station_history_remains_readable_after_backend_restart(
    database_url: str,
    report_setup: dict,
) -> None:
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            db.execute(
                update(Election)
                .where(Election.id == report_setup["scope"]["election"]["id"])
                .values(status="finalized")
            )
            db.commit()
    finally:
        engine.dispose()
    po, path = report_setup["po"], report_setup["path"]
    credentials = {"username": report_setup["actor"]["username"], "password": READY_PASSWORD}
    with TestClient(
        create_app(database_url, now=report_setup["clock"]), base_url="https://testserver"
    ) as restarted:
        login = restarted.post("/api/auth/login", json=credentials)
        assert login.status_code == 200
        restarted.headers["Authorization"] = "Bearer " + login.json()["token"]
        report = restarted.get(path + "/statement?locale=en")
        assert report.status_code == 200
        assert report.json()["scope"]["election"]["status"] == "finalized"
        assert report.json()["items"] == po.get(path + "/statement?locale=en").json()["items"]
        assert restarted.get(path + "/1/statement.pdf?revision=1").status_code == 200


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_long_frozen_labels_and_reason_flow_without_losing_membership(
    admin: TestClient,
    report_setup: dict,
    locale: str,
) -> None:
    scope, po, path = report_setup["scope"], report_setup["po"], report_setup["path"]
    label_tc = ("保留準備時投訴分類名稱及核實來源文字" * 20)[:255]
    label_sc = ("保留准备时投诉分类名称及核实来源文字" * 20)[:255]
    label_en = ("Project configured label preserved exactly in this frozen report " * 5)[:255]
    custom = admin.post(
        f"/api/elections/{scope['election']['id']}/complaint-categories",
        json={
            "request_id": str(uuid4()),
            "code": "PROJECT-LAYOUT",
            "label_en": label_en,
            "label_tc": label_tc,
            "label_sc": label_sc,
        },
    )
    assert custom.status_code == 201
    reference = "000002-" + "frozen-reference-" * 3
    new_case = po.post(
        scope["case_path"],
        json=complaint_payload(
            custom.json(), case_reference=reference, reason="根據紙本補錄，保留原投訴資料"
        ),
    )
    assert new_case.status_code == 201
    reason = ("核對紙本記錄及凍結分類版本，完整保留主管覆核基礎。" * 50)[:1000]
    amended = po.post(path + "/1/amend", json=period_command(1, reason=reason))
    assert amended.status_code == 200
    assert po.post(path + "/1/submit", json=period_command(2)).status_code == 200
    assert (
        report_setup["sv"]
        .post(path + "/1/approve", json=period_command(2, password=READY_PASSWORD))
        .status_code
        == 200
    )
    query = f"?revision=2&locale={locale}"
    projection = po.get(path + "/1/statement" + query)
    assert projection.status_code == 200
    report = projection.json()
    assert report["items"][0]["amendment_reason"] == reason
    assert report["items"][0]["total_received"] == 2
    assert report["items"][0]["total_completed"] == 1
    assert report["items"][0]["total_in_progress"] == 1
    group = report["items"][0]["group_counts"][1]
    assert not group["verified_source"] and group["source"] == "project_configured"
    csv_response = po.get(path + "/1/statement.csv" + query)
    assert csv_response.status_code == 200
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
    assert [report["labels"]["amendment_reason"], reason] in rows
    pdf = po.get(path + "/1/statement.pdf" + query)
    assert pdf.status_code == 200
    pages = PdfReader(BytesIO(pdf.content)).pages
    assert len(pages) >= 4
    extracted = "".join("".join(page.extract_text().split()) for page in pages)
    for text in (label_tc, label_sc, label_en, reason, reference):
        assert "".join(text.split()) in extracted
    for page in pages:
        assert page.extract_text().strip()
    if os.getenv("ELECTION_WRITE_COMPLAINT_LAYOUT") == "1":
        target = Path("docs/evidence/ticket-13/report-layout")
        target.mkdir(parents=True, exist_ok=True)
        (target / f"complaints-{locale}.pdf").write_bytes(pdf.content)
        (target / f"complaints-{locale}.csv").write_bytes(csv_response.content)
        (target / f"complaints-{locale}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
