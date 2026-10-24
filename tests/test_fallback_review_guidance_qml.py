"""Material guidance distinguishes source invalidation from a new P(15) revision."""

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import TLS_DIRECTORY, HttpsServer
from tests.fallback_support import approved_mixed_period, fallback_setup
from tests.qml_workspace_support import run_workspace_qml
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD


@pytest.mark.parametrize("locale,newer_message,review_message", [
    ("tc",
     "伺服器資料或確認狀態已有變更。您審閱的版本及未儲存內容已保留，請重新載入並比較。",
     "原確認已保留，但其來源或前一時段基礎已變更，現須重新覆核。請建立有原因的修訂草稿並重新提交。"),
    ("sc",
     "服务器资料或确认状态已有变更。您审阅的版本及未保存内容已保留，请重新载入并比较。",
     "原确认已保留，但其来源或前一时段基础已变更，现须重新复核。请建立有原因的修订草稿并重新提交。"),
    ("en",
     "Server data or approval status has changed. Your reviewed version and unsaved input are "
     "retained. Reload and compare before continuing.",
     "The earlier approval is retained, but its source or preceding-period basis has changed. "
     "Create a reasoned amendment and submit it for renewed review."),
], ids=["tc", "sc", "en"])
def test_material_source_invalidation_guidance_keeps_the_same_reviewed_p15_revision(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    locale: str, newer_message: str, review_message: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        activation, endpoint = prepared["activation"], prepared["endpoint"]
        assert prepared["approved"]["revision"] == 1
        assert prepared["approved"]["derived_hourly"] == 15
        assert prepared["approved"]["derived_cumulative_end"] == 115
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": endpoint["station_id"], "locale": locale,
             "activation_id": activation["id"], "snapshot_id": endpoint["id"],
             "fallback_path": setup["path"], "ca_file": str(TLS_DIRECTORY / "ca.pem"),
             "supervisor_username": setup["supervisor_account"]["username"],
             "newer_message": newer_message, "review_message": review_message},
            """
            import ssl
            from uuid import uuid4
            import httpx
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            def idle():
                return not any(turnout.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            choose('turnoutPeriodPicker', 1)
            wait(idle)
            original = turnout.property('state')['selected']
            assert original['revision'] == 1 and original['derived_cumulative_end_display'] == '115'
            assert turnout.property('state')['approved_prefix']['cumulative_end_display'] == '115'
            trust = ssl.create_default_context(cafile=setup['ca_file'])
            with httpx.Client(base_url=setup['server'], verify=trust, timeout=8) as officer:
                login = officer.post('/api/auth/login', json={
                    'username': setup['username'], 'password': setup['password']})
                assert login.status_code == 200
                officer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                created = officer.post(setup['fallback_path'], json={
                    'request_id': str(uuid4()), 'expected_schedule_revision': 1, 'kind': 'recovery',
                    'activation_id': setup['activation_id'], 'activation_revision': 1,
                    'stock_snapshot_id': setup['snapshot_id'], 'stock_snapshot_revision': 1,
                    'event_at': '2026-11-15T12:00:00+08:00', 'cumulative_quantity': 116,
                    'source_context': 'Peer recovered manual register: cumulative 116 at noon.',
                    'reason': 'Reconcile this source without creating another P(15) revision.'})
                assert created.status_code == 201
                recovery_path = setup['fallback_path'] + '/' + str(created.json()['id'])
                submitted = officer.post(recovery_path + '/submit', json={
                    'request_id': str(uuid4()), 'expected_revision': 1,
                    'expected_schedule_revision': 1})
                assert submitted.status_code == 200
                assert officer.delete('/api/auth/session').status_code == 204
            with httpx.Client(base_url=setup['server'], verify=trust, timeout=8) as supervisor:
                login = supervisor.post('/api/auth/login', json={
                    'username': setup['supervisor_username'], 'password': setup['password']})
                assert login.status_code == 200
                supervisor.headers['Authorization'] = 'Bearer ' + login.json()['token']
                confirmed = supervisor.post(recovery_path + '/approve', json={
                    'request_id': str(uuid4()), 'expected_revision': 1,
                    'expected_schedule_revision': 1, 'password': setup['password']})
                assert confirmed.status_code == 200
                assert confirmed.json()['cumulative_quantity'] == 116
                assert confirmed.json()['status'] == 'approved'
                assert supervisor.delete('/api/auth/session').status_code == 204
            click('turnoutRefresh')
            wait(lambda: idle() and turnout.property('state')['newer_revision'])
            frame()
            state = turnout.property('state')
            assert state['selected'] == original
            assert state['current']['record'] == original
            assert state['current']['record']['revision'] == 1
            assert state['current']['review_required'] is True
            assert state['current']['approval_valid'] is False
            assert state['approved_prefix']['cumulative_end_display'] == '100'
            assert state['selected']['derived_hourly_display'] == '15'
            assert state['selected']['derived_cumulative_end_display'] == '115'
            pending = list(window.contentItem().childItems())
            visible_texts = []
            while pending:
                item = pending.pop()
                text = item.property('text')
                if item.property('visible') and isinstance(text, str):
                    visible_texts.append(text)
                pending.extend(item.childItems())
            assert '15' in visible_texts and '115' in visible_texts
            warning = control('turnoutNewerWarning')
            assert warning.property('visible') is True
            old_review_label = controller.texts['turnout_review_invalid']
            actual_review = [text for text in visible_texts if old_review_label in text]
            # First new assertion is wrong visible copy, after all real peer/state checks pass.
            assert warning.property('text') == setup['newer_message'], {
                'actual_newer': warning.property('text'), 'visible_review_guidance': actual_review}
            assert any(setup['review_message'] in text for text in visible_texts)
            """,
        )
