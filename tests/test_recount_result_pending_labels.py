"""Actual result UI/report rows explain the required recount in three languages."""

import csv
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup

EXPECTED_PENDING_LABELS = {
    "tc": "所需重新點票輪次尚未獲批核並選用",
    "sc": "所需重新点票轮次尚未获批核并选用",
    "en": "The required recount round has not been approved and selected",
}


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@contextmanager
def pending_local_recount(admin: TestClient, database_url: str) -> Iterator[dict]:
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        prior = saved["selected"]
        station_id, scope_id = setup["stations"]["N1"]["id"], setup["scope"]["id"]
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(result_path)
        assert before.status_code == 200, before.text
        assert before.json()["complete"] is True
        assert [row["quantity"] for row in before.json()["candidate_totals"]] == [6, 4]
        setup["clock"].value += timedelta(minutes=10)
        recount_path = (
            f"/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/recounts"
        )
        request_id = str(uuid4())
        created = supervisor.post(recount_path, json={
            "request_id": request_id,
            "scope_revision": setup["scope"]["revision"],
            "expected_selection_revision": prior["selection"]["revision"],
            "source_round_id": prior["id"],
            "source_round_revision": prior["revision"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "The selected source is retained while a new physical recount is required.",
            "password": READY_PASSWORD,
        })
        assert created.status_code == 201, created.text
        instruction = created.json()["instruction"]
        assert instruction["request_id"] == request_id
        assert instruction["source_round_id"] == prior["id"]
        assert instruction["status"] == "pending"
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        result = after.json()
        assert result["complete"] is False and result["provisional"] is True
        matching = [row for row in result["pending"]
                    if row["code"] == "recount_pending" and row.get("scope_id") == scope_id]
        assert len(matching) == 1
        assert matching[0]["instruction_id"] == instruction["id"]
        assert matching[0]["new_round_id"] == instruction["new_round_id"]
        assert [row["quantity"] for row in result["candidate_totals"]] == [0, 0]
        assert [row["scope_id"] for row in result["contributions"]] == [setup["n3_scope"]["id"]]
        yield {
            **setup, "prior": prior, "instruction": instruction, "station_id": station_id,
            "scope_id": scope_id, "result_path": result_path, "recount_path": recount_path,
            "pending_result": result,
        }


def test_material_result_pending_row_explains_required_recount_in_three_languages(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with pending_local_recount(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["station_id"],
                "locale": "en",
                "scope_id": setup["scope_id"],
                "instruction_id": setup["instruction"]["id"],
                "expected_pending_labels": EXPECTED_PENDING_LABELS,
            },
            """
            results = controller.property('constituencyResults')
            click('constituencyResultsNavigation')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            record = results.property('state')['result']
            assert record['complete'] is False and record['provisional'] is True
            indexes = [index for index, row in enumerate(record['pending'])
                if row['code'] == 'recount_pending' and row.get('scope_id') == setup['scope_id']]
            assert len(indexes) == 1
            assert record['pending'][indexes[0]]['instruction_id'] == setup['instruction_id']
            name = 'constituencyResultPending_' + str(indexes[0])
            for locale in ('tc', 'sc', 'en'):
                controller.setLocale(locale)
                wait(lambda: controller.property('state')['locale'] == locale)
                frame()
                label = control(name)
                assert label.property('visible') is True
                shown = label.property('text')
                expected = setup['expected_pending_labels'][locale]
                # Literal Root-approved wording, not the translation dict under test.
                assert shown.startswith(expected + ' · '), (locale, shown)
                assert 'recount_pending' not in shown
                assert not any(shown.startswith(value) for value in (
                    '未有記錄', '未有记录', 'Not recorded'))
                current = results.property('state')['result']
                assert current['complete'] is False and current['provisional'] is True
                assert current['pending'][indexes[0]]['instruction_id'] == setup['instruction_id']
            """,
        )
        assert https_server.request_count("GET", setup["result_path"]) >= 1
        assert not [row for row in https_server.requests
                    if row[0] in {"POST", "PUT", "PATCH", "DELETE"}
                    and row[1].startswith("/api/workspace/")]
        final = setup["clients"]["supervisor"].get(setup["recount_path"])
        assert final.status_code == 200, final.text
        assert [row["id"] for row in final.json()["instructions"]] == [setup["instruction"]["id"]]


def test_result_report_pending_row_is_translated_in_preview_csv_and_pdf(
    admin: TestClient,
    database_url: str,
) -> None:
    with pending_local_recount(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        reports = {}
        # Establish real route/record/export validity before new-label assertions.
        for locale in ("tc", "sc", "en"):
            base = setup["result_path"] + "/statement"
            preview = supervisor.get(base, params={"locale": locale})
            assert preview.status_code == 200, preview.text
            report = preview.json()
            assert report["locale"] == locale
            assert report["result"]["complete"] is False
            assert report["result"]["provisional"] is True
            pending = [row for row in report["result"]["pending"]
                       if row["code"] == "recount_pending"
                       and row.get("scope_id") == setup["scope_id"]]
            assert len(pending) == 1
            assert pending[0]["instruction_id"] == setup["instruction"]["id"]
            table_rows = [row for table in report["tables"] for row in table["rows"]]
            preview_rows = [row for row in table_rows if len(row) == 5
                            and row[1] == str(setup["station_id"])
                            and row[2] == str(setup["scope_id"])]
            assert len(preview_rows) == 1
            csv_response = supervisor.get(base + ".csv", params={"locale": locale})
            assert csv_response.status_code == 200, csv_response.text
            csv_text = csv_response.content.decode("utf-8-sig")
            csv_rows = [row for row in csv.reader(StringIO(csv_text)) if len(row) == 5
                        and row[1] == str(setup["station_id"])
                        and row[2] == str(setup["scope_id"])]
            assert len(csv_rows) == 1
            pdf_response = supervisor.get(base + ".pdf", params={"locale": locale})
            assert pdf_response.status_code == 200, pdf_response.text
            assert pdf_response.content.startswith(b"%PDF-")
            pages = PdfReader(BytesIO(pdf_response.content)).pages
            page_texts = [page.extract_text() or "" for page in pages]
            assert page_texts and all(text.strip() for text in page_texts)
            reports[locale] = {
                "report": report, "preview_row": preview_rows[0], "csv_row": csv_rows[0],
                "csv_text": csv_text, "pdf_text": "\n".join(page_texts),
            }

        for locale, expected in EXPECTED_PENDING_LABELS.items():
            actual = reports[locale]
            # Expected raw-code RED at215a05f; machine JSON code remains unchanged.
            assert actual["preview_row"][0] == expected
            assert actual["report"]["labels"].get("recount_pending") == expected
            assert actual["csv_row"][0] == expected
            assert "recount_pending" not in actual["csv_text"]
            assert "".join(expected.split()) in "".join(actual["pdf_text"].split())
            assert "recount_pending" not in actual["pdf_text"]
            assert "\ufffd" not in actual["pdf_text"]
        after = supervisor.get(setup["result_path"])
        assert after.status_code == 200, after.text
        assert after.json() == setup["pending_result"]
