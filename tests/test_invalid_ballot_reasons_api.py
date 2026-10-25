"""Election F1 reason configuration is observed through authenticated public APIs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.configuration_support import create_election
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url
from tests.turnout_support import (
    TurnoutClock,
    arrange_finalized_turnout_election,
    turnout_scope,
    turnout_staff,
)


def test_administrator_reads_verified_f1_sources_and_project_other(admin: TestClient) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    response = admin.get(path)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 8
    assert [row["code"] for row in items] == [
        "gc-f1-a",
        "gc-f1-b",
        "gc-f1-c",
        "gc-f1-d",
        "gc-f1-e",
        "gc-f1-f",
        "gc-f1-g",
        "other-f1",
    ]
    first, last_verified, other = items[0], items[6], items[7]
    assert first["source_english"] == "Endorsed with the words “重複” and “TENDERED”"
    assert first["source_letter"] == "a"
    assert first["reference_page"] == 114 and first["reference_printed_page"] == 115
    assert last_verified["source_english"] == (
        "Contains a vote for a candidate whose name thereon is crossed out"
    )
    assert last_verified["reference_page"] == 123
    assert last_verified["reference_printed_page"] == 124
    assert all(row["verified_source"] and row["stage"] == "f1" for row in items[:7])
    assert all(row["translation_provenance"] == "project_translation" for row in items)
    assert other["is_other"] is True and other["verified_source"] is False
    assert other["source_english"] == "" and other["source_letter"] is None
    assert other["reference_page"] is None and other["reference_printed_page"] is None
    assert other["enabled"] is True and other["explanation_required"] is True


def test_administrator_can_filter_the_stage_specific_reason_catalog(admin: TestClient) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    f1 = admin.get(path)
    f2 = admin.get(path, params={"stage": "f2"})
    assert f1.status_code == 200 and f2.status_code == 200
    assert [row["stage"] for row in f1.json()["items"]] == ["f1"] * 8
    assert [row["code"] for row in f2.json()["items"]] == [
        "gc-f2-h",
        "gc-f2-i",
        "gc-f2-j",
        "gc-f2-k",
        "other-f2",
    ]
    assert all(row["stage"] == "f2" for row in f2.json()["items"])


def catalog_input(**changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "label_en": "Project-specific reason",
        "label_tc": "項目自訂原因",
        "label_sc": "项目自定义原因",
        "enabled": True,
        "explanation_required": False,
        **changes,
    }


def test_administrator_creates_project_reason_and_replays_one_saved_effect(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    payload = catalog_input(code="project-f1-note")
    created = admin.post(path, json=payload)
    assert created.status_code == 201, created.text
    reason = created.json()
    assert reason["code"] == "project-f1-note" and reason["stage"] == "f1"
    assert reason["revision"] == 1 and reason["enabled"] is True
    assert reason["source"] == "project_configured" and reason["verified_source"] is False
    assert reason["source_english"] == "" and reason["source_letter"] is None
    assert reason["reference_page"] is None and reason["reference_printed_page"] is None
    assert reason["is_other"] is False
    assert reason["label_tc"] == "項目自訂原因"
    assert reason["actor_id"] == admin.get("/api/auth/me").json()["id"]
    replay = admin.post(path, json=payload)
    assert replay.status_code == 200 and replay.json() == reason
    assert len(admin.get(path).json()["items"]) == 9
    conflict = admin.post(path, json={**payload, "label_en": "Changed effect"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "request_conflict"
    duplicate = admin.post(path, json={**payload, "request_id": str(uuid4())})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "invalid_reason_code_exists"


def test_administrator_creates_and_edits_project_f2_reason_without_changing_stage(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    created = admin.post(
        path,
        json=catalog_input(code="project-f2-note", stage="f2"),
    )
    assert created.status_code == 201, created.text
    reason = created.json()
    assert reason["stage"] == "f2" and reason["code"] == "project-f2-note"
    assert reason["source"] == "project_configured" and reason["source_english"] == ""
    assert [row["id"] for row in admin.get(path).json()["items"]].count(reason["id"]) == 0
    f2 = admin.get(path, params={"stage": "f2"}).json()["items"]
    assert reason["id"] in {row["id"] for row in f2}
    edited = admin.put(
        f"{path}/{reason['id']}",
        json=catalog_input(
            expected_revision=1,
            label_en="F2 display wording",
            label_tc="F2 顯示文字",
            label_sc="F2 显示文字",
        ),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["stage"] == "f2" and edited.json()["revision"] == 2
    assert edited.json()["label_en"] == "F2 display wording"
    assert admin.get(f"{path}/{reason['id']}").json()["record"] == edited.json()
    forged_stage = admin.put(
        f"{path}/{reason['id']}",
        json=catalog_input(
            expected_revision=2,
            request_id=str(uuid4()),
            stage="f1",
        ),
    )
    assert forged_stage.status_code == 422
    assert admin.get(f"{path}/{reason['id']}").json()["record"] == edited.json()


def test_admin_revises_display_labels_without_replacing_verified_source_history(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    target = path + f"/{original['id']}"
    payload = catalog_input(
        expected_revision=1,
        label_en="Local display wording",
        label_tc="本站顯示文字",
        label_sc="本站显示文字",
        enabled=False,
        explanation_required=True,
    )
    changed = admin.put(target, json=payload)
    assert changed.status_code == 200, changed.text
    current = changed.json()
    assert current["revision"] == 2 and current["enabled"] is False
    assert current["label_en"] == "Local display wording"
    assert current["label_tc"] == "本站顯示文字"
    assert current["explanation_required"] is True
    for key in (
        "code",
        "stage",
        "verified_source",
        "source_english",
        "source_letter",
        "reference_page",
        "reference_printed_page",
        "is_other",
    ):
        assert current[key] == original[key]
    history = admin.get(target)
    assert history.status_code == 200
    assert history.json() == {"record": current, "history": [current, original]}
    assert admin.put(target, json=payload).json() == current
    stale = admin.put(target, json={**payload, "request_id": str(uuid4())})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    rejected = admin.put(
        target,
        json={
            **payload,
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "source_english": "Invented official source",
        },
    )
    assert rejected.status_code == 422
    assert admin.get(target).json() == history.json()


def test_project_other_cannot_be_disabled_or_stop_requiring_an_explanation(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    other = next(row for row in admin.get(path).json()["items"] if row["is_other"])
    target = path + f"/{other['id']}"
    for enabled, required in ((False, True), (True, False), (False, False)):
        denied = admin.put(
            target,
            json=catalog_input(
                expected_revision=1,
                enabled=enabled,
                explanation_required=required,
            ),
        )
        assert denied.status_code == 422, denied.text
        assert denied.json()["detail"]["code"] == "invalid_reason_other_required"
    history = admin.get(target)
    assert history.status_code == 200
    assert history.json() == {"record": other, "history": [other]}
    renamed = admin.put(
        target,
        json=catalog_input(
            expected_revision=1,
            explanation_required=True,
            label_en="Other: record details",
        ),
    )
    assert renamed.status_code == 200
    assert renamed.json()["is_other"] is True and renamed.json()["enabled"] is True
    assert renamed.json()["explanation_required"] is True
    assert renamed.json()["source_english"] == ""


def test_station_catalog_is_assigned_operational_and_enabled_f1_only(
    admin: TestClient,
    database_url: str,
) -> None:
    scope = turnout_scope(admin, activate=False)
    election_id = scope["election"]["id"]
    path = f"/api/elections/{election_id}/invalid-ballot-reasons"
    catalog = admin.get(path).json()["items"]
    disabled = catalog[0]
    changed = admin.put(
        path + f"/{disabled['id']}",
        json=catalog_input(
            expected_revision=1,
            enabled=False,
        ),
    )
    assert changed.status_code == 200
    custom = admin.post(path, json=catalog_input(code="operational-f1-choice"))
    assert custom.status_code == 201
    station_id, other_id = [row["id"] for row in scope["stations"]]
    station_path = f"/api/workspace/stations/{station_id}/invalid-ballot-reasons"
    for role in ("polling_officer", "counting_officer", "supervisor"):
        with turnout_staff(admin, database_url, TurnoutClock(), [station_id], role) as (client, _):
            response = client.get(station_path)
            f2_response = client.get(station_path, params={"stage": "f2"})
            assert response.status_code == 200, response.text
            assert f2_response.status_code == 200, f2_response.text
            items = response.json()["items"]
            f2_items = f2_response.json()["items"]
            assert len(items) == 8
            assert all(row["enabled"] and row["stage"] == "f1" for row in items)
            assert len(f2_items) == 5
            assert all(row["enabled"] and row["stage"] == "f2" for row in f2_items)
            assert disabled["id"] not in {row["id"] for row in items}
            assert custom.json()["id"] in {row["id"] for row in items}
            denied = client.get(path)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "administrator_required"
            assert client.post(path, json=catalog_input(code="role-denied")).status_code == 403
            target = path + f"/{disabled['id']}"
            assert client.get(target).status_code == 403
            assert client.put(target, json=catalog_input(expected_revision=2)).status_code == 403
            denied = client.get(f"/api/workspace/stations/{other_id}/invalid-ballot-reasons")
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "station_access_denied"
    assert len(admin.get(path).json()["items"]) == 9
    assert admin.get(station_path).status_code == 403


@pytest.mark.parametrize(
    "invalid",
    [
        {"label_en": " \t "},
        {"label_tc": ""},
        {"label_sc": " "},
        {"code": " \n "},
        {"code": "x" * 65},
        {"stage": "f3"},
        {"enabled": "false"},
        {"explanation_required": 1},
        {"source_english": "Unverified official wording"},
        {"verified_source": True},
        {"is_other": True},
    ],
)
def test_creation_rejects_invalid_labels_types_and_forged_provenance(
    admin: TestClient,
    invalid: dict,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    response = admin.post(path, json=catalog_input(**{"code": "project-validation", **invalid}))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert len(admin.get(path).json()["items"]) == 8


def test_catalog_history_and_reason_ids_remain_with_their_election(admin: TestClient) -> None:
    first, second = create_election(admin), create_election(admin)
    paths = [f"/api/elections/{row['id']}/invalid-ballot-reasons" for row in (first, second)]
    original = admin.get(paths[0]).json()["items"][0]
    wrong = paths[1] + f"/{original['id']}"
    assert admin.get(wrong).status_code == 404
    response = admin.put(wrong, json=catalog_input(expected_revision=1))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "invalid_reason_not_found"
    created = [admin.post(path, json=catalog_input(code="same-project-code")) for path in paths]
    assert [response.status_code for response in created] == [201, 201]
    assert created[0].json()["id"] != created[1].json()["id"]
    assert admin.get("/api/elections/2147483647/invalid-ballot-reasons").status_code == 404


def test_finalized_catalog_is_readable_but_cannot_create_or_edit(
    admin: TestClient,
    database_url: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    # Existing synthetic lifecycle arrangement; this does not exercise Ticket24 finalization.
    arrange_finalized_turnout_election(database_url, election["id"])
    assert admin.get(path).status_code == 200
    target = path + f"/{original['id']}"
    assert admin.get(target).json() == {"record": original, "history": [original]}
    created = admin.post(path, json=catalog_input(code="finalized-denied"))
    edited = admin.put(target, json=catalog_input(expected_revision=1))
    for response in (created, edited):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "election_read_only"
    assert len(admin.get(path).json()["items"]) == 8


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_catalog_creation_preserves_one_code_and_one_replay_effect(
    admin: TestClient,
    database_url: str,
    same_request: bool,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    first = catalog_input(code="concurrent-project-code")
    second = dict(first) if same_request else catalog_input(code="concurrent-project-code")
    ready = Barrier(3)

    def create(payload: dict) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            ready.wait(timeout=5)
            response = client.post(path, json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create, payload) for payload in (first, second)]
        ready.wait(timeout=5)
        outcomes = [future.result() for future in futures]
    assert sorted(status for status, _ in outcomes) == ([200, 201] if same_request else [201, 409])
    if same_request:
        assert outcomes[0][1] == outcomes[1][1]
    else:
        assert next(body for status, body in outcomes if status == 409)["detail"]["code"] == (
            "invalid_reason_code_exists"
        )
    items = admin.get(path).json()["items"]
    assert len(items) == 9
    reason = next(row for row in items if row["code"] == "concurrent-project-code")
    assert len(admin.get(path + f"/{reason['id']}").json()["history"]) == 1


def test_concurrent_edits_preserve_one_new_revision_and_visible_conflict(
    admin: TestClient,
    database_url: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    original = admin.get(path).json()["items"][0]
    target = path + f"/{original['id']}"
    ready = Barrier(3)

    def edit(english: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url)) as client:
            client.headers.update(admin.headers)
            ready.wait(timeout=5)
            response = client.put(
                target,
                json=catalog_input(
                    expected_revision=1,
                    label_en=english,
                ),
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(edit, name) for name in ("Revision A", "Revision B")]
        ready.wait(timeout=5)
        outcomes = [future.result() for future in futures]
    assert sorted(status for status, _ in outcomes) == [200, 409]
    rejected = next(body for status, body in outcomes if status == 409)
    assert rejected["detail"]["code"] == "revision_conflict"
    history = admin.get(target).json()
    assert history["record"]["revision"] == 2
    assert history["record"]["label_en"] in ("Revision A", "Revision B")
    assert len(history["history"]) == 2
    assert history["history"][1] == original
