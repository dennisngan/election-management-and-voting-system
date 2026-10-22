"""Authorized receipt statements preserve the selected revision in every format."""

import csv
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from io import BytesIO, StringIO
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from election.server.app import create_app
from tests.stock_support import (
    INITIAL_PASSWORD,
    READY_PASSWORD,
    ready_client,
    staff_account,
    stock_payload,
    stock_stations,
)


@pytest.fixture
def report_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    stations = stock_stations(admin)
    station = stations[0]
    account = staff_account(admin, [station["id"]])
    with ready_client(database_url, account) as officer:
        path = f"/api/workspace/stations/{station['id']}/stock"
        payload = stock_payload(series="報表系列 " + uuid4().hex[:12])
        response = officer.post(path, json=payload)
        assert response.status_code == 201
        receipt = response.json()
        yield {
            "officer": officer,
            "station": station,
            "other_station": stations[1],
            "account": account,
            "receipt": receipt,
            "payload": payload,
            "path": f"{path}/{receipt['id']}",
        }


def test_assigned_officer_previews_the_exact_receipt_revision_with_generation_context(
    report_setup: dict,
) -> None:
    response = report_setup["officer"].get(report_setup["path"] + "/statement?revision=1&locale=tc")
    assert response.status_code == 200
    preview = response.json()
    assert preview["title"] == "選票接收及儲備報表"
    assert preview["locale"] == "tc"
    assert preview["revision_state"] == "current"
    assert preview["items"] == [report_setup["receipt"]]
    assert preview["scope"]["station"]["id"] == report_setup["station"]["id"]
    assert preview["scope"]["constituency"]["id"] == report_setup["station"]["constituency_id"]
    assert preview["scope"]["election"]["id"] == report_setup["station"]["election_id"]
    generated = datetime.fromisoformat(preview["generated_at"].replace("Z", "+00:00"))
    assert generated.utcoffset() is not None
    assert preview["generation_timezone"] == "Asia/Hong_Kong"
    assert preview["labels"]["ordinary_quantity"] == "普通選票"


@pytest.mark.parametrize(
    ("locale", "title", "ordinary", "replacement", "tendered"),
    [
        ("tc", "選票接收及儲備報表", "普通選票", "替換選票儲備", "重複選票儲備"),
        ("sc", "选票接收及储备报表", "普通选票", "替换选票储备", "重复选票储备"),
        (
            "en",
            "Ballot stock receipt and reserves",
            "Ordinary papers",
            "Replacement reserve",
            "Tendered reserve",
        ),
    ],
)
def test_csv_download_preserves_serials_zero_pools_scope_and_selected_language(
    report_setup: dict,
    locale: str,
    title: str,
    ordinary: str,
    replacement: str,
    tendered: str,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    reason = "按實物單核對 <保留> & original"
    corrected = officer.put(
        path,
        json=stock_payload(
            series=report_setup["payload"]["series"],
            revision=1,
            reason=reason,
            ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": "000010"}],
            ordinary_quantity=10,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert corrected.status_code == 200
    response = officer.get(path + f"/statement.csv?revision=2&locale={locale}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    filename = f"stock-receipt-{report_setup['receipt']['id']}-r2-{locale}.csv"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == [title]
    assert [ordinary, "10"] in rows
    assert [replacement, "0"] in rows
    assert [tendered, "0"] in rows
    assert [ordinary, "000001", "000010", "10"] in rows
    values = [value for row in rows for value in row]
    assert report_setup["payload"]["series"] in values
    assert reason in values
    assert "2026-11-08 08:00:00 HKT" in values
    assert "Asia/Hong_Kong (UTC+08:00)" in values
    assert report_setup["station"]["name"] in " ".join(values)


@pytest.mark.parametrize(
    ("locale", "title", "ordinary", "replacement", "tendered"),
    [
        ("tc", "選票接收及儲備報表", "普通選票", "替換選票儲備", "重複選票儲備"),
        ("sc", "选票接收及储备报表", "普通选票", "替换选票储备", "重复选票储备"),
        (
            "en",
            "Ballot stock receipt and reserves",
            "Ordinary papers",
            "Replacement reserve",
            "Tendered reserve",
        ),
    ],
)
def test_pdf_download_renders_chinese_data_and_safe_literal_text_in_each_language(
    report_setup: dict,
    locale: str,
    title: str,
    ordinary: str,
    replacement: str,
    tendered: str,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    reason = "核對 <選票> & 原始記錄"
    correction = officer.put(
        path,
        json=stock_payload(series="系列 <A&B> " + uuid4().hex[:8], revision=1, reason=reason),
    )
    assert correction.status_code == 200
    response = officer.get(path + f"/statement.pdf?revision=2&locale={locale}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    filename = f"stock-receipt-{report_setup['receipt']['id']}-r2-{locale}.pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    compact = "".join(text.split())
    for expected in (
        title,
        ordinary,
        replacement,
        tendered,
        report_setup["station"]["name"],
        correction.json()["series"],
        reason,
        "000001",
        "000008",
        "000009",
        "000010",
        "2026-11-08 08:00:00 HKT",
        "Asia/Hong_Kong (UTC+08:00)",
    ):
        assert "".join(expected.split()) in compact


def test_historical_statement_formats_keep_old_values_after_a_receipt_correction(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    original = report_setup["receipt"]
    correction = officer.put(
        path,
        json=stock_payload(
            series="新的修正系列 " + uuid4().hex[:8],
            revision=1,
            reason="修正資料但保留原始版本",
            ranges=[{"pool": "ordinary", "serial_from": "000101", "serial_to": "000120"}],
            ordinary_quantity=20,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert correction.status_code == 200
    preview = officer.get(path + "/statement?revision=1&locale=en")
    assert preview.status_code == 200
    assert preview.json()["items"] == [original]
    assert preview.json()["revision_state"] == "historical"
    assert (
        officer.get(path + "/statement?revision=2&locale=en").json()["revision_state"] == "current"
    )
    csv_response = officer.get(path + "/statement.csv?revision=1&locale=en")
    assert csv_response.status_code == 200
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
    assert ["Revision", "1"] in rows
    assert ["Revision state", "Historical revision"] in rows
    assert ["Ballot series", original["series"]] in rows
    assert ["Ordinary papers", "8"] in rows
    assert ["Replacement reserve", "1"] in rows
    assert ["Tendered reserve", "1"] in rows
    pdf_response = officer.get(path + "/statement.pdf?revision=1&locale=en")
    assert pdf_response.status_code == 200
    pdf = PdfReader(BytesIO(pdf_response.content))
    text = "".join("".join(page.extract_text().split()) for page in pdf.pages)
    assert "Historicalrevision" in text
    assert "".join(original["series"].split()) in text
    assert "000001" in text and "000120" not in text
    assert "".join(correction.json()["series"].split()) not in text


def test_many_ranges_and_long_reason_paginate_without_losing_rows_or_chinese(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    reason = "逐頁核對選票來源並保留完整記錄。" * 50
    ranges = [
        {"pool": "ordinary", "serial_from": f"{number:06d}", "serial_to": f"{number:06d}"}
        for number in range(1, 121)
    ]
    corrected = officer.put(
        path,
        json=stock_payload(
            series=report_setup["payload"]["series"],
            revision=1,
            reason=reason,
            ranges=ranges,
            ordinary_quantity=120,
            replacement_quantity=0,
            tendered_quantity=0,
        ),
    )
    assert corrected.status_code == 200
    response = officer.get(path + "/statement.pdf?revision=2&locale=tc")
    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) >= 3
    extracted_pages = [page.extract_text() for page in reader.pages]
    page_texts = ["".join(text.split()) for text in extracted_pages]
    all_text = "".join(page_texts)
    assert reason in all_text
    all_tokens = [token for text in extracted_pages for token in text.split()]
    for number in range(1, 121):
        assert all_tokens.count(f"{number:06d}") == 2
    range_pages = [
        text
        for text in extracted_pages
        if any(f"{number:06d}" in text.split() for number in range(1, 121))
    ]
    assert len(range_pages) >= 2
    for text in range_pages:
        for header in ("選票類別", "起始編號", "結束編號", "數量"):
            assert header in text


def test_a_missing_pdf_glyph_fails_visibly_while_utf8_csv_preserves_the_source(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    series = "選票系列 🦖"
    correction = officer.put(
        path, json=stock_payload(series=series, revision=1, reason="保留實際輸入的系列名稱")
    )
    assert correction.status_code == 200
    response = officer.get(path + "/statement.pdf?revision=2&locale=tc")
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "report_glyph_unavailable"}}
    preview = officer.get(path + "/statement?revision=2&locale=tc")
    assert preview.status_code == 200
    assert preview.json()["items"][0]["series"] == series
    csv_response = officer.get(path + "/statement.csv?revision=2&locale=tc")
    assert csv_response.status_code == 200
    assert series in csv_response.content.decode("utf-8-sig")


def test_exports_preserve_source_and_server_timestamp_precision_in_hong_kong_time(
    report_setup: dict, database_url: str
) -> None:
    fixed_now = datetime(2026, 11, 8, 1, 2, 3, 123456, tzinfo=UTC)
    with TestClient(
        create_app(database_url, now=lambda: fixed_now), base_url="https://testserver"
    ) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": report_setup["account"]["username"], "password": READY_PASSWORD},
        )
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        received = client.post(
            report_setup["path"].rsplit("/", 1)[0],
            json=stock_payload(
                series="精確時間 " + uuid4().hex[:12], event_at="2026-11-08T08:00:00.654321+08:00"
            ),
        )
        assert received.status_code == 201
        path = report_setup["path"].rsplit("/", 1)[0] + "/" + str(received.json()["id"])
        preview = client.get(path + "/statement?revision=1&locale=en")
        assert preview.status_code == 200
        assert preview.json()["generated_at"] == "2026-11-08T01:02:03.123456Z"
        assert preview.json()["items"][0]["event_at"] == "2026-11-08T00:00:00.654321Z"
        assert preview.json()["items"][0]["entered_at"] == "2026-11-08T01:02:03.123456Z"
        csv_response = client.get(path + "/statement.csv?revision=1&locale=en")
        assert csv_response.status_code == 200
        csv_text = csv_response.content.decode("utf-8-sig")
        assert "2026-11-08 08:00:00.654321 HKT" in csv_text
        assert "2026-11-08 09:02:03.123456 HKT" in csv_text
        pdf_response = client.get(path + "/statement.pdf?revision=1&locale=en")
        assert pdf_response.status_code == 200
        pdf = PdfReader(BytesIO(pdf_response.content))
        text = "".join("".join(page.extract_text().split()) for page in pdf.pages)
        assert "2026-11-0808:00:00.654321HKT" in text
        assert "2026-11-0809:02:03.123456HKT" in text


def test_all_statement_formats_require_ready_station_authority(
    report_setup: dict, admin: TestClient, database_url: str
) -> None:
    path = report_setup["path"]
    suffixes = ("/statement", "/statement.csv", "/statement.pdf")
    with TestClient(create_app(database_url), base_url="https://testserver") as client:
        for suffix in suffixes:
            response = client.get(path + suffix + "?revision=1&locale=en")
            assert response.status_code == 401
            assert response.json() == {"detail": {"code": "session_expired"}}
        initial_account = staff_account(admin, [report_setup["station"]["id"]])
        login = client.post(
            "/api/auth/login",
            json={"username": initial_account["username"], "password": INITIAL_PASSWORD},
        )
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        for suffix in suffixes:
            response = client.get(path + suffix + "?revision=1&locale=en")
            assert response.status_code == 403
            assert response.json() == {"detail": {"code": "password_change_required"}}
    outsider = staff_account(admin, [report_setup["other_station"]["id"]])
    with ready_client(database_url, outsider) as unassigned:
        for suffix in suffixes:
            response = unassigned.get(path + suffix + "?revision=1&locale=en")
            assert response.status_code == 403
            assert response.json() == {"detail": {"code": "station_access_denied"}}
    for suffix in suffixes:
        response = admin.get(path + suffix + "?revision=1&locale=en")
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "operational_role_required"}}


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_readers_download_reports_but_a_receipt_cannot_cross_station_scope(
    report_setup: dict, admin: TestClient, database_url: str, role: str
) -> None:
    station, other = report_setup["station"], report_setup["other_station"]
    reader_account = staff_account(admin, [station["id"], other["id"]], role)
    receipt_id = report_setup["receipt"]["id"]
    with ready_client(database_url, reader_account) as reader:
        for suffix in ("/statement", "/statement.csv", "/statement.pdf"):
            good = reader.get(report_setup["path"] + suffix + "?revision=1&locale=tc")
            assert good.status_code == 200
            wrong = reader.get(
                f"/api/workspace/stations/{other['id']}/stock/{receipt_id}{suffix}?revision=1&locale=tc"
            )
            assert wrong.status_code == 404
            assert wrong.json() == {"detail": {"code": "stock_receipt_not_found"}}


def test_statement_queries_require_an_existing_explicit_revision_and_supported_locale(
    report_setup: dict,
) -> None:
    for suffix in ("/statement", "/statement.csv", "/statement.pdf"):
        for query in (
            "locale=tc",
            "revision=0&locale=tc",
            "revision=-1&locale=tc",
            "revision=wrong&locale=tc",
            "revision=1&locale=unsupported",
        ):
            response = report_setup["officer"].get(report_setup["path"] + suffix + "?" + query)
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "validation_error"
        missing = report_setup["officer"].get(
            report_setup["path"] + suffix + "?revision=999&locale=tc"
        )
        assert missing.status_code == 404
        assert missing.json() == {"detail": {"code": "stock_receipt_not_found"}}


def test_supplementary_chinese_is_faithful_in_pdf_or_rejected_without_silent_corruption(
    report_setup: dict,
) -> None:
    officer, path = report_setup["officer"], report_setup["path"]
    series = "𠮷氏選票系列"
    changed = officer.put(
        path, json=stock_payload(series=series, revision=1, reason="保留原始漢字，不可靜默替換")
    )
    assert changed.status_code == 200
    preview = officer.get(path + "/statement?revision=2&locale=tc")
    assert preview.json()["items"][0]["series"] == series
    csv_response = officer.get(path + "/statement.csv?revision=2&locale=tc")
    assert csv_response.status_code == 200
    assert series in csv_response.content.decode("utf-8-sig")
    pdf_response = officer.get(path + "/statement.pdf?revision=2&locale=tc")
    assert pdf_response.status_code in (200, 422)
    if pdf_response.status_code == 422:
        assert pdf_response.json() == {"detail": {"code": "report_glyph_unavailable"}}
    else:
        reader = PdfReader(BytesIO(pdf_response.content))
        text = "".join("".join(page.extract_text().split()) for page in reader.pages)
        assert series in text


def test_three_clients_export_distinct_multilingual_pdfs_concurrently_without_row_leaks(
    admin: TestClient, database_url: str
) -> None:
    stations = stock_stations(admin)
    cases = [
        ("tc", "甲站繁體獨立系列", 100001, 140, "選票接收及儲備報表", "選區 N"),
        ("sc", "乙站简体独立系列", 200001, 160, "选票接收及储备报表", "選區 N"),
        (
            "en",
            "丙站 Mixed English 中文系列",
            300001,
            180,
            "Ballot stock receipt and reserves",
            "選區 S",
        ),
    ]
    application = create_app(database_url)
    barrier = Barrier(3)
    requests = []
    with ExitStack() as stack:
        for station, (locale, series, first, count, title, constituency) in zip(
            stations, cases, strict=True
        ):
            account = staff_account(admin, [station["id"]])
            client = stack.enter_context(TestClient(application, base_url="https://testserver"))
            login = client.post(
                "/api/auth/login",
                json={"username": account["username"], "password": INITIAL_PASSWORD},
            )
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
            changed = client.post(
                "/api/auth/password",
                json={"current_password": INITIAL_PASSWORD, "new_password": READY_PASSWORD},
            )
            assert changed.status_code == 200
            client.headers["Authorization"] = "Bearer " + changed.json()["token"]
            ranges = [
                {"pool": "ordinary", "serial_from": str(number), "serial_to": str(number)}
                for number in range(first, first + count)
            ] + [
                {
                    "pool": "replacement",
                    "serial_from": str(first + count),
                    "serial_to": str(first + count + 2),
                },
                {
                    "pool": "tendered",
                    "serial_from": str(first + count + 3),
                    "serial_to": str(first + count + 4),
                },
            ]
            received = client.post(
                f"/api/workspace/stations/{station['id']}/stock",
                json=stock_payload(
                    series=series,
                    ranges=ranges,
                    ordinary_quantity=count,
                    replacement_quantity=3,
                    tendered_quantity=2,
                ),
            )
            assert received.status_code == 201
            requests.append(
                {
                    "client": client,
                    "path": f"/api/workspace/stations/{station['id']}/stock/{received.json()['id']}"
                    + f"/statement.pdf?revision=1&locale={locale}",
                    "series": series,
                    "station": station["name"],
                    "constituency": constituency,
                    "title": title,
                    "serials": Counter(
                        row[key] for row in ranges for key in ("serial_from", "serial_to")
                    ),
                }
            )

        def download(index: int) -> bytes:
            request = requests[index]
            barrier.wait(timeout=10)
            response = request["client"].get(request["path"])
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            return response.content

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(download, range(3)))

        for index, content in enumerate(results):
            expected = requests[index]
            reader = PdfReader(BytesIO(content))
            assert len(reader.pages) >= 3
            pages = [page.extract_text() for page in reader.pages]
            tokens = Counter(token for text in pages for token in text.split())
            compact = "".join("".join(text.split()) for text in pages)
            for value in (
                expected["series"],
                expected["station"],
                expected["constituency"],
                expected["title"],
            ):
                assert "".join(value.split()) in compact
            for serial, occurrences in expected["serials"].items():
                assert tokens[serial] == occurrences
            for other_index, foreign in enumerate(requests):
                if other_index == index:
                    continue
                assert "".join(foreign["series"].split()) not in compact
                assert "".join(foreign["station"].split()) not in compact
                assert not set(foreign["serials"]).intersection(tokens)
