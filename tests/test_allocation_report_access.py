"""P(14) exports enforce assigned station access and explicit revision selection."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url
from tests.stock_support import ready_client, staff_account
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup

FORMATS = ("", ".csv", ".pdf")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture
def allocation_report_setup(allocation_setup: dict) -> dict:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    created = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    original = created.json()
    amended = setup["officer"].put(
        path + f"/{original['id']}",
        json=allocation_payload(
            setup["counter"]["id"],
            revision=1,
            serial_from="000002",
            serial_to="000005",
            reason="核對派票文件，更正櫃台派票範圍",
        ),
    )
    assert amended.status_code == 200
    return {**setup, "path": path, "original": original, "current": amended.json()}


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_assigned_readers_can_export_station_and_exact_historical_reports_in_all_formats(
    allocation_report_setup: dict, admin: TestClient, database_url: str, role: str
) -> None:
    setup = allocation_report_setup
    account = staff_account(admin, [setup["station"]["id"]], role)
    with ready_client(database_url, account) as reader:
        for params in (
            {"locale": "en"},
            {"locale": "en", "allocation_id": setup["original"]["id"], "revision": 1},
        ):
            for extension in FORMATS:
                response = reader.get(setup["path"] + "/statement" + extension, params=params)
                assert response.status_code == 200
                if extension == ".csv":
                    assert response.headers["content-type"].startswith("text/csv")
                    assert response.content.startswith(b"\xef\xbb\xbf")
                elif extension == ".pdf":
                    assert response.headers["content-type"] == "application/pdf"
                    assert response.content.startswith(b"%PDF-")
                else:
                    report = response.json()
                    assert report["scope"]["station"]["id"] == setup["station"]["id"]
                    if "revision" in params:
                        assert report["report_scope"] == "allocation_revision"
                        assert report["items"] == [setup["original"]]
                        assert report["revision_state"] == "historical"
                        assert report["availability"] is None
                    else:
                        assert report["report_scope"] == "station_current"
                        assert report["items"] == [setup["current"]]
                        assert report["availability"][0]["allocated_quantity"] == 4
    history = setup["officer"].get(setup["path"] + f"/{setup['original']['id']}/history")
    assert history.status_code == 200
    assert history.json()["items"] == [setup["original"], setup["current"]]


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_unassigned_station_reports_deny_access_before_resolving_record_ids(
    allocation_report_setup: dict, admin: TestClient, database_url: str, role: str
) -> None:
    setup = allocation_report_setup
    account = staff_account(admin, [setup["stations"][1]["id"]], role)
    with ready_client(database_url, account) as outsider:
        for extension in FORMATS:
            for params in (
                {},
                {"allocation_id": setup["original"]["id"], "revision": 1},
                {"allocation_id": 9223372036854775807, "revision": 1},
            ):
                denied = outsider.get(setup["path"] + "/statement" + extension, params=params)
                assert denied.status_code == 403
                assert denied.json() == {"detail": {"code": "station_access_denied"}}


def test_administrator_cannot_read_operational_reports_even_for_missing_record_ids(
    allocation_report_setup: dict, admin: TestClient
) -> None:
    setup = allocation_report_setup
    for extension in FORMATS:
        for params in (
            {},
            {"allocation_id": setup["original"]["id"], "revision": 1},
            {"allocation_id": 9223372036854775807, "revision": 1},
        ):
            denied = admin.get(setup["path"] + "/statement" + extension, params=params)
            assert denied.status_code == 403
            assert denied.json() == {"detail": {"code": "operational_role_required"}}


@pytest.mark.parametrize(
    ("query", "status", "code"),
    [
        pytest.param({"revision": 1}, 422, "allocation_required", id="revision-without-record"),
        pytest.param(
            {"allocation_id": "saved"},
            422,
            "allocation_revision_required",
            id="record-without-revision",
        ),
        pytest.param(
            {"allocation_id": "saved", "revision": 99},
            404,
            "allocation_not_found",
            id="missing-revision",
        ),
        pytest.param(
            {"allocation_id": 9223372036854775807, "revision": 1},
            404,
            "allocation_not_found",
            id="missing-record",
        ),
        pytest.param({"locale": "fr"}, 422, None, id="unsupported-locale"),
    ],
)
def test_report_formats_require_an_existing_explicit_revision_and_supported_locale(
    allocation_report_setup: dict, query: dict, status: int, code: str | None
) -> None:
    setup = allocation_report_setup
    params = dict(query)
    if params.get("allocation_id") == "saved":
        params["allocation_id"] = setup["original"]["id"]
    for extension in FORMATS:
        response = setup["officer"].get(setup["path"] + "/statement" + extension, params=params)
        assert response.status_code == status
        if code is not None:
            assert response.json() == {"detail": {"code": code}}


def test_report_selection_cannot_move_an_allocation_into_another_assigned_station(
    allocation_report_setup: dict, admin: TestClient, database_url: str
) -> None:
    setup = allocation_report_setup
    other_station = setup["stations"][1]
    account = staff_account(admin, [setup["station"]["id"], other_station["id"]], "supervisor")
    path = f"/api/workspace/stations/{other_station['id']}/allocations/statement"
    with ready_client(database_url, account) as reader:
        empty = reader.get(path)
        assert empty.status_code == 200
        report = empty.json()
        assert report["scope"]["station"]["id"] == other_station["id"]
        assert report["scope"]["constituency"]["id"] == other_station["constituency_id"]
        assert report["scope"]["election"]["id"] == other_station["election_id"]
        assert report["items"] == [] and report["availability"] == []
        for extension in FORMATS:
            wrong_station = reader.get(
                path + extension,
                params={"allocation_id": setup["original"]["id"], "revision": 1},
            )
            assert wrong_station.status_code == 404
            assert wrong_station.json() == {"detail": {"code": "allocation_not_found"}}
