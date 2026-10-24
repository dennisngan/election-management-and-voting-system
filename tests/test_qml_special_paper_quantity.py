"""Actual Material input accepts a legal count produced by an inclusive serial range."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_material_accepts_a_legal_nineteen_digit_tendered_quantity(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    path = base + "/special-papers"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        receipt = officer.post(base + "/stock", json=stock_payload(
            series="Inclusive tendered boundary",
            ordinary_quantity=0, replacement_quantity=0,
            tendered_quantity=1000000000000000000,
            ranges=[{
                "pool": "tendered", "serial_from": "000000000000000000",
                "serial_to": "999999999999999999",
            }],
        ))
        assert receipt.status_code == 201
        assert receipt.json()["total_quantity"] == 1000000000000000000
        assert receipt.json()["ranges"][0]["quantity"] == 1000000000000000000
        options = officer.get(base + "/allocations")
        assert options.status_code == 200 and options.json()["items"] == []
        counter_id = options.json()["counters"][0]["id"]
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{"counter_id": counter_id, "ranges": []}],
        })
        assert observed.status_code == 201
        ordinary = observed.json()
        assert ordinary["complete"] is True
        assert ordinary["ordinary_issued_quantity"] == 0
        turnout_before = officer.get(scope["path"])
        assert turnout_before.status_code == 200
        command = {
            "request_id": str(uuid4()), "event_at": "2026-11-15T09:45:17.123456+08:00",
            "stock_snapshot_id": ordinary["id"], "stock_snapshot_revision": 1,
            "series": [{
                "series": "Inclusive tendered boundary",
                "replacement_issued_quantity": 0, "spoilt_original_quantity": 0,
                "tendered_issued_quantity": 1000000000000000000,
                "retrieved_refused_quantity": 0, "retrieved_found_quantity": 0,
                "retrieved_held_quantity": 0,
            }],
        }
        created = officer.post(path, json=command)
        assert created.status_code == 201
        earlier = created.json()
        expected = {
            "received_quantity": 1000000000000000000,
            "ordinary_issued_quantity": 0,
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 1000000000000000000,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
            "retrieved_unused_quantity": 0,
            "ordinary_unissued_quantity": 0,
            "replacement_unissued_quantity": 0,
            "tendered_unissued_quantity": 0,
            "never_issued_quantity": 0,
            "estimated_box_papers_quantity": 0,
        }
        assert len(earlier["series"]) == 1
        for row in (earlier, earlier["series"][0]):
            for key, value in expected.items():
                assert type(row[key]) is int and row[key] == value, (key, row[key])
        reopened = officer.get(path + f"/{earlier['id']}")
        assert reopened.status_code == 200 and reopened.json() == earlier
        run_workspace_qml(
            {"server": https_server.url, "username": account["username"],
             "password": READY_PASSWORD, "station_id": station_id, "locale": "en",
             "basis_id": ordinary["id"]},
            """
            click('specialPapersNavigation')
            editor = controller.property('specialPapers')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            frame()
            click('specialNew')
            wait(idle)
            frame()
            enter('specialEventTime', '2026-11-15 10:00:17.123456')
            choose('specialBasisPicker', 1)
            assert editor.property('state')['basis']['id'] == setup['basis_id']
            click('specialZeroAll')
            frame()
            assert control('specialCount_tendered_issued_quantity').property('text') == '0'
            # First new boundary: actual text entry must retain the full legal 19-digit count.
            # The shared enter helper asserts equality; do not accept a truncated value.
            enter('specialCount_tendered_issued_quantity', '1000000000000000000')
            click('specialSave')
            wait(idle)
            saved = editor.property('state')
            assert saved['error'] == '' and saved['dirty'] is False
            assert saved['selected']['event_at'] == '2026-11-15T02:00:17.123456Z'
            assert saved['selected']['tendered_issued_quantity'] == 1000000000000000000
            assert saved['selected']['ordinary_issued_quantity'] == 0
            assert control('specialTotal_tendered_issued_quantity').property('text') == (
                '1000000000000000000')
            assert control('specialNeverIssuedTotal').property('text') == '0'
            """,
        )
        # These unchanged-state/save assertions are intentionally unreached in the input RED.
        collection = officer.get(path)
        assert collection.status_code == 200
        latest = collection.json()["latest"]
        assert latest["id"] != earlier["id"]
        assert latest["event_at"] == "2026-11-15T02:00:17.123456Z"
        for row in (latest, latest["series"][0]):
            for key, value in expected.items():
                assert type(row[key]) is int and row[key] == value
        assert collection.json()["items"] == [earlier, latest]
        assert officer.get(path + f"/{earlier['id']}").json() == earlier
        unchanged = officer.get(base + f"/stock-snapshots/{ordinary['id']}")
        assert unchanged.status_code == 200 and unchanged.json() == ordinary
        turnout_after = officer.get(scope["path"])
        assert turnout_after.status_code == 200
        assert turnout_after.json() == turnout_before.json()
