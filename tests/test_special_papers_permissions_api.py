"""Special-paper records respect operational roles and assigned-station boundaries."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import turnout_staff


@pytest.mark.parametrize("role", ["counting_officer", "supervisor", "administrator"])
def test_other_roles_can_only_read_assigned_special_papers_if_operational(
    admin: TestClient, database_url: str, role: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        saved = created.json()
        target = path + f"/{saved['id']}"
        station_ids = [] if role == "administrator" else [saved["station_id"]]
        with turnout_staff(
            admin, database_url, setup["clock"], station_ids, role,
        ) as (actor, _):
            for read_path, expected in (
                (target, saved),
                (target + "/history", {"items": [saved]}),
            ):
                response = actor.get(read_path)
                if role == "administrator":
                    assert response.status_code == 403
                    assert response.json()["detail"]["code"] == "operational_role_required"
                else:
                    assert response.status_code == 200 and response.json() == expected
            for command in (
                setup["command"],
                {**setup["command"], "request_id": str(uuid4())},
            ):
                # Successful cached request IDs must not bypass current role checks.
                denied = actor.post(path, json=command)
                assert denied.status_code == 403
                assert denied.json()["detail"]["code"] == "operational_role_required"
            denied = actor.put(
                target,
                json={
                    **setup["command"], "request_id": str(uuid4()), "revision": 1,
                    "reason": "Permission check must not create a revised accounting record.",
                },
            )
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "operational_role_required"
        current = officer.get(target)
        assert current.status_code == 200 and current.json() == saved
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json() == {"items": [saved]}
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]


def test_another_station_cannot_read_or_write_foreign_records_or_snapshot_sources(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        saved = created.json()
        target = path + f"/{saved['id']}"
        options = admin.get("/api/accounts/station-options")
        assert options.status_code == 200
        other_station_id = next(
            row["station"]["id"] for row in options.json()["items"]
            if row["election"]["id"] == saved["scope"]["election"]["id"]
            and row["station"]["id"] != saved["station_id"]
        )
        own_path = f"/api/workspace/stations/{other_station_id}/special-papers"
        correction = {
            **setup["command"], "request_id": str(uuid4()), "revision": 1,
            "reason": "Cross-station permission check must not change the saved accounting.",
        }
        with turnout_staff(
            admin, database_url, setup["clock"], [other_station_id],
        ) as (actor, _):
            for read_path in (target, target + "/history"):
                denied = actor.get(read_path)
                assert denied.status_code == 403
                assert denied.json()["detail"]["code"] == "station_access_denied"
            for command in (
                setup["command"],
                {**setup["command"], "request_id": str(uuid4())},
            ):
                denied = actor.post(path, json=command)
                assert denied.status_code == 403
                assert denied.json()["detail"]["code"] == "station_access_denied"
            denied = actor.put(target, json=correction)
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "station_access_denied"

            # A valid assigned path still cannot reveal a foreign record ID.
            foreign_target = own_path + f"/{saved['id']}"
            for read_path in (foreign_target, foreign_target + "/history"):
                missing = actor.get(read_path)
                assert missing.status_code == 404
                assert missing.json()["detail"]["code"] == "special_paper_not_found"
            missing = actor.put(foreign_target, json=correction)
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "special_paper_not_found"
            missing_source = actor.post(
                own_path, json={**setup["command"], "request_id": str(uuid4())},
            )
            assert missing_source.status_code == 404
            assert missing_source.json()["detail"]["code"] == "stock_snapshot_not_found"
        current = officer.get(target)
        assert current.status_code == 200 and current.json() == saved
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json() == {"items": [saved]}
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
