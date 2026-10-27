"""Rejected constituency instructions preserve both scopes and their reviewed rounds."""

from collections.abc import Iterator
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import INITIAL_PASSWORD, READY_PASSWORD, box_staff
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


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("missing_receiving_station", 403, "station_access_denied"),
        ("missing_transfer_origin", 403, "station_access_denied"),
        ("other_constituency_supervisor", 403, "station_access_denied"),
        ("counting_officer", 403, "supervisor_required"),
        ("polling_officer", 403, "supervisor_required"),
        ("administrator", 403, "supervisor_required"),
        ("wrong_password", 401, "invalid_credentials"),
        ("missing_source", 409, "constituency_recount_sources_stale"),
        ("reordered_sources", 409, "constituency_recount_sources_stale"),
        ("duplicate_source", 409, "constituency_recount_sources_stale"),
        ("foreign_constituency_source", 409, "constituency_recount_sources_stale"),
        ("stale_scope_revision", 409, "constituency_recount_sources_stale"),
        ("stale_round_revision", 409, "constituency_recount_sources_stale"),
        ("mismatched_selection_revision", 409, "constituency_recount_sources_stale"),
        ("changed_replay_body", 409, "request_conflict"),
    ],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_rejected_instruction_does_not_create_a_parent_or_change_either_scope(
    admin: TestClient, database_url: str, case: str, status: int, code: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup, ExitStack() as stack:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        target = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        south_id = setup["stations"]["S1"]["constituency_id"]
        south_target = f"/api/workspace/constituencies/{south_id}/recounts"
        options_response = supervisor.get(target)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        assert options["can_instruct"] is True
        assert options["instructions"] == []
        sources = options["scope_sources"]
        assert [(row["station_id"], row["scope_id"]) for row in sources] == [
            (setup["stations"]["N1"]["id"], setup["scope"]["id"]),
            (setup["stations"]["N3"]["id"], setup["n3_scope"]["id"]),
        ]
        assert [row["scope_revision"] for row in sources] == [2, 1]
        assert [row["source_round_revision"] for row in sources] == [4, 4]
        assert [row["expected_selection_revision"] for row in sources] == [1, 1]
        # N2 sends its boxes to N1; no separate tally capsule can grant its authority.
        assert setup["stations"]["N2"]["counting_mode"] == "send"
        assert setup["stations"]["N2"]["destination_station_id"] == sources[0]["station_id"]

        setup["clock"].value += timedelta(minutes=10)
        command = {
            "request_id": str(uuid4()),
            "basis_digest": options["basis_digest"],
            "scope_sources": deepcopy(sources),
            "event_at": "2026-11-16T00:05:42.123456+08:00",
            "reason": "Repeat all required North tallies without changing the reviewed sources.",
            "password": READY_PASSWORD,
        }
        actor = supervisor
        if case in ("missing_receiving_station", "missing_transfer_origin",
                    "other_constituency_supervisor"):
            assigned_codes = {
                "missing_receiving_station": ("N2", "N3"),
                "missing_transfer_origin": ("N1", "N3"),
                "other_constituency_supervisor": ("S1",),
            }[case]
            actor, _ = stack.enter_context(box_staff(
                admin, database_url, setup["clock"], "supervisor",
                [setup["stations"][station]["id"] for station in assigned_codes],
            ))
        elif case == "counting_officer":
            actor = setup["clients"]["receiveronly"]
        elif case == "polling_officer":
            actor = setup["clients"]["polling"]
        elif case == "administrator":
            actor = admin
        elif case == "wrong_password":
            command["password"] = INITIAL_PASSWORD
        elif case == "missing_source":
            command["scope_sources"] = command["scope_sources"][:-1]
        elif case == "reordered_sources":
            command["scope_sources"].reverse()
        elif case == "duplicate_source":
            command["scope_sources"][1] = deepcopy(command["scope_sources"][0])
        elif case == "foreign_constituency_source":
            command["scope_sources"][0]["station_id"] = setup["stations"]["S1"]["id"]
        elif case == "stale_scope_revision":
            command["scope_sources"][0]["scope_revision"] = 1
        elif case == "stale_round_revision":
            command["scope_sources"][0]["source_round_revision"] = 3
        elif case == "mismatched_selection_revision":
            command["scope_sources"][0]["expected_selection_revision"] = 2
        elif case == "changed_replay_body":
            created = supervisor.post(target, json=command)
            assert created.status_code == 201, created.text
            original = created.json()
            assert len(original["members"]) == 2
            command["reason"] += " A changed body must not replay this UUID."

        round_paths = [
            f"/api/workspace/stations/{source['station_id']}"
            f"/counting-scopes/{source['scope_id']}/rounds"
            for source in sources
        ]
        source_paths = [saved["round_path"], setup["n3_round"]["round_path"]]
        local_paths = [path.rsplit("/", 1)[0] + "/recounts" for path in round_paths]
        observed_paths = [target, south_target, *round_paths, *source_paths, *local_paths]
        before = {}
        for path in observed_paths:
            response = supervisor.get(path)
            assert response.status_code == 200, response.text
            before[path] = response.json()
        expected_round_count = 2 if case == "changed_replay_body" else 1
        expected_instruction_count = 1 if case == "changed_replay_body" else 0
        assert len(before[target]["instructions"]) == expected_instruction_count
        assert before[south_target]["instructions"] == []
        for path in round_paths:
            assert len(before[path]["rounds"]) == expected_round_count
        for path in local_paths:
            assert len(before[path]["instructions"]) == expected_instruction_count

        denied = actor.post(target, json=command)
        assert denied.status_code == status, denied.text
        assert denied.json()["detail"]["code"] == code
        # Only staff-facing GETs establish no parent, orphan instruction, extra round,
        # revision, source-history or explicit selection changed after this rejection.
        for path in observed_paths:
            response = supervisor.get(path)
            assert response.status_code == 200, response.text
            assert response.json() == before[path], path
