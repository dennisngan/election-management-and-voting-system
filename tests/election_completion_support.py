"""Whole-election reviewed source arrangements through public staff APIs only."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_staff, event_command, prepared_box
from tests.counting_support import _prepare_source_accounting
from tests.polling_support import draft_payload, transition_payload
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@contextmanager
def reviewed_election_setup(
    admin: TestClient, database_url: str, *, n1_quantities: tuple[int, int] = (6, 4),
    n1_selected: bool = True,
) -> Iterator[dict[str, Any]]:
    """Complete one two-constituency/four-station source arrangement, without finalizing."""
    with complete_tie_setup(admin, database_url, candidate_count=2) as setup:
        n1_round = save_result_round(setup, list(n1_quantities), approve_and_select=n1_selected)
        station = setup["stations"]["S1"]
        station_id = station["id"]
        polling = setup["clients"]["polling"]
        supervisor = setup["clients"]["supervisor"]
        with box_staff(
            admin, database_url, setup["clock"], "counting_officer", [station_id]
        ) as (s1_counter, s1_account):
            accounting = _prepare_source_accounting(
                polling, s1_counter, supervisor, station
            )
            base = f"/api/workspace/stations/{station_id}"
            prepared = polling.post(
                base + "/boxes",
                json=prepared_box(box_reference="Election completion S1 local box"),
            )
            assert prepared.status_code == 201, prepared.text
            box_id = prepared.json()["id"]
            received = s1_counter.post(
                f"{base}/boxes/{box_id}/receipt",
                json=event_command(1, "2026-11-15T22:45:00+08:00"),
            )
            assert received.status_code == 201, received.text
            scope_path = base + "/counting-scopes"
            created = s1_counter.post(
                scope_path,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "reference": "Election completion S1 local counting scope",
                    "event_at": "2026-11-15T23:10:00+08:00",
                    "box_revisions": [
                        {"box_id": box_id, "revision": received.json()["revision"]}
                    ],
                    "accounting_revisions": [
                        {
                            "station_id": station_id,
                            "revision": accounting["record"]["revision"],
                        }
                    ],
                },
            )
            assert created.status_code == 201, created.text
            submitted = s1_counter.post(
                f"{scope_path}/{created.json()['id']}/submit",
                json={"request_id": str(uuid4()), "expected_revision": 1},
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["count_ready"] is True
            rounds_path = f"{scope_path}/{created.json()['id']}/rounds"
            s1_setup = {
                **setup,
                "clients": {**setup["clients"], "receiveronly": s1_counter},
                "scope": submitted.json(),
                "rounds_path": rounds_path,
            }
            s1_round = save_result_round(s1_setup, [4, 1], approve_and_select=True)

            completions = {}
            for code in ("N1", "N2", "N3", "S1"):
                polling_path = (
                    f"/api/workspace/stations/{setup['stations'][code]['id']}"
                    "/polling/service_completion"
                )
                saved = polling.put(
                    polling_path,
                    json=draft_payload(event_at="2026-11-15T22:35:00+08:00"),
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["revision"] == 1
                assert saved.json()["status"] == "draft"
                submitted_completion = polling.post(
                    polling_path + "/submit", json=transition_payload(1)
                )
                assert submitted_completion.status_code == 200, submitted_completion.text
                approved = supervisor.post(
                    polling_path + "/approve",
                    json=transition_payload(1, password=BOX_READY_PASSWORD),
                )
                assert approved.status_code == 200, approved.text
                assert approved.json()["revision"] == 1
                assert approved.json()["status"] == "approved"
                assert approved.json()["event_at"] == "2026-11-15T14:35:00Z"
                completions[code] = approved.json()

            yield {
                **setup,
                "clients": {**setup["clients"], "s1_counter": s1_counter},
                "accounts": {**setup["accounts"], "s1_counter": s1_account},
                "accounting": {**setup["accounting"], "S1": accounting},
                "n1_round": n1_round,
                "s1_box": received.json(),
                "s1_scope": submitted.json(),
                "s1_scope_path": scope_path,
                "s1_rounds_path": rounds_path,
                "s1_round": s1_round,
                "polling_completion_records": completions,
                "completion_path": (
                    f"/api/workspace/elections/{setup['election']['id']}/completion"
                ),
            }
