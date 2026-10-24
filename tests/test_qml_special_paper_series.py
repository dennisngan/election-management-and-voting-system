"""Material series selection stays aligned after an assigned-station change."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


def test_material_retains_distinct_series_counts_and_realigns_after_station_change(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    first_station, second_station = scope["stations"][:2]
    first_id, second_id = first_station["id"], second_station["id"]
    with turnout_staff(admin, database_url, clock, [first_id, second_id]) as (officer, account):
        snapshots = {}
        for station_id, series_names in (
            (first_id, ("多系列 A", "多系列 B")),
            (second_id, ("單一系列 C",)),
        ):
            base = f"/api/workspace/stations/{station_id}"
            options = officer.get(base + "/allocations")
            assert options.status_code == 200
            counter_id = options.json()["counters"][0]["id"]
            for series in series_names:
                received = officer.post(base + "/stock", json=stock_payload(
                    series=series, ordinary_quantity=10, replacement_quantity=3,
                    tendered_quantity=2, ranges=[
                        {"pool": "ordinary", "serial_from": "000001", "serial_to": "000010"},
                        {"pool": "replacement", "serial_from": "000011", "serial_to": "000013"},
                        {"pool": "tendered", "serial_from": "000014", "serial_to": "000015"},
                    ],
                ))
                assert received.status_code == 201
                allocated = officer.post(base + "/allocations", json={
                    "request_id": str(uuid4()), "counter_id": counter_id, "series": series,
                    "serial_from": "000001", "serial_to": "000010",
                    "event_at": "2026-11-15T09:00:00+08:00",
                })
                assert allocated.status_code == 201
            observed = officer.post(base + "/stock-snapshots", json={
                "request_id": str(uuid4()), "event_at": "2026-11-15T09:30:17.123456+08:00",
                "counters": [{"counter_id": counter_id, "ranges": [
                    {"series": series, "serial_from": "000006", "serial_to": "000010"}
                    for series in series_names
                ]}],
            })
            assert observed.status_code == 201
            snapshots[station_id] = observed.json()
            assert snapshots[station_id]["complete"] is True
        run_workspace_qml(
            {
                "server": https_server.url, "username": account["username"],
                "password": READY_PASSWORD, "station_id": first_id, "locale": "en",
                "other_station_id": second_id,
            },
            """
            click('specialPapersNavigation')
            editor = controller.property('specialPapers')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            keys = ('replacement_issued_quantity', 'spoilt_original_quantity',
                    'tendered_issued_quantity', 'retrieved_refused_quantity',
                    'retrieved_found_quantity', 'retrieved_held_quantity')
            wait(idle)
            enter('specialEventTime', '2026-11-15 09:45:17.123456')
            choose('specialBasisPicker', 1)
            click('specialZeroAll')
            frame()
            assert control('specialSeriesPicker').property('count') == 2
            choose('specialSeriesPicker', 1)
            frame()
            assert control('specialSeriesPicker').property('currentText') == '多系列 B'
            for key, value in zip(keys, ('2', '2', '1', '1', '1', '1'), strict=True):
                enter('specialCount_' + key, value)
            choose('specialSeriesPicker', 0)
            frame()
            assert control('specialSeriesPicker').property('currentText') == '多系列 A'
            assert all(control('specialCount_' + key).property('text') == '0' for key in keys)
            choose('specialSeriesPicker', 1)
            frame()
            for key, value in zip(keys, ('2', '2', '1', '1', '1', '1'), strict=True):
                assert control('specialCount_' + key).property('text') == value
            click('specialSave')
            wait(idle)
            saved = editor.property('state')
            assert saved['error'] == '' and saved['dirty'] is False
            by_series = {row['series']: row for row in saved['selected']['series']}
            assert all(by_series['多系列 A'][key] == 0 for key in keys)
            assert by_series['多系列 B']['replacement_issued_quantity'] == 2
            assert by_series['多系列 B']['retrieved_unused_quantity'] == 3
            assert saved['selected']['never_issued_quantity'] == 17
            assert saved['selected']['estimated_box_papers_quantity'] == 7
            assert control('specialSeriesPicker').property('currentIndex') == 1

            # Use the visible Account workspace selector; the station pages retain
            # their task state while hidden, as they do during normal navigation.
            click('accountNavigation')
            frame()
            workspace = controller.property('workspace')
            contexts = workspace.property('state')['contexts']
            other_index = next(index for index, row in enumerate(contexts)
                               if row['station']['id'] == setup['other_station_id'])
            choose('workspaceStationPicker', other_index)
            wait(lambda: not workspace.property('state')['busy'] and
                 workspace.property('state')['selected']['station']['id'] ==
                 setup['other_station_id'])
            click('specialPapersNavigation')
            wait(idle)
            enter('specialEventTime', '2026-11-15 09:45:17.123456')
            choose('specialBasisPicker', 1)
            click('specialZeroAll')
            frame()
            assert editor.property('state')['station_id'] == setup['other_station_id']
            assert len(editor.property('state')['series_reports']) == 1
            assert control('specialSeriesPicker').property('count') == 1
            assert control('specialSeriesPicker').property('currentIndex') == 0
            assert control('specialSeriesPicker').property('currentText') == '單一系列 C'
            # The selected station has one valid series. Its six fields must remain
            # aligned with the visible picker, rather than an obsolete second row.
            for key in keys:
                field = control('specialCount_' + key)
                assert field.property('visible') is True, key
                assert field.property('readOnly') is False, key
                assert field.property('text') == '0', key
            enter('specialCount_retrieved_found_quantity', '1')
            click('specialSave')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['selected']['series'][0]['series'] == '單一系列 C'
            assert editor.property('state')['selected']['retrieved_unused_quantity'] == 1
            assert editor.property('state')['selected']['never_issued_quantity'] == 10
            assert editor.property('state')['selected']['estimated_box_papers_quantity'] == 4
            """,
        )
        first = officer.get(f"/api/workspace/stations/{first_id}/special-papers")
        second = officer.get(f"/api/workspace/stations/{second_id}/special-papers")
        assert first.status_code == second.status_code == 200
        first_saved, second_saved = first.json()["latest"], second.json()["latest"]
        assert first_saved["never_issued_quantity"] == 17
        assert first_saved["estimated_box_papers_quantity"] == 7
        assert second_saved["series"][0]["series"] == "單一系列 C"
        assert second_saved["retrieved_unused_quantity"] == 1
        assert second_saved["never_issued_quantity"] == 10
        assert second_saved["estimated_box_papers_quantity"] == 4
        for station_id, snapshot in snapshots.items():
            retained = officer.get(
                f"/api/workspace/stations/{station_id}/stock-snapshots/{snapshot['id']}"
            )
            assert retained.status_code == 200 and retained.json() == snapshot
