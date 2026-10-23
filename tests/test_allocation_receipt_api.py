"""Receipt revisions retain physical counter ownership without freezing unrelated stock."""

from tests.stock_support import stock_payload
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


def test_unallocated_stock_can_change_while_original_allocation_basis_stays_frozen(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    created = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    target = setup["base"] + f"/stock/{setup['receipt']['id']}"
    changed = officer.put(
        target,
        json=stock_payload(
            revision=1,
            reason="實收未派發選票少一張",
            ordinary_quantity=7,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000007"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    view = officer.get(path).json()
    assert view["items"] == [created.json()]
    assert created.json()["receipt_basis"] == [
        {"receipt_id": setup["receipt"]["id"], "revision": 1, "range_line": 0}
    ]
    assert view["availability"][0]["ordinary_received_quantity"] == 7
    assert view["availability"][0]["allocated_quantity"] == 3
    assert view["availability"][0]["available_quantity"] == 4
    assert view["availability"][0]["ranges"] == [
        {
            "serial_from": "000004",
            "serial_to": "000007",
            "quantity": 4,
            "receipt_id": setup["receipt"]["id"],
            "receipt_revision": 2,
        }
    ]
    renamed = officer.put(
        target,
        json=stock_payload(
            revision=2,
            reason="更改系列",
            series="另一系列",
            ordinary_quantity=7,
            ranges=[
                {"pool": "ordinary", "serial_from": "000001", "serial_to": "000007"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert renamed.status_code == 409
    assert renamed.json()["detail"]["code"] == "stock_allocations_conflict"
    reclassified = officer.put(
        target,
        json=stock_payload(
            revision=2,
            reason="更改儲備分類",
            ordinary_quantity=4,
            replacement_quantity=4,
            ranges=[
                {"pool": "ordinary", "serial_from": "000004", "serial_to": "000007"},
                {"pool": "replacement", "serial_from": "000001", "serial_to": "000003"},
                {"pool": "replacement", "serial_from": "000009", "serial_to": "000009"},
                {"pool": "tendered", "serial_from": "000010", "serial_to": "000010"},
            ],
        ),
    )
    assert reclassified.status_code == 409
    assert reclassified.json()["detail"]["code"] == "stock_allocations_conflict"
    assert officer.get(target).json() == changed.json()
    assert officer.get(target + "/history").json()["items"] == [setup["receipt"], changed.json()]
    assert officer.get(path).json() == view
