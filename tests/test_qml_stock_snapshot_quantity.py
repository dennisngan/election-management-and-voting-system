"""Material stock totals stay exact beyond one machine-sized integer."""

from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshot_quantity_api import allocate_large_series
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_material_snapshot_keeps_exact_aggregate_above_unsigned_integer_size(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    scope, clock = turnout_scope(admin, activate=False), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        options = officer.get(base + "/allocations")
        assert options.status_code == 200 and options.json()["items"] == []
        counter_id = options.json()["counters"][0]["id"]
        allocate_large_series(officer, base, [(counter_id, 20)])
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "counter_id": counter_id,
                "locale": "en",
            },
            """
            click('stockSnapshotsNavigation')
            editor = controller.property('stockSnapshots')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            enter('snapshotEventTime', '2026-11-15 09:30:17.123456')
            click('snapshotReported' + str(setup['counter_id']))
            assert control('snapshotExplicitZero' + str(setup['counter_id'])).property('visible')
            frame()
            click('snapshotSave')
            wait(idle)
            saved = editor.property('state')
            assert saved['error'] == ''
            assert saved['notice'] == 'stock_snapshot_saved', (
                saved['notice'], saved['selected'],
                control('snapshotCurrentIssued').property('text'))
            expected = '19999999999999999980'
            assert control('snapshotCurrentIssued').property('text') == expected
            assert control('snapshotRemainingTotal').property('text') == '0'
            totals = editor.property('state')['totals']
            for key in ('ordinary_allocated_display', 'ordinary_net_allocated_display',
                        'ordinary_issued_display'):
                assert totals[key] == expected, (key, totals[key])
            selected = editor.property('state')['selected']
            assert selected['ordinary_allocated_quantity'] == expected
            assert type(selected['ordinary_remaining_quantity']) is int
            assert selected['ordinary_remaining_quantity'] == 0
            assert type(selected['revision']) is int and selected['revision'] == 1
            assert selected['complete'] is True
            assert selected['counters'][0]['reported'] is True
            assert selected['counters'][0]['issued_ranges'][0]['serial_from'] == '1'
            # Inspect actual rendered labels, including the three anonymous
            # saved-total Details, rather than treating Python strings as UI proof.
            pending = list(window.contentItem().childItems())
            labels = []
            while pending:
                item = pending.pop()
                if item.property('text') == expected and item.property('visible'):
                    labels.append(item)
                pending.extend(item.childItems())
            assert len(labels) == 4, 'Current, gross, net and issued totals must all render exactly'
            frame()
            for label in labels:
                assert label.property('contentWidth') <= label.width() + 1
                assert label.property('contentHeight') <= label.height() + 1
            click('snapshotReload')
            wait(idle)
            click('snapshotHistoryRevision1')
            wait(idle)
            assert control('snapshotCurrentIssued').property('text') == expected
            click('snapshotPreview')
            wait(idle)
            assert editor.property('state')['error'] == ''
            preview = control('snapshotReportPreview').property('text')
            assert 'Gross ordinary allocations · ' + expected in preview
            assert 'Net ordinary allocations · ' + expected in preview
            assert 'Stock-derived ordinary issuance · ' + expected in preview
            assert '19999999999999999980' in preview and '1.999999' not in preview
            assert editor.property('state')['report']['availability'] is None
            click('allocationNavigation')
            allocations = controller.property('allocations')
            wait(lambda: not any(allocations.property('state')[key]
                                for key in ('busy', 'refreshing')))
            balances = allocations.property('state')['availability']
            assert len(balances) == 20
            for row in balances:
                assert type(row['ordinary_received_quantity']) is int
                assert row['ordinary_received_quantity'] == 999999999999999999
                assert type(row['allocated_quantity']) is int
                assert row['allocated_quantity'] == 999999999999999999
                assert row['ordinary_received_display'] == '999999999999999999'
                assert row['allocated_display'] == '999999999999999999'
                assert row['available_display'] == '0'
            expected_labels = {
                controller.texts['allocation_received'] + ' · 999999999999999999': 0,
                controller.texts['allocation_allocated'] + ' · 999999999999999999': 0,
            }
            pending = list(window.contentItem().childItems())
            while pending:
                item = pending.pop()
                text = item.property('text')
                if isinstance(text, str) and text in expected_labels and item.property('visible'):
                    expected_labels[text] += 1
                pending.extend(item.childItems())
            assert all(count == 20 for count in expected_labels.values()), expected_labels
            """,
        )
        collection = officer.get(base + "/stock-snapshots")
        assert collection.status_code == 200
        saved = collection.json()["latest"]
        assert saved["revision"] == 1 and saved["complete"] is True
        for row in (saved, saved["counters"][0]):
            for key in ("ordinary_allocated_quantity", "ordinary_net_allocated_quantity",
                        "ordinary_issued_quantity"):
                assert type(row[key]) is int and row[key] == 19999999999999999980
            assert type(row["ordinary_remaining_quantity"]) is int
            assert row["ordinary_remaining_quantity"] == 0
        assert len(saved["allocation_basis"]) == 20
        assert saved["counters"][0]["ranges"] == []
        history = officer.get(base + f"/stock-snapshots/{saved['id']}/history")
        assert history.status_code == 200 and history.json()["items"] == [saved]
        allocations = officer.get(base + "/allocations")
        assert allocations.status_code == 200
        assert len(allocations.json()["availability"]) == 20
        assert all(
            type(row["ordinary_received_quantity"]) is int
            and row["ordinary_received_quantity"] == 999999999999999999
            and type(row["allocated_quantity"]) is int
            and row["allocated_quantity"] == 999999999999999999
            for row in allocations.json()["availability"]
        )
