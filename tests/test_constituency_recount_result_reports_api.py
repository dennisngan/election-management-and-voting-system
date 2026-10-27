"""Constituency statements preserve wide membership beside current result readiness."""

import csv
from collections.abc import Iterator
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_constituency_statements_show_original_wide_members_and_current_required_rounds(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}"
        result_path, instructions_path = base + "/results", base + "/recounts"
        baseline_response = supervisor.get(result_path)
        assert baseline_response.status_code == 200, baseline_response.text
        baseline = baseline_response.json()
        assert baseline["complete"] is True
        assert [row["quantity"] for row in baseline["candidate_totals"]] == [6, 4]
        options_response = supervisor.get(instructions_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        assert options["can_instruct"] is True and len(options["scope_sources"]) == 2
        setup["clock"].value += timedelta(minutes=10)
        command = {
            "request_id": str(uuid4()), "basis_digest": options["basis_digest"],
            "scope_sources": options["scope_sources"],
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "The constituency statement must explain both required replacement rounds.",
            "password": READY_PASSWORD,
        }
        created = supervisor.post(instructions_path, json=command)
        assert created.status_code == 201, created.text
        original = created.json()
        history_response = supervisor.get(instructions_path)
        assert history_response.status_code == 200, history_response.text
        instructions = history_response.json()["instructions"]
        assert len(instructions) == 1 and instructions[0] == original["instruction"]
        parent = instructions[0]
        assert parent["historical_complete"] is False and parent["completed_member_count"] == 0
        result_response = supervisor.get(result_path)
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()
        assert result["complete"] is False and result["provisional"] is True
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        assert {row["scope_id"] for row in result["pending"]} == {
            row["scope_id"] for row in options["scope_sources"]
        }
        reports = {}
        for locale in ("en", "tc", "sc"):
            response = supervisor.get(result_path + "/statement", params={"locale": locale})
            assert response.status_code == 200, response.text
            reports[locale] = response.json()
            assert reports[locale]["result"] == result

        # First RED: result statements currently have no wide-instruction projection.
        assert result.get("constituency_recounts") == instructions
        assert parent["member_count"] == 2 and parent["scope_sources"] == command["scope_sources"]
        for locale, report in reports.items():
            labels, rows = report["labels"], report["rows"]
            assert report["result"]["constituency_recounts"] == instructions
            if locale == "en":
                assert labels["constituency_recount_history"] == (
                    "Constituency-wide recount instructions"
                )
            else:
                assert any("\u4e00" <= char <= "\u9fff"
                           for char in labels["constituency_recount_history"])
            assert [labels["constituency_recount_instruction_id"], str(parent["id"])] in rows
            assert [labels["constituency_recount_request_id"], command["request_id"]] in rows
            assert [labels["constituency_recount_reason"], command["reason"]] in rows
            assert [labels["constituency_recount_member_count"], "2"] in rows
            assert [labels["constituency_recount_completed_count"], "0"] in rows
            assert [labels["constituency_recount_historical_complete"], labels["no"]] in rows
            assert [labels["constituency_recount_event_at"],
                    "2026-11-16 00:05:42.123456 HKT"] in rows
            assert [labels["constituency_recount_entered_at"],
                    "2026-11-16 00:10:00 HKT"] in rows
            assert [labels["scope_id"], labels["station_id"],
                    labels["constituency_recount_replacement_round"],
                    labels["constituency_recount_progress"],
                    labels["constituency_recount_current_required_round"]] in rows
            for member in parent["members"]:
                assert [str(member["scope_id"]), str(member["station_id"]),
                        str(member["new_round_id"]), labels["constituency_recount_incomplete"],
                        str(member["current_required_round_id"]) ] in rows
            exported = supervisor.get(result_path + "/statement.csv", params={"locale": locale})
            assert exported.status_code == 200, exported.text
            parsed = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
            assert parsed == rows
        replay = supervisor.post(instructions_path, json=command)
        assert replay.status_code == 200 and replay.json() == original
