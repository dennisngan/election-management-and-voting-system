"""Visible snapshot errors guide corrections without losing unsaved serial ranges."""

import pytest

from tests.qml_workspace_support import run_workspace_qml
from tests.test_qml_stock_snapshots import saved_snapshot_qml_setup as saved_snapshot_qml_setup
from tests.test_qml_stock_snapshots import snapshot_qml_setup as snapshot_qml_setup
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_visible_validation_future_time_and_ownership_errors_preserve_the_snapshot_form(
    snapshot_qml_setup: dict,
    locale: str,
) -> None:
    setup = snapshot_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('stockSnapshotsNavigation')
        editor = controller.property('stockSnapshots')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        def readable_error(code):
            assert editor.property('state')['error'] == code
            feedback = control('snapshotFeedback')
            assert feedback.property('visible') is True
            labels = [item for item in feedback.childItems()
                      if isinstance(item.property('text'), str)]
            assert len(labels) == 1
            text = labels[0].property('text')
            assert text and text != code, 'The visible error exposes an untranslated code: ' + code
        wait(idle)
        click('snapshotSave')
        readable_error('stock_snapshot_validation')
        suffix = str(setup['counter_id'])
        enter('snapshotEventTime', '2099-11-15 09:30')
        click('snapshotReported' + suffix)
        click('snapshotAddRange' + suffix)
        enter('snapshotSeries' + suffix + '_0', '普通系列 A')
        enter('snapshotSerialFrom' + suffix + '_0', '000004')
        enter('snapshotSerialTo' + suffix + '_0', '000006')
        click('snapshotSave')
        wait(idle)
        readable_error('event_time_in_future')
        assert editor.property('state')['dirty'] is True
        assert control('snapshotSerialFrom' + suffix + '_0').property('text') == '000004'
        enter('snapshotEventTime', '2026-11-15 09:30')
        enter('snapshotSerialTo' + suffix + '_0', '000009')
        click('snapshotSave')
        wait(idle)
        readable_error('remaining_outside_owned_stock')
        assert editor.property('state')['dirty'] is True
        assert control('snapshotSerialTo' + suffix + '_0').property('text') == '000009'
        enter('snapshotSerialTo' + suffix + '_0', '000006')
        click('snapshotSave')
        wait(idle)
        assert editor.property('state')['error'] == ''
        assert editor.property('state')['selected']['revision'] == 1
        assert editor.property('state')['selected']['ordinary_issued_quantity'] == 3
        """,
    )
    records = setup["api"].get(setup["base"] + "/stock-snapshots")
    assert records.status_code == 200
    assert len(records.json()["items"]) == 1


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_readers_review_snapshot_ranges_and_reports_without_visible_write_actions(
    saved_snapshot_qml_setup: dict,
    admin,
    database_url: str,
    role: str,
) -> None:
    from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_staff

    setup = saved_snapshot_qml_setup
    station_id = setup["qml"]["station_id"]
    with turnout_staff(admin, database_url, TurnoutClock(), [station_id], role) as (api, account):
        run_workspace_qml(
            {
                **setup["qml"],
                "username": account["username"],
                "password": READY_PASSWORD,
                "locale": "tc",
            },
            """
            click('stockSnapshotsNavigation')
            editor = controller.property('stockSnapshots')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            choose('snapshotPicker', 0)
            wait(idle)
            assert control('snapshotNew').property('visible') is False
            assert control('snapshotEdit').property('visible') is False
            assert control('snapshotSave').property('visible') is False
            suffix = str(setup['counter_id'])
            assert control('snapshotReported' + suffix).property('enabled') is False
            assert control('snapshotAddRange' + suffix).property('visible') is False
            field = focus('snapshotSerialFrom' + suffix + '_0')
            before = field.property('text')
            assert field.property('readOnly') is True
            QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(window, Qt.Key.Key_9)
            assert field.property('text') == before == '000004'
            click('snapshotPreview')
            wait(idle)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['report']['revision'] == 1
            assert control('snapshotReportPreview').property('readOnly') is True
            assert control('snapshotExportPdf').property('enabled') is True
            assert control('snapshotExportCsv').property('enabled') is True
            """,
        )
        saved = api.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert saved.status_code == 200 and saved.json() == setup["snapshot"]
