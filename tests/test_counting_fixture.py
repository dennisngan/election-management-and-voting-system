"""Real-MySQL smoke coverage for the Ticket 17 public setup fixture."""

import hashlib
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.counting_support import counting_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state


class _RedactedDatabaseUrl(str):
    def __repr__(self) -> str:
        return "<dedicated MySQL test URL redacted>"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    source = lifecycle_database_url()
    url = next(source)
    try:
        yield _RedactedDatabaseUrl(url)
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_counting_setup_has_received_boxes_and_current_approved_source_accounting(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        active = admin.get("/api/active-election")
        assert active.status_code == 200, active.text
        assert active.json()["election"]["id"] == setup["election"]["id"]

        boxes = setup["boxes"]
        assert boxes["local_n1"]["status"] == "received"
        assert boxes["local_n1"]["origin_station_id"] == setup["stations"]["N1"]["id"]
        assert boxes["transferred_n2"]["status"] == "received"
        assert boxes["transferred_n2"]["origin_station_id"] == setup["stations"]["N2"]["id"]
        assert boxes["transferred_n2"]["destination_station_id"] == setup["stations"]["N1"]["id"]
        assert boxes["unreceived_n2"]["status"] == "prepared"

        for code in ("N1", "N2"):
            source = setup["accounting"][code]
            assert source["record"]["status"] == "approved"
            assert source["record"]["source_current"] is True
            assert source["record"]["summary"]["estimated_box_from_stock_quantity"] == 5
            assert source["record"]["summary"]["observed_counted_quantity"] is None

            readback = setup["clients"]["bothcounting"].get(source["path"])
            assert readback.status_code == 200, readback.text
            assert readback.json()["record"] == source["record"]
            assert readback.json()["record"]["source_current"] is True
            source_fingerprint = hashlib.sha256(
                json.dumps(
                    source["record"]["summary"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            readback_fingerprint = hashlib.sha256(
                json.dumps(
                    readback.json()["record"]["summary"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            assert readback_fingerprint == source_fingerprint

        assert setup["paths"]["n1_counting_scopes"] == (
            f"/api/workspace/stations/{setup['stations']['N1']['id']}/counting-scopes"
        )

        receiver_profile = setup["clients"]["receiveronly"].get("/api/auth/me")
        assert receiver_profile.status_code == 200, receiver_profile.text
        assert receiver_profile.json()["role"] == "counting_officer"
        assert receiver_profile.json()["id"] == setup["accounts"]["receiveronly"]["id"]
