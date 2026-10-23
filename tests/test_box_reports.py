"""Station handover reports retain physical box identity and unrecorded count values."""

import csv
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO, StringIO
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from election.server.app import create_app
from tests.box_support import (
    INITIAL_PASSWORD,
    READY_PASSWORD,
    BoxClock,
    box_staff,
    box_stations,
    event_command,
    prepared_box,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import arrange_retained_polling_election
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
    stations, clock = box_stations(admin), BoxClock()
    source = f"/api/workspace/stations/{stations['N2']['id']}/boxes"
    target = f"/api/workspace/stations/{stations['N1']['id']}/boxes"
    with ExitStack() as stack:
        sender, po = stack.enter_context(
            box_staff(
                admin,
                database_url,
                clock,
                "polling_officer",
                [stations[key]["id"] for key in ("N1", "N2")],
            )
        )
        receiver, co = stack.enter_context(
            box_staff(
                admin,
                database_url,
                clock,
                "counting_officer",
                [stations["N1"]["id"]],
            )
        )
        commands = []

        def saved(client: TestClient, method: str, path: str, payload: dict) -> dict:
            commands.append(payload)
            response = getattr(client, method)(path, json=payload)
            assert response.status_code in (200, 201)
            return response.json()

        prepared = saved(
            sender,
            "post",
            source,
            prepared_box(
                box_reference="票箱 000001",
                seal_reference="封條 000099",
                prepared_at="2026-11-15T22:40:00.123456+08:00",
            ),
        )
        box_id = prepared["id"]
        departed = saved(
            sender,
            "post",
            f"{source}/{box_id}/departure",
            event_command(
                1,
                "2026-11-15T22:45:00.500000+08:00",
            ),
        )
        received = saved(
            receiver,
            "post",
            f"{target}/{box_id}/receipt",
            event_command(
                2,
                "2026-11-15T23:00:00.250000+08:00",
            ),
        )
        departure_reason = "核對離站 <紙本> & original\n修正一分鐘"
        corrected_departure = saved(
            sender,
            "put",
            f"{source}/{box_id}/departure",
            event_command(
                3,
                "2026-11-15T22:46:00.500000+08:00",
                reason=departure_reason,
            ),
        )
        receipt_reason = "核對接收；保留原始值"
        corrected_receipt = saved(
            receiver,
            "put",
            f"{target}/{box_id}/receipt",
            event_command(
                4,
                "2026-11-15T23:01:00.250000+08:00",
                reason=receipt_reason,
            ),
        )
        for kind, revision, at, reason, opening_box in (
            ("conversion_complete", 0, "23:02:00", "", None),
            ("conversion_complete", 1, "23:03:00", "核對場地轉換紀錄", None),
            ("first_box_opening", 0, "23:05:00", "", box_id),
            ("questionable_determination_start", 0, "23:10:00", "", None),
        ):
            saved(
                receiver,
                "put",
                target + "/milestones/" + kind,
                event_command(
                    revision,
                    f"2026-11-15T{at}+08:00",
                    reason=reason,
                    box_id=opening_box,
                ),
            )
        yield {
            "sender": sender,
            "receiver": receiver,
            "source": source,
            "target": target,
            "stations": stations,
            "clock": clock,
            "po": po,
            "co": co,
            "prepared": prepared,
            "departed": departed,
            "received": received,
            "corrected_departure": corrected_departure,
            "box": corrected_receipt,
            "departure_reason": departure_reason,
            "receipt_reason": receipt_reason,
            "commands": commands,
        }


def test_receiver_previews_origin_handover_and_missing_count_completion(
    admin: TestClient, database_url: str
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, _):
        path = f"/api/workspace/stations/{origin['id']}/boxes"
        created = sender.post(path, json=prepared_box())
        assert created.status_code == 201
        box = created.json()
        departed = sender.post(
            f"{path}/{box['id']}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert departed.status_code == 201
    with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
        receiver,
        _,
    ):
        path = f"/api/workspace/stations/{destination['id']}/boxes"
        received = receiver.post(
            f"{path}/{box['id']}/receipt",
            json=event_command(2, "2026-11-15T23:00:00+08:00"),
        )
        assert received.status_code == 201
        response = receiver.get(path + "/statement?locale=tc")
        assert response.status_code == 200
        report = response.json()
        assert report["scope"]["station"]["id"] == destination["id"]
        assert report["items"][0]["origin"]["id"] == origin["id"]
        assert report["items"][0]["destination"]["id"] == destination["id"]
        assert report["items"][0]["status"] == "received"
        assert report["items"][0]["revision"] == 3
        assert report["count_completion"] is None
        assert report["milestones"] == []
        assert len(report["box_history"]) == 3
        assert "2026-11-15 23:00:00 HKT" in "\n".join(report["preview_lines"])


def test_current_statement_preserves_corrections_original_times_sources_and_safe_preview(
    report_setup: dict,
) -> None:
    response = report_setup["receiver"].get(report_setup["target"] + "/statement?locale=tc")
    assert response.status_code == 200
    report = response.json()
    assert report["items"] == [report_setup["box"]]
    assert report["items"][0]["origin"]["code"] == "N2"
    assert report["items"][0]["destination"]["code"] == "N1"
    assert [row["kind"] for row in report["box_history"]] == [
        "prepared",
        "departure",
        "receipt",
        "departure_correction",
        "receipt_correction",
    ]
    assert [row["revision"] for row in report["box_history"]] == [1, 2, 3, 4, 5]
    assert [row["event_at"] for row in report["box_history"]] == [
        "2026-11-15T14:40:00.123456Z",
        "2026-11-15T14:45:00.500000Z",
        "2026-11-15T15:00:00.250000Z",
        "2026-11-15T14:46:00.500000Z",
        "2026-11-15T15:01:00.250000Z",
    ]
    assert [row["actor_id"] for row in report["box_history"]] == [
        report_setup["po"]["id"],
        report_setup["po"]["id"],
        report_setup["co"]["id"],
        report_setup["po"]["id"],
        report_setup["co"]["id"],
    ]
    assert all(row["entered_at"] == "2026-11-15T16:00:00Z" for row in report["box_history"])
    assert [row["revision"] for row in report["milestone_history"]] == [1, 2, 1, 1]
    assert report["milestone_history"][0]["event_at"] == "2026-11-15T15:02:00Z"
    assert report["milestones"][0]["event_at"] == "2026-11-15T15:03:00Z"
    assert report["count_completion"] is None and report["counting_applicable"] is True
    assert report["generated_at"] == "2026-11-15T16:00:00Z"
    assert report["generation_timezone"] == "Asia/Hong_Kong"
    lines = report["preview_lines"]
    assert lines[0] == "票箱交收及點票工作時間表" and "" in lines
    assert all(isinstance(line, str) for line in lines)
    preview = "\n".join(lines)
    assert "N2 · 票箱測試站 N2" in preview and "N1 · 票箱測試站 N1" in preview
    assert "票箱 000001" in preview and "封條 000099" in preview
    assert "2026-11-15 22:40:00.123456 HKT" in preview
    assert "點票完成時間: 尚未記錄" in preview
    assert report_setup["departure_reason"] in preview
    serialized = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "request_id",
        "payload_digest",
        "password",
        "token",
        INITIAL_PASSWORD,
        READY_PASSWORD,
    ):
        assert forbidden not in serialized
    assert all(command["request_id"] not in serialized for command in report_setup["commands"])
    assert not ({"accounting", "turnout", "valid_votes", "counted_total"} & report.keys())


@pytest.mark.parametrize(
    ("locale", "title", "completion_label", "missing"),
    [
        ("tc", "票箱交收及點票工作時間表", "點票完成時間", "尚未記錄"),
        ("sc", "票箱交收及点票工作时间表", "点票完成时间", "尚未记录"),
        (
            "en",
            "Ballot-box handover and counting timeline",
            "Count completion time",
            "Not recorded",
        ),
    ],
)
@pytest.mark.parametrize("extension", ["csv", "pdf"])
def test_multilingual_exports_retain_source_revisions_fractional_times_and_missing_count(
    report_setup: dict, locale: str, title: str, completion_label: str, missing: str, extension: str
) -> None:
    response = report_setup["receiver"].get(
        report_setup["target"] + f"/statement.{extension}?locale={locale}"
    )
    assert response.status_code == 200
    station_id = report_setup["stations"]["N1"]["id"]
    assert response.headers["content-disposition"] == (
        f'attachment; filename="box-handover-{station_id}-{locale}.{extension}"'
    )
    if extension == "csv":
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0] == [title]
        assert [completion_label, missing] in rows
        assert any(report_setup["departure_reason"] in row for row in rows)
        assert any(report_setup["receipt_reason"] in row for row in rows)
        values = [value for row in rows for value in row]
        assert "票箱 000001" in values and "封條 000099" in values
        assert "2026-11-15 22:40:00.123456 HKT" in values
        assert "2026-11-15 22:45:00.500000 HKT" in values
        assert "2026-11-15 22:46:00.500000 HKT" in values
        assert str(report_setup["po"]["id"]) in values and str(report_setup["co"]["id"]) in values
        text = "\n".join(values)
    else:
        assert response.headers["content-type"] == "application/pdf"
        document = PdfReader(BytesIO(response.content))
        text = "\n".join(page.extract_text() for page in document.pages)
        assert "核對離站 <紙本> & original" in text and "修正一分鐘" in text
        assert document.pages[0].mediabox.width > document.pages[0].mediabox.height
        for page in document.pages:
            fonts = page["/Resources"]["/Font"].get_object().values()
            assert any(
                "/ToUnicode" in font.get_object()
                and "/FontDescriptor" in font.get_object()
                and "/FontFile2" in font.get_object()["/FontDescriptor"]
                for font in fonts
            )
    normalized = " ".join(text.split())
    assert title in normalized and completion_label in normalized and missing in normalized
    assert "N2 · 票箱測試站 N2" in normalized and "N1 · 票箱測試站 N1" in normalized
    assert "Asia/Hong_Kong (UTC+08:00)" in text
    assert "2026-11-16 00:00:00 HKT" in normalized
    for forbidden in (INITIAL_PASSWORD, READY_PASSWORD, "request_id", "payload_digest"):
        assert forbidden not in text
    assert all(command["request_id"] not in text for command in report_setup["commands"])


@pytest.mark.parametrize(
    ("locale", "not_applicable"),
    [
        ("tc", "不適用（本站送箱至點票站）"),
        ("sc", "不适用（本站送箱至点票站）"),
        ("en", "Not applicable (boxes sent to the counting destination)"),
    ],
)
def test_sending_station_reports_counting_as_not_applicable_and_retains_destination_history(
    report_setup: dict, locale: str, not_applicable: str
) -> None:
    client, path = report_setup["sender"], report_setup["source"]
    response = client.get(path + f"/statement?locale={locale}")
    assert response.status_code == 200
    report = response.json()
    assert report["counting_applicable"] is False and report["count_completion"] is None
    assert report["milestones"] == [] and report["milestone_history"] == []
    assert report["items"] == [report_setup["box"]]
    assert report["items"][0]["origin"]["code"] == "N2"
    assert report["items"][0]["destination"]["code"] == "N1"
    assert not_applicable in "\n".join(report["preview_lines"])
    exported = client.get(path + f"/statement.csv?locale={locale}")
    assert exported.status_code == 200
    rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
    assert [report["labels"]["count_completion"], not_applicable] in rows
    assert [report["labels"]["counting_applicable"], report["labels"]["no"]] in rows


@pytest.mark.parametrize(
    ("locale", "empty", "missing"),
    [
        ("tc", "尚無已記錄的票箱；不代表實際沒有票箱。", "尚未記錄"),
        ("sc", "尚无已记录的票箱；不代表实际没有票箱。", "尚未记录"),
        (
            "en",
            "No boxes recorded; this does not mean there are no physical boxes.",
            "Not recorded",
        ),
    ],
)
def test_empty_counting_station_is_explicitly_unrecorded_in_each_report_format(
    admin: TestClient, database_url: str, locale: str, empty: str, missing: str
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    station = stations["N3"]
    with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (client, _):
        path = f"/api/workspace/stations/{station['id']}/boxes/statement"
        report = client.get(path + f"?locale={locale}").json()
        assert report["items"] == [] and report["box_history"] == []
        assert report["milestones"] == [] and report["milestone_history"] == []
        assert report["counting_applicable"] is True and report["count_completion"] is None
        assert empty in "\n".join(report["preview_lines"])
        assert report["labels"]["count_completion"] + ": " + missing in report["preview_lines"]
        for extension in ("csv", "pdf"):
            response = client.get(path + f".{extension}?locale={locale}")
            assert response.status_code == 200
            if extension == "csv":
                text = response.content.decode("utf-8-sig")
            else:
                text = "\n".join(
                    page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
                )
            assert empty in " ".join(text.split()) and missing in text


def test_report_permissions_and_locale_validation_do_not_expose_other_station_records(
    report_setup: dict, admin: TestClient, database_url: str
) -> None:
    client, path = report_setup["receiver"], report_setup["target"]
    wrong = f"/api/workspace/stations/{report_setup['stations']['N3']['id']}/boxes"
    with TestClient(
        create_app(database_url, now=report_setup["clock"]), base_url="https://testserver"
    ) as anonymous:
        for extension in ("", ".csv", ".pdf"):
            endpoint = path + "/statement" + extension
            assert anonymous.get(endpoint).status_code == 401
            assert admin.get(endpoint).status_code == 403
            denied = client.get(wrong + "/statement" + extension)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "station_access_denied"
            invalid = client.get(endpoint + "?locale=fr")
            assert invalid.status_code == 422
            assert invalid.json()["detail"]["code"] == "validation_error"
    station_id = report_setup["stations"]["N1"]["id"]
    with box_staff(
        admin, database_url, report_setup["clock"], "polling_officer", [station_id], ready=False
    ) as (pending, _):
        for extension in ("", ".csv", ".pdf"):
            denied = pending.get(path + "/statement" + extension)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "password_change_required"
    default = client.get(path + "/statement")
    assert default.status_code == 200 and default.json()["locale"] == "tc"


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_assigned_roles_report_retained_history_even_while_a_different_election_is_active(
    report_setup: dict, admin: TestClient, database_url: str, role: str
) -> None:
    station_id = report_setup["stations"]["N1"]["id"]
    with box_staff(admin, database_url, report_setup["clock"], role, [station_id]) as (client, _):
        arrange_retained_polling_election(database_url, report_setup["stations"]["election"]["id"])
        box_stations(admin)
        path = report_setup["target"] + "/statement"
        response = client.get(path + "?locale=en")
        assert response.status_code == 200
        report = response.json()
        assert report["scope"]["election"]["status"] == "finalized"
        assert report["items"] == [report_setup["box"]]
        assert "Finalized" in "\n".join(report["preview_lines"])
        for extension in ("csv", "pdf"):
            assert client.get(path + "." + extension + "?locale=en").status_code == 200
        with TestClient(
            create_app(database_url, now=report_setup["clock"]), base_url="https://testserver"
        ) as restarted:
            restarted.headers.update(client.headers)
            assert restarted.get(path + "?locale=en").json() == report


@pytest.mark.parametrize("source", ["罕見字𠮷", "票箱🙂", "未定義字\u0378"])
def test_unsupported_pdf_source_is_a_visible_error_while_json_and_csv_keep_it(
    report_setup: dict, source: str
) -> None:
    client, box_id = report_setup["receiver"], report_setup["box"]["id"]
    corrected = client.put(
        f"{report_setup['target']}/{box_id}/receipt",
        json=event_command(5, "2026-11-15T23:01:00.250000+08:00", reason=source),
    )
    assert corrected.status_code == 200
    path = report_setup["target"] + "/statement"
    report = client.get(path).json()
    assert report["box_history"][-1]["reason"] == source
    assert source in "\n".join(report["preview_lines"])
    exported = client.get(path + ".csv")
    assert exported.status_code == 200 and source in exported.content.decode("utf-8-sig")
    rejected = client.get(path + ".pdf")
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "report_glyph_unavailable"


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_nine_box_report_paginates_long_source_fields_without_losing_history(
    report_setup: dict, tmp_path: Path, locale: str
) -> None:
    sender, receiver = report_setup["sender"], report_setup["receiver"]
    source, target = report_setup["source"], report_setup["target"]
    last_box = None
    long_reference = "長票箱00000009" + "長" * 53
    long_seal = "封條000009" + "封" * 120
    assert len(long_reference) == 64 and len(long_seal) == 128
    for number in range(2, 10):
        prepared = sender.post(
            source,
            json=prepared_box(
                box_reference=long_reference if number == 9 else f"票箱 {number:06d}",
                seal_reference=long_seal if number == 9 else f"封條{number:06d}",
                prepared_at="2026-11-15T22:40:00.123456+08:00",
            ),
        )
        assert prepared.status_code == 201
        last_box = prepared.json()
        assert (
            sender.post(
                f"{source}/{last_box['id']}/departure",
                json=event_command(1, "2026-11-15T22:45:00.500000+08:00"),
            ).status_code
            == 201
        )
        assert (
            receiver.post(
                f"{target}/{last_box['id']}/receipt",
                json=event_command(2, "2026-11-15T23:00:00.250000+08:00"),
            ).status_code
            == 201
        )
    assert last_box is not None
    long_reason = "述" * 993 + "終段標記END"
    assert len(long_reason) == 1000
    corrected = receiver.put(
        f"{target}/{last_box['id']}/receipt",
        json=event_command(3, "2026-11-15T23:00:00.500000+08:00", reason=long_reason),
    )
    assert corrected.status_code == 200
    statement = receiver.get(target + f"/statement?locale={locale}")
    assert statement.status_code == 200
    report = statement.json()
    assert len(report["items"]) == 9 and len(report["box_history"]) == 30
    assert len(report["milestone_history"]) == 4 and report["count_completion"] is None
    exported_csv = receiver.get(target + f"/statement.csv?locale={locale}")
    assert exported_csv.status_code == 200
    csv_values = [
        value
        for row in csv.reader(StringIO(exported_csv.content.decode("utf-8-sig")))
        for value in row
    ]
    assert long_reference in csv_values and long_seal in csv_values and long_reason in csv_values
    response = receiver.get(target + f"/statement.pdf?locale={locale}")
    assert response.status_code == 200
    destination = tmp_path / f"box-handover-{locale}.pdf"
    destination.write_bytes(response.content)
    document = PdfReader(BytesIO(response.content))
    assert len(document.pages) >= 3
    texts = [page.extract_text() for page in document.pages]
    compact = "".join("\n".join(texts).split())
    assert compact.count("述") == 993 and "終段標記END" in compact
    assert "2026-11-1522:40:00.123456HKT" in compact
    assert long_reference in compact and long_seal in compact
    for number in range(1, 9):
        assert f"票箱{number:06d}" in compact
    for index, text in enumerate(texts, start=1):
        assert f"{report['labels']['page']} {index}" in text
        assert "N1" in text
    evidence_directory = os.getenv("ELECTION_BOX_REPORT_LAYOUT_DIRECTORY")
    if evidence_directory:
        allowed = Path(__file__).resolve().parents[1] / "docs/evidence/ticket-15/report-layout"
        assert Path(evidence_directory).resolve() == allowed.resolve()
        allowed.mkdir(parents=True, exist_ok=True)
        (allowed / destination.name).write_bytes(response.content)


def test_concurrent_box_queue_and_stock_pdfs_keep_their_source_text_and_font_mappings(
    report_setup: dict, database_url: str
) -> None:
    station_id = report_setup["stations"]["N1"]["id"]
    stock_path = f"/api/workspace/stations/{station_id}/stock"
    stock = report_setup["sender"].post(stock_path, json=stock_payload(series="STOCK_ONLY_SOURCE"))
    assert stock.status_code == 201
    stock_path += f"/{stock.json()['id']}/statement.pdf?revision=1&locale=tc"
    queue_path = (
        f"/api/workspace/stations/{report_setup['stations']['N2']['id']}"
        "/queue/statement.pdf?revision=0&locale=sc"
    )
    paths = [
        report_setup["target"] + "/statement.pdf?locale=tc",
        queue_path,
        stock_path,
        report_setup["target"] + "/statement.pdf?locale=en",
    ]
    authorizations = [
        report_setup["receiver"].headers["Authorization"],
        report_setup["sender"].headers["Authorization"],
        report_setup["sender"].headers["Authorization"],
        report_setup["receiver"].headers["Authorization"],
    ]
    applications = [create_app(database_url, now=report_setup["clock"]) for _ in paths]
    barrier = Barrier(4)

    def download(index: int) -> str:
        with TestClient(applications[index], base_url="https://testserver") as client:
            client.headers["Authorization"] = authorizations[index]
            barrier.wait(timeout=10)
            response = client.get(paths[index])
            assert response.status_code == 200
            return "\n".join(
                page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, index) for index in range(4)]
        texts = [future.result(timeout=20) for future in futures]
    for text in (texts[0], texts[3]):
        assert "核對離站 <紙本> & original" in text and "STOCK_ONLY_SOURCE" not in text
    assert "轮候观察及提醒报表" in texts[1]
    assert "核對離站" not in texts[1] and "STOCK_ONLY_SOURCE" not in texts[1]
    assert "STOCK_ONLY_SOURCE" in texts[2] and "核對離站" not in texts[2]


def test_pdf_box_overview_keeps_short_english_headers_and_fractional_times_readable(
    report_setup: dict,
) -> None:
    response = report_setup["receiver"].get(report_setup["target"] + "/statement.pdf?locale=en")
    assert response.status_code == 200
    first_page = PdfReader(BytesIO(response.content)).pages[0].extract_text()
    overview = first_page.split("Current saved boxes", 1)[1].split(
        "Box handover and correction history", 1
    )[0]
    lines = [line.strip() for line in overview.splitlines()]
    assert "Revision" in lines
    assert any("22:40:00.123456 HKT" in line for line in lines)
    assert any("22:46:00.500000 HKT" in line for line in lines)
    assert any("23:01:00.250000 HKT" in line for line in lines)


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_pdf_exports_an_accepted_multiline_identity_larger_than_a_page(
    report_setup: dict, tmp_path: Path, locale: str
) -> None:
    seal = "\n".join(["S"] * 64) + "Z"
    created = report_setup["sender"].post(
        report_setup["source"],
        json=prepared_box(box_reference="MULTILINE_LAST", seal_reference=seal),
    )
    assert created.status_code == 201
    assert created.json()["seal_reference"] == seal
    following = report_setup["sender"].post(
        report_setup["source"],
        json=prepared_box(box_reference="AFTER_TALL_END", seal_reference="FINAL_SEAL"),
    )
    assert following.status_code == 201
    csv_response = report_setup["receiver"].get(
        report_setup["target"] + f"/statement.csv?locale={locale}"
    )
    assert csv_response.status_code == 200
    assert seal in [
        value
        for row in csv.reader(StringIO(csv_response.content.decode("utf-8-sig")))
        for value in row
    ]
    response = report_setup["receiver"].get(
        report_setup["target"] + f"/statement.pdf?locale={locale}"
    )
    assert response.status_code == 200
    document = PdfReader(BytesIO(response.content))
    assert len(document.pages) >= 3
    lines = [line.strip() for page in document.pages for line in page.extract_text().splitlines()]
    assert lines.count("S") == 63
    assert lines.count("SZ") == 1
    assert "MULTILINE_LAST" in "".join(lines)
    assert "AFTER_TALL_END" in "".join(lines)
    assert "FINAL_SEAL" in "".join(lines)
    seal_end_page = next(
        index for index, page in enumerate(document.pages) if "SZ" in page.extract_text()
    )
    following_page = next(
        index for index, page in enumerate(document.pages) if "FINAL_SEAL" in page.extract_text()
    )
    assert following_page >= seal_end_page
    report = (
        report_setup["receiver"].get(report_setup["target"] + f"/statement?locale={locale}").json()
    )
    for index, page in enumerate(document.pages, start=1):
        assert f"{report['labels']['page']} {index}" in page.extract_text()
    (tmp_path / f"box-oversized-identity-{locale}.pdf").write_bytes(response.content)


def test_history_exports_disambiguate_identical_references_from_two_origin_stations(
    admin: TestClient, database_url: str
) -> None:
    stations, clock = box_stations(admin, activate=False), BoxClock()
    third, target = stations["N3"], stations["N1"]
    configured = admin.put(
        f"/api/elections/{stations['election']['id']}/constituencies/"
        f"{third['constituency_id']}/stations/{third['id']}",
        json={
            "code": third["code"],
            "name": third["name"],
            "revision": third["revision"],
            "counting_mode": "send",
            "destination_station_id": target["id"],
        },
    )
    assert configured.status_code == 200
    activated = admin.post(
        f"/api/elections/{stations['election']['id']}/activate",
        json={"election_revision": stations["election"]["revision"], "schedule_revision": 1},
    )
    assert activated.status_code == 200
    target_path = f"/api/workspace/stations/{target['id']}/boxes"
    with box_staff(
        admin, database_url, clock, "polling_officer", [stations[key]["id"] for key in ("N2", "N3")]
    ) as (sender, _):
        with box_staff(admin, database_url, clock, "counting_officer", [target["id"]]) as (
            receiver,
            _,
        ):
            received = []
            for code in ("N2", "N3"):
                source = f"/api/workspace/stations/{stations[code]['id']}/boxes"
                created = sender.post(
                    source,
                    json=prepared_box(
                        box_reference="COMMON0001",
                        seal_reference="SEAL-" + code,
                    ),
                )
                assert created.status_code == 201
                box_id = created.json()["id"]
                assert (
                    sender.post(
                        f"{source}/{box_id}/departure",
                        json=event_command(1, "2026-11-15T22:45:00+08:00"),
                    ).status_code
                    == 201
                )
                arrival = receiver.post(
                    f"{target_path}/{box_id}/receipt",
                    json=event_command(2, "2026-11-15T23:00:00+08:00"),
                )
                assert arrival.status_code == 201
                received.append(arrival.json())
            assert (
                receiver.put(
                    target_path + "/milestones/first_box_opening",
                    json=event_command(0, "2026-11-15T23:05:00+08:00", box_id=received[1]["id"]),
                ).status_code
                == 200
            )
            response = receiver.get(target_path + "/statement.csv?locale=en")
            assert response.status_code == 200
            rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))

            def section(title: str) -> tuple[list[str], list[list[str]]]:
                start = rows.index([title])
                header = rows[start + 1]
                body = []
                for row in rows[start + 2 :]:
                    if not row:
                        break
                    body.append(row)
                return header, body

            header, history = section("Box handover and correction history")
            assert "Origin polling station" in header
            origin_column = header.index("Origin polling station")
            reference_column = header.index("Box reference")
            assert len(history) == 6
            assert all(row[reference_column] == "COMMON0001" for row in history)
            origin_n2 = "N2 · 票箱測試站 N2"
            origin_n3 = "N3 · 票箱測試站 N3"
            assert [row[origin_column] for row in history].count(origin_n2) == 3
            assert [row[origin_column] for row in history].count(origin_n3) == 3
            milestone_header, milestones = section("Counting milestone correction history")
            assert "Origin polling station" in milestone_header
            assert len(milestones) == 1
            assert milestones[0][milestone_header.index("Origin polling station")] == origin_n3
            assert milestones[0][milestone_header.index("Box reference")] == "COMMON0001"
            report = receiver.get(target_path + "/statement?locale=en").json()
            assert any(
                "First box opening" in line and "COMMON0001" in line and origin_n3 in line
                for line in report["preview_lines"]
            )
