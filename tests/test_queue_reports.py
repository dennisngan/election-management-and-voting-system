"""Revision-bound queue statements through the authorized real-MySQL API."""

import csv
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.queue_support import (
    QueueClock,
    active_queue_stations,
    observation,
    queue_account,
    queue_client,
)
from tests.stock_support import stock_payload


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def report_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    contexts = active_queue_stations(admin)
    context = contexts[0]
    station = context["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        first = client.post(
            path,
            json=observation(clock, band="60_90", reason="現場觀察 <輪候> & source\n第二行"),
        )
        assert first.status_code == 201
        clock.value += timedelta(minutes=10)
        confirmation = client.post(
            path + "/confirm",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "current_event_id": first.json()["id"],
                "event_at": clock.value.isoformat(),
            },
        )
        assert confirmation.status_code == 201
        clock.value += timedelta(minutes=30)
        backdated = client.post(
            path,
            json=observation(
                clock,
                expected_revision=2,
                event_at="2026-11-15T00:05:00Z",
                reason="較後補錄的早前觀察",
            ),
        )
        assert backdated.status_code == 201
        yield {
            "client": client,
            "path": path,
            "context": context,
            "other_station": contexts[1]["station"],
            "account": account,
            "clock": clock,
            "items": [first.json(), confirmation.json(), backdated.json()],
        }


def test_selected_revision_statement_derives_freshness_from_its_own_history_prefix(
    admin: TestClient, database_url: str
) -> None:
    context = active_queue_stations(admin)[0]
    station = context["station"]
    account = queue_account(admin, [station["id"]])
    clock = QueueClock()
    path = f"/api/workspace/stations/{station['id']}/queue"
    with queue_client(database_url, account, clock) as client:
        empty = client.get(path + "/statement?revision=0").json()
        assert empty["revision_state"] == "current"
        assert empty["missing"] is True and empty["items"] == []
        assert empty["current"] is None and empty["due_at"] is None
        first = client.post(path, json=observation(clock, band="30_59"))
        assert first.status_code == 201
        clock.value += timedelta(minutes=20)
        second = client.post(path, json=observation(clock, expected_revision=1, band="over_90"))
        assert second.status_code == 201
        clock.value += timedelta(minutes=20)
        response = client.get(path + "/statement?revision=1&locale=tc")
        assert response.status_code == 200
        statement = response.json()
        # The report identity is separate from the live workspace lifecycle revision.
        assert statement["scope"]["election"] == {
            key: context["election"][key] for key in ("id", "name", "status")
        }
        assert statement["scope"]["constituency"] == context["constituency"]
        assert statement["scope"]["station"] == {
            key: station[key] for key in ("id", "name", "code")
        }
        assert statement["items"] == [first.json()]
        assert statement["current"] == first.json()
        assert statement["revision"] == 1
        assert statement["revision_state"] == "historical"
        assert statement["missing"] is False
        assert statement["due_at"] == "2026-11-15T00:30:00Z"
        assert statement["reminder_due"] is True
        assert statement["overdue_periods"] == 1
        assert statement["generated_at"] == "2026-11-15T00:40:00Z"
        assert statement["generation_timezone"] == "Asia/Hong_Kong"
        assert statement["locale"] == "tc"
        assert statement["title"] == "輪候觀察及提醒報表"


@pytest.mark.parametrize(
    ("locale", "title", "band", "confirmation"),
    [
        ("tc", "輪候觀察及提醒報表", "60–90 分鐘", "確認輪候時間不變"),
        ("sc", "轮候观察及提醒报表", "60–90 分钟", "确认轮候时间不变"),
        (
            "en",
            "Queue observations and reminders",
            "60–90 minutes",
            "Waiting time confirmed unchanged",
        ),
    ],
)
@pytest.mark.parametrize("extension", ["csv", "pdf"])
def test_selected_history_exports_preserve_source_context_and_language(
    report_setup: dict, locale: str, title: str, band: str, confirmation: str, extension: str
) -> None:
    preview = report_setup["client"].get(
        report_setup["path"] + f"/statement?revision=2&locale={locale}"
    )
    assert preview.status_code == 200
    preview_lines = preview.json()["preview_lines"]
    assert all(isinstance(line, str) for line in preview_lines)
    assert preview_lines[0] == title and "" in preview_lines
    preview_text = "\n".join(preview_lines)
    assert "2026-11-15 08:00:00 HKT" in preview_text
    assert "2026-11-15 08:10:00 HKT" in preview_text
    assert preview.json()["labels"]["history"] in preview_lines
    assert band in preview_text and confirmation in preview_text
    response = report_setup["client"].get(
        report_setup["path"] + f"/statement.{extension}?revision=2&locale={locale}"
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f'attachment; filename="queue-history-{report_setup["context"]["station"]["id"]}'
        f'-r2-{locale}.{extension}"'
    )
    if extension == "csv":
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        values = [value for row in rows for value in row]
        text = "\n".join(values)
        assert "現場觀察 <輪候> & source\n第二行" in values
        assert str(report_setup["account"]["id"]) in values
        assert str(report_setup["items"][0]["id"]) in values
    else:
        assert response.headers["content-type"] == "application/pdf"
        document = PdfReader(BytesIO(response.content))
        text = "\n".join(page.extract_text() for page in document.pages)
        assert "現場觀察 <輪候> & source" in text
        assert "第二行" in text
        assert document.pages[0].mediabox.width > document.pages[0].mediabox.height
        assert any(
            "/FontFile2" in font.get_object()["/FontDescriptor"]
            for font in (document.pages[0]["/Resources"]["/Font"].get_object().values())
            if "/FontDescriptor" in font.get_object()
        )
    normalized = " ".join(text.split())
    assert title in normalized and band in normalized and confirmation in normalized
    assert report_setup["context"]["election"]["name"] in text
    assert report_setup["context"]["constituency"]["name"] in text
    assert report_setup["context"]["station"]["name"] in text
    assert "2026-11-15 08:00:00 HKT" in text
    assert "2026-11-15 08:10:00 HKT" in text
    assert "2026-11-15 08:40:00 HKT" in text
    assert "Asia/Hong_Kong (UTC+08:00)" in text
    assert "較後補錄的早前觀察" not in text


def test_current_statement_retains_backdated_history_without_replacing_the_latest_observation(
    report_setup: dict,
) -> None:
    response = report_setup["client"].get(report_setup["path"] + "/statement?revision=3&locale=en")
    assert response.status_code == 200
    statement = response.json()
    assert statement["revision_state"] == "current"
    assert statement["items"] == report_setup["items"]
    assert statement["current"] == report_setup["items"][1]
    assert statement["current"]["confirmed_event_id"] == report_setup["items"][0]["id"]
    assert statement["due_at"] == "2026-11-15T00:40:00Z"
    assert statement["reminder_due"] is True
    assert statement["overdue_periods"] == 1
    csv_response = report_setup["client"].get(report_setup["path"] + "/statement.csv?revision=3")
    assert "較後補錄的早前觀察" in csv_response.content.decode("utf-8-sig")


def test_fractional_observation_times_keep_the_correct_current_event_and_reminder_boundary(
    report_setup: dict,
) -> None:
    client, path, clock = report_setup["client"], report_setup["path"], report_setup["clock"]
    latest = client.post(
        path,
        json=observation(
            clock,
            expected_revision=3,
            event_at="2026-11-15T00:10:00.500000Z",
            band="over_90",
        ),
    )
    assert latest.status_code == 201
    backdated = client.post(
        path,
        json=observation(
            clock,
            expected_revision=4,
            event_at="2026-11-15T00:10:00Z",
            band="under_30",
        ),
    )
    assert backdated.status_code == 201
    response = client.get(path + "/statement?revision=5")
    assert response.status_code == 200
    statement = response.json()
    assert statement["current"] == latest.json()
    assert statement["due_at"] == "2026-11-15T00:40:00.500000Z"
    assert statement["reminder_due"] is False and statement["overdue_periods"] == 0
    assert "2026-11-15 08:10:00.500000 HKT" in "\n".join(statement["preview_lines"])
    clock.value += timedelta(microseconds=500000)
    boundary = client.get(path + "/statement?revision=5").json()
    assert boundary["reminder_due"] is True and boundary["overdue_periods"] == 1


@pytest.mark.parametrize(
    ("locale", "missing"),
    [
        ("tc", "尚無輪候觀察；不可視為沒有輪候人士。"),
        ("sc", "尚无轮候观察；不可视为没有轮候人士。"),
        ("en", "No queue observation recorded; this does not mean there is no queue."),
    ],
)
def test_zero_revision_is_explicitly_missing_in_all_report_formats(
    report_setup: dict, locale: str, missing: str
) -> None:
    client, path = report_setup["client"], report_setup["path"]
    response = client.get(path + f"/statement?revision=0&locale={locale}")
    assert response.status_code == 200
    statement = response.json()
    assert statement["revision"] == 0 and statement["revision_state"] == "historical"
    assert statement["missing"] is True
    assert statement["items"] == [] and statement["current"] is None
    assert statement["due_at"] is None and statement["reminder_due"] is False
    assert statement["overdue_periods"] == 0
    csv_response = client.get(path + f"/statement.csv?revision=0&locale={locale}")
    assert csv_response.status_code == 200
    assert missing in csv_response.content.decode("utf-8-sig")
    pdf_response = client.get(path + f"/statement.pdf?revision=0&locale={locale}")
    assert pdf_response.status_code == 200
    document = PdfReader(BytesIO(pdf_response.content))
    text = " ".join(" ".join(page.extract_text().split()) for page in document.pages)
    assert missing in text
    assert "較後補錄的早前觀察" not in text


def test_report_revision_and_locale_validation_and_station_permissions(
    report_setup: dict, admin: TestClient, database_url: str
) -> None:
    client, path = report_setup["client"], report_setup["path"]
    for extension in ("", ".csv", ".pdf"):
        endpoint = path + "/statement" + extension
        assert client.get(endpoint).status_code == 422
        assert client.get(endpoint + "?revision=-1").status_code == 422
        assert client.get(endpoint + "?revision=1&locale=fr").status_code == 422
        missing = client.get(endpoint + "?revision=4")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "queue_revision_not_found"
        denied = client.get(
            f"/api/workspace/stations/{report_setup['other_station']['id']}"
            f"/queue/statement{extension}?revision=0"
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "station_access_denied"
        assert admin.get(endpoint + "?revision=1").status_code == 403
    for role in ("supervisor", "counting_officer"):
        reviewer = queue_account(admin, [report_setup["context"]["station"]["id"]], role=role)
        with queue_client(database_url, reviewer, report_setup["clock"]) as authorized:
            assert authorized.get(path + "/statement?revision=3").status_code == 200
            assert authorized.get(path + "/statement.csv?revision=3").status_code == 200
    password_pending = queue_account(admin, [report_setup["context"]["station"]["id"]])
    with queue_client(
        database_url, password_pending, report_setup["clock"], ready=False
    ) as pending:
        assert pending.get(path + "/statement?revision=3").status_code == 403


@pytest.mark.parametrize("source", ["罕見字𠮷", "輪候🙂", "未定義字\u0378"])
def test_unavailable_pdf_glyph_is_visible_error_and_source_remains_in_preview_and_csv(
    report_setup: dict, source: str
) -> None:
    client, path, clock = report_setup["client"], report_setup["path"], report_setup["clock"]
    saved = client.post(path, json=observation(clock, expected_revision=3, reason=source))
    assert saved.status_code == 201
    preview = client.get(path + "/statement?revision=4")
    assert preview.status_code == 200
    assert preview.json()["items"][-1]["reason"] == source
    exported = client.get(path + "/statement.csv?revision=4")
    assert exported.status_code == 200
    assert source in exported.content.decode("utf-8-sig")
    rejected = client.get(path + "/statement.pdf?revision=4")
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "report_glyph_unavailable"


def test_long_queue_history_pdf_paginates_and_repeats_readable_headers(
    report_setup: dict, tmp_path: Path
) -> None:
    client, path, clock = report_setup["client"], report_setup["path"], report_setup["clock"]
    for revision in range(4, 45):
        clock.value += timedelta(minutes=1)
        reason = "長" * 990 + "最後一段" if revision == 4 else f"觀察序號 {revision:04d}"
        saved = client.post(
            path, json=observation(clock, expected_revision=revision - 1, reason=reason)
        )
        assert saved.status_code == 201
    response = client.get(path + "/statement.pdf?revision=44&locale=tc")
    assert response.status_code == 200
    destination = tmp_path / "queue-history-long-tc.pdf"
    destination.write_bytes(response.content)
    document = PdfReader(BytesIO(response.content))
    assert len(document.pages) >= 3
    texts = [page.extract_text() for page in document.pages]
    combined = "\n".join(texts)
    assert "最後一段" in "".join(combined.split())
    assert combined.count("長") == 990
    for revision in range(5, 45):
        assert f"觀察序號 {revision:04d}" in combined
    for text in texts[1:]:
        compact = "".join(text.split())
        assert "修訂版本" in compact and "輪候時間" in compact
        assert "伺服器記錄時間" in compact and "記錄職員編號" in compact


def test_all_four_waiting_bands_remain_distinct_in_exported_history(report_setup: dict) -> None:
    client, path, clock = report_setup["client"], report_setup["path"], report_setup["clock"]
    for revision, band in enumerate(("30_59", "over_90"), start=4):
        clock.value += timedelta(seconds=1)
        assert (
            client.post(
                path, json=observation(clock, expected_revision=revision - 1, band=band)
            ).status_code
            == 201
        )
    response = client.get(path + "/statement.csv?revision=5&locale=tc")
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    for value in ("少於 30 分鐘", "30–59 分鐘", "60–90 分鐘", "超過 90 分鐘"):
        assert value in text


def test_concurrent_queue_and_stock_pdfs_share_safe_font_builds(
    report_setup: dict, database_url: str
) -> None:
    station_id = report_setup["context"]["station"]["id"]
    client = report_setup["client"]
    stock_path = f"/api/workspace/stations/{station_id}/stock"
    stock = client.post(stock_path, json=stock_payload(series="STOCK_ONLY_SOURCE"))
    assert stock.status_code == 201
    stock_path += f"/{stock.json()['id']}/statement.pdf?revision=1"
    queue_path = report_setup["path"] + "/statement.pdf?revision=3"
    barrier = Barrier(4)
    applications = [create_app(database_url, now=report_setup["clock"]) for _ in range(4)]

    def download(index: int, path: str) -> str:
        with TestClient(applications[index], base_url="https://testserver") as other:
            other.headers["Authorization"] = client.headers["Authorization"]
            barrier.wait(timeout=10)
            response = other.get(path)
            assert response.status_code == 200
            return "\n".join(
                page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(download, index, path)
            for index, path in enumerate(
                (
                    stock_path + "&locale=tc",
                    queue_path + "&locale=tc",
                    stock_path + "&locale=en",
                    queue_path + "&locale=sc",
                )
            )
        ]
        texts = [future.result(timeout=20) for future in futures]
    for text in (texts[0], texts[2]):
        assert "STOCK_ONLY_SOURCE" in text
        assert "現場觀察" not in text
    for text in (texts[1], texts[3]):
        assert "現場觀察" in text
        assert "STOCK_ONLY_SOURCE" not in text
