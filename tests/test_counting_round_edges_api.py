"""F1 API edge cases through authenticated public APIs and real MySQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import BoxClock, box_staff
from tests.tally_support import tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def initial_draft(setup: dict[str, Any], **changes: object) -> dict[str, Any]:
    options = setup.setdefault(
        "options", setup["counter"].get(setup["rounds_path"]).json()
    )
    candidate = options["candidates"][0]
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "scope_revision": setup["scope"]["revision"],
        "event_at": "2026-11-15T23:15:12.123456+08:00",
        "candidate_votes": [{"candidate_id": candidate["id"], "quantity": None}],
        "invalid_papers": [],
        "questionable_quantity": None,
        "actual_counted_quantity": None,
        "notes": "Partial F1 edge draft.",
        **changes,
    }


def test_concurrent_initial_round_creation_is_single_effect(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        payload = initial_draft(setup)
        barrier = Barrier(2)

        def create() -> tuple[int, dict[str, Any]]:
            with TestClient(create_app(database_url, now=setup["clock"])) as peer:
                peer.headers.update(client.headers)
                barrier.wait(timeout=5)
                response = peer.post(path, json=payload)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        assert sorted(status for status, _ in results) == [200, 201]
        assert results[0][1] == results[1][1]
        assert results[0][1]["round_number"] == 1
        assert client.get(path).json()["rounds"] == [results[0][1]]


def test_concurrent_initial_rounds_with_distinct_requests_reject_the_loser(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        station_id = setup["stations"]["N1"]["id"]
        path = setup["rounds_path"]
        with box_staff(
            admin, database_url, BoxClock(), "counting_officer", [station_id]
        ) as (peer, _):
            clients = (setup["counter"], peer)
            payloads = [initial_draft(setup), initial_draft(setup)]
            barrier = Barrier(2)

            def create(index: int) -> tuple[int, dict[str, Any]]:
                barrier.wait(timeout=5)
                response = clients[index].post(path, json=payloads[index])
                return response.status_code, response.json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(create, range(2)))
        statuses = sorted(status for status, _ in results)
        assert statuses == [201, 409]
        conflict = next(body for status, body in results if status == 409)
        assert conflict["detail"]["code"] == "initial_round_exists"
        rounds = setup["counter"].get(path).json()["rounds"]
        assert len(rounds) == 1 and rounds[0]["round_number"] == 1


def test_simultaneous_edits_of_same_revision_have_one_winner(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        created = client.post(path, json=initial_draft(setup))
        assert created.status_code == 201, created.text
        round_id = created.json()["id"]
        station_id = setup["stations"]["N1"]["id"]
        with box_staff(
            admin, database_url, BoxClock(), "counting_officer", [station_id]
        ) as (peer, _):
            clients = (client, peer)
            payloads = [
                initial_draft(
                    setup,
                    expected_revision=1,
                    notes="Concurrent amendment A.",
                    amendment_reason="Preserve the paper note from A.",
                ),
                initial_draft(
                    setup,
                    expected_revision=1,
                    notes="Concurrent amendment B.",
                    amendment_reason="Preserve the paper note from B.",
                ),
            ]
            barrier = Barrier(2)

            def amend(index: int) -> tuple[int, dict[str, Any]]:
                barrier.wait(timeout=5)
                response = clients[index].put(f"{path}/{round_id}", json=payloads[index])
                return response.status_code, response.json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(amend, range(2)))
        statuses = sorted(status for status, _ in results)
        assert statuses == [200, 409]
        conflict = next(body for status, body in results if status == 409)
        assert conflict["detail"]["code"] == "revision_conflict"
        history = client.get(f"{path}/{round_id}").json()["history"]
        assert [row["revision"] for row in history] == [2, 1]
        assert history[0]["notes"] in {
            "Concurrent amendment A.", "Concurrent amendment B."
        }


def test_role_station_candidate_and_reason_ownership_are_enforced(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        path = setup["rounds_path"]
        polling = setup["clients"]["polling"]
        denied = polling.post(path, json=initial_draft(setup))
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "counting_officer_required"

        with box_staff(
            admin, database_url, BoxClock(), "counting_officer", [setup["stations"]["N2"]["id"]]
        ) as (other_station, _):
            unassigned = other_station.get(path)
            assert unassigned.status_code == 403
            wrong_scope_path = path.replace(
                f"/stations/{setup['stations']['N1']['id']}/",
                f"/stations/{setup['stations']['N2']['id']}/",
            )
            wrong_scope = other_station.get(wrong_scope_path)
            assert wrong_scope.status_code == 404
            assert wrong_scope.json()["detail"]["code"] == "counting_scope_not_found"

        election_id = setup["election"]["id"]
        foreign_constituency_id = setup["stations"]["S1"]["constituency_id"]
        foreign_candidates = admin.get(
            f"/api/elections/{election_id}/constituencies/{foreign_constituency_id}/candidates"
        )
        assert foreign_candidates.status_code == 200
        foreign_candidate_id = foreign_candidates.json()["items"][0]["id"]
        bad_candidate = setup["counter"].post(
            path,
            json=initial_draft(
                setup,
                candidate_votes=[{"candidate_id": foreign_candidate_id, "quantity": 0}],
            ),
        )
        assert bad_candidate.status_code == 422
        assert bad_candidate.json()["detail"]["code"] == "count_candidate_invalid"

        bad_reason = setup["counter"].post(
            path,
            json=initial_draft(
                setup,
                invalid_papers=[{
                    "reason_id": 2_000_000_000,
                    "reason_revision": 1,
                    "quantity": 0,
                }],
            ),
        )
        assert bad_reason.status_code == 422
        assert bad_reason.json()["detail"]["code"] == "count_invalid_reason_invalid"

        reason = setup["options"]["invalid_reasons"][0]
        stale_reason = setup["counter"].post(
            path,
            json=initial_draft(
                setup,
                invalid_papers=[{
                    "reason_id": reason["id"],
                    "reason_revision": reason["revision"] + 1,
                    "quantity": 0,
                }],
            ),
        )
        assert stale_reason.status_code == 409
        assert stale_reason.json()["detail"]["code"] == "invalid_reason_revision_conflict"


def test_stale_scope_basis_blocks_writes_but_historical_frozen_basis_remains(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        created = client.post(path, json=initial_draft(setup))
        assert created.status_code == 201, created.text
        original = created.json()
        box = setup["boxes"]["local_n1"]
        corrected = client.put(
            setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
            json={
                "request_id": str(uuid4()),
                "expected_revision": box["revision"],
                "event_at": "2026-11-15T22:46:00+08:00",
                "reason": "Correct the receipt time from the paper record.",
            },
        )
        assert corrected.status_code == 200, corrected.text

        attempted = client.put(
            f"{path}/{original['id']}",
            json=initial_draft(
                setup,
                expected_revision=1,
                notes="Do not write against the stale source basis.",
            ),
        )
        assert attempted.status_code == 409
        assert attempted.json()["detail"]["code"] == "count_scope_not_ready"

        historical = client.get(f"{path}/{original['id']}")
        assert historical.status_code == 200, historical.text
        record = historical.json()["record"]
        frozen_box = record["scope_basis"]["box_basis"][0]
        assert record["source_current"] is False
        assert frozen_box["revision"] == box["revision"]
        assert frozen_box["receipt"]["event_at"] == box["receipt"]["event_at"]
        assert corrected.json()["receipt"]["event_at"] != frozen_box["receipt"]["event_at"]
        assert historical.json()["history"] == [record]


def test_public_round_storage_and_replay_keep_quantities_above_javascript_safe_integer(
    admin: TestClient, database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        huge = 9007199254740993
        candidate_id = initial_draft(setup)["candidate_votes"][0]["candidate_id"]
        payload = initial_draft(
            setup,
            candidate_votes=[{
                "candidate_id": candidate_id,
                "quantity": huge,
            }],
            notes="Exact quantity boundary.",
        )
        saved = client.post(path, json=payload)
        assert saved.status_code == 201, saved.text
        saved_record = saved.json()
        assert saved_record["candidate_votes"][0]["quantity"] == huge
        assert saved_record["initial_valid_quantity"] == huge
        assert saved_record["f1_complete"] is False

        reread = client.get(f"{path}/{saved_record['id']}")
        assert reread.status_code == 200
        assert reread.json()["record"]["candidate_votes"][0]["quantity"] == huge
        assert reread.json()["history"][0]["initial_valid_quantity"] == huge
        replay = client.post(path, json=payload)
        assert replay.status_code == 200
        assert replay.json() == saved_record
