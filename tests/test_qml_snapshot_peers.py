"""A newer shared snapshot cannot hide or replace a retained local correction."""

from tests.qml_workspace_support import run_workspace_qml
from tests.test_qml_stock_snapshots import (
    saved_snapshot_qml_setup as saved_snapshot_qml_setup,
)
from tests.test_qml_stock_snapshots import snapshot_qml_setup as snapshot_qml_setup
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url


def test_peer_snapshot_revision_keeps_dirty_ranges_and_reason_visible_until_explicit_reload(
    saved_snapshot_qml_setup: dict,
) -> None:
    setup = saved_snapshot_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": "en", "base": setup["base"]},
        """
        import ssl
        from uuid import uuid4
        import httpx
        from PySide6.QtCore import QObject
        click('stockSnapshotsNavigation')
        editor = controller.property('stockSnapshots')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('snapshotPicker', 0)
        wait(idle)
        click('snapshotEdit')
        suffix = str(setup['counter_id'])
        enter('snapshotSerialTo' + suffix + '_0', '000005')
        reason = 'Local draft line one: compare the paper log.\\nLine two: retain this draft.'
        enter('snapshotReason', reason)
        selected = editor.property('state')['selected']
        trust = ssl.create_default_context(cafile='.runtime/tls/ca.pem')
        with httpx.Client(base_url=setup['server'], verify=trust, timeout=8) as peer:
            login = peer.post('/api/auth/login', json={
                'username': setup['username'], 'password': setup['password']})
            assert login.status_code == 200
            peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
            corrected = peer.put(setup['base'] + '/stock-snapshots/' + str(selected['id']), json={
                'request_id': str(uuid4()), 'revision': 1, 'event_at': selected['event_at'],
                'reason': 'Independent peer checked the fourth paper against the log.',
                'counters': [{'counter_id': setup['counter_id'], 'ranges': [{
                    'series': '普通系列 A', 'serial_from': '000005', 'serial_to': '000006'}]}]})
            assert corrected.status_code == 200 and corrected.json()['revision'] == 2
            assert peer.delete('/api/auth/session').status_code == 204
        editor.refresh()
        wait(idle)
        state = editor.property('state')
        assert state['selected']['revision'] == 1 and state['newer_revision'] is True
        assert state['dirty'] is True and state['historical'] is True
        assert state['forms']['reason'] == reason
        assert control('snapshotSerialTo' + suffix + '_0').property('text') == '000005'
        assert control('snapshotSerialTo' + suffix + '_0').property('readOnly') is True
        assert control('snapshotReason').property('visible') is True
        assert control('snapshotReason').property('text') == reason
        assert control('snapshotReason').property('readOnly') is True
        assert control('snapshotSave').property('visible') is False
        click('snapshotReload')
        dialog = window.findChild(QObject, 'snapshotDiscardDialog')
        click_confirmation(dialog, controller.texts['discard_changes'])
        wait(lambda: idle() and editor.property('state')['selected']['revision'] == 2)
        assert editor.property('state')['dirty'] is False
        assert control('snapshotSerialFrom' + suffix + '_0').property('text') == '000005'
        """,
    )
    history = setup["api"].get(
        setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}/history"
    )
    assert history.status_code == 200
    rows = history.json()["items"]
    assert len(rows) == 2 and rows[0] == setup["snapshot"]
    assert rows[1]["ordinary_issued_quantity"] == 4
    assert rows[1]["reason"] == "Independent peer checked the fourth paper against the log."
