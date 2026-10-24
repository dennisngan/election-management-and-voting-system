"""Counting-scope isolation, exact pins and simultaneous replay through public APIs."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import READY_PASSWORD, event_command, prepared_box
from tests.counting_support import counting_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def local_scope(setup: dict, **changes: object) -> dict:
    box, accounting = setup["boxes"]["local_n1"], setup["accounting"]["N1"]["record"]
    return {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "reference": "Local N1 received-box scope",
        "event_at": "2026-11-15T23:10:00+08:00",
        "box_revisions": [{"box_id": box["id"], "revision": 2}],
        "accounting_revisions": [{"station_id": accounting["station_id"], "revision": 1}],
        "notes": "Use the received local box and its approved source accounting.",
        **changes,
    }


def command(revision: int, **changes: object) -> dict:
    return {"request_id": str(uuid4()), "expected_revision": revision, **changes}


def ready_local_scope(setup: dict) -> dict:
    receiver = setup["clients"]["receiveronly"]
    path = setup["paths"]["n1_counting_scopes"]
    saved = receiver.post(path, json=local_scope(setup))
    assert saved.status_code == 201, saved.text
    submitted = receiver.post(f"{path}/{saved.json()['id']}/submit", json=command(1))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["count_ready"] is True
    assert submitted.json()["estimated_box_from_stock_quantity"] == 5
    return submitted.json()


@pytest.mark.parametrize("same_request", [False, True])
def test_simultaneous_scope_creation_gives_one_physical_box_one_active_membership(
    admin: TestClient,
    database_url: str,
    same_request: bool,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        first = local_scope(setup, reference="Race scope A")
        second = dict(first) if same_request else local_scope(setup, reference="Race scope B")
        clients_ready = Barrier(3)

        def create(payload: dict) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=setup["clock"])) as peer:
                peer.headers.update(receiver.headers)
                clients_ready.wait(timeout=5)
                response = peer.post(path, json=payload)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, payload) for payload in (first, second)]
            clients_ready.wait(timeout=5)
            outcomes = [future.result() for future in futures]
        assert sorted(status for status, _ in outcomes) == (
            [200, 201] if same_request else [201, 409]
        )
        if same_request:
            assert outcomes[0][1] == outcomes[1][1]
        else:
            failed = next(body for status, body in outcomes if status == 409)
            assert failed["detail"]["code"] == "box_already_in_scope"
        current = receiver.get(path)
        assert current.status_code == 200
        assert len(current.json()["scopes"]) == 1
        scope = current.json()["scopes"][0]
        assert scope["revision"] == 1
        assert [row["id"] for row in scope["box_basis"]] == [setup["boxes"]["local_n1"]["id"]]
        local = next(
            row for row in current.json()["boxes"] if row["id"] == setup["boxes"]["local_n1"]["id"]
        )
        assert local["scope_id"] == scope["id"]
        history = receiver.get(f"{path}/{scope['id']}")
        assert history.status_code == 200
        assert len(history.json()["history"]) == 1


def test_received_links_allow_only_scoped_source_snapshots_and_correct_destination_boxes(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, polling = setup["clients"]["receiveronly"], setup["clients"]["polling"]
        path = setup["paths"]["n1_counting_scopes"]
        allowed = receiver.get(path)
        assert allowed.status_code == 200
        sources = {
            row["station"]["id"]: row["record"] for row in allowed.json()["source_accounting"]
        }
        assert set(sources) == {setup["stations"]["N1"]["id"], setup["stations"]["N2"]["id"]}
        source = sources[setup["stations"]["N2"]["id"]]
        assert source["revision"] == 1 and source["approval_valid"] is True
        assert source["summary"]["ordinary_issued_quantity"] == 5
        assert source["summary"]["estimated_box_from_stock_quantity"] == 5
        assert source["summary"]["observed_counted_quantity"] is None
        source_base = f"/api/workspace/stations/{setup['stations']['N2']['id']}"
        for suffix in (
            "/accounting",
            "/accounting/revisions/1",
            "/stock",
            "/stock-snapshots",
            "/special-papers",
            "/turnout",
            "/polling",
        ):
            denied = receiver.get(source_base + suffix)
            assert denied.status_code == 403, (suffix, denied.text)
            assert denied.json()["detail"]["code"] == "station_access_denied"

        for code in ("N3", "S1"):
            station_id = setup["stations"][code]["id"]
            foreign_path = f"/api/workspace/stations/{station_id}"
            assert receiver.get(foreign_path + "/counting-scopes").status_code == 403
            foreign = polling.post(
                foreign_path + "/boxes",
                json=prepared_box(
                    box_reference="Other destination " + code,
                ),
            )
            assert foreign.status_code == 201
            denied = receiver.post(
                path,
                json=local_scope(
                    setup,
                    reference="Reject foreign " + code,
                    box_revisions=[{"box_id": foreign.json()["id"], "revision": 1}],
                    accounting_revisions=[],
                ),
            )
            assert denied.status_code == 404
            assert denied.json()["detail"]["code"] == "box_not_found"
        assert receiver.get(path).json()["scopes"] == []


@pytest.mark.parametrize("role", ["polling", "supervisor"])
def test_operational_read_access_does_not_allow_non_counting_scope_writes(
    admin: TestClient,
    database_url: str,
    role: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        client, path = setup["clients"][role], setup["paths"]["n1_counting_scopes"]
        assert client.get(path).status_code == 200
        rejected = client.post(path, json=local_scope(setup))
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["code"] == "counting_officer_required"
        scope = ready_local_scope(setup)
        rejected = client.put(
            f"{path}/{scope['id']}",
            json=local_scope(
                setup,
                expected_revision=1,
                amendment_reason="A non-counting role cannot amend",
            ),
        )
        assert rejected.status_code == 403
        rejected = client.post(f"{path}/{scope['id']}/submit", json=command(1))
        assert rejected.status_code == 403
        assert setup["clients"]["receiveronly"].get(path).json()["scopes"][0] == scope


def test_receipt_correction_invalidates_ready_scope_and_preserves_original_box_pin(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        rejected = receiver.post(
            path,
            json=local_scope(
                setup,
                box_revisions=[{"box_id": setup["boxes"]["local_n1"]["id"], "revision": 1}],
            ),
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "box_revision_conflict"
        scope = ready_local_scope(setup)
        box = setup["boxes"]["local_n1"]
        correction = receiver.put(
            f"{setup['paths']['n1_boxes']}/{box['id']}/receipt",
            json=event_command(2, "2026-11-15T22:46:00+08:00", reason="Checked receipt minute"),
        )
        assert correction.status_code == 200, correction.text
        assert correction.json()["revision"] == 3
        current = receiver.get(f"{path}/{scope['id']}")
        assert current.status_code == 200
        stale = current.json()["record"]
        assert stale["status"] == "submitted"
        assert stale["source_current"] is False
        assert stale["count_ready"] is False
        assert {row["code"] for row in stale["blockers"]} == {"scope_basis_stale"}
        assert stale["box_basis"] == scope["box_basis"]
        assert stale["box_basis"][0]["revision"] == 2
        assert stale["box_basis"][0]["receipt_at"] == "2026-11-15T14:45:00Z"
        assert stale["accounting_basis"] == scope["accounting_basis"]
        assert receiver.get(f"{path}/{scope['id']}/revisions/1").json() == stale


def test_new_source_p18_revision_invalidates_ready_scope_without_replacing_frozen_source(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        scope = ready_local_scope(setup)
        source, both = setup["accounting"]["N1"], setup["clients"]["bothcounting"]
        revised = both.put(
            source["path"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": source["special_papers"]["id"],
                "special_paper_revision": 1,
                "notes": "A reasoned accounting note correction creates a new P(18) revision.",
                "amendment_reason": "Checked source document reference",
            },
        )
        assert revised.status_code == 200
        assert revised.json()["revision"] == 2
        assert both.post(source["path"] + "/submit", json=command(2)).status_code == 200
        approved = setup["clients"]["supervisor"].post(
            source["path"] + "/approve",
            json=command(2, password=READY_PASSWORD),
        )
        assert approved.status_code == 200
        assert approved.json()["approval_valid"] is True
        current = receiver.get(f"{path}/{scope['id']}")
        assert current.status_code == 200
        stale = current.json()["record"]
        assert stale["source_current"] is False
        assert stale["count_ready"] is False
        assert {row["code"] for row in stale["blockers"]} == {"scope_basis_stale"}
        assert stale["accounting_basis"] == scope["accounting_basis"]
        assert stale["accounting_basis"][0]["revision"] == 1
        assert stale["accounting_basis"][0]["summary"]["estimated_box_from_stock_quantity"] == 5
        assert stale["accounting_basis"][0]["notes"] == ""
        rejected = receiver.put(
            f"{path}/{scope['id']}",
            json=local_scope(
                setup,
                expected_revision=1,
                amendment_reason="Do not accept an obsolete P(18) pin",
            ),
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "accounting_source_stale"
        assert receiver.get(f"{path}/{scope['id']}/revisions/1").json() == stale


def test_request_identity_stale_revision_and_blank_amendment_are_visible_conflicts(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver, path = setup["clients"]["receiveronly"], setup["paths"]["n1_counting_scopes"]
        payload = local_scope(setup)
        saved = receiver.post(path, json=payload)
        assert saved.status_code == 201
        rejected = receiver.post(path, json={**payload, "notes": "Changed payload at same UUID"})
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "request_conflict"
        scope_path = f"{path}/{saved.json()['id']}"
        rejected = receiver.put(scope_path, json={**payload, "request_id": str(uuid4())})
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "revision_conflict"
        submitted = receiver.post(scope_path + "/submit", json=command(1))
        assert submitted.status_code == 200
        for reason in ("", " \t\n "):
            rejected = receiver.put(
                scope_path,
                json={
                    **payload,
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "amendment_reason": reason,
                    "notes": "Cannot alter submitted sources silently",
                },
            )
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "scope_reason_required"
        assert receiver.post(path, json=payload).json() == saved.json()
        history = receiver.get(scope_path)
        assert history.status_code == 200
        assert len(history.json()["history"]) == 1
        assert history.json()["record"] == submitted.json()
