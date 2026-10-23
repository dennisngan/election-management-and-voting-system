"""P(15) reports use saved server figures and explicit approval coverage."""

import csv
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import (
    TurnoutClock,
    approve_period,
    arrange_finalized_turnout_election,
    submit_period,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def report_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    scope, clock = (
        turnout_scope(admin),
        TurnoutClock(datetime(2026, 11, 15, 4, 0, 0, 654321, tzinfo=UTC)),
    )
    station_id, path = scope["stations"][0]["id"], scope["path"]
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, account),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        source = "外部 <紙本> & original\n保留來源文字"
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=9223372036854775807,
            supplied_cumulative=9223372036854775807,
            event_at="2026-11-15T01:30:00.123456Z",
            source_context=source,
        )
        first = approve_period(supervisor, path, 1)
        submit_period(
            officer,
            path,
            2,
            supplied_cumulative=9223372036854775807,
            event_at="2026-11-15T02:30:00.500000Z",
            source_context="下一時段明確零增幅",
        )
        second = approve_period(supervisor, path, 2)
        yield {
            "scope": scope,
            "clock": clock,
            "officer": officer,
            "account": account,
            "supervisor": supervisor,
            "path": path,
            "first": first,
            "second": second,
            "source": source,
        }


def test_station_p15_reports_explicit_zero_and_missing_periods_from_saved_server_data(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(admin)
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (officer, _),
        turnout_staff(admin, database_url, clock, [station_id], "supervisor") as (supervisor, _),
    ):
        submit_period(
            officer,
            path,
            1,
            supplied_hourly=0,
            event_at="2026-11-15T01:30:00Z",
            source_context="外部紙本 <原樣> & zero\n明確零人",
        )
        approved = approve_period(supervisor, path, 1)
        response = officer.get(path + "/statement?locale=tc")
        assert response.status_code == 200
        report = response.json()
        assert report["report_scope"] == "station_current"
        assert report["scope"]["station"]["id"] == station_id
        assert report["period_count"] == 3
        assert report["saved_period_count"] == 1
        assert report["missing_period_count"] == 2
        assert report["approved_prefix"]["cumulative_end"] == 0
        assert report["items"][0]["id"] == approved["id"]
        assert report["items"][0]["approval_valid"] is True
        assert report["items"][0]["review_required"] is False
        assert report["items"][0]["supplied_hourly"] == 0
        assert report["items"][0]["supplied_cumulative"] is None
        assert report["generation_timezone"] == "Asia/Hong_Kong"
        assert report["generated_at"] == "2026-11-15T04:00:00Z"
        assert report["preview_lines"]
        assert "外部紙本 <原樣> & zero\n明確零人" in "\n".join(report["preview_lines"])


@pytest.mark.parametrize(
    "locale,title",
    [
        ("tc", "P(15) 時段及累計投票人數報表"),
        ("sc", "P(15) 时段及累计投票人数报表"),
        ("en", "P(15) period and cumulative turnout"),
    ],
)
def test_all_formats_preserve_exact_signed64_source_and_fractional_hkt_times(
    report_setup: dict, locale: str, title: str
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    projection = officer.get(path + f"/statement?locale={locale}").json()
    assert projection["title"] == title
    assert projection["approved_prefix"]["cumulative_end"] == 9223372036854775807
    assert projection["items"][1]["derived_hourly"] == 0
    assert projection["missing_period_count"] == 1
    assert projection["generated_at"] == "2026-11-15T04:00:00.654321Z"
    text = "\n".join(projection["preview_lines"])
    assert "9223372036854775807" in text
    assert "2026-11-15 09:30:00.123456 HKT" in text
    assert "2026-11-15 12:00:00.654321 HKT" in text
    csv_response = officer.get(path + f"/statement.csv?locale={locale}")
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert csv_response.headers["content-type"] == "text/csv; charset=utf-8"
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
    labels = projection["labels"]
    assert [labels["source_context"], report_setup["source"]] in rows
    assert [labels["supplied_hourly"], "9223372036854775807"] in rows
    assert [labels["derived_hourly"], "0"] in rows
    pdf_response = officer.get(path + f"/statement.pdf?locale={locale}")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    pages = PdfReader(BytesIO(pdf_response.content)).pages
    extracted = "\n".join(page.extract_text() for page in pages)
    assert title in extracted
    assert "9223372036854775807" in extracted
    assert "外部 <紙本> & original" in extracted
    assert "09:30:00.123456 HKT" in extracted
    assert "".join(labels["coverage_legend"].split()) in "".join(extracted.split())
    for page in pages:
        page_text = page.extract_text()
        if labels["details"] in page_text:
            assert labels["field"] in page_text


def test_historical_revision_keeps_original_approval_without_current_station_totals(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    amended = officer.post(
        path + "/1/amend",
        json=turnout_draft(
            1,
            supplied_hourly=9223372036854775806,
            event_at="2026-11-15T01:30:00.123456Z",
            source_context="核對後的來源",
            amendment_reason="紙本數字修訂減一",
        ),
    )
    assert amended.status_code == 200
    current = officer.get(path + "/statement?locale=en").json()
    assert current["approved_prefix"]["cumulative_end"] is None
    assert current["items"][1]["review_required"] is True
    assert current["items"][1]["approved_by"] == report_setup["second"]["approved_by"]
    historical = officer.get(path + "/1/statement?revision=1&locale=en")
    assert historical.status_code == 200
    report = historical.json()
    assert report["report_scope"] == "period_revision"
    assert report["revision_state"] == "historical"
    assert report["approved_prefix"] is None
    assert report["period_count"] is None and report["missing_period_count"] is None
    item = report["items"][0]
    assert item["status"] == "approved"
    assert item["supplied_hourly"] == 9223372036854775807
    assert item["derived_cumulative_end"] == 9223372036854775807
    assert item["approved_by"] == report_setup["first"]["approved_by"]
    assert item["approved_at"] == report_setup["first"]["approved_at"]
    assert item["source_context"] == report_setup["source"]
    assert item["is_current"] is False
    assert item["approval_valid"] is False and item["review_required"] is False
    preview = "\n".join(report["preview_lines"])
    assert report["labels"]["approved_total"] not in preview
    assert "Original approving account ID" in preview


def test_station_statement_includes_saved_periods_outside_the_first_controller_page(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(
        admin, planned_closing_at="2026-11-15T10:18:00+08:00", reporting_interval_minutes=1
    )
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        for index in (1, 107):
            assert (
                officer.put(f"{path}/{index}", json=turnout_draft(supplied_hourly=0)).status_code
                == 200
            )
        assert officer.get(path).json()["items"][-1]["period_index"] == 100
        report = officer.get(path + "/statement?locale=en").json()
        assert report["period_count"] == 108
        assert report["saved_period_count"] == 2
        assert report["missing_period_count"] == 106
        assert [row["period_index"] for row in report["items"]] == [1, 107]


def test_empty_extreme_station_report_counts_missing_periods_without_enumerating_them(
    admin: TestClient, database_url: str
) -> None:
    scope = turnout_scope(
        admin,
        election_date="1000-01-01",
        planned_opening_at="1000-01-01T08:00:00+08:00",
        planned_closing_at="9999-12-31T23:59:59.999999Z",
        reporting_interval_minutes=1,
    )
    station_id, path, clock = scope["stations"][0]["id"], scope["path"], TurnoutClock()
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, _):
        response = officer.get(path + "/statement?locale=en")
        assert response.status_code == 200
        report = response.json()
        assert report["period_count"] == 4733542080
        assert report["missing_period_count"] == 4733542080
        assert report["saved_period_count"] == 0
        assert report["items"] == []
        assert report["approved_prefix"]["cumulative_end"] is None
        assert len(report["preview_lines"]) < 100
        assert len(response.content) < 25000
        assert "10000-01-01 07:59:59.999999 HKT" in "\n".join(report["preview_lines"])


def test_unsupported_source_glyph_remains_in_json_csv_and_pdf_fails_explicitly(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    source = "保留原字 \U0001f600 and =SUM(A1:A2)"
    assert (
        officer.put(
            path + "/3", json=turnout_draft(supplied_hourly=0, source_context=source)
        ).status_code
        == 200
    )
    projection = officer.get(path + "/3/statement?revision=1&locale=tc")
    assert projection.status_code == 200
    assert projection.json()["items"][0]["source_context"] == source
    csv_response = officer.get(path + "/3/statement.csv?revision=1&locale=tc")
    assert csv_response.status_code == 200
    assert source in csv_response.content.decode("utf-8-sig")
    pdf = officer.get(path + "/3/statement.pdf?revision=1&locale=tc")
    assert pdf.status_code == 422
    assert pdf.json()["detail"]["code"] == "report_glyph_unavailable"


def test_selected_reports_reject_invalid_scope_or_revision_and_remain_readable_when_finalized(
    report_setup: dict,
    database_url: str,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    for suffix, status in (
        ("/1/statement?revision=0", 422),
        ("/1/statement?revision=99", 404),
        ("/3/statement?revision=1", 404),
        ("/4/statement?revision=1", 404),
        ("/statement?locale=fr", 422),
    ):
        assert officer.get(path + suffix).status_code == status
    arrange_finalized_turnout_election(database_url, report_setup["scope"]["election"]["id"])
    retained = officer.get(path + "/statement?locale=en")
    assert retained.status_code == 200
    assert retained.json()["scope"]["election"]["status"] == "finalized"
    assert officer.get(path + "/1/statement.csv?revision=1&locale=en").status_code == 200
    assert officer.get(path + "/1/statement.pdf?revision=1&locale=en").status_code == 200


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_every_report_format_enforces_assigned_operational_read_scope(
    report_setup: dict,
    admin: TestClient,
    database_url: str,
    role: str,
) -> None:
    scope, clock, path = report_setup["scope"], report_setup["clock"], report_setup["path"]
    station_id, other_id = [station["id"] for station in scope["stations"]]
    with turnout_staff(admin, database_url, clock, [station_id], role) as (reader, _):
        for suffix in (
            "/statement",
            "/statement.csv",
            "/statement.pdf",
            "/1/statement?revision=1",
            "/1/statement.csv?revision=1",
            "/1/statement.pdf?revision=1",
        ):
            assert reader.get(path + suffix).status_code == 200
            denied = reader.get(f"/api/workspace/stations/{other_id}/turnout" + suffix)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "station_access_denied"


def test_reports_reject_anonymous_temporary_password_and_administrator_override(
    report_setup: dict,
    admin: TestClient,
    database_url: str,
) -> None:
    scope, clock, path = report_setup["scope"], report_setup["clock"], report_setup["path"]
    station_id = scope["stations"][0]["id"]
    with (
        TestClient(create_app(database_url, now=clock)) as anonymous,
        turnout_staff(admin, database_url, clock, [station_id], ready=False) as (temporary, _),
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


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_long_source_and_whole_signed64_amounts_survive_pdf_pagination(
    report_setup: dict,
    locale: str,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    beginning, ending = "BEGIN_SOURCE_11\n", "\nEND_SOURCE_11"
    repeated = 2000 - len(beginning) - len(ending)
    source = beginning + "永" * repeated + ending
    assert (
        officer.put(
            path + "/3",
            json=turnout_draft(supplied_hourly=9223372036854775807, source_context=source),
        ).status_code
        == 200
    )
    projection = officer.get(path + f"/statement?locale={locale}")
    assert projection.status_code == 200
    pdf = officer.get(path + f"/statement.pdf?locale={locale}")
    assert pdf.status_code == 200
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) > 1
    text = "\n".join(page.extract_text() for page in reader.pages)
    labels = projection.json()["labels"]
    for page in reader.pages:
        page_text = page.extract_text()
        if labels["details"] in page_text:
            assert labels["field"] in page_text
    assert "BEGIN_SOURCE_11" in text and "END_SOURCE_11" in text
    assert text.count("永") == repeated
    assert "9223372036854775807" in text
    csv_response = officer.get(path + f"/statement.csv?locale={locale}")
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
    assert [projection.json()["labels"]["source_context"], source] in rows
    if os.getenv("ELECTION_WRITE_TURNOUT_LAYOUT") == "1":
        output = Path("docs/evidence/ticket-11/report-layout")
        output.mkdir(parents=True, exist_ok=True)
        (output / f"turnout-{locale}.pdf").write_bytes(pdf.content)
        (output / f"turnout-{locale}.csv").write_bytes(csv_response.content)
        (output / f"turnout-{locale}.json").write_text(
            json.dumps(projection.json(), ensure_ascii=False, indent=2)
        )
