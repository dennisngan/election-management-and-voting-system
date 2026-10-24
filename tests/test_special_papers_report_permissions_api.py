"""Selected special-paper statements preserve role and station boundaries."""

import csv
from collections.abc import Iterator
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import turnout_staff

FORMATS = ("", ".csv")


@pytest.fixture
def special_report_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        corrected = officer.put(target, json={
            **setup["command"], "request_id": str(uuid4()), "revision": 1,
            "reason": "Report readers must preserve both saved observations.",
            "series": [{
                **setup["entered_series"], "replacement_issued_quantity": 3,
                "spoilt_original_quantity": 3, "retrieved_found_quantity": 0,
            }],
        })
        assert corrected.status_code == 200
        current = corrected.json()
        assert current["revision"] == 2
        snapshot_path = setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}"
        read_paths = (
            target, target + "/history", snapshot_path, snapshot_path + "/history",
            setup["base"] + "/turnout",
        )

        def read_original_records() -> dict:
            records = {}
            for read_path in read_paths:
                response = officer.get(read_path)
                assert response.status_code == 200, read_path
                records[read_path] = response.json()
            return records

        before = read_original_records()
        assert before[target] == current
        assert before[target + "/history"] == {"items": [first, current]}
        assert before[snapshot_path] == setup["snapshot"]
        assert before[setup["base"] + "/turnout"] == setup["turnout"]

        def assert_unchanged() -> None:
            assert read_original_records() == before

        yield {
            **setup, "original": first, "current": current,
            "assert_unchanged": assert_unchanged,
        }


@pytest.mark.parametrize("role", ["counting_officer", "supervisor", "administrator"])
def test_reports_allow_only_assigned_operational_readers_and_preserve_selected_history(
    special_report_setup: dict, admin: TestClient, database_url: str, role: str,
) -> None:
    setup = special_report_setup
    first = setup["original"]
    station_ids = [] if role == "administrator" else [first["station_id"]]
    with turnout_staff(
        admin, database_url, setup["clock"], station_ids, role,
    ) as (reader, _):
        identities = (
            (first["id"], 9223372036854775807) if role == "administrator" else (first["id"],)
        )
        for identity in identities:
            params = {"snapshot_id": identity, "revision": 1, "locale": "en"}
            for extension in FORMATS:
                response = reader.get(setup["path"] + "/statement" + extension, params=params)
                if role == "administrator":
                    assert response.status_code == 403
                    assert response.json()["detail"]["code"] == "operational_role_required"
                else:
                    assert response.status_code == 200
                    if extension:
                        assert response.headers["content-type"].startswith("text/csv")
                        assert response.content.startswith(b"\xef\xbb\xbf")
                        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
                        assert ["Replacement papers issued", "2"] in rows
                        assert ["Retrieved-unused papers total", "3"] in rows
                        assert ["Never-issued stock total", "7"] in rows
                    else:
                        report = response.json()
                        assert report["items"] == [first]
                        assert report["revision_state"] == "historical"
                        assert report["report_scope"] == "snapshot_revision"
                        assert report["availability"] is None
                setup["assert_unchanged"]()


def test_report_station_isolation_and_authorized_query_validation_preserve_records(
    special_report_setup: dict, admin: TestClient, database_url: str,
) -> None:
    setup = special_report_setup
    first = setup["original"]
    options = admin.get("/api/accounts/station-options")
    assert options.status_code == 200
    other_id = next(
        row["station"]["id"] for row in options.json()["items"]
        if row["election"]["id"] == first["scope"]["election"]["id"]
        and row["station"]["id"] != first["station_id"]
    )
    own_path = f"/api/workspace/stations/{other_id}/special-papers/statement"
    valid = {"snapshot_id": first["id"], "revision": 1, "locale": "en"}
    with turnout_staff(
        admin, database_url, setup["clock"], [other_id],
    ) as (outsider, _):
        for extension in FORMATS:
            for identity in (first["id"], 9223372036854775807):
                denied = outsider.get(
                    setup["path"] + "/statement" + extension,
                    params={**valid, "snapshot_id": identity},
                )
                assert denied.status_code == 403
                assert denied.json()["detail"]["code"] == "station_access_denied"
                setup["assert_unchanged"]()
            missing = outsider.get(own_path + extension, params=valid)
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "special_paper_not_found"
            setup["assert_unchanged"]()
    for extension in FORMATS:
        for query in (
            {}, {"snapshot_id": first["id"]}, {"revision": 1}, {**valid, "locale": "fr"},
        ):
            invalid = setup["officer"].get(setup["path"] + "/statement" + extension, params=query)
            assert invalid.status_code == 422
            setup["assert_unchanged"]()
