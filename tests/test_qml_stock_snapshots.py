"""Actual Material snapshot controls preserve inclusive ranges and explicit reporting."""

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture
def snapshot_qml_setup(admin: TestClient, database_url: str, https_server: HttpsServer):
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        yield {
            "api": api,
            "base": base,
            "turnout_path": scope["path"],
            "qml": {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "counter_id": counter["id"],
            },
        }


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_saves_a_complete_snapshot_using_actual_material_controls(
    snapshot_qml_setup: dict, locale: str
) -> None:
    setup = snapshot_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
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
    saved = setup["api"].get(setup["base"] + "/stock-snapshots")
    assert saved.status_code == 200
    assert len(saved.json()["items"]) == 1
    assert saved.json()["latest"]["ordinary_issued_quantity"] == 3
    assert saved.json()["latest"]["ordinary_remaining_quantity"] == 3
    assert all(
        row["record"] is None for row in setup["api"].get(setup["turnout_path"]).json()["items"]
    )


def test_missing_counter_is_incomplete_but_an_explicit_zero_is_a_complete_new_observation(
    snapshot_qml_setup: dict,
) -> None:
    setup = snapshot_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": "en"},
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
    records = setup["api"].get(setup["base"] + "/stock-snapshots")
    assert records.status_code == 200
    rows = records.json()["items"]
    assert len(rows) == 2
    assert rows[0]["complete"] is False and rows[0]["ordinary_issued_quantity"] is None
    assert rows[1]["complete"] is True and rows[1]["ordinary_issued_quantity"] == 6
    assert rows[1]["counters"][0]["ranges"] == []


@pytest.fixture
def saved_snapshot_qml_setup(snapshot_qml_setup: dict) -> dict:
    from uuid import uuid4

    setup = snapshot_qml_setup
    created = setup["api"].post(
        setup["base"] + "/stock-snapshots",
        json={
            "request_id": str(uuid4()),
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [
                {
                    "counter_id": setup["qml"]["counter_id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000004", "serial_to": "000006"}
                    ],
                }
            ],
        },
    )
    assert created.status_code == 201
    original = created.json()
    return {**setup, "snapshot": original}


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_amends_and_reviews_precise_saved_snapshot_revisions_in_material(
    saved_snapshot_qml_setup: dict,
    locale: str,
) -> None:
    setup = saved_snapshot_qml_setup
    original = setup["snapshot"]
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('stockSnapshotsNavigation')
        editor = controller.property('stockSnapshots')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('snapshotPicker', 0)
        wait(idle)
        suffix = str(setup['counter_id'])
        assert control('snapshotSerialFrom' + suffix + '_0').property('readOnly') is True
        assert '09:30:17.123456 HKT' in control('snapshotEventContext').property('text')
        click('snapshotEdit')
        enter('snapshotSerialFrom' + suffix + '_0', '000005')
        enter('snapshotReason', '紙本核對第一行：第四號已發出。\\n第二行：保留原始版本。')
        assert_multiline_inside_border('snapshotReason')
        QTest.keyClick(window, Qt.Key.Key_Tab)
        wait(lambda: control('snapshotSave').property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Backtab)
        wait(lambda: control('snapshotReason').property('activeFocus'))
        assert_multiline_inside_border('snapshotReason')
        click('snapshotSave')
        wait(idle)
        assert editor.property('state')['error'] == ''
        assert editor.property('state')['selected']['revision'] == 2
        assert control('snapshotRemainingTotal').property('text') == '2'
        click('snapshotHistoryRevision1')
        wait(idle)
        assert editor.property('state')['historical'] is True
        assert control('snapshotSerialFrom' + suffix + '_0').property('text') == '000004'
        assert control('snapshotSerialFrom' + suffix + '_0').property('readOnly') is True
        assert control('snapshotSave').property('visible') is False
        assert control('snapshotEdit').property('visible') is False
        assert control('snapshotRemainingTotal').property('text') == '3'
        assert control('snapshotCurrentIssued').property('text') == '4'
        click('snapshotReload')
        wait(idle)
        assert editor.property('state')['selected']['revision'] == 2
        assert control('snapshotRemainingTotal').property('text') == '2'
        """,
    )
    history = setup["api"].get(setup["base"] + f"/stock-snapshots/{original['id']}/history")
    assert history.status_code == 200
    revisions = history.json()["items"]
    assert revisions[0] == original
    assert revisions[1]["event_at"] == original["event_at"]
    assert revisions[1]["reason"] == "紙本核對第一行：第四號已發出。\n第二行：保留原始版本。"
    assert revisions[1]["ordinary_issued_quantity"] == 4


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_historical_p12_preview_in_material_keeps_its_saved_revision(
    saved_snapshot_qml_setup: dict,
    locale: str,
) -> None:
    from uuid import uuid4

    setup = saved_snapshot_qml_setup
    original = setup["snapshot"]
    corrected = setup["api"].put(
        setup["base"] + f"/stock-snapshots/{original['id']}",
        json={
            "request_id": str(uuid4()),
            "revision": 1,
            "event_at": original["event_at"],
            "reason": "Paper balance correction",
            "counters": [
                {
                    "counter_id": setup["qml"]["counter_id"],
                    "ranges": [
                        {"series": "普通系列 A", "serial_from": "000005", "serial_to": "000006"}
                    ],
                }
            ],
        },
    )
    assert corrected.status_code == 200
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('stockSnapshotsNavigation')
        editor = controller.property('stockSnapshots')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('snapshotPicker', 0)
        wait(idle)
        click('snapshotHistoryRevision1')
        wait(idle)
        click('snapshotPreview')
        wait(idle)
        assert editor.property('state')['error'] == ''
        report = editor.property('state')['report']
        assert report['revision'] == 1 and report['revision_state'] == 'historical'
        assert report['locale'] == setup['locale']
        assert report['items'][0]['ordinary_issued_quantity'] == 3
        assert report['items'][0]['counters'][0]['ranges'][0]['serial_from'] == '000004'
        preview = control('snapshotReportPreview')
        before = preview.property('text')
        assert before.startswith(report['title']) and '000004' in before
        assert preview.property('readOnly') is True
        assert_multiline_inside_border('snapshotReportPreview')
        QTest.keyClick(window, Qt.Key.Key_9)
        assert preview.property('text') == before
        assert control('snapshotExportPdf').property('enabled') is True
        assert control('snapshotExportCsv').property('enabled') is True
        assert editor.property('state')['selected']['revision'] == 1
        assert control('snapshotCurrentIssued').property('text') == '4'
        """,
    )
