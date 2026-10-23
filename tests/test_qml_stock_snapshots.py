"""Actual Material snapshot controls preserve inclusive ranges and explicit reporting."""

from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_officer_saves_a_complete_snapshot_using_actual_material_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "counter_id": counter["id"],
                "locale": "tc",
            },
            """
            click('stockSnapshotsNavigation')
            editor = controller.property('stockSnapshots')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            frame()
            assert control('snapshotState').property('text') == controller.texts['snapshot_missing']
            assert control('snapshotCurrentIssued').property('text') == '—'
            enter('snapshotEventTime', '2026-11-15 09:30')
            suffix = str(setup['counter_id'])
            assert control('snapshotReported' + suffix).property('checked') is False
            click('snapshotReported' + suffix)
            click('snapshotAddRange' + suffix)
            enter('snapshotSeries' + suffix + '_0', '普通系列 A')
            enter('snapshotSerialFrom' + suffix + '_0', '000004')
            enter('snapshotSerialTo' + suffix + '_0', '000006')
            assert control('snapshotQuantity' + suffix + '_0').property('text') == '3'
            assert control('snapshotQuantity' + suffix + '_0').property('readOnly') is True
            click('snapshotSave')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['selected']['revision'] == 1
            assert control('snapshotCurrentIssued').property('text') == '3'
            assert control('snapshotRemainingTotal').property('text') == '3'
            assert control('snapshotSerialFrom' + suffix + '_0').property('text') == '000004'
            assert control('snapshotSerialFrom' + suffix + '_0').property('readOnly') is True
            assert control('snapshotSave').property('visible') is False
            """,
        )
        saved = api.get(base + "/stock-snapshots")
        assert saved.status_code == 200
        assert len(saved.json()["items"]) == 1
        assert saved.json()["latest"]["ordinary_issued_quantity"] == 3
        assert saved.json()["latest"]["ordinary_remaining_quantity"] == 3
        assert all(row["record"] is None for row in api.get(scope["path"]).json()["items"])


def test_missing_counter_is_incomplete_but_an_explicit_zero_is_a_complete_new_observation(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "counter_id": counter["id"],
                "locale": "en",
            },
            """
            click('stockSnapshotsNavigation')
            editor = controller.property('stockSnapshots')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            enter('snapshotEventTime', '2026-11-15 09:30')
            click('snapshotSave')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['selected']['complete'] is False
            assert control('snapshotState').property('text') == (
                controller.texts['snapshot_incomplete'])
            assert control('snapshotCurrentIssued').property('text') == '—'
            assert control('snapshotRemainingTotal').property('text') == '—'
            click('snapshotNew')
            wait(idle)
            enter('snapshotEventTime', '2026-11-15 09:45')
            suffix = str(setup['counter_id'])
            click('snapshotReported' + suffix)
            assert control('snapshotExplicitZero' + suffix).property('visible') is True
            click('snapshotSave')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['selected']['complete'] is True
            assert control('snapshotState').property('text') == (
                controller.texts['snapshot_complete'])
            assert control('snapshotCurrentIssued').property('text') == '6'
            assert control('snapshotRemainingTotal').property('text') == '0'
            """,
        )
        records = api.get(base + '/stock-snapshots')
        assert records.status_code == 200
        rows = records.json()['items']
        assert len(rows) == 2
        assert rows[0]['complete'] is False and rows[0]['ordinary_issued_quantity'] is None
        assert rows[1]['complete'] is True and rows[1]['ordinary_issued_quantity'] == 6
        assert rows[1]['counters'][0]['ranges'] == []
