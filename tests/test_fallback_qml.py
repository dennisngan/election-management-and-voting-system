"""Actual Material controls save, submit and confirm an EPR fallback activation."""

from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.fallback_support import fallback_setup
from tests.qml_workspace_support import run_workspace_qml
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD


def test_material_officer_submits_and_supervisor_confirms_the_frozen_fallback_activation(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["snapshot"]["station_id"]
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": station_id, "locale": "tc",
             "snapshot_id": setup["snapshot"]["id"], "counter_id": setup["counter_id"],
             "supervisor_username": setup["supervisor_account"]["username"],
             "supervisor_id": setup["supervisor_account"]["id"]},
            """
            # First new UI boundary: a missing public navigation control is RED.
            # Later entry, saved-source, review and API-readback assertions are unreached.
            from PySide6.QtCore import QObject
            click('fallbackNavigation')
            fallback = controller.property('fallback')
            def idle():
                return not any(fallback.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            frame()
            assert control('fallbackMode').property('text') == '正常外部數字模式'
            assert control('fallbackCumulative').property('text') == ''
            assert control('fallbackCumulative').property('readOnly') is False
            enter('fallbackEventTime', '2026-11-15 11:20')
            enter('fallbackCumulative', '110')
            enter('fallbackSnapshotId', str(setup['snapshot_id']))
            enter('fallbackSnapshotRevision', '1')
            enter('fallbackSource', '登記冊確認11:20累計110人，保留已儲存櫃台結餘。')
            click('fallbackReload')
            dialog = window.findChild(QObject, 'fallbackDiscardDialog')
            assert dialog is not None
            click_confirmation(dialog, '繼續編輯')
            assert control('fallbackCumulative').property('text') == '110'
            assert fallback.property('state')['dirty'] is True
            click('fallbackSave')
            wait(idle)
            saved = fallback.property('state')
            assert saved['error'] == '' and saved['dirty'] is False
            assert saved['selected']['status'] == 'draft'
            assert saved['selected']['event_at'] == '2026-11-15T03:20:00Z'
            assert saved['selected']['cumulative_quantity'] == 110
            assert saved['selected']['stock_snapshot_id'] == setup['snapshot_id']
            assert saved['selected']['stock_snapshot_revision'] == 1
            assert control('fallbackCumulative').property('text') == '110'
            assert control('fallbackCumulative').property('readOnly') is True
            assert control('fallbackSave').property('visible') is False
            assert control('fallbackOrdinaryRemaining').property('text') == '90'
            assert control('fallbackOrdinaryIssued').property('text') == '110'
            remaining_control = control('fallbackCounterRemaining' + str(setup['counter_id']))
            assert remaining_control.property('text') == '90'
            source_reference = control('fallbackSnapshotReference').property('text')
            assert '2026-11-15 11:20 HKT' in source_reference
            choose('fallbackRecordPicker', 0)
            wait(idle)
            click('fallbackHistoryRevision1')
            wait(idle)
            assert fallback.property('state')['selected']['cumulative_quantity'] == 110
            assert control('fallbackOrdinaryRemaining').property('text') == '90'
            click('fallbackSubmit')
            wait(idle)
            assert fallback.property('state')['error'] == ''
            assert fallback.property('state')['selected']['status'] == 'submitted'
            assert control('fallbackMode').property('text') == '正常外部數字模式'
            assert control('fallbackApprovalPassword').property('visible') is False

            controller.signOut()
            wait(lambda: controller.property('state')['phase'] == 'signed_out')
            frame()
            controller.signIn(setup['server'], setup['supervisor_username'], setup['password'])
            wait(lambda: controller.property('state')['phase'] == 'workspace')
            workspace = controller.property('workspace')
            workspace.open()
            wait(lambda: not workspace.property('state')['busy'])
            workspace.selectStation(setup['station_id'])
            wait(lambda: not workspace.property('state')['busy'])
            click('fallbackNavigation')
            wait(idle)
            assert fallback.property('state')['selected']['status'] == 'submitted'
            assert control('fallbackCumulative').property('readOnly') is True
            assert control('fallbackOrdinaryRemaining').property('text') == '90'
            enter('fallbackApprovalPassword', setup['password'])
            click('fallbackApprove')
            wait(idle)
            approved = fallback.property('state')
            assert approved['error'] == ''
            assert approved['selected']['status'] == 'approved'
            assert approved['selected']['approved_by'] == setup['supervisor_id']
            assert control('fallbackApprovalPassword').property('text') == ''
            assert control('fallbackMode').property('text') == '後備庫存推算模式'
            remaining_control = control('fallbackCounterRemaining' + str(setup['counter_id']))
            assert remaining_control.property('text') == '90'
            """,
        )
        collection = setup["officer"].get(setup["path"])
        assert collection.status_code == 200 and collection.json()["mode"] == "fallback"
        assert len(collection.json()["items"]) == 1
        saved = collection.json()["items"][0]
        assert saved["status"] == "approved" and saved["revision"] == 1
        assert saved["cumulative_quantity"] == 110
        assert saved["stock_snapshot"] == setup["snapshot"]
        assert saved["approved_by"] == setup["supervisor_account"]["id"]
        turnout = setup["officer"].get(setup["scope"]["path"])
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
