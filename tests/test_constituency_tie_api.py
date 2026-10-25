"""Supervisor tie dispositions bind to the current constituency result basis."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, box_staff, event_command, prepared_box
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.results_support import result_setup, save_result_round
from tests.stock_support import stock_payload
from tests.tally_support import complete_f1_command


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _prepare_n3_zero_accounting(admin: TestClient, setup: dict, database_url: str):
    station = setup["stations"]["N3"]
    station_id = station["id"]
    base = f"/api/workspace/stations/{station_id}"
    polling = setup["clients"]["polling"]
    received = polling.post(
        base + "/stock",
        json=stock_payload(
            event_at="2026-11-15T08:00:00+08:00",
            ordinary_quantity=10,
            replacement_quantity=0,
            tendered_quantity=0,
            ranges=[{"pool": "ordinary", "serial_from": "000021", "serial_to": "000030"}],
        ),
    )
    assert received.status_code == 201, received.text
    counters = polling.get(base + "/allocations")
    assert counters.status_code == 200, counters.text
    counter_id = counters.json()["counters"][0]["id"]
    allocation = polling.post(
        base + "/allocations",
        json={
            "request_id": str(uuid4()),
            "counter_id": counter_id,
            "series": "普通系列 A",
            "serial_from": "000021",
            "serial_to": "000030",
            "event_at": "2026-11-15T09:00:00+08:00",
        },
    )
    assert allocation.status_code == 201, allocation.text
    snapshot = polling.post(
        base + "/stock-snapshots",
        json={
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17+08:00",
            "counters": [
                {
                    "counter_id": counter_id,
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000021", "serial_to": "000030"}
                    ],
                }
            ],
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    assert snapshot.json()["ordinary_issued_quantity"] == 0

    special = polling.post(
        base + "/special-papers",
        json={
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:45:17+08:00",
            "stock_snapshot_id": snapshot.json()["id"],
            "stock_snapshot_revision": 1,
            "series": [
                {
                    "series": "普通系列 A",
                    "replacement_issued_quantity": 0,
                    "spoilt_original_quantity": 0,
                    "tendered_issued_quantity": 0,
                    "retrieved_refused_quantity": 0,
                    "retrieved_found_quantity": 0,
                    "retrieved_held_quantity": 0,
                }
            ],
        },
    )
    assert special.status_code == 201, special.text

    with box_staff(admin, database_url, setup["clock"], "counting_officer", [station_id]) as (
        counter,
        _,
    ):
        accounting_path = base + "/accounting"
        saved = counter.put(
            accounting_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["summary"]["estimated_box_from_stock_quantity"] == 0
        submitted = counter.post(
            accounting_path + "/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert submitted.status_code == 200, submitted.text
        approved = setup["clients"]["supervisor"].post(
            accounting_path + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approval_valid"] is True
    return station


def _include_all_n2_boxes_in_n1_scope(setup: dict) -> None:
    receiver = setup["clients"]["receiveronly"]
    polling = setup["clients"]["polling"]
    unreceived = setup["boxes"]["unreceived_n2"]
    departure = polling.post(
        f"{setup['paths']['n2_boxes']}/{unreceived['id']}/departure",
        json=event_command(1, "2026-11-15T23:12:00+08:00"),
    )
    assert departure.status_code == 201, departure.text
    receipt = receiver.post(
        f"{setup['paths']['n1_boxes']}/{unreceived['id']}/receipt",
        json=event_command(2, "2026-11-15T23:15:00+08:00"),
    )
    assert receipt.status_code == 201, receipt.text

    scope = setup["scope"]
    path = f"{setup['scope_path']}/{scope['id']}"
    box_revisions = [
        {"box_id": row["id"], "revision": row["revision"]}
        for row in scope["box_basis"]
    ]
    box_revisions.append(
        {"box_id": unreceived["id"], "revision": receipt.json()["revision"]}
    )
    revised = receiver.put(
        path,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "reference": scope["reference"],
            "event_at": scope["event_at"],
            "box_revisions": box_revisions,
            "accounting_revisions": [
                {"station_id": row["station_id"], "revision": row["revision"]}
                for row in scope["accounting_basis"]
            ],
            "notes": "Include every received N2 source box in the N1 counting scope.",
            "amendment_reason": "The previously pending N2 box has now been received.",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == 2
    submitted = receiver.post(
        path + "/submit",
        json={"request_id": str(uuid4()), "expected_revision": 2},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    assert submitted.json()["estimated_box_from_stock_quantity"] == 10
    setup["scope"] = submitted.json()


def _save_tie_round(setup: dict, quantities: list[int]) -> dict:
    """Count the ten expected papers while preserving the requested candidate totals."""
    counter = setup["clients"]["receiveronly"]
    rounds_path = setup["rounds_path"]
    options = counter.get(rounds_path).json()
    assert options["scope"]["count_ready"] is True
    assert options["scope"]["estimated_box_from_stock_quantity"] == 10
    assert len(options["candidates"]) == len(quantities)
    initial = complete_f1_command(
        options,
        questionable_quantity=0,
        actual_counted_quantity=10,
    )
    for row, quantity in zip(initial["candidate_votes"], quantities, strict=True):
        row["quantity"] = quantity
    invalid_reason = next(row for row in options["invalid_reasons"] if not row["is_other"])
    invalid_input = next(
        row for row in initial["invalid_papers"] if row["reason_id"] == invalid_reason["id"]
    )
    invalid_input["quantity"] = 10 - sum(quantities)
    f1 = counter.post(rounds_path, json=initial)
    assert f1.status_code == 201, f1.text
    target = f"{rounds_path}/{f1.json()['id']}"
    f2 = counter.put(target + "/f2", json=complete_f2_command(options))
    assert f2.status_code == 200, f2.text
    submitted = counter.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": f2.json()["revision"],
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    approved = setup["clients"]["supervisor"].post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": submitted.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = setup["clients"]["supervisor"].post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": approved.json()["revision"],
            "scope_revision": options["scope"]["revision"],
            "expected_selection_revision": 0,
            "password": READY_PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.text
    return {"selected": selected.json(), "options": options}


@contextmanager
def complete_tie_setup(
    admin: TestClient, database_url: str, *, candidate_count: int = 2
) -> Iterator[dict]:
    with result_setup(admin, database_url, candidate_count=candidate_count) as setup:
        _include_all_n2_boxes_in_n1_scope(setup)
        station = _prepare_n3_zero_accounting(admin, setup, database_url)
        polling = setup["clients"]["polling"]
        n3_counter_context = box_staff(
            admin, database_url, setup["clock"], "counting_officer", [station["id"]]
        )
        with n3_counter_context as (n3_counter, _):
            base = f"/api/workspace/stations/{station['id']}"
            prepared = polling.post(
                base + "/boxes", json=prepared_box(box_reference="Tie basis N3 local box")
            )
            assert prepared.status_code == 201, prepared.text
            box_id = prepared.json()["id"]
            received = n3_counter.post(
                f"{base}/boxes/{box_id}/receipt",
                json=event_command(1, "2026-11-15T22:45:00+08:00"),
            )
            assert received.status_code == 201, received.text
            scope_path = base + "/counting-scopes"
            created = n3_counter.post(
                scope_path,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "reference": "N3 complete tie basis",
                    "event_at": "2026-11-15T23:10:00+08:00",
                    "box_revisions": [
                        {"box_id": box_id, "revision": received.json()["revision"]}
                    ],
                    "accounting_revisions": [{"station_id": station["id"], "revision": 1}],
                },
            )
            assert created.status_code == 201, created.text
            scope = n3_counter.post(
                f"{scope_path}/{created.json()['id']}/submit",
                json={"request_id": str(uuid4()), "expected_revision": 1},
            )
            assert scope.status_code == 200, scope.text
            assert scope.json()["count_ready"] is True
            n3_inventory = n3_counter.get(scope_path).json()
            n3_box = next(row for row in n3_inventory["boxes"] if row["id"] == box_id)
            assert n3_box["scope_id"] == created.json()["id"]
            n3_setup = {
                **setup,
                "clients": {**setup["clients"], "receiveronly": n3_counter},
                "counter": n3_counter,
                "scope": scope.json(),
                "rounds_path": f"{scope_path}/{created.json()['id']}/rounds",
            }
            n3_round = save_result_round(
                n3_setup,
                [0] * candidate_count,
                approve_and_select=True,
            )
            assert n3_round["selected"]["approval_valid"] is True
            assert n3_round["selected"]["selected"] is True
            supervisor_inventory = setup["clients"]["supervisor"].get(scope_path).json()
            supervisor_box = next(
                row for row in supervisor_inventory["boxes"] if row["id"] == box_id
            )
            assert supervisor_box["scope_id"] == created.json()["id"]
            setup["n3_scope"] = scope.json()
            setup["n3_round"] = n3_round
            setup["n3_scope_path"] = scope_path
            setup["n3_station_id"] = station["id"]
            setup["n3_box_id"] = box_id
        yield setup


def test_supervisor_resolves_equal_zero_totals_against_exact_result_basis(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(path)
        assert before.status_code == 200, before.text
        basis = before.json()
        n3_inventory = supervisor.get(setup["n3_scope_path"]).json()
        n3_box = next(
            row for row in n3_inventory["boxes"] if row["id"] == setup["n3_box_id"]
        )
        assert n3_box["scope_id"] == setup["n3_scope"]["id"]
        assert basis["complete"] is True, {
            "pending": basis["pending"],
            "stations": {code: row["id"] for code, row in setup["stations"].items()},
            "n3_box_id": setup["n3_box_id"],
        }
        assert basis["pending"] == [], basis["pending"]
        assert basis["tie_candidate_ids"]
        assert len(basis["tie_candidate_ids"]) == 2
        assert {row["quantity"] for row in basis["candidate_totals"]} == {0}
        command = {
            "request_id": str(uuid4()),
            "expected_resolution_revision": 0,
            "basis_digest": basis["basis_digest"],
            "candidate_id": basis["tie_candidate_ids"][0],
            "reason": "Supervisor reviewed the tie and recorded the authorized decision.",
            "password": READY_PASSWORD,
        }
        saved = supervisor.post(path + "/tie-resolutions", json=command)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        decision = result["tie_resolution"]
        assert decision["revision"] == 1
        assert decision["candidate_id"] == command["candidate_id"]
        assert decision["reason"] == command["reason"]
        assert decision["actor_id"] == setup["accounts"]["supervisor"]["id"]
        assert decision["accepted_at"]
        assert decision["basis_digest"] == basis["basis_digest"]
        assert decision["valid"] is True
        assert result["resolved_candidate_id"] == command["candidate_id"]
        assert len(result["resolution_history"]) == 1
        assert result["tie_candidate_ids"] == basis["tie_candidate_ids"]
        assert result["candidate_totals"] == basis["candidate_totals"]


def _tie_command(result: dict, candidate_id: int, *, request_id: str | None = None) -> dict:
    return {
        "request_id": request_id or str(uuid4()),
        "expected_resolution_revision": 0,
        "basis_digest": result["basis_digest"],
        "candidate_id": candidate_id,
        "reason": "Supervisor reviewed the tie and recorded the authorized decision.",
        "password": READY_PASSWORD,
    }


def test_changed_box_basis_invalidates_resolution_and_rejects_old_digest(
    admin: TestClient, database_url: str,
) -> None:
    from tests.box_support import event_command

    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(result_path).json()
        assert before["complete"] is True, before["pending"]
        assert before["pending"] == [], before["pending"]
        decision = supervisor.post(
            result_path + "/tie-resolutions",
            json=_tie_command(before, before["tie_candidate_ids"][0]),
        )
        assert decision.status_code == 200, decision.text
        saved = decision.json()["tie_resolution"]
        box = setup["boxes"]["local_n1"]
        corrected = setup["clients"]["receiveronly"].put(
            setup["paths"]["n1_boxes"] + f"/{box['id']}/receipt",
            json=event_command(
                box["revision"],
                "2026-11-15T22:46:00+08:00",
                reason="Correct the receipt event from the signed box log.",
            ),
        )
        assert corrected.status_code == 200, corrected.text
        after = supervisor.get(result_path)
        assert after.status_code == 200, after.text
        current = after.json()
        assert current["basis_digest"] != before["basis_digest"]
        assert current["tie_resolution"]["valid"] is False
        assert current["resolution_history"][0]["revision"] == saved["revision"]
        assert current["resolution_history"][0]["candidate_id"] == saved["candidate_id"]
        stale = supervisor.post(
            result_path + "/tie-resolutions",
            json={
                **_tie_command(current, saved["candidate_id"], request_id=str(uuid4())),
                "expected_resolution_revision": saved["revision"],
                "basis_digest": before["basis_digest"],
            },
        )
        assert stale.status_code == 409, stale.text
        reread = supervisor.get(result_path).json()
        assert reread["resolution_history"] == current["resolution_history"]


def test_tie_resolution_replay_is_idempotent_and_decision_revision_is_compare_and_set(
    admin: TestClient, database_url: str,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        initial = supervisor.get(path).json()
        assert initial["complete"] is True, initial["pending"]
        assert initial["pending"] == [], initial["pending"]
        command = _tie_command(initial, initial["tie_candidate_ids"][1])
        saved = supervisor.post(path + "/tie-resolutions", json=command)
        assert saved.status_code == 200, saved.text
        replay = supervisor.post(path + "/tie-resolutions", json=command)
        assert replay.status_code == 200, replay.text
        assert replay.json()["tie_resolution"] == saved.json()["tie_resolution"]
        assert len(replay.json()["resolution_history"]) == 1
        stale = supervisor.post(
            path + "/tie-resolutions",
            json={**command, "request_id": str(uuid4()), "expected_resolution_revision": 0},
        )
        assert stale.status_code == 409, stale.text
        reread = supervisor.get(path).json()
        assert len(reread["resolution_history"]) == 1
        assert reread["tie_resolution"]["revision"] == 1


def test_tie_resolution_rejects_nonleader_blank_reason_wrong_password_and_unauthorized_roles(
    admin: TestClient, database_url: str,
) -> None:
    from tests.box_support import box_staff

    with complete_tie_setup(admin, database_url, candidate_count=3) as setup:
        round_state = _save_tie_round(setup, [2, 2, 0])
        supervisor = setup["clients"]["supervisor"]
        path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        result = supervisor.get(path).json()
        assert result["complete"] is True, result["pending"]
        assert result["pending"] == [], result["pending"]
        assert len(result["tie_candidate_ids"]) == 2
        nonleader = round_state["options"]["candidates"][2]["id"]

        wrong_candidate = supervisor.post(
            path + "/tie-resolutions", json=_tie_command(result, nonleader)
        )
        assert wrong_candidate.status_code >= 400
        blank_reason = supervisor.post(
            path + "/tie-resolutions",
            json={**_tie_command(result, result["tie_candidate_ids"][0]), "reason": "   "},
        )
        assert blank_reason.status_code == 422
        wrong_password = supervisor.post(
            path + "/tie-resolutions",
            json={
                **_tie_command(result, result["tie_candidate_ids"][0]),
                "password": "Incorrect-Password-42!",
            },
        )
        assert wrong_password.status_code == 401
        limited_path = path + "/tie-resolutions"
        with box_staff(
            admin,
            database_url,
            setup["clock"],
            "supervisor",
            [setup["stations"]["N1"]["id"]],
        ) as (limited_supervisor, _):
            limited = limited_supervisor.post(
                limited_path,
                json=_tie_command(result, result["tie_candidate_ids"][0]),
            )
            assert limited.status_code == 403
        administrator = admin.post(
            path + "/tie-resolutions",
            json=_tie_command(result, result["tie_candidate_ids"][0]),
        )
        assert administrator.status_code == 403
        current = supervisor.get(path).json()
        assert current["tie_resolution"] is None
        assert current["resolution_history"] == []
