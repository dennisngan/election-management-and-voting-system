"""Real MySQL public API behavior for configurable complaint categories and cases."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from election.server.app import create_app
from election.server.configuration_models import Election
from election.server.db import make_engine
from tests.complaint_support import (
    ComplaintClock,
    category_edit,
    complaint_payload,
    complaint_staff,
    complaint_stations,
    station_categories,
)
from tests.configuration_support import create_election
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_new_election_has_only_verified_default_category_codes(admin: TestClient) -> None:
    election = create_election(admin)
    response = admin.get(f"/api/elections/{election['id']}/complaint-categories")
    assert response.status_code == 200
    categories = response.json()["items"]
    assert [row["code"] for row in categories] == ["9", "10", "11", "12", "30"]
    assert [row["source_english"] for row in categories] == [
        "Polling arrangements",
        "NCZ arrangements",
        "Illegal conduct at the polling station (e.g. photo-taking)",
        "Against Returning Officer or his/her staff",
        "Miscellaneous (please specify nature)",
    ]
    assert all(row["verified_source"] for row in categories)
    assert all(row["translation_provenance"] == "project_translation" for row in categories)
    assert categories[-1]["is_other"] and categories[-1]["description_required"]


def test_assigned_station_starts_with_no_cases_without_an_opening_event(
    admin: TestClient, database_url: str
) -> None:
    station = complaint_stations(admin)["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["context"]["station"]["id"] == station["id"]
        assert response.json()["schedule_state"] == "configured"


def test_administrator_creates_and_revises_project_category_without_inventing_source(
    admin: TestClient,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    body = {
        "request_id": str(uuid4()),
        "code": "PROJECT-A",
        "label_en": "Project support",
        "label_tc": "項目支援",
        "label_sc": "项目支援",
        "enabled": True,
        "description_required": False,
    }
    created = admin.post(path, json=body)
    assert created.status_code == 201
    original = created.json()
    assert original["source"] == "project_configured" and not original["verified_source"]
    assert original["source_english"] == "" and original["reference_page"] is None
    assert original["code"] == "PROJECT-A" and original["revision"] == 1
    replay = admin.post(path, json=body)
    assert replay.status_code == 200 and replay.json() == original
    update = {key: value for key, value in body.items() if key != "code"}
    update.update(request_id=str(uuid4()), expected_revision=1, label_tc="項目協助", enabled=False)
    edited = admin.put(f"{path}/{original['id']}", json=update)
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2 and not edited.json()["enabled"]
    assert edited.json()["label_tc"] == "項目協助"
    assert edited.json()["code"] == "PROJECT-A"
    stale = admin.put(f"{path}/{original['id']}", json={**update, "request_id": str(uuid4())})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"


def test_case_creation_preserves_source_category_actual_and_server_times_and_replay(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, actor):
        categories = client.get(
            f"/api/workspace/stations/{station['id']}/complaint-categories"
        ).json()["items"]
        body = complaint_payload(categories[0], case_reference="  000AbC  ")
        created = client.post(path, json=body)
        assert created.status_code == 201
        row = created.json()
        assert row["id"] > 0 and row["revision_id"] > 0 and row["revision"] == 1
        assert row["case_reference"] == "000AbC"
        assert row["received_at"] == "2026-11-15T00:15:00Z"
        assert row["entered_at"] == "2026-11-15T16:00:00Z" and row["actor_id"] == actor["id"]
        assert row["category_label_en"] == "Polling arrangements"
        assert row["category_label_tc"] == "投票安排" and row["category_code"] == "9"
        assert row["category_source"] == "verified_reference" and not row["ever_submitted"]
        assert row["work_status"] == "in_progress" and row["completed_at"] is None
        assert row["period_index"] == 1 and row["coverage_status"] == "within_configured_periods"
        replay = client.post(path, json=body)
        assert replay.status_code == 200 and replay.json() == row
        assert client.get(path).json()["items"] == [row]


def test_completion_and_reasoned_amendment_retain_exact_case_history(
    admin: TestClient,
    database_url: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    clock = ComplaintClock()
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        client,
        actor,
    ):
        category = station_categories(client, station["id"])[0]
        body = complaint_payload(category)
        original = client.post(path, json=body).json()
        update = complaint_payload(
            category,
            expected_revision=1,
            work_status="completed",
            completed_at="2026-11-15T08:45:00+08:00",
        )
        completed = client.put(f"{path}/{original['id']}", json=update)
        assert completed.status_code == 200
        assert completed.json()["revision"] == 2
        assert completed.json()["completed_at"] == "2026-11-15T00:45:00Z"
        amendment = complaint_payload(
            category,
            expected_revision=2,
            work_status="completed",
            completed_at="2026-11-15T08:46:00+08:00",
            reason="核對紙本完成時間更正一分鐘",
        )
        amended = client.post(f"{path}/{original['id']}/amend", json=amendment)
        assert amended.status_code == 200
        assert amended.json()["revision"] == 3
        assert amended.json()["amendment_reason"] == "核對紙本完成時間更正一分鐘"
        history = client.get(f"{path}/{original['id']}/history")
        assert history.status_code == 200
        assert history.json()["items"] == [original, completed.json(), amended.json()]
        historical = client.get(f"{path}/{original['id']}?revision=1")
        assert historical.status_code == 200 and historical.json() == original
        assert client.get(f"{path}/{original['id']}").json() == amended.json()
        assert all(row["actor_id"] == actor["id"] for row in history.json()["items"])


def test_existing_case_pins_old_labels_after_category_rename_and_disable(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    catalog = f"/api/elections/{setup['election']['id']}/complaint-categories"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        original = client.post(path, json=complaint_payload(category)).json()
        edited = admin.put(
            f"{catalog}/{category['id']}",
            json=category_edit(
                category,
                label_en="Renamed project display",
                label_tc="改名顯示",
                enabled=False,
            ),
        )
        assert edited.status_code == 200
        assert edited.json()["source_english"] == "Polling arrangements"
        assert edited.json()["verified_source"] and edited.json()["reference_page"] == 61
        completed = client.put(
            f"{path}/{original['id']}",
            json=complaint_payload(
                edited.json(),
                expected_revision=1,
                work_status="completed",
                completed_at="2026-11-15T09:00:00+08:00",
            ),
        )
        assert completed.status_code == 200
        assert completed.json()["category_revision"] == 1
        assert completed.json()["category_label_en"] == "Polling arrangements"
        assert completed.json()["category_label_tc"] == "投票安排"
        disabled = client.post(
            path,
            json=complaint_payload(
                edited.json(),
                case_reference="投訴 0002",
            ),
        )
        assert disabled.status_code == 422
        assert disabled.json()["detail"]["code"] == "complaint_category_disabled"
        assert client.get(f"{path}/{original['id']}?revision=1").json() == original


@pytest.mark.parametrize("changes", [{"enabled": False}, {"description_required": False}])
def test_other_category_cannot_lose_fallback_rule(admin: TestClient, changes: dict) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    other = admin.get(path).json()["items"][-1]
    response = admin.put(f"{path}/{other['id']}", json=category_edit(other, **changes))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "complaint_other_required"
    assert admin.get(path).json()["items"][-1] == other


def test_reference_corrections_reserve_all_aliases_and_allow_own_alias_return(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"], setup["N2"]["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        original = client.post(
            path, json=complaint_payload(category, case_reference="000ABC")
        ).json()
        corrected = client.post(
            f"{path}/{original['id']}/amend",
            json=complaint_payload(
                category,
                expected_revision=1,
                case_reference="000DEF",
                reason="核對投訴紙本編號",
            ),
        )
        assert corrected.status_code == 200
        for reference in ("000ABC", "000DEF", " 000ABC "):
            duplicate = client.post(
                path, json=complaint_payload(category, case_reference=reference)
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "complaint_reference_exists"
        returned = client.post(
            f"{path}/{original['id']}/amend",
            json=complaint_payload(
                category,
                expected_revision=2,
                case_reference="000ABC",
                reason="確認原編號正確",
            ),
        )
        assert returned.status_code == 200 and returned.json()["case_reference"] == "000ABC"
        distinct_case = client.post(path, json=complaint_payload(category, case_reference="000abc"))
        assert distinct_case.status_code == 201
        other_path = f"/api/workspace/stations/{setup['N2']['id']}/complaints"
        other_station = client.post(
            other_path, json=complaint_payload(category, case_reference="000ABC")
        )
        assert other_station.status_code == 201
        assert [
            row["case_reference"]
            for row in client.get(f"{path}/{original['id']}/history").json()["items"]
        ] == ["000ABC", "000DEF", "000ABC"]


def test_reference_limit_applies_after_trimming_outer_whitespace_only(
    admin: TestClient,
    database_url: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        response = client.post(
            path,
            json=complaint_payload(
                category,
                case_reference=" " * 70 + "000 A b" + "\t" * 70,
            ),
        )
        assert response.status_code == 201
        assert response.json()["case_reference"] == "000 A b"


@pytest.mark.parametrize(
    "changes",
    [
        {"case_reference": " "},
        {"case_reference": "x" * 65},
        {"description": "x" * 4001},
        {"received_at": "2026-11-15T08:15:00"},
        {"received_at": "0999-12-31T23:59:00Z"},
        {"received_at": "1000-01-01T00:00:00+14:00"},
        {"received_at": "9999-12-31T23:59:00-14:00"},
        {"received_at": "2026-11-16T00:01:00+08:00"},
        {"work_status": "completed", "completed_at": None},
        {"work_status": "completed", "completed_at": "2026-11-15T08:14:59+08:00"},
        {"work_status": "completed", "completed_at": "2026-11-16T00:01:00+08:00"},
        {"completed_at": "2026-11-15T08:45:00+08:00"},
        {"work_status": "submitted"},
        {"ever_submitted": True},
        {"category_verified_source": True},
        {"expected_category_revision": True},
    ],
)
def test_case_rejects_invalid_content_without_leaving_a_case(
    admin: TestClient,
    database_url: str,
    changes: dict,
) -> None:
    station = complaint_stations(admin)["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        rejected = client.post(path, json=complaint_payload(category, **changes))
        assert rejected.status_code == 422
        assert client.get(path).json()["items"] == []


@pytest.mark.parametrize(
    "received,period,coverage",
    [
        ("2026-11-15T07:29:59+08:00", None, "outside_configured_periods"),
        ("2026-11-15T07:30:00+08:00", 1, "within_configured_periods"),
        ("2026-11-15T08:30:00+08:00", 2, "within_configured_periods"),
        ("2026-11-15T22:29:59+08:00", 15, "within_configured_periods"),
        ("2026-11-15T22:30:00+08:00", None, "outside_configured_periods"),
    ],
)
def test_period_coverage_is_schedule_anchored_and_never_clamps_actual_receipt(
    admin: TestClient,
    database_url: str,
    received: str,
    period: int | None,
    coverage: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        created = client.post(path, json=complaint_payload(category, received_at=received))
        assert created.status_code == 201
        row = created.json()
        assert row["period_index"] == period and row["coverage_status"] == coverage
        assert row["received_at"] == datetime.fromisoformat(received).astimezone(
            UTC
        ).isoformat().replace("+00:00", "Z")


def test_other_description_is_raw_but_must_be_meaningful_and_category_switch_is_current(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    catalog = f"/api/elections/{setup['election']['id']}/complaint-categories"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category, *_, other = station_categories(client, station["id"])
        empty = client.post(path, json=complaint_payload(other, description=" \n\t"))
        assert empty.status_code == 422
        assert empty.json()["detail"]["code"] == "complaint_description_required"
        raw = "  Water flooding\n入口積水 & <需協助>  "
        created = client.post(path, json=complaint_payload(other, description=raw)).json()
        assert created["description"] == raw and created["is_other"]
        changed_category = admin.put(
            f"{catalog}/{category['id']}",
            json=category_edit(
                category,
                label_tc="更新顯示名稱",
            ),
        ).json()
        stale = client.put(
            f"{path}/{created['id']}",
            json=complaint_payload(
                category,
                expected_revision=1,
                description=raw,
            ),
        )
        assert stale.status_code == 409
        changed = client.put(
            f"{path}/{created['id']}",
            json=complaint_payload(
                changed_category,
                expected_revision=1,
                description=raw,
            ),
        )
        assert changed.status_code == 200
        assert changed.json()["category_revision"] == 2
        assert changed.json()["category_label_tc"] == "更新顯示名稱"
        assert client.get(f"{path}/{created['id']}?revision=1").json()["category_code"] == "30"


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_readers_can_view_cases_but_cannot_record_or_configure_them(
    admin: TestClient,
    database_url: str,
    role: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    catalog = f"/api/elections/{setup['election']['id']}/complaint-categories"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (po, _):
        category = station_categories(po, station["id"])[0]
        original = po.post(path, json=complaint_payload(category)).json()
    with complaint_staff(admin, database_url, ComplaintClock(), role, [station["id"]]) as (
        reader,
        _,
    ):
        assert reader.get(path).json()["items"] == [original]
        assert reader.get(f"{path}/{original['id']}").json() == original
        assert reader.get(f"{path}/{original['id']}/history").json()["items"] == [original]
        assert station_categories(reader, station["id"])[0] == category
        assert reader.post(path, json=complaint_payload(category)).status_code == 403
        assert (
            reader.put(
                f"{path}/{original['id']}",
                json=complaint_payload(
                    category,
                    expected_revision=1,
                ),
            ).status_code
            == 403
        )
        assert (
            reader.post(
                f"{path}/{original['id']}/amend",
                json=complaint_payload(
                    category,
                    expected_revision=1,
                    reason="更正",
                ),
            ).status_code
            == 403
        )
        assert reader.get(catalog).status_code == 403
        assert (
            reader.put(f"{catalog}/{category['id']}", json=category_edit(category)).status_code
            == 403
        )


def test_station_and_election_isolation_and_administrator_has_no_operational_override(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        original = client.post(path, json=complaint_payload(category)).json()
        denied = f"/api/workspace/stations/{setup['N2']['id']}/complaints"
        assert client.get(denied).status_code == 403
        assert client.get(f"{denied}/{original['id']}/history").status_code == 403
        assert client.post(denied, json=complaint_payload(category)).status_code == 403
        assert admin.get(path).status_code == 403
        assert admin.post(path, json=complaint_payload(category)).status_code == 403
        other_election = create_election(admin)
        foreign = admin.get(f"/api/elections/{other_election['id']}/complaint-categories").json()[
            "items"
        ][0]
        rejected = client.post(path, json=complaint_payload(foreign, case_reference="other"))
        assert rejected.status_code == 404
        assert rejected.json()["detail"]["code"] == "complaint_category_not_found"
        assert client.get(f"{path}/2147483647").status_code == 404
        assert client.get(f"{path}/{original['id']}?revision=99").status_code == 404
        assert client.get(f"{path}/{original['id']}?revision=0").status_code == 422


def test_password_change_required_account_cannot_access_complaint_workflows(
    admin: TestClient,
    database_url: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    with complaint_staff(
        admin,
        database_url,
        ComplaintClock(),
        "polling_officer",
        [station["id"]],
        ready=False,
    ) as (client, _):
        assert client.get(f"/api/workspace/stations/{station['id']}/complaints").status_code == 403
        assert (
            client.get(f"/api/workspace/stations/{station['id']}/complaint-categories").status_code
            == 403
        )


def test_finalized_cases_and_catalog_are_readable_but_no_longer_writable(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    catalog = f"/api/elections/{setup['election']['id']}/complaint-categories"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        category = station_categories(client, station["id"])[0]
        original = client.post(path, json=complaint_payload(category)).json()
        engine = make_engine(database_url)
        try:
            with Session(engine) as db:
                db.execute(
                    update(Election)
                    .where(Election.id == setup["election"]["id"])
                    .values(status="finalized")
                )
                db.commit()
        finally:
            engine.dispose()
        assert client.get(path).json()["items"] == [original]
        assert client.get(f"{path}/{original['id']}/history").json()["items"] == [original]
        assert (
            client.put(
                f"{path}/{original['id']}",
                json=complaint_payload(
                    category,
                    expected_revision=1,
                ),
            ).status_code
            == 409
        )
        assert admin.get(catalog).status_code == 200
        denied = admin.put(f"{catalog}/{category['id']}", json=category_edit(category))
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "election_read_only"


def test_draft_station_read_explicitly_reports_missing_schedule_and_rejects_writes(
    admin: TestClient,
    database_url: str,
) -> None:
    election = create_election(admin)
    constituency = admin.post(
        f"/api/elections/{election['id']}/constituencies",
        json={
            "request_id": str(uuid4()),
            "code": "N",
            "name": "北區",
        },
    ).json()
    station = admin.post(
        f"/api/elections/{election['id']}/constituencies/{constituency['id']}/stations",
        json={"request_id": str(uuid4()), "code": "N1", "name": "北區投票站"},
    ).json()
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        view = client.get(path)
        assert view.status_code == 200 and view.json()["schedule_state"] == "unavailable"
        assert view.json()["schedule"] is None
        category = station_categories(client, station["id"])[0]
        rejected = client.post(path, json=complaint_payload(category))
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "active_election_required"


@pytest.mark.parametrize(
    "extra",
    [
        {"verified_source": True},
        {"source_english": "Invented official source"},
        {"reference_page": 61},
        {"is_other": True},
    ],
)
def test_catalog_source_provenance_cannot_be_forged(admin: TestClient, extra: dict) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    body = {
        "request_id": str(uuid4()),
        "code": "CUSTOM",
        "label_en": "Custom",
        "label_tc": "自訂",
        "label_sc": "自定义",
        **extra,
    }
    assert admin.post(path, json=body).status_code == 422
    default = admin.get(path).json()["items"][0]
    assert (
        admin.put(
            f"{path}/{default['id']}",
            json=category_edit(
                default,
                **extra,
            ),
        ).status_code
        == 422
    )
    assert admin.get(path).json()["items"][0] == default


def test_catalog_code_identity_and_request_payload_conflicts_are_visible(admin: TestClient) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    category = admin.get(path).json()["items"][0]
    duplicate = admin.post(
        path,
        json={
            "request_id": str(uuid4()),
            "code": "9",
            "label_en": "Custom",
            "label_tc": "自訂",
            "label_sc": "自定义",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "complaint_category_code_exists"
    command = category_edit(category, label_tc="新的項目顯示")
    changed = admin.put(f"{path}/{category['id']}", json=command)
    assert changed.status_code == 200
    replay = admin.put(f"{path}/{category['id']}", json=command)
    assert replay.status_code == 200 and replay.json() == changed.json()
    conflict = admin.put(f"{path}/{category['id']}", json={**command, "label_tc": "另一顯示"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "request_conflict"
    assert (
        admin.put(
            f"{path}/{category['id']}",
            json=category_edit(
                changed.json(),
                code="changed-code",
            ),
        ).status_code
        == 422
    )
    assert admin.delete(f"{path}/{category['id']}").status_code == 405
    assert admin.put(f"{path}/2147483647", json=category_edit(category)).status_code == 404


def test_catalog_request_uuid_is_serialized_across_different_elections(
    admin: TestClient,
    database_url: str,
) -> None:
    elections = [create_election(admin), create_election(admin)]
    body = {
        "request_id": str(uuid4()),
        "code": "PROJECT-A",
        "label_en": "Custom",
        "label_tc": "自訂",
        "label_sc": "自定义",
    }
    barrier = Barrier(2)
    authorization = admin.headers["Authorization"]

    def create(election: dict) -> tuple[int, dict]:
        with TestClient(create_app(database_url), base_url="https://testserver") as client:
            client.headers["Authorization"] = authorization
            barrier.wait(timeout=10)
            response = client.post(
                f"/api/elections/{election['id']}/complaint-categories",
                json=body,
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, elections))
    assert sorted(status for status, _ in results) == [201, 409]
    assert (
        next(body for status, body in results if status == 409)["detail"]["code"]
        == "request_conflict"
    )
    sizes = [
        len(admin.get(f"/api/elections/{election['id']}/complaint-categories").json()["items"])
        for election in elections
    ]
    assert sorted(sizes) == [5, 6]


def test_concurrent_case_replay_and_stale_edits_have_one_effect(
    admin: TestClient,
    database_url: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    clock = ComplaintClock()
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        client,
        _,
    ):
        category = station_categories(client, station["id"])[0]
        command = complaint_payload(category)
        barrier = Barrier(2)
        authorization = client.headers["Authorization"]

        def post(_: int) -> tuple[int, dict]:
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                barrier.wait(timeout=10)
                response = peer.post(path, json=command)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(post, (1, 2)))
        assert sorted(status for status, _ in results) == [200, 201]
        assert results[0][1] == results[1][1]
        row = results[0][1]
        barrier = Barrier(2)

        def edit(reference: str) -> tuple[int, dict]:
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                barrier.wait(timeout=10)
                response = peer.put(
                    f"{path}/{row['id']}",
                    json=complaint_payload(
                        category,
                        expected_revision=1,
                        case_reference=reference,
                    ),
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            edits = list(pool.map(edit, ("concurrent-A", "concurrent-B")))
        assert sorted(status for status, _ in edits) == [200, 409]
        history = client.get(f"{path}/{row['id']}/history").json()["items"]
        assert len(history) == 2 and history[0] == row
        assert history[1] == next(result for status, result in edits if status == 200)
        assert len(client.get(path).json()["items"]) == 1
        reused = client.post(path, json={**command, "description": "changed payload"})
        assert reused.status_code == 409 and reused.json()["detail"]["code"] == "request_conflict"


def test_custom_explanation_rule_and_maximum_raw_description_are_preserved(
    admin: TestClient,
    database_url: str,
) -> None:
    setup = complaint_stations(admin)
    # An active election does not prohibit catalog setup for a different draft election.
    draft = create_election(admin)
    body = {
        "request_id": str(uuid4()),
        "code": "PROJECT-EXPLANATION",
        "label_en": "Project explanation",
        "label_tc": "項目說明",
        "label_sc": "项目说明",
        "description_required": True,
    }
    other_catalog = f"/api/elections/{draft['id']}/complaint-categories"
    assert admin.post(other_catalog, json=body).status_code == 201
    catalog = f"/api/elections/{setup['election']['id']}/complaint-categories"
    custom = admin.post(catalog, json={**body, "request_id": str(uuid4())})
    assert custom.status_code == 201
    category = custom.json()
    station = setup["N1"]
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(
        admin, database_url, ComplaintClock(), "polling_officer", [station["id"]]
    ) as (client, _):
        empty = client.post(path, json=complaint_payload(category, description="\t  "))
        assert empty.status_code == 422
        assert empty.json()["detail"]["code"] == "complaint_description_required"
        maximum = client.post(
            path,
            json=complaint_payload(
                category,
                description="投" * 4000,
                case_reference="0" * 64,
            ),
        )
        assert maximum.status_code == 201
        row = maximum.json()
        assert row["description"] == "投" * 4000 and row["case_reference"] == "0" * 64
        assert (
            not row["category_verified_source"] and row["category_source"] == "project_configured"
        )


def test_case_snapshots_and_new_cases_overlap_without_failed_reads_or_lost_writes(
    admin: TestClient,
    database_url: str,
) -> None:
    station = complaint_stations(admin)["N1"]
    clock = ComplaintClock()
    path = f"/api/workspace/stations/{station['id']}/complaints"
    with complaint_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        client,
        _,
    ):
        category = station_categories(client, station["id"])[0]
        authorization = client.headers["Authorization"]
        barrier = Barrier(2)

        def write_cases() -> list[int]:
            statuses = []
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                for number in range(20):
                    barrier.wait(timeout=10)
                    statuses.append(
                        peer.post(
                            path,
                            json=complaint_payload(
                                category,
                                case_reference=f"overlap-{number:04}",
                            ),
                        ).status_code
                    )
            return statuses

        def read_cases() -> list[int]:
            counts = []
            with TestClient(
                create_app(database_url, now=clock), base_url="https://testserver"
            ) as peer:
                peer.headers["Authorization"] = authorization
                for _ in range(20):
                    barrier.wait(timeout=10)
                    response = peer.get(path)
                    assert response.status_code == 200
                    counts.append(len(response.json()["items"]))
            return counts

        with ThreadPoolExecutor(max_workers=2) as pool:
            writes = pool.submit(write_cases)
            reads = pool.submit(read_cases)
            assert writes.result(timeout=30) == [201] * 20
            counts = reads.result(timeout=30)
        assert counts == sorted(counts) and counts[-1] in (19, 20)
        assert [row["case_reference"] for row in client.get(path).json()["items"]] == [
            f"overlap-{number:04}" for number in range(20)
        ]


def test_draft_case_snapshot_and_activation_overlap_without_lock_failure(
    admin: TestClient,
    database_url: str,
) -> None:
    for _ in range(6):
        with lifecycle_test_state(database_url):
            setup = complaint_stations(admin, activate=False)
            station = setup["N1"]
            clock = ComplaintClock()
            path = f"/api/workspace/stations/{station['id']}/complaints"
            with complaint_staff(
                admin, database_url, clock, "polling_officer", [station["id"]]
            ) as (client, _):
                barrier = Barrier(2)
                reader_token = client.headers["Authorization"]
                admin_token = admin.headers["Authorization"]

                def read() -> int:
                    with TestClient(
                        create_app(database_url, now=clock),
                        base_url="https://testserver",
                        raise_server_exceptions=False,
                    ) as peer:
                        peer.headers["Authorization"] = reader_token
                        barrier.wait(timeout=10)
                        return peer.get(path).status_code

                def activate() -> int:
                    with TestClient(
                        create_app(database_url),
                        base_url="https://testserver",
                        raise_server_exceptions=False,
                    ) as peer:
                        peer.headers["Authorization"] = admin_token
                        barrier.wait(timeout=10)
                        return peer.post(
                            f"/api/elections/{setup['election']['id']}/activate",
                            json={"election_revision": 1, "schedule_revision": 1},
                        ).status_code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    snapshot = pool.submit(read)
                    activation = pool.submit(activate)
                    assert (snapshot.result(timeout=30), activation.result(timeout=30)) == (
                        200,
                        200,
                    )
                assert client.get(path).json()["context"]["election"]["status"] == "active"
