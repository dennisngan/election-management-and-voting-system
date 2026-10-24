"""Special-paper accounting preserves physical pools and supplied ordinary turnout."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.special_paper_support import special_paper_setup


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_officer_accounts_for_special_papers_without_reissuing_stock_or_adding_turnout(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, account, clock = setup["officer"], setup["account"], setup["clock"]
        base, path = setup["base"], setup["path"]
        original_snapshot, received = setup["snapshot"], setup["receipt"]
        station_id = original_snapshot["station_id"]
        turnout_dto, entered_series = setup["turnout"], setup["entered_series"]
        created = officer.post(path, json=setup["command"])
        # First new-feature assertion: a missing route is the intended RED.
        # All saved-accounting/readback assertions below remain unreached in that RED.
        assert created.status_code == 201
        saved = created.json()
        assert type(saved["id"]) is int and saved["id"] > 0
        assert saved["revision"] == 1 and saved["station_id"] == station_id
        assert saved["actor_id"] == account["id"]
        assert saved["event_at"] == "2026-11-15T01:45:17.123456Z"
        assert saved["entered_at"] == "2026-11-15T04:00:00Z"
        assert saved["stock_snapshot_id"] == original_snapshot["id"]
        assert saved["stock_snapshot_revision"] == 1
        assert saved["receipt_basis"] == [{"receipt_id": received["id"], "revision": 1}]
        expected = {
            "received_quantity": 15,
            "ordinary_issued_quantity": 5,
            "replacement_issued_quantity": 2,
            "spoilt_original_quantity": 2,
            "tendered_issued_quantity": 1,
            "retrieved_unused_quantity": 3,
            "ordinary_unissued_quantity": 5,
            "replacement_unissued_quantity": 1,
            "tendered_unissued_quantity": 1,
            "never_issued_quantity": 7,
            "estimated_box_papers_quantity": 2,
        }
        for key, value in expected.items():
            assert type(saved[key]) is int and saved[key] == value
        assert len(saved["series"]) == 1
        row = saved["series"][0]
        for key, value in entered_series.items():
            assert row[key] == value
        for key, value in expected.items():
            assert type(row[key]) is int and row[key] == value
        with TestClient(create_app(database_url, now=clock)) as another:
            another.headers.update(officer.headers)
            reopened = another.get(path + f"/{saved['id']}")
            assert reopened.status_code == 200 and reopened.json() == saved
            snapshot = another.get(base + f"/stock-snapshots/{original_snapshot['id']}")
            assert snapshot.status_code == 200 and snapshot.json() == original_snapshot
            turnout_after = another.get(base + "/turnout")
            assert turnout_after.status_code == 200 and turnout_after.json() == turnout_dto
