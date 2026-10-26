"""Dirty-basis and uncertain-retry edges for constituency tie decisions."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD, box_staff, event_command, prepared_box
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import result_setup
from tests.test_constituency_tie_api import _save_tie_round, complete_tie_setup
from tests.test_counting_workflow_retry_desktop import (
    LostSelectionResponse,
)
from tests.test_counting_workflow_retry_desktop import (
    lost_selection_response as lost_selection_response,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_dirty_tie_review_tracks_same_digest_decision_and_discards_explicitly(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "result_path": result_path,
                "reason": "Local Supervisor review before the peer decision.",
                "peer_reason": "Second Supervisor confirms the same tied candidate.",
            },
            """
            import ssl
            import urllib.request
            import uuid
            from pathlib import Path

            results = controller.property('constituencyResults')
            assert results is not None
            results.refresh()
            unopened = results.property('state')
            assert unopened['busy'] is False and unopened['refreshing'] is False
            assert unopened['result'] == {}
            prior_refresh = controller.property('state')['last_refresh']
            controller.refresh()
            wait(lambda: controller.property('state')['last_refresh'] != prior_refresh)
            assert results.property('state')['result'] == {}

            results.open()
            wait(lambda: not results.property('state')['busy'])
            reviewed = results.property('state')['result']
            candidate_id = reviewed['tie_candidate_ids'][0]
            results.setResolutionCandidate(candidate_id)
            assert results.property('state')['dirty'] is True
            results.setResolutionCandidate(candidate_id)
            assert results.property('state')['dirty'] is True
            results.setResolutionReason(setup['reason'])
            assert results.property('state')['dirty'] is True

            def post_json(path, payload, token=None):
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                request = urllib.request.Request(
                    setup['server'] + path,
                    data=json.dumps(payload).encode(),
                    headers=headers,
                    method='POST',
                )
                context = ssl.create_default_context(
                    cafile=str(Path('.runtime/tls/ca.pem').resolve())
                )
                with urllib.request.urlopen(request, context=context) as response:
                    return json.loads(response.read())

            session = post_json('/api/auth/login', {
                'username': setup['username'], 'password': setup['password']
            })
            peer = post_json(setup['result_path'] + '/tie-resolutions', {
                'request_id': str(uuid.uuid4()),
                'expected_resolution_revision': 0,
                'basis_digest': reviewed['basis_digest'],
                'candidate_id': candidate_id,
                'reason': setup['peer_reason'],
                'password': setup['password'],
            }, session['token'])
            assert peer['resolved_candidate_id'] == candidate_id
            assert peer['basis_digest'] == reviewed['basis_digest']

            results.refresh()
            wait(lambda: not results.property('state')['refreshing'])
            newer = results.property('state')
            assert newer['newer_basis'] is True
            assert newer['dirty'] is True
            assert newer['selected_candidate_id'] == candidate_id
            assert newer['reason'] == setup['reason']

            results.discardAndReload()
            wait(lambda: not results.property('state')['busy'])
            reloaded = results.property('state')
            assert reloaded['dirty'] is False
            assert reloaded['newer_basis'] is False
            assert reloaded['selected_candidate_id'] == 0
            assert reloaded['reason'] == ''
            assert reloaded['result']['tie_resolution']['revision'] == 1
            """,
        )
        # The only result reads are the explicit open, peer-change refresh, and discard reload.
        assert https_server.request_count("GET", result_path) == 3


def test_dropped_tie_response_retries_original_receipt_with_fresh_password(
    admin: TestClient,
    database_url: str,
    lost_selection_response: LostSelectionResponse,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        endpoint = lost_selection_response
        endpoint.clock.value = setup["clock"].value
        endpoint.drop_path = (
            f"/api/workspace/constituencies/{setup['constituency_id']}/results/tie-resolutions"
        )
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        run_workspace_qml(
            {
                "server": endpoint.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "reason": "Supervisor decision committed before TLS response loss.",
                "wrong_password": "Wrong-Password-42!",
            },
            """
            import json

            results = controller.property('constituencyResults')
            assert results is not None
            results.open()
            wait(lambda: not results.property('state')['busy'])
            initial = results.property('state')['result']
            candidate_id = initial['tie_candidate_ids'][1]
            results.setResolutionCandidate(candidate_id)
            results.setResolutionReason(setup['reason'])
            results.resolveTie(setup['password'])
            wait(lambda: not results.property('state')['busy'])
            assert results.property('state')['uncertain_save'] is True

            results.refresh()
            wait(lambda: not results.property('state')['refreshing'])
            uncertain = results.property('state')
            assert uncertain['newer_basis'] is True
            assert uncertain['uncertain_save'] is True
            assert uncertain['selected_candidate_id'] == candidate_id
            assert uncertain['reason'] == setup['reason']

            results.resolveTie(setup['wrong_password'])
            wait(lambda: not results.property('state')['busy'])
            denied = results.property('state')
            assert denied['error'] == 'invalid_credentials'
            assert denied['uncertain_save'] is True
            assert denied['selected_candidate_id'] == candidate_id
            assert denied['reason'] == setup['reason']

            results.setResolutionCandidate(initial['tie_candidate_ids'][0])
            results.setResolutionReason('Changed command must not replace the pending receipt.')
            assert results.property('state')['selected_candidate_id'] == candidate_id
            assert results.property('state')['reason'] == setup['reason']
            results.discardAndReload()
            assert results.property('state')['uncertain_save'] is True
            assert results.property('state')['dirty'] is True

            results.resolveTie(setup['password'])
            wait(lambda: not results.property('state')['busy'])
            recovered = results.property('state')
            assert recovered['uncertain_save'] is False
            assert recovered['dirty'] is False
            assert recovered['newer_basis'] is False
            assert recovered['result']['resolved_candidate_id'] == candidate_id
            assert len(recovered['result']['resolution_history']) == 1
            assert setup['password'] not in json.dumps(recovered, ensure_ascii=False)
            """,
        )
        assert endpoint.response_tagged.is_set()
        assert endpoint.response_dropped.is_set()
        assert endpoint.request_count("POST", f"{result_path}/tie-resolutions") == 3
        result = setup["clients"]["supervisor"].get(result_path)
        assert result.status_code == 200, result.text
        assert len(result.json()["resolution_history"]) == 1


def test_report_preview_rejects_peer_tie_resolution_on_same_count_basis(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        peer_station_ids = [setup["stations"][code]["id"] for code in ("N1", "N2", "N3")]

        with box_staff(admin, database_url, setup["clock"], "supervisor", peer_station_ids) as (
            peer,
            peer_account,
        ):
            before = peer.get(result_path)
            assert before.status_code == 200, before.text
            basis = before.json()
            assert basis["complete"] is True
            assert basis["tie_candidate_ids"]
            result_digest = basis["basis_digest"]
            candidate_id = basis["tie_candidate_ids"][1]
            peer_reason = "Second Supervisor recorded the reviewed tie outcome."

            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": setup["accounts"]["supervisor"]["username"],
                    "password": READY_PASSWORD,
                    "station_id": setup["stations"]["N1"]["id"],
                    "locale": "en",
                    "peer_username": peer_account["username"],
                    "peer_password": READY_PASSWORD,
                    "result_path": result_path,
                    "result_digest": result_digest,
                    "candidate_id": candidate_id,
                    "peer_reason": peer_reason,
                },
                """
                import ssl
                import urllib.request
                import uuid
                from pathlib import Path

                results = controller.property('constituencyResults')
                assert results is not None
                results.open()
                wait(lambda: not results.property('state')['busy'])
                original = results.property('state')['result']
                assert original['basis_digest'] == setup['result_digest']
                assert original.get('resolved_candidate_id') is None
                assert original['tie_candidate_ids']

                def post_json(path, payload, token=None):
                    headers = {'Content-Type': 'application/json'}
                    if token:
                        headers['Authorization'] = 'Bearer ' + token
                    request = urllib.request.Request(
                        setup['server'] + path,
                        data=json.dumps(payload).encode(),
                        headers=headers,
                        method='POST',
                    )
                    context = ssl.create_default_context(
                        cafile=str(Path('.runtime/tls/ca.pem').resolve())
                    )
                    with urllib.request.urlopen(request, context=context) as response:
                        return json.loads(response.read())

                session = post_json('/api/auth/login', {
                    'username': setup['peer_username'],
                    'password': setup['peer_password'],
                })
                peer = post_json(setup['result_path'] + '/tie-resolutions', {
                    'request_id': str(uuid.uuid4()),
                    'expected_resolution_revision': 0,
                    'basis_digest': original['basis_digest'],
                    'candidate_id': setup['candidate_id'],
                    'reason': setup['peer_reason'],
                    'password': setup['peer_password'],
                }, session['token'])
                assert peer['resolved_candidate_id'] == setup['candidate_id']
                assert peer['basis_digest'] == original['basis_digest']
                assert peer['resolution_history'][0]['valid'] is True

                # The result basis is unchanged, but the statement endpoint has a
                # newer tie-resolution snapshot than the page currently displays.
                results.preview('en')
                wait(lambda: not results.property('state')['busy'])
                stale = results.property('state')
                assert stale['newer_basis'] is True
                assert stale['notice'] == 'constituency_result_newer_basis'
                assert stale['report'] == {}
                assert stale['report_text'] == ''
                assert stale['result']['basis_digest'] == setup['result_digest']
                assert stale['result'].get('resolved_candidate_id') is None

                results.refresh()
                wait(lambda: not results.property('state')['refreshing'])
                assert results.property('state')['newer_basis'] is True
                assert results.property('state')['result'].get('resolved_candidate_id') is None

                results.discardAndReload()
                wait(lambda: not results.property('state')['busy'])
                refreshed = results.property('state')
                assert refreshed['newer_basis'] is False
                assert refreshed['result']['resolved_candidate_id'] == setup['candidate_id']
                assert refreshed['result']['tie_resolution']['revision'] == 1
                assert refreshed['report'] == {}
                """,
            )


def test_tie_conflict_codes_render_localized_form_notices(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with complete_tie_setup(admin, database_url) as setup:
        _save_tie_round(setup, [0, 0])
        https_server.clock.value = setup["clock"].value
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        before = supervisor.get(result_path)
        assert before.status_code == 200, before.text
        result = before.json()
        candidate_id = result["tie_candidate_ids"][0]

        stale_digest = ("1" if result["basis_digest"][0] != "1" else "2") + result["basis_digest"][
            1:
        ]
        stale = supervisor.post(
            result_path + "/tie-resolutions",
            json={
                "request_id": str(uuid4()),
                "expected_resolution_revision": 0,
                "basis_digest": stale_digest,
                "candidate_id": candidate_id,
                "reason": "Review the current result basis.",
                "password": READY_PASSWORD,
            },
        )
        assert stale.status_code == 409, stale.text
        stale_code = stale.json()["detail"]["code"]
        assert stale_code == "constituency_result_basis_stale"

        resolved = supervisor.post(
            result_path + "/tie-resolutions",
            json={
                "request_id": str(uuid4()),
                "expected_resolution_revision": 0,
                "basis_digest": result["basis_digest"],
                "candidate_id": candidate_id,
                "reason": "Supervisor records the explicitly selected tied candidate.",
                "password": READY_PASSWORD,
            },
        )
        assert resolved.status_code == 200, resolved.text
        revision_conflict = supervisor.post(
            result_path + "/tie-resolutions",
            json={
                "request_id": str(uuid4()),
                "expected_resolution_revision": 0,
                "basis_digest": result["basis_digest"],
                "candidate_id": candidate_id,
                "reason": "A stale revision must be explained to the Supervisor.",
                "password": READY_PASSWORD,
            },
        )
        assert revision_conflict.status_code == 409, revision_conflict.text
        revision_code = revision_conflict.json()["detail"]["code"]
        assert revision_code == "tie_resolution_revision_conflict"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "api_error_codes": [stale_code, revision_code],
            },
            """
            from pathlib import Path
            from PySide6.QtQml import QQmlComponent

            notice_component = QQmlComponent(engine)
            notice_component.loadUrl(QUrl.fromLocalFile(
                str(Path('src/election/desktop/qml/FormNotice.qml').resolve())
            ))
            wait(lambda: notice_component.status() != QQmlComponent.Status.Loading)
            assert notice_component.status() == QQmlComponent.Status.Ready

            def text_items(root):
                pending = list(root.childItems())
                values = []
                while pending:
                    item = pending.pop()
                    value = item.property('text')
                    if isinstance(value, str):
                        values.append(value)
                    pending.extend(item.childItems())
                return values

            for locale in ('tc', 'sc', 'en'):
                controller.setLocale(locale)
                wait(lambda: controller.property('state')['locale'] == locale)
                words = controller.texts
                for code in setup['api_error_codes']:
                    notice = notice_component.createWithInitialProperties({
                        'words': words, 'error': code, 'notice': ''
                    })
                    assert notice is not None, notice_component.errorString()
                    notice.setParentItem(window.contentItem())
                    notice.setWidth(window.width())
                    notice.setHeight(100)
                    wait(lambda: notice.property('visible'))
                    displayed = text_items(notice)
                    message = words.get(code, code)
                    assert message in displayed
                    assert message != code
                    assert code not in displayed
                    assert '_' not in message
                    if locale in ('tc', 'sc'):
                        assert any('\u4e00' <= char <= '\u9fff' for char in message)
                    notice.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    application.processEvents()
            """,
        )


def test_unreceived_scope_blocker_uses_selected_language_in_statement(
    admin: TestClient,
    database_url: str,
) -> None:
    with result_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        scope_path = setup["scope_path"]
        station_id = setup["stations"]["N2"]["id"]
        polling = setup["clients"]["polling"]
        n2_boxes_path = setup["paths"]["n2_boxes"]
        prepared = polling.post(
            n2_boxes_path,
            json=prepared_box(
                box_reference="Additional received N2 box " + uuid4().hex[:8],
                prepared_at="2026-11-15T23:05:00+08:00",
            ),
        )
        assert prepared.status_code == 201, prepared.text
        received_box = prepared.json()
        departure = polling.post(
            f"{n2_boxes_path}/{received_box['id']}/departure",
            json=event_command(1, "2026-11-15T23:06:00+08:00"),
        )
        assert departure.status_code == 201, departure.text
        receipt = receiver.post(
            f"{setup['paths']['n1_boxes']}/{received_box['id']}/receipt",
            json=event_command(2, "2026-11-15T23:07:00+08:00"),
        )
        assert receipt.status_code == 201, receipt.text

        options = receiver.get(scope_path)
        assert options.status_code == 200, options.text
        source = next(
            row["record"]
            for row in options.json()["source_accounting"]
            if row["station"]["id"] == station_id
        )
        unreceived = setup["boxes"]["unreceived_n2"]
        draft = receiver.post(
            scope_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Scope with an unreceived physical box " + uuid4().hex[:8],
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [
                    {"box_id": receipt.json()["id"], "revision": receipt.json()["revision"]},
                    {"box_id": unreceived["id"], "revision": unreceived["revision"]},
                ],
                "accounting_revisions": [
                    {"station_id": station_id, "revision": source["revision"]}
                ],
            },
        )
        assert draft.status_code == 201, draft.text
        pending_scope_id = draft.json()["id"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results/statement"
        localized_blockers = {
            "tc": "尚未記錄選票箱接收。",
            "sc": "尚未记录选票箱接收。",
            "en": "Ballot-box receipt is not recorded.",
        }
        supervisor = setup["clients"]["supervisor"]
        for locale, label in localized_blockers.items():
            response = supervisor.get(result_path, params={"locale": locale})
            assert response.status_code == 200, response.text
            report = response.json()
            scope_pending = next(
                row
                for row in report["result"]["pending"]
                if row.get("scope_id") == pending_scope_id and row["code"] == "scope_not_ready"
            )
            assert "box_receipt_missing" in [
                blocker["code"] for blocker in scope_pending["blockers"]
            ]
            rendered = " ".join(
                cell for table in report["tables"] for row in table["rows"] for cell in row
            )
            assert label in rendered
            assert "box_receipt_missing" not in rendered
