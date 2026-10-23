"""P(14) reports distinguish an exact saved revision from current station stock."""

from datetime import datetime

from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup


def test_selected_historical_report_does_not_mix_current_station_totals(
    allocation_setup: dict,
) -> None:
    setup = allocation_setup
    officer, path = setup["officer"], setup["base"] + "/allocations"
    original = officer.post(path, json=allocation_payload(setup["counter"]["id"]))
    assert original.status_code == 201
    changed = officer.put(
        path + f"/{original.json()['id']}",
        json=allocation_payload(
            setup["counter"]["id"],
            revision=1,
            serial_from="000002",
            serial_to="000005",
            reason="核對紙本派票範圍後更正",
        ),
    )
    assert changed.status_code == 200
    selected = officer.get(
        path + "/statement",
        params={"allocation_id": original.json()["id"], "revision": 1, "locale": "tc"},
    )
    assert selected.status_code == 200
    report = selected.json()
    assert report["title"] == "P(14) 發票櫃台選票派發紀錄"
    assert report["report_scope"] == "allocation_revision"
    assert report["allocation_id"] == original.json()["id"]
    assert report["revision"] == 1
    assert report["revision_state"] == "historical"
    assert report["items"] == [original.json()]
    assert report["availability"] is None
    assert report["scope"]["station"]["id"] == setup["station"]["id"]
    assert report["locale"] == "tc" and report["generation_timezone"] == "Asia/Hong_Kong"
    assert datetime.fromisoformat(report["generated_at"]).utcoffset() is not None
    current = officer.get(path + "/statement", params={"locale": "tc"})
    assert current.status_code == 200
    overview = current.json()
    assert overview["report_scope"] == "station_current"
    assert overview["allocation_id"] is None and overview["revision"] is None
    assert overview["revision_state"] == "current"
    assert overview["items"] == [changed.json()]
    assert overview["availability"][0]["allocated_quantity"] == 4
    assert overview["availability"][0]["available_quantity"] == 4
    assert [
        (row["serial_from"], row["serial_to"], row["quantity"])
        for row in overview["availability"][0]["ranges"]
    ] == [("000001", "000001", 1), ("000006", "000008", 3)]
