"""Parent stock revisions retain the special papers already physically accounted for."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.lifecycle_support import lifecycle_database_url
from tests.special_paper_support import special_paper_setup
from tests.stock_support import stock_payload
from tests.test_special_papers_api import private_active_election as private_active_election


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_receipt_correction_cannot_remove_replacement_stock_already_issued(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, base, path = setup["officer"], setup["base"], setup["path"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        special = created.json()
        receipt = setup["receipt"]
        receipt_path = base + f"/stock/{receipt['id']}"
        snapshot_path = base + f"/stock-snapshots/{setup['snapshot']['id']}"
        special_path = path + f"/{special['id']}"
        observed_paths = (
            receipt_path, receipt_path + "/history",
            special_path, special_path + "/history",
            base + "/stock-snapshots", snapshot_path, snapshot_path + "/history",
            base + "/turnout", base + "/turnout/1/history",
        )

        def public_readbacks() -> dict:
            result = {}
            for target in observed_paths:
                response = officer.get(target)
                assert response.status_code == 200, target
                result[target] = response.json()
            return result

        before = public_readbacks()
        corrected = officer.put(receipt_path, json=stock_payload(
            revision=receipt["revision"],
            reason="The proposed receipt correction removes stock already issued as replacements.",
            ordinary_quantity=10,
            replacement_quantity=1,
            tendered_quantity=2,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000010"},
                {"pool": "replacement", "serial_from": "000011", "serial_to": "000011"},
                {"pool": "tendered", "serial_from": "000014", "serial_to": "000015"},
            ],
        ))
        # This is the first new guard assertion. A 200 RED leaves every later
        # conflict-code and unchanged-state/history assertion unreached.
        assert corrected.status_code == 409
        assert corrected.json()["detail"]["code"] == "special_paper_stock_conflict"
        assert public_readbacks() == before
