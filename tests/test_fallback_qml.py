"""Actual Material controls save, submit and confirm an EPR fallback activation."""

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.fallback_support import approved_mixed_period, fallback_setup
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


@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("tc", {"new": "記錄恢復外部數字", "normal": "正常外部數字模式",
                "stock": "後備庫存推算模式", "comparison": "恢復核對比較"}),
        ("sc", {"new": "记录恢复外部数字", "normal": "正常外部数字模式",
                "stock": "后备库存推算模式", "comparison": "恢复核对比较"}),
        ("en", {"new": "Record external recovery", "normal": "Normal external-figure mode",
                "stock": "Stock-derived fallback mode", "comparison": "Recovery comparison"}),
    ],
)
def test_material_recovery_retains_stock_115_and_confirms_external_116_without_addition(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    locale: str, words: dict[str, str],
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": setup["snapshot"]["station_id"],
             "locale": locale, "words": words, "snapshot_id": prepared["endpoint"]["id"],
             "activation_id": prepared["activation"]["id"],
             "supervisor_username": setup["supervisor_account"]["username"],
             "supervisor_id": setup["supervisor_account"]["id"]},
            """
            click('fallbackNavigation')
            fallback = controller.property('fallback')
            def idle():
                return not any(fallback.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            assert control('fallbackMode').property('text') == setup['words']['stock']
            # First new recovery UI assertion: the missing new-record action is RED.
            # Later entry/comparison/approval and renewed-review readbacks are unreached.
            click('fallbackNewRecovery')
            frame()
            assert control('fallbackNewRecovery').property('text') == setup['words']['new']
            assert fallback.property('state')['forms']['kind'] == 'recovery'
            assert control('fallbackActivationId').property('text') == str(setup['activation_id'])
            assert control('fallbackActivationId').property('readOnly') is True
            assert control('fallbackActivationRevision').property('text') == '1'
            assert control('fallbackActivationRevision').property('readOnly') is True
            enter('fallbackEventTime', '2026-11-15 12:00')
            enter('fallbackCumulative', '116')
            enter('fallbackSnapshotId', str(setup['snapshot_id']))
            enter('fallbackSnapshotRevision', '1')
            enter('fallbackSource', 'Recovered manual register confirms 116 at noon.')
            enter('fallbackReason', '恢復外部累計116，比庫存推算115多一人。')
            click('fallbackSave')
            wait(idle)
            selected = fallback.property('state')['selected']
            assert fallback.property('state')['error'] == ''
            assert selected['kind'] == 'recovery' and selected['status'] == 'draft'
            assert selected['cumulative_quantity'] == 116
            assert selected['activation_id'] == setup['activation_id']
            comparison_title = control('fallbackReconciliationTitle').property('text')
            assert comparison_title == setup['words']['comparison']
            assert control('fallbackComparisonStock').property('text') == '115'
            assert control('fallbackComparisonRecovered').property('text') == '116'
            assert control('fallbackComparisonDifference').property('text') == '1'
            assert control('fallbackOrdinaryIssued').property('text') == '115'
            assert control('fallbackOrdinaryRemaining').property('text') == '85'
            click('fallbackSubmit')
            wait(idle)
            assert fallback.property('state')['selected']['status'] == 'submitted'
            assert control('fallbackMode').property('text') == setup['words']['stock']
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
            assert fallback.property('state')['selected']['kind'] == 'recovery'
            assert control('fallbackCumulative').property('readOnly') is True
            assert control('fallbackComparisonStock').property('text') == '115'
            enter('fallbackApprovalPassword', setup['password'])
            click('fallbackApprove')
            wait(idle)
            assert fallback.property('state')['error'] == ''
            assert fallback.property('state')['selected']['status'] == 'approved'
            assert fallback.property('state')['selected']['approved_by'] == setup['supervisor_id']
            assert control('fallbackApprovalPassword').property('text') == ''
            assert control('fallbackMode').property('text') == setup['words']['normal']
            assert control('fallbackComparisonRecovered').property('text') == '116'
            """,
        )
        collection = setup["officer"].get(setup["path"])
        assert collection.status_code == 200 and collection.json()["mode"] == "normal"
        recovery = collection.json()["items"][-1]
        assert recovery["kind"] == "recovery" and recovery["status"] == "approved"
        assert recovery["reconciliation"]["stock_derived_cumulative_quantity"] == 115
        assert recovery["reconciliation"]["recovered_cumulative_quantity"] == 116
        assert recovery["reconciliation"]["difference"] == 1
        turnout = setup["officer"].get(setup["scope"]["path"])
        assert turnout.status_code == 200
        assert turnout.json()["items"][1]["record"] == prepared["approved"]
        assert turnout.json()["items"][1]["approval_valid"] is False
        assert turnout.json()["items"][1]["review_required"] is True
        assert turnout.json()["approved_prefix"]["cumulative_end"] == 100
        snapshot = setup["officer"].get(setup["base"] + "/stock-snapshots/"
                                          + str(prepared["endpoint"]["id"]))
        assert snapshot.status_code == 200 and snapshot.json() == prepared["endpoint"]


@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("tc", {"begin": "建立有原因的修正", "keep": "繼續編輯", "discard": "捨棄變更"}),
        ("sc", {"begin": "建立有原因的修正", "keep": "继续编辑", "discard": "舍弃更改"}),
        ("en", {"begin": "Prepare a reasoned correction", "keep": "Keep editing",
                "discard": "Discard changes"}),
    ],
)
def test_material_reasoned_correction_preserves_discard_guards_and_readonly_history(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    locale: str, words: dict[str, str],
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": setup["snapshot"]["station_id"],
             "locale": locale, "words": words,
             "supervisor_username": setup["supervisor_account"]["username"]},
            """
            from PySide6.QtCore import QObject
            click('fallbackNavigation')
            fallback = controller.property('fallback')
            def idle():
                return not any(fallback.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            assert control('fallbackCumulative').property('text') == '110'
            assert control('fallbackCumulative').property('readOnly') is True
            # First new correction boundary: the explicit Begin action is missing.
            # Later dirty guards, r2/history and renewed-review assertions are unreached.
            click('fallbackBeginAmend')
            assert control('fallbackBeginAmend').property('text') == setup['words']['begin']
            assert fallback.property('state')['editing'] is True
            assert control('fallbackCumulative').property('readOnly') is False
            assert control('fallbackReason').property('text') == ''
            enter('fallbackCumulative', '111')
            enter('fallbackSource', 'Corrected supplied baseline is 111 at 11:20.')
            enter('fallbackReason', '更正登記：110應為111，保留原始來源。')
            dialog = window.findChild(QObject, 'fallbackDiscardDialog')
            for name in ('fallbackHistoryRevision1', 'fallbackNewActivation', 'fallbackReload'):
                click(name)
                click_confirmation(dialog, setup['words']['keep'])
                assert control('fallbackCumulative').property('text') == '111'
                assert fallback.property('state')['editing'] is True
                assert fallback.property('state')['dirty'] is True
            click('fallbackRefresh')
            wait(idle)
            assert control('fallbackCumulative').property('text') == '111'
            click('fallbackReload')
            click_confirmation(dialog, setup['words']['discard'])
            wait(idle)
            assert control('fallbackCumulative').property('text') == '110'
            assert fallback.property('state')['editing'] is False
            assert fallback.property('state')['dirty'] is False
            click('fallbackBeginAmend')
            enter('fallbackCumulative', '111')
            enter('fallbackSource', 'Corrected supplied baseline is 111 at 11:20.')
            enter('fallbackReason', '更正登記：110應為111，保留原始來源。')
            click('fallbackAmend')
            wait(idle)
            selected = fallback.property('state')['selected']
            assert fallback.property('state')['error'] == ''
            assert selected['revision'] == 2 and selected['status'] == 'draft'
            assert selected['cumulative_quantity'] == 111
            assert selected['reason'] == '更正登記：110應為111，保留原始來源。'
            assert fallback.property('state')['editing'] is False
            assert control('fallbackCumulative').property('readOnly') is True
            remaining_text = control('fallbackOrdinaryRemaining').property('text')
            current_selected = fallback.property('state')['selected']
            display_source = current_selected.get('stock_snapshot_display', {})
            assert remaining_text == '90', (remaining_text, sorted(display_source),
                display_source.get('ordinary_remaining_quantity_display'))
            click('fallbackHistoryRevision1')
            wait(idle)
            assert fallback.property('state')['historical'] is True
            assert control('fallbackCumulative').property('text') == '110'
            assert control('fallbackCumulative').property('readOnly') is True
            assert control('fallbackBeginAmend').property('visible') is False
            assert control('fallbackAmend').property('visible') is False
            choose('fallbackRecordPicker', 0)
            wait(idle)
            assert fallback.property('state')['selected']['revision'] == 2
            click('fallbackSubmit')
            wait(idle)
            assert fallback.property('state')['selected']['status'] == 'submitted'
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
            assert fallback.property('state')['selected']['revision'] == 2
            assert control('fallbackBeginAmend').property('visible') is False
            enter('fallbackApprovalPassword', setup['password'])
            click('fallbackApprove')
            wait(idle)
            assert fallback.property('state')['error'] == ''
            assert fallback.property('state')['selected']['status'] == 'approved'
            assert control('fallbackApprovalPassword').property('text') == ''
            click('fallbackHistoryRevision1')
            wait(idle)
            assert control('fallbackCumulative').property('text') == '110'
            assert control('fallbackCumulative').property('readOnly') is True
            """,
        )
        activation = prepared["activation"]
        history = setup["officer"].get(setup["path"] + f"/{activation['id']}/history")
        assert history.status_code == 200
        assert [row["cumulative_quantity"] for row in history.json()["items"]] == [110, 111]
        assert history.json()["items"][0] == activation
        assert history.json()["items"][1]["status"] == "approved"
        assert history.json()["items"][1]["reason"] == "更正登記：110應為111，保留原始來源。"
        turnout = setup["officer"].get(setup["scope"]["path"])
        assert turnout.status_code == 200
        assert turnout.json()["items"][1]["record"] == prepared["approved"]
        assert turnout.json()["items"][1]["review_required"] is True
        assert turnout.json()["approved_prefix"]["cumulative_end"] == 100


def test_material_recovery_preserves_nineteen_digit_turnout_and_exact_large_difference_text(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": setup["snapshot"]["station_id"],
             "locale": "en", "snapshot_id": prepared["endpoint"]["id"]},
            """
            click('fallbackNavigation')
            fallback = controller.property('fallback')
            def idle():
                return not any(fallback.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            click('fallbackNewRecovery')
            enter('fallbackEventTime', '2026-11-15 12:00')
            enter('fallbackCumulative', '1000000000000000000')
            enter('fallbackSnapshotId', str(setup['snapshot_id']))
            enter('fallbackSnapshotRevision', '1')
            enter('fallbackSource', 'Synthetic exact integer register boundary.')
            enter('fallbackReason', 'Keep the large external total separate from ordinary stock.')
            click('fallbackSave')
            wait(idle)
            assert fallback.property('state')['error'] == ''
            assert control('fallbackCumulative').property('text') == '1000000000000000000'
            assert control('fallbackComparisonStock').property('text') == '115'
            assert control('fallbackComparisonRecovered').property('text') == '1000000000000000000'
            assert control('fallbackComparisonDifference').property('text') == '999999999999999885'
            assert control('fallbackOrdinaryIssued').property('text') == '115'
            assert control('fallbackOrdinaryRemaining').property('text') == '85'
            assert fallback.property('state')['selected']['status'] == 'draft'
            """,
        )
        response = setup["officer"].get(setup["path"])
        assert response.status_code == 200 and response.json()["mode"] == "fallback"
        draft = response.json()["items"][-1]
        assert draft["status"] == "draft" and draft["kind"] == "recovery"
        assert type(draft["cumulative_quantity"]) is int
        assert draft["cumulative_quantity"] == 1000000000000000000
        assert type(draft["reconciliation"]["difference"]) is int
        assert draft["reconciliation"]["difference"] == 999999999999999885
        assert draft["stock_snapshot"] == prepared["endpoint"]
        turnout = setup["officer"].get(setup["scope"]["path"])
        assert turnout.status_code == 200
        assert turnout.json()["approved_prefix"]["cumulative_end"] == 115
        assert turnout.json()["items"][1]["record"] == prepared["approved"]
