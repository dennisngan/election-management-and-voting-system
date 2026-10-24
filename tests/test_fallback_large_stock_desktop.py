"""Large physical stock bases retain a small exact turnout delta through Qt/TLS."""

from uuid import uuid4

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.fallback_support import confirm_fallback_activation, fallback_setup
from tests.stock_support import stock_payload
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.test_turnout_desktop import turnout_editor
from tests.turnout_support import READY_PASSWORD


def test_qt_approves_small_turnout_delta_from_physical_sources_above_unsigned64(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        officer, base = setup["officer"], setup["base"]
        for index in range(20):
            series = f"Large physical source {index + 1}"
            received = officer.post(base + "/stock", json=stock_payload(
                series=series, event_at="2026-11-15T10:00:00+08:00",
                ordinary_quantity=999999999999999999,
                replacement_quantity=0, tendered_quantity=0,
                ranges=[{
                    "pool": "ordinary", "serial_from": "000000000000000001",
                    "serial_to": "999999999999999999",
                }],
            ))
            assert received.status_code == 201, received.json()
            assert received.json()["ordinary_quantity"] == 999999999999999999
            allocated = officer.post(base + "/allocations", json={
                "request_id": str(uuid4()), "counter_id": setup["counter_id"],
                "series": series, "serial_from": "000000000000000001",
                "serial_to": "999999999999999999",
                "event_at": "2026-11-15T10:00:00+08:00",
            })
            assert allocated.status_code == 201, allocated.json()

        # These fresh observations supersede the original, now stale P(12) basis.
        sources = []
        for event_at, first_remaining, issued, remaining in (
            ("2026-11-15T11:20:00+08:00", "000111", 20000000000000000090, 90),
            ("2026-11-15T12:00:00+08:00", "000116", 20000000000000000095, 85),
        ):
            observed = officer.post(base + "/stock-snapshots", json={
                "request_id": str(uuid4()), "event_at": event_at,
                "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                    "series": "普通系列 A", "serial_from": first_remaining,
                    "serial_to": "000200",
                }]}],
            })
            assert observed.status_code == 201, observed.json()
            snapshot = observed.json()
            assert snapshot["complete"] is True
            assert type(snapshot["ordinary_issued_quantity"]) is int
            assert snapshot["ordinary_issued_quantity"] == issued
            assert snapshot["ordinary_remaining_quantity"] == remaining
            assert snapshot["counters"][0]["ordinary_issued_quantity"] == issued
            sources.append(snapshot)
        activation_snapshot, endpoint = sources
        assert activation_snapshot["id"] != setup["snapshot"]["id"]
        activation = confirm_fallback_activation({
            **setup, "snapshot": activation_snapshot,
            "command": {
                **setup["command"], "request_id": str(uuid4()),
                "stock_snapshot_id": activation_snapshot["id"],
                "stock_snapshot_revision": activation_snapshot["revision"],
            },
        })
        https_server.clock.value = setup["clock"].value
        station_id = endpoint["station_id"]
        with turnout_editor(https_server, qt_app, setup["account"], station_id) as (_, editor):
            assert editor.selectPeriod(2) is True
            wait_for_editor_idle(qt_app, editor)
            for name, value in {
                "mode": "fallback", "fallback_activation_id": str(activation["id"]),
                "fallback_activation_revision": "1",
                "stock_snapshot_id": str(endpoint["id"]), "stock_snapshot_revision": "1",
                "event_time": "2026-11-15 12:00",
                "source_context": (
                    "Confirmed 110 plus five ordinary issues above a large stock base."
                ),
            }.items():
                editor.setField(name, value)
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            saved = editor.property("state")
            assert saved["error"] == "" and saved["notice"] == "turnout_saved"
            display = saved["selected"]["source_basis_display"]
            assert display["activation_stock_snapshot"][
                "ordinary_issued_quantity_display"
            ] == "20000000000000000090"
            assert display["stock_snapshot"][
                "ordinary_issued_quantity_display"
            ] == "20000000000000000095"
            assert display["ordinary_issued_since_activation_quantity_display"] == "5"
            assert display["stock_derived_cumulative_quantity_display"] == "115"
            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            submitted = editor.property("state")
            assert submitted["error"] == ""
            assert submitted["selected"]["status"] == "submitted"
            with turnout_editor(
                https_server, qt_app, setup["supervisor_account"], station_id,
            ) as (_, reviewer):
                assert reviewer.selectPeriod(2) is True
                wait_for_editor_idle(qt_app, reviewer)
                reviewer.approve(READY_PASSWORD)
                wait_for_editor_idle(qt_app, reviewer)
                reviewed = reviewer.property("state")
                assert reviewed["error"] == "" and reviewed["notice"] == "turnout_approved"
                approved = reviewed["selected"]
                assert approved["status"] == "approved"
                assert approved["derived_cumulative_start_display"] == "100"
                assert approved["derived_hourly_display"] == "15"
                assert approved["derived_cumulative_end_display"] == "115"
                assert approved["source_basis_display"] == display

        current = officer.get(setup["scope"]["path"])
        assert current.status_code == 200
        approved = current.json()["items"][1]["record"]
        assert approved["status"] == "approved"
        assert approved["derived_cumulative_start"] == 100
        assert approved["derived_hourly"] == 15
        assert approved["derived_cumulative_end"] == 115
        basis = approved["source_basis"]
        assert type(basis["activation_stock_snapshot"]["ordinary_issued_quantity"]) is int
        assert type(basis["stock_snapshot"]["ordinary_issued_quantity"]) is int
        assert basis["activation_stock_snapshot"][
            "ordinary_issued_quantity"
        ] == 20000000000000000090
        assert basis["stock_snapshot"]["ordinary_issued_quantity"] == 20000000000000000095
        assert basis["ordinary_issued_since_activation_quantity"] == 5
        assert basis["stock_derived_cumulative_quantity"] == 115
        assert basis["activation_stock_snapshot"] == activation_snapshot
        assert basis["stock_snapshot"] == endpoint
        for original in sources:
            unchanged = officer.get(base + f"/stock-snapshots/{original['id']}")
            assert unchanged.status_code == 200
            assert unchanged.json() == original
            assert type(unchanged.json()["ordinary_issued_quantity"]) is int
