"""A Supervisor reads actionable election completion through the actual Material UI."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import prepared_box
from tests.desktop_support import HttpsServer
from tests.election_completion_support import reviewed_election_setup
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import (
    READY_PASSWORD,
    draft_payload,
    polling_scope,
    ready_polling_staff,
)
from tests.qml_workspace_support import run_workspace_qml
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields

COMPLETION_LABELS = """
def completion_blocker_labels(station_id):
    pending = [window.contentItem()]
    labels = []
    while pending:
        item = pending.pop()
        if item.objectName() == 'electionCompletionBlocker_' + str(station_id):
            labels.append(item)
        pending.extend(item.childItems())
    return labels
"""


def run_completion_material(setup: dict, scenario: str) -> None:
    run_workspace_qml(setup, COMPLETION_LABELS + dedent(scenario))


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_supervisor_opens_completion_and_sees_missing_actual_polling_in_material(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with ready_polling_staff(
        admin, database_url, "supervisor", station_ids
    ) as (_, account):
        run_completion_material(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_ids[0],
                "locale": "en",
                "election_id": scope.election["id"],
                "required_station_ids": station_ids,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            assert completion is not None
            wait(lambda: not completion.property('state')['busy']
                and not completion.property('state')['refreshing'])
            state = completion.property('state')
            assert state['election_id'] == setup['election_id']
            assert state['error'] == ''
            assert state['assessment']['can_finalize'] is False
            assert control('electionCompletionStatus').property('text') == (
                'Election cannot be finalized yet')
            for station_id in setup['required_station_ids']:
                notice = next(item for item in completion_blocker_labels(station_id)
                    if 'Polling completion is missing' in item.property('text'))
                assert notice.property('visible')
                assert 'Polling completion is missing' in notice.property('text')
                assert str(station_id) in notice.property('text')
            """,
        )


@pytest.mark.parametrize(
    ("locale", "approval_message", "station_caption"),
    [
        ("en", "Polling completion requires current approval", "Polling station"),
        ("tc", "投票服務完成記錄需要有效批准", "投票站"),
        ("sc", "投票服务完成记录需要有效批准", "投票站"),
    ],
)
def test_supervisor_sees_draft_polling_completion_requires_approval_in_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    approval_message: str,
    station_caption: str,
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with (
        ready_polling_staff(
            admin, database_url, "polling_officer", station_ids
        ) as (officer, _),
        ready_polling_staff(
            admin, database_url, "supervisor", station_ids
        ) as (_, account),
    ):
        saved = officer.put(
            scope.path + "/service_completion",
            json=draft_payload(event_at="2025-11-15T23:25:00+08:00"),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "draft"
        assert saved.json()["revision"] == 1
        run_completion_material(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_ids[0],
                "locale": locale,
                "election_id": scope.election["id"],
                "constituency_id": scope.constituency["id"],
                "approval_message": approval_message,
                "station_caption": station_caption,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            assert completion is not None
            wait(lambda: not completion.property('state')['busy']
                and not completion.property('state')['refreshing'])
            state = completion.property('state')
            assert state['election_id'] == setup['election_id']
            assert state['error'] == ''
            assessment = state['assessment']
            assert assessment['can_finalize'] is False
            assert {
                'code': 'polling_completion_approval_required',
                'station_id': setup['station_id'],
                'constituency_id': setup['constituency_id'],
                'revision': 1,
                'status': 'draft',
            } in assessment['blockers']
            frame()
            expected = (setup['approval_message'] + ' · '
                + setup['station_caption'] + ' #' + str(setup['station_id']))
            notice = next(item for item in completion_blocker_labels(setup['station_id'])
                if item.property('text') == expected)
            assert notice.property('visible')
            assert notice.width() > 0 and notice.height() > 0
            assert _pointer_geometry(notice) is not None, (
                'The approval blocker must be inside the actual Material viewport')
            assert notice.property('text') == (
                setup['approval_message'] + ' · ' + setup['station_caption']
                + ' #' + str(setup['station_id']))
            """,
        )


@pytest.mark.parametrize(
    ("locale", "polling_message", "box_message", "station_caption"),
    [
        ("en", "Polling completion is missing", "Required ballot boxes are missing",
         "Polling station"),
        ("tc", "缺少投票服務完成記錄", "缺少所需票箱", "投票站"),
        ("sc", "缺少投票服务完成记录", "缺少所需票箱", "投票站"),
    ],
)
def test_material_displays_polling_and_box_blockers_for_the_same_station(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    locale: str, polling_message: str, box_message: str, station_caption: str,
) -> None:
    scope = polling_scope(admin)
    station_ids = [station["id"] for station in scope.stations]
    with ready_polling_staff(
        admin, database_url, "supervisor", station_ids
    ) as (_, account):
        run_completion_material(
            {
                "server": https_server.url, "username": account["username"],
                "password": READY_PASSWORD, "station_id": station_ids[0],
                "locale": locale, "polling_message": polling_message,
                "box_message": box_message, "station_caption": station_caption,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not completion.property('state')['refreshing'])
            assert completion.property('state')['error'] == ''
            frame()
            labels = completion_blocker_labels(setup['station_id'])
            expected = {message + ' · ' + setup['station_caption']
                + ' #' + str(setup['station_id'])
                for message in (setup['polling_message'], setup['box_message'])}
            assert {label.property('text') for label in labels} == expected
            assert all(label.property('visible') for label in labels)
            assert all(_pointer_geometry(label) is not None for label in labels)
            """,
        )


@pytest.mark.parametrize(
    ("locale", "reason", "constituency_caption"),
    [
        ("en", "Result-affecting tie requires an authorized resolution", "Constituency"),
        ("tc", "影響結果的平票需要授權決定", "選區"),
        ("sc", "影响结果的平票需要授权决定", "选区"),
    ],
)
def test_material_identifies_unresolved_tie_and_its_constituency(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    locale: str, reason: str, constituency_caption: str,
) -> None:
    with reviewed_election_setup(admin, database_url, n1_quantities=(5, 5)) as setup:
        supervisor = setup["clients"]["supervisor"]
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        assert [row["code"] for row in response.json()["blockers"]] == [
            "result_tie_resolution_required",
        ]
        https_server.clock.value = setup["clock"].value
        run_completion_material(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD, "locale": locale,
                "station_id": setup["stations"]["N1"]["id"],
                "constituency_id": setup["constituency_id"],
                "reason": reason, "constituency_caption": constituency_caption,
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not completion.property('state')['refreshing'])
            assert completion.property('state')['error'] == ''
            assert completion.property('state')['assessment']['can_finalize'] is False
            frame()
            notice = control('electionCompletionBlocker_global_0')
            assert notice.property('visible')
            assert _pointer_geometry(notice) is not None
            assert notice.property('text') == (
                setup['reason'] + ' · ' + setup['constituency_caption']
                + ' #' + str(setup['constituency_id']))
            """,
        )


@pytest.mark.parametrize("locale", ["en", "tc", "sc"])
@pytest.mark.parametrize("case", ["missing_selection", "changed_boxes", "recount"])
def test_material_explains_count_prerequisites_with_scope_and_box_references(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str, case: str,
) -> None:
    copy = {
        "en": {
            "station": "Polling station", "scope": "Counting scope", "boxes": "Ballot-box IDs",
            "selected_count_missing": "No approved count is selected",
            "scope_not_ready": "Counting scope is not ready",
            "selected_count_stale": "Selected count is stale",
            "box_unscoped": "Ballot box is not in a counting scope",
            "recount_pending": "The required recount round has not been approved and selected",
        },
        "tc": {
            "station": "投票站", "scope": "點票範圍", "boxes": "選票箱編號",
            "selected_count_missing": "未有選定核准點票",
            "scope_not_ready": "點票範圍未就緒",
            "selected_count_stale": "選定點票已過時",
            "box_unscoped": "選票箱未納入點票範圍",
            "recount_pending": "所需重新點票輪次尚未獲批核並選用",
        },
        "sc": {
            "station": "投票站", "scope": "点票范围", "boxes": "选票箱编号",
            "selected_count_missing": "未有选定核准点票",
            "scope_not_ready": "点票范围未就绪",
            "selected_count_stale": "选定点票已过时",
            "box_unscoped": "选票箱未纳入点票范围",
            "recount_pending": "所需重新点票轮次尚未获批核并选用",
        },
    }[locale]
    with reviewed_election_setup(
        admin, database_url, n1_selected=case != "missing_selection"
    ) as setup:
        supervisor = setup["clients"]["supervisor"]
        expected_codes = {"selected_count_missing"}
        if case == "changed_boxes":
            changed = setup["clients"]["polling"].post(
                setup["paths"]["n1_boxes"],
                json=prepared_box(box_reference="Additional box needs current scope review"),
            )
            assert changed.status_code == 201, changed.text
            expected_codes = {"box_unscoped", "scope_not_ready", "selected_count_stale"}
        elif case == "recount":
            options = supervisor.get(
                f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
            )
            assert options.status_code == 200, options.text
            source = next(
                row for row in options.json()["scope_sources"]
                if row["scope_id"] == setup["n3_scope"]["id"]
            )
            changed = supervisor.post(
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}/recounts",
                json={
                    "request_id": str(uuid4()), "scope_revision": source["scope_revision"],
                    "expected_selection_revision": source["expected_selection_revision"],
                    "source_round_id": source["source_round_id"],
                    "source_round_revision": source["source_round_revision"],
                    "event_at": "2026-11-16T00:00:00+08:00",
                    "reason": "Complete the required count before finalization.",
                    "password": BOX_READY_PASSWORD,
                },
            )
            assert changed.status_code == 201, changed.text
            expected_codes = {"recount_pending"}
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        blockers = response.json()["blockers"]
        assert {row["code"] for row in blockers} == expected_codes
        expected = []
        for row in blockers:
            text = copy[row["code"]] + " · " + copy["station"] + f" #{row['station_id']}"
            if "scope_id" in row:
                text += " · " + copy["scope"] + f" #{row['scope_id']}"
            if row.get("box_ids"):
                text += " · " + copy["boxes"] + " " + ", ".join(map(str, row["box_ids"]))
            expected.append({"station_id": row["station_id"], "text": text})
        https_server.clock.value = setup["clock"].value
        run_completion_material(
            {
                "server": https_server.url, "locale": locale, "expected": expected,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not completion.property('state')['refreshing'])
            assert completion.property('state')['error'] == ''
            assert completion.property('state')['assessment']['can_finalize'] is False
            frame()
            for expected in setup['expected']:
                labels = completion_blocker_labels(expected['station_id'])
                texts = [item.property('text') for item in labels]
                assert expected['text'] in texts, (expected['text'], texts)
                label = next(item for item in labels if item.property('text') == expected['text'])
                assert label.property('visible')
                assert _pointer_geometry(label) is not None
            """,
        )


@pytest.mark.parametrize(
    ("locale", "finalize_label", "finalized_status"),
    [
        ("en", "Finalize election", "Election finalized. Preserved outcome available."),
        ("tc", "確認選舉完成", "選舉已完成確認；已保留結果。"),
        ("sc", "确认选举完成", "选举已完成确认；已保留结果。"),
    ],
)
def test_material_reviews_and_finalizes_ready_election_with_own_password(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
    finalize_label: str,
    finalized_status: str,
) -> None:
    journal_directory = tmp_path / "material-election-finalization-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        initial_response = supervisor.get(setup["completion_path"])
        assert initial_response.status_code == 200, initial_response.text
        reviewed = initial_response.json()
        assert reviewed["can_finalize"] is True and reviewed["blockers"] == []
        election_id = setup["election"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        https_server.clock.value = setup["clock"].value
        assert https_server.request_count("POST", target) == 0
        run_completion_material(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "election_id": election_id,
                "locale": locale,
                "finalize_label": finalize_label,
                "finalized_status": finalized_status,
                "cancel_label": "Cancel" if locale == "en" else "取消",
                "reviewed_revision": reviewed["election"]["revision"],
                "reviewed_basis": reviewed["basis_digest"],
                "journal_directory": str(journal_directory),
            },
            """
            from tests.test_physical_acceptance_recovery_desktop import (
                assert_public_business_fields,
            )

            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            initial = completion.property('state')
            assert initial['error'] == '' and initial['election_id'] == setup['election_id']
            assert initial['assessment']['can_finalize'] is True
            assert initial['assessment']['election']['revision'] == setup['reviewed_revision']
            assert initial['assessment']['basis_digest'] == setup['reviewed_basis']
            finalize = control('electionCompletionFinalize')
            assert finalize.property('visible') and finalize.property('enabled')
            assert finalize.property('text') == setup['finalize_label']
            click('electionCompletionFinalize')
            dialog = window.findChild(QObject, 'electionCompletionPasswordDialog')
            assert dialog is not None
            wait(lambda: dialog.property('opened'))
            staged = completion.property('state')
            assert staged['reviewing'] is True and staged['review']
            assert staged['newer_basis'] is False
            password = control('electionCompletionPassword')
            confirm = control('electionCompletionPasswordConfirm')
            cancel = control('electionCompletionPasswordCancel')
            assert password.property('text') == ''
            assert confirm.property('enabled') is False
            assert cancel.property('text') == setup['cancel_label']
            enter('electionCompletionPassword', setup['password'])
            assert setup['password'] not in json.dumps(completion.property('state'))
            assert confirm.property('enabled') is True
            reviewed_before_refresh = completion.property('state')['review']
            workspace = controller.property('workspace')
            workspace.refresh()
            wait(lambda: not any(workspace.property('state')[key]
                for key in ('busy', 'refreshing')))
            completion.refresh()
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            unchanged = completion.property('state')
            assert unchanged['assessment']['basis_digest'] == (
                reviewed_before_refresh['basis_digest'])
            assert unchanged['review'] == reviewed_before_refresh
            assert unchanged['newer_basis'] is False
            assert password.property('text') == setup['password']
            assert confirm.property('enabled') is True
            click('electionCompletionPasswordConfirm')
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            settled = completion.property('state')
            assert settled['error'] == '' and settled['uncertain_save'] is False
            assert settled['pending_request_id'] == '' and settled['reviewing'] is False
            assert controller.property('state')['active_election'] is None
            assert settled['receipt']['election']['id'] == setup['election_id']
            assert settled['receipt']['election']['status'] == 'finalized'
            assert settled['receipt']['election']['revision'] == setup['reviewed_revision'] + 1
            assert settled['receipt']['active_election_id'] is None
            wait(lambda: not dialog.property('visible'))
            assert password.property('text') == ''
            assert setup['password'] not in json.dumps(settled)
            frame()
            assert control('electionCompletionStatus').property('text') == (
                setup['finalized_status'])
            files = list(Path(setup['journal_directory']).rglob('*.json'))
            assert len(files) == 1
            durable = json.loads(files[0].read_text(encoding='utf-8'))
            assert durable['namespace'] == 'election' and 'station_id' not in durable
            assert durable['election_id'] == setup['election_id']
            assert durable['status'] == 'committed'
            assert durable['payload'] == {
                'request_id': durable['request_id'],
                'expected_election_revision': setup['reviewed_revision'],
                'basis_digest': setup['reviewed_basis'],
            }
            assert_public_business_fields(settled['receipt'], durable['receipt']['record'])
            """,
        )
        assert https_server.request_count("POST", target) == 1
        with https_server.lock:
            statuses = [
                row["status"] for row in https_server.request_timings
                if row["method"] == "POST" and row["path"] == target
            ]
        assert statuses == [201]
        files = list(journal_directory.rglob("*.json"))
        assert len(files) == 1
        durable = json.loads(files[0].read_text(encoding="utf-8"))
        request_id = durable["request_id"]
        canonical_response = supervisor.get(
            f"/api/workspace/elections/{election_id}/request-outcomes/{request_id}"
            "?workflow=election_completion"
        )
        assert canonical_response.status_code == 200, canonical_response.text
        canonical = canonical_response.json()
        assert canonical["request_id"] == request_id
        assert canonical["workflow"] == "election_completion" and canonical["status"] == "committed"
        assert durable["receipt"]["record"] == canonical["record"]
        assert_public_business_fields(durable["receipt"]["record"], canonical["record"])
        assert canonical["record"]["event"]["outcome"]["sources"] == reviewed["sources"]
        current_response = supervisor.get(setup["completion_path"])
        assert current_response.status_code == 200, current_response.text
        assert current_response.json()["election"] == canonical["record"]["election"]
        assert current_response.json()["active_election_id"] is None


@pytest.mark.parametrize("locale", ["en", "tc", "sc"])
def test_material_cancels_unsent_finalization_and_erases_password_on_sign_out(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
) -> None:
    journal_directory = tmp_path / "material-finalization-cancel-and-scope-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        before_response = supervisor.get(setup["completion_path"])
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["can_finalize"] is True and before["blockers"] == []
        election_id = setup["election"]["id"]
        target = f"/api/workspace/elections/{election_id}/finalizations"
        https_server.clock.value = setup["clock"].value
        run_completion_material(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "election_id": election_id,
                "locale": locale,
                "cancel_label": "Cancel" if locale == "en" else "取消",
                "journal_directory": str(journal_directory),
            },
            """
            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            initial_assessment = completion.property('state')['assessment']
            assert initial_assessment['can_finalize'] is True
            assert initial_assessment['election']['id'] == setup['election_id']
            click('electionCompletionFinalize')
            dialog = window.findChild(QObject, 'electionCompletionPasswordDialog')
            assert dialog is not None
            wait(lambda: dialog.property('opened'))
            password = control('electionCompletionPassword')
            assert password.property('text') == ''
            assert completion.property('state')['reviewing'] is True
            enter('electionCompletionPassword', setup['password'])
            assert control('electionCompletionPasswordConfirm').property('enabled') is True
            assert setup['password'] not in json.dumps(completion.property('state'))
            assert control('electionCompletionPasswordCancel').property('text') == (
                setup['cancel_label'])
            click('electionCompletionPasswordCancel')
            wait(lambda: not dialog.property('visible'))
            cancelled = completion.property('state')
            assert password.property('text') == ''
            assert cancelled['review'] == {} and cancelled['reviewing'] is False
            assert cancelled['assessment'] == initial_assessment
            assert cancelled['pending_request_id'] == ''
            assert cancelled['uncertain_save'] is False and cancelled['receipt'] == {}
            assert list(Path(setup['journal_directory']).rglob('*')) == []

            click('electionCompletionFinalize')
            wait(lambda: dialog.property('opened'))
            assert password.property('text') == ''
            assert control('electionCompletionPasswordConfirm').property('enabled') is False
            reopened_review = completion.property('state')
            assert reopened_review['reviewing'] is True
            assert reopened_review['review']['basis_digest'] == initial_assessment['basis_digest']
            enter('electionCompletionPassword', setup['password'])
            assert control('electionCompletionPasswordConfirm').property('enabled') is True
            assert setup['password'] not in json.dumps(controller.property('state'))
            assert setup['password'] not in json.dumps(completion.property('state'))
            controller.signOut()
            wait(lambda: controller.property('state')['phase'] == 'signed_out'
                and not dialog.property('visible'))
            assert password.property('text') == ''
            cleared = completion.property('state')
            assert cleared['review'] == {} and cleared['reviewing'] is False
            assert cleared['pending_request_id'] == '' and cleared['uncertain_save'] is False
            assert cleared['receipt'] == {}
            assert controller.property('state')['account'] == {}
            assert setup['password'] not in json.dumps(cleared)
            assert setup['password'] not in json.dumps(controller.property('state'))
            assert list(Path(setup['journal_directory']).rglob('*')) == []
            """,
        )
        assert https_server.request_count("POST", target) == 0
        with https_server.lock:
            business_writes = [
                (method, path) for method, path in https_server.requests
                if method in {"POST", "PUT", "PATCH", "DELETE"}
                and not path.startswith("/api/auth/")
            ]
        assert business_writes == []
        assert list(journal_directory.rglob("*")) == []
        after_response = supervisor.get(setup["completion_path"])
        assert after_response.status_code == 200, after_response.text
        assert after_response.json() == before


@pytest.mark.parametrize(
    ("locale", "review_changed_text"),
    [
        ("en", "Election data changed. Cancel and review the current facts before confirming."),
        ("tc", "選舉資料已更新。請取消並重新檢視後再確認。"),
        ("sc", "选举资料已更新。请取消并重新检视后再确认。"),
    ],
)
def test_material_source_change_keeps_review_and_clears_confirmation_password(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
    review_changed_text: str,
) -> None:
    journal_directory = tmp_path / "material-stale-finalization-review-journal"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        election_id = setup["election"]["id"]
        complaints_path = f"/api/workspace/stations/{station_id}/complaints"
        case_reference = "Material review case " + uuid4().hex[:12]
        before_response = supervisor.get(setup["completion_path"])
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["can_finalize"] is True and before["blockers"] == []
        assert next(
            row["records"] for row in before["sources"]["complaints"]
            if row["station_id"] == station_id
        ) == []
        target = f"/api/workspace/elections/{election_id}/finalizations"
        https_server.clock.value = setup["clock"].value
        run_completion_material(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": BOX_READY_PASSWORD,
                "polling_username": setup["accounts"]["polling"]["username"],
                "station_id": station_id,
                "election_id": election_id,
                "locale": locale,
                "review_changed_text": review_changed_text,
                "case_reference": case_reference,
                "journal_directory": str(journal_directory),
            },
            """
            import ssl
            import httpx
            from tests.complaint_support import complaint_payload, station_categories
            from tests.test_physical_acceptance_recovery_desktop import (
                assert_public_business_fields,
            )

            click('electionCompletionNavigation')
            completion = controller.property('electionCompletion')
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            assert completion.property('state')['assessment']['can_finalize'] is True
            click('electionCompletionFinalize')
            dialog = window.findChild(QObject, 'electionCompletionPasswordDialog')
            assert dialog is not None
            wait(lambda: dialog.property('opened'))
            reviewed = completion.property('state')['review']
            assert reviewed['election']['id'] == setup['election_id']
            assert reviewed['can_finalize'] is True
            enter('electionCompletionPassword', setup['password'])
            password = control('electionCompletionPassword')
            assert password.property('text') == setup['password']
            assert control('electionCompletionPasswordConfirm').property('enabled') is True
            assert setup['password'] not in json.dumps(completion.property('state'))

            trust = ssl.create_default_context(cafile=str(Path('.runtime/tls/ca.pem').resolve()))
            with httpx.Client(base_url=setup['server'], verify=trust) as peer:
                login = peer.post('/api/auth/login', json={
                    'username': setup['polling_username'], 'password': setup['password'],
                })
                assert login.status_code == 200, 'Synthetic Polling Officer login failed'
                peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                try:
                    categories = station_categories(peer, setup['station_id'])
                    created = peer.post(
                        '/api/workspace/stations/' + str(setup['station_id']) + '/complaints',
                        json=complaint_payload(
                            categories[0], case_reference=setup['case_reference'],
                        ),
                    )
                    assert created.status_code == 201, 'Expected a genuine new complaint201'
                    complaint = created.json()
                    assert complaint['work_status'] == 'in_progress'
                    assert complaint['completed_at'] is None
                finally:
                    logout = peer.delete('/api/auth/session')
                    assert logout.status_code == 204, 'Normal peer logout did not complete'

            completion.refresh()
            wait(lambda: not any(completion.property('state')[key]
                for key in ('busy', 'refreshing')))
            stale = completion.property('state')
            assert stale['newer_basis'] is True and stale['reviewing'] is True
            assert stale['review'] == reviewed
            assert stale['assessment']['election'] == reviewed['election']
            assert stale['assessment']['can_finalize'] is True
            assert stale['assessment']['basis_digest'] != reviewed['basis_digest']
            records = next(row['records'] for row in stale['assessment']['sources']['complaints']
                if row['station_id'] == setup['station_id'])
            assert len(records) == 1
            assert_public_business_fields(records[0], complaint)
            assert dialog.property('visible') is True
            notice = control('electionCompletionReviewChanged')
            frame()
            assert notice.property('visible') is True
            assert notice.property('text') == setup['review_changed_text']
            assert _pointer_geometry(notice) is not None
            assert password.property('text') == ''
            assert control('electionCompletionPasswordConfirm').property('enabled') is False
            assert stale['pending_request_id'] == '' and stale['uncertain_save'] is False
            assert stale['receipt'] == {}
            assert list(Path(setup['journal_directory']).rglob('*')) == []
            changed_assessment = stale['assessment']
            click('electionCompletionPasswordCancel')
            wait(lambda: not dialog.property('visible'))
            cancelled = completion.property('state')
            assert password.property('text') == ''
            assert cancelled['review'] == {} and cancelled['reviewing'] is False
            assert cancelled['assessment'] == changed_assessment
            assert cancelled['pending_request_id'] == '' and cancelled['uncertain_save'] is False
            assert cancelled['receipt'] == {}
            assert setup['password'] not in json.dumps(cancelled)
            assert list(Path(setup['journal_directory']).rglob('*')) == []
            """,
        )
        assert https_server.request_count("POST", target) == 0
        assert https_server.request_count("POST", complaints_path) == 1
        assert list(journal_directory.rglob("*")) == []
        with https_server.lock:
            actual_complaint_statuses = [
                row["status"] for row in https_server.request_timings
                if row["method"] == "POST" and row["path"] == complaints_path
            ]
        assert actual_complaint_statuses == [201]
        records_response = setup["clients"]["polling"].get(complaints_path)
        assert records_response.status_code == 200, records_response.text
        matches = [
            row for row in records_response.json()["items"]
            if row["case_reference"] == case_reference
        ]
        assert len(matches) == 1
        complaint = matches[0]
        assert complaint["work_status"] == "in_progress" and complaint["completed_at"] is None
        after_response = supervisor.get(setup["completion_path"])
        assert after_response.status_code == 200, after_response.text
        after = after_response.json()
        assert after["election"] == before["election"]
        assert after["active_election_id"] == election_id
        assert after["can_finalize"] is True and after["blockers"] == []
        assert after["basis_digest"] != before["basis_digest"]
        assert {"station_id": station_id, "records": [complaint]} in after["sources"]["complaints"]


@pytest.mark.parametrize(
    ("locale", "review_changed_text"),
    [
        ("en", "Election data changed. Cancel and review the current facts before confirming."),
        ("tc", "選舉資料已更新。請取消並重新檢視後再確認。"),
        ("sc", "选举资料已更新。请取消并重新检视后再确认。"),
    ],
)
def test_material_peer_finalization_invalidates_review_from_workspace_context_refresh(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
    review_changed_text: str,
) -> None:
    journal_directory = tmp_path / "material-peer-finalization-own-journal"
    observation_path = tmp_path / "material-peer-finalization-observation.json"
    transport_path = tmp_path / "material-peer-finalization-transport.json"
    assert not journal_directory.exists()
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        target = base + "/finalizations"
        before_response = supervisor.get(setup["completion_path"])
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        assert before["can_finalize"] is True and before["blockers"] == []
        https_server.clock.value = setup["clock"].value
        try:
            run_completion_material(
                {
                    "server": https_server.url,
                    "username": setup["accounts"]["supervisor"]["username"],
                    "password": BOX_READY_PASSWORD,
                    "station_id": setup["stations"]["N1"]["id"],
                    "election_id": election_id,
                    "locale": locale,
                    "review_changed_text": review_changed_text,
                    "journal_directory": str(journal_directory),
                    "observation_path": str(observation_path),
                },
                """
                import os
                import ssl
                from uuid import uuid4
                import httpx

                click('electionCompletionNavigation')
                completion = controller.property('electionCompletion')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                assert completion.property('state')['assessment']['can_finalize'] is True
                click('electionCompletionFinalize')
                dialog = window.findChild(QObject, 'electionCompletionPasswordDialog')
                assert dialog is not None
                wait(lambda: dialog.property('opened'))
                reviewed = completion.property('state')['review']
                assert reviewed['election']['id'] == setup['election_id']
                enter('electionCompletionPassword', setup['password'])
                password = control('electionCompletionPassword')
                assert password.property('text') == setup['password']
                assert control('electionCompletionPasswordConfirm').property('enabled') is True
                trust = ssl.create_default_context(
                    cafile=str(Path('.runtime/tls/ca.pem').resolve()))
                with httpx.Client(base_url=setup['server'], verify=trust) as peer:
                    login = peer.post('/api/auth/login', json={
                        'username': setup['username'], 'password': setup['password'],
                    })
                    assert login.status_code == 200, 'Normal peer Supervisor login failed'
                    peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                    try:
                        base = '/api/workspace/elections/' + str(setup['election_id'])
                        ready_response = peer.get(base + '/completion')
                        assert ready_response.status_code == 200, 'Peer readiness read failed'
                        ready = ready_response.json()
                        assert ready['can_finalize'] is True
                        assert ready['election'] == reviewed['election']
                        assert ready['basis_digest'] == reviewed['basis_digest']
                        peer_request_id = str(uuid4())
                        saved = peer.post(base + '/finalizations', json={
                            'request_id': peer_request_id,
                            'expected_election_revision': ready['election']['revision'],
                            'basis_digest': ready['basis_digest'],
                            'password': setup['password'],
                        })
                        assert saved.status_code == 201, 'Expected genuine peer finalization201'
                        peer_ack = saved.json()
                        assert peer_ack['request_id'] == peer_request_id
                        assert peer_ack['event']['kind'] == 'finalization'
                        assert peer_ack['election']['status'] == 'finalized'
                        assert peer_ack['event']['outcome']['sources'] == ready['sources']
                        history_response = peer.get(base + '/completion/history')
                        assert history_response.status_code == 200, 'Peer history read failed'
                        peer_history = history_response.json()
                        assert peer_history['events'] == [peer_ack['event']]
                    finally:
                        logout = peer.delete('/api/auth/session')
                        assert logout.status_code == 204, 'Normal peer logout did not complete'

                workspace = controller.property('workspace')
                workspace.refresh()
                wait(lambda: not any(workspace.property('state')[key]
                    for key in ('busy', 'refreshing')))
                selected = workspace.property('state')['selected']
                observed = completion.property('state')
                root_election = controller.property('state').get('election') or {}
                completion_election = observed.get('election') or {}
                notice = control('electionCompletionReviewChanged')
                observation = {
                    'peer_ack': peer_ack,
                    'peer_history': peer_history,
                    'workspace_election': selected.get('election', {}),
                    'workspace_election_keys': sorted(selected.get('election', {})),
                    'root_election': root_election,
                    'completion_election': completion_election,
                    'assessment_election': observed.get('assessment', {}).get('election'),
                    'prepared_election': reviewed['election'],
                    'prepared_review_unchanged': observed.get('review') == reviewed,
                    'newer_basis': observed.get('newer_basis'),
                    'password_visible': bool(password.property('text')),
                    'confirm_enabled': control(
                        'electionCompletionPasswordConfirm').property('enabled'),
                    'dialog_visible': dialog.property('visible'),
                    'notice_visible': notice.property('visible'),
                    'notice_text': notice.property('text'),
                    'only_explicit_refresh': 'workspace.refresh',
                }
                descriptor = os.open(setup['observation_path'],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(observation, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                assert selected['station']['id'] == setup['station_id']
                assert selected['election']['id'] == setup['election_id']
                assert selected['election']['status'] == 'finalized'
                assert root_election['id'] == setup['election_id']
                assert root_election['status'] == 'finalized'
                assert completion_election['id'] == setup['election_id']
                assert completion_election['status'] == 'finalized'
                assert observed['review'] == reviewed and observed['reviewing'] is True
                assert observed['newer_basis'] is True
                assert dialog.property('visible') is True
                assert notice.property('visible') is True
                assert notice.property('text') == setup['review_changed_text']
                frame()
                assert _pointer_geometry(notice) is not None
                assert password.property('text') == ''
                assert control('electionCompletionPasswordConfirm').property('enabled') is False
                assert observed['pending_request_id'] == '' and observed['uncertain_save'] is False
                assert observed['receipt'] == {}
                assert list(Path(setup['journal_directory']).rglob('*')) == []
                terminal_before = completion.property('state')
                terminal_button_before = control('electionCompletionFinalize').property('enabled')
                click('electionCompletionPasswordCancel')
                wait(lambda: not dialog.property('visible'))
                terminal_cancelled = completion.property('state')
                terminal_button_cancelled = control(
                    'electionCompletionFinalize').property('enabled')
                terminal_root_cancelled = controller.property('state').get('election') or {}
                terminal_prepare_result = completion.prepareFinalization()
                terminal_after = completion.property('state')
                terminal_button_after = control('electionCompletionFinalize').property('enabled')
                terminal_observation = {
                    'election_id': setup['election_id'],
                    'before_cancel': {
                        'finalize_enabled': terminal_button_before,
                        'review_present': bool(terminal_before.get('review')),
                        'reviewing': terminal_before.get('reviewing'),
                        'context_status': terminal_before.get('election', {}).get('status'),
                        'assessment_status': terminal_before.get('assessment', {}).get(
                            'election', {}).get('status'),
                    },
                    'after_cancel': {
                        'finalize_enabled': terminal_button_cancelled,
                        'review_present': bool(terminal_cancelled.get('review')),
                        'reviewing': terminal_cancelled.get('reviewing'),
                        'root_status': terminal_root_cancelled.get('status'),
                        'context_status': terminal_cancelled.get('election', {}).get('status'),
                        'assessment_status': terminal_cancelled.get('assessment', {}).get(
                            'election', {}).get('status'),
                        'assessment_can_finalize': terminal_cancelled.get('assessment', {}).get(
                            'can_finalize'),
                    },
                    'after_public_prepare': {
                        'returned': terminal_prepare_result,
                        'finalize_enabled': terminal_button_after,
                        'review_present': bool(terminal_after.get('review')),
                        'reviewing': terminal_after.get('reviewing'),
                        'context_status': terminal_after.get('election', {}).get('status'),
                        'pending_request_present': bool(terminal_after.get('pending_request_id')),
                        'uncertain_save': terminal_after.get('uncertain_save'),
                        'password_visible': bool(password.property('text')),
                        'dialog_visible': dialog.property('visible'),
                        'journal_files': [
                            path.name for path in Path(setup['journal_directory']).rglob('*')
                        ],
                    },
                    'no_explicit_completion_refresh': True,
                }
                terminal_observation_path = Path(setup['observation_path']).with_name(
                    'material-terminal-context-cancel-observation.json')
                descriptor = os.open(terminal_observation_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(terminal_observation, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                assert terminal_cancelled['review'] == {}
                assert terminal_cancelled['reviewing'] is False
                assert password.property('text') == '' and not dialog.property('visible')
                assert terminal_root_cancelled['status'] == 'finalized'
                assert terminal_cancelled['election']['status'] == 'finalized'
                assert terminal_button_cancelled is False, terminal_observation
                assert terminal_prepare_result is False, terminal_observation
                assert terminal_after['review'] == {} and terminal_after['reviewing'] is False
                assert terminal_after['election']['status'] == 'finalized'
                assert terminal_after['pending_request_id'] == ''
                assert terminal_after['uncertain_save'] is False
                assert terminal_after['receipt'] == {}
                assert list(Path(setup['journal_directory']).rglob('*')) == []
                """,
            )
        finally:
            with https_server.lock:
                transport = {
                    "requests": list(https_server.requests),
                    "request_timings": list(https_server.request_timings),
                }
            descriptor = os.open(transport_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(transport, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
        assert https_server.request_count("POST", target) == 1
        statuses = [
            row["status"] for row in transport["request_timings"]
            if row["method"] == "POST" and row["path"] == target
        ]
        assert statuses == [201]
        peer_write = transport["requests"].index(("POST", target))
        # Health polling is allowed; a fresh completion read would mask this boundary.
        assert not any(
            method == "GET" and path == base + "/completion"
            for method, path in transport["requests"][peer_write + 1:]
        ), transport["requests"]
        assert list(journal_directory.rglob("*")) == []
        proof = json.loads(observation_path.read_text(encoding="utf-8"))
        peer_ack = proof["peer_ack"]
        cached = supervisor.get(
            base + f"/request-outcomes/{peer_ack['request_id']}?workflow=election_completion"
        )
        assert cached.status_code == 200, cached.text
        assert cached.json()["record"] == peer_ack
        assert peer_ack["event"]["outcome"]["sources"] == before["sources"]
        history = supervisor.get(base + "/completion/history")
        assert history.status_code == 200, history.text
        assert history.json() == proof["peer_history"]
        assert history.json()["election"]["status"] == "finalized"
        assert history.json()["election"]["revision"] == before["election"]["revision"] + 1


@pytest.mark.parametrize(("locale", "words"), [
    ("en", {"title": "Preserved election completion statement", "finalized": "Finalized",
            "finalization": "Finalization", "reopening": "Reopening"}),
    ("tc", {"title": "已保留選舉完成確認報表", "finalized": "已定案",
            "finalization": "完成確認", "reopening": "重新開放"}),
    ("sc", {"title": "已保留选举完成确认报表", "finalized": "已定案",
            "finalization": "完成确认", "reopening": "重新开放"}),
])
def test_material_selects_old_completion_event_and_previews_its_localized_saved_statement(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str, words: dict[str, str],
) -> None:
    journal_directory = tmp_path / "material-selected-history-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    preview_path = tmp_path / "canonical-old-event-preview.json"
    observation_path = tmp_path / "material-selected-history-observation.json"
    transport_path = tmp_path / "material-selected-history-transport.json"
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        assessment_response = supervisor.get(setup["completion_path"])
        assert assessment_response.status_code == 200, assessment_response.text
        assessment = assessment_response.json()
        assert assessment["can_finalize"] is True and assessment["election"]["revision"] == 2
        finalized_response = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": assessment["election"]["revision"],
            "basis_digest": assessment["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        assert finalized_response.status_code == 201, finalized_response.text
        original = finalized_response.json()
        assert original["election"]["status"] == "finalized"
        assert original["election"]["revision"] == 3
        reopened_response = supervisor.post(base + "/reopenings", json={
            "request_id": str(uuid4()),
            "expected_election_revision": original["election"]["revision"],
            "previous_finalization_id": original["event"]["id"],
            "reason": "Read the first signed statement while current election work stays active.",
            "password": BOX_READY_PASSWORD,
        })
        assert reopened_response.status_code == 201, reopened_response.text
        reopened = reopened_response.json()
        assert reopened["election"]["status"] == "active"
        assert reopened["election"]["revision"] == 4
        old_statement_path = base + f"/completion/history/{original['event']['id']}/statement"
        canonical_response = supervisor.get(old_statement_path, params={"locale": locale})
        descriptor = os.open(preview_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_response.content)
            output.flush()
            os.fsync(output.fileno())
        assert canonical_response.status_code == 200, canonical_response.text
        canonical = canonical_response.json()
        assert canonical["event"] == original["event"] and canonical["locale"] == locale
        assert canonical["title"] == words["title"]
        https_server.clock.value = setup["clock"].value
        try:
            run_completion_material(
                {
                    "server": https_server.url,
                    "username": setup["accounts"]["supervisor"]["username"],
                    "password": BOX_READY_PASSWORD, "locale": locale,
                    "station_id": setup["stations"]["N1"]["id"], "election_id": election_id,
                    "current_election": reopened["election"],
                    "old_event_id": original["event"]["id"],
                    "new_event_id": reopened["event"]["id"],
                    "canonical_preview_path": str(preview_path), "words": words,
                    "journal_directory": str(journal_directory),
                    "observation_path": str(observation_path),
                },
                """
                import os
                from copy import deepcopy
                from tests.test_physical_acceptance_recovery_desktop import (
                    assert_public_business_fields,
                )

                canonical = json.loads(Path(setup['canonical_preview_path']).read_text('utf-8'))
                wait(lambda: (controller.property('state')['active_election'] or {}).get('id')
                    == setup['election_id'])
                active_before = deepcopy(controller.property('state')['active_election'])
                click('electionCompletionNavigation')
                completion = controller.property('electionCompletion')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                assert completion.property('state')['error'] == ''
                assert workspace.property('state')['selected']['station']['id'] == (
                    setup['station_id'])
                # Expected first actual Material RED: the explicit history control is absent.
                refresh = focus('electionCompletionHistoryRefresh')
                assert refresh.property('visible') and refresh.property('text').strip()
                assert _pointer_geometry(refresh) is not None
                click('electionCompletionHistoryRefresh')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                history_state = completion.property('state')
                assert history_state['error'] == ''
                assert history_state['history']['election'] == setup['current_election']
                assert [event['id'] for event in history_state['history']['events']] == [
                    setup['new_event_id'], setup['old_event_id']]
                assert str(history_state['selected_event_id']) == str(setup['new_event_id'])
                selector = focus('electionCompletionHistoryEvent')
                assert _pointer_geometry(selector) is not None
                assert selector.property('count') == 2 and selector.property('currentIndex') == 0
                newest_text = selector.property('currentText')
                assert setup['words']['reopening'] in newest_text
                assert str(setup['new_event_id']) in newest_text and '4' in newest_text
                assert 'HKT' in newest_text
                current_label = control('electionCompletionHistoryCurrent')
                assert current_label.property('visible')
                current_text_before = current_label.property('text')
                assert setup['current_election']['name'] in current_text_before
                assert controller.texts['active'] in current_text_before
                assert str(setup['current_election']['revision']) in current_text_before
                choose('electionCompletionHistoryEvent', 1)
                selected = completion.property('state')
                assert str(selected['selected_event_id']) == str(setup['old_event_id'])
                assert_public_business_fields(selected['selected_event'], canonical['event'])
                assert selected['report'] == {} and selected['report_text'] == ''
                oldest_text = control('electionCompletionHistoryEvent').property('currentText')
                assert setup['words']['finalization'] in oldest_text
                assert str(setup['old_event_id']) in oldest_text and '3' in oldest_text
                assert 'HKT' in oldest_text
                preview_button = focus('electionCompletionPreview')
                assert preview_button.property('visible')
                assert preview_button.property('text').strip()
                assert _pointer_geometry(preview_button) is not None
                click('electionCompletionPreview')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                shown = completion.property('state')
                frame()
                preview = control('electionCompletionReportPreview')
                public_text = preview.property('text')
                root_election = controller.property('state')['election'] or {}
                observed = {
                    'locale': controller.property('state')['locale'],
                    'page_locale': control('electionCompletionPage').property('locale'),
                    'selected_event_id': shown['selected_event_id'],
                    'selected_event': shown['selected_event'], 'report': shown['report'],
                    'preview_visible': preview.property('visible'), 'preview_text': public_text,
                    'preview_width': preview.width(), 'preview_height': preview.height(),
                    'newest_text': newest_text, 'oldest_text': oldest_text,
                    'current_label_before': current_text_before,
                    'current_label_after': current_label.property('text'),
                    'root_election': root_election, 'completion_election': shown['election'],
                    'active_before': active_before,
                    'active_after': controller.property('state')['active_election'],
                    'pending_request_id': shown['pending_request_id'],
                    'uncertain_save': shown['uncertain_save'],
                }
                descriptor = os.open(setup['observation_path'],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(observed, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                assert observed['locale'] == setup['locale']
                assert observed['page_locale'] == setup['locale']
                assert shown['error'] == ''
                assert_public_business_fields(shown['selected_event'], canonical['event'])
                assert_public_business_fields(shown['report'], canonical)
                assert shown['report']['locale'] == setup['locale']
                assert shown['report']['rows'] == canonical['rows']
                assert preview.property('visible') is True
                assert preview.width() > 0 and preview.height() > 0
                assert public_text == shown['report_text'] and public_text.strip()
                assert setup['words']['title'] in public_text
                assert setup['words']['finalized'] in public_text and 'HKT' in public_text
                for result in canonical['event']['outcome']['results']:
                    for candidate in result['candidate_totals']:
                        assert candidate['name'] in public_text
                        assert str(candidate['quantity']) in public_text
                assert current_label.property('text') == current_text_before
                known = setup['current_election']
                assert {key: root_election[key] for key in known} == known
                assert shown['election'] == known
                assert controller.property('state')['active_election'] == active_before
                assert shown['receipt'] == {} and shown['pending_request_id'] == ''
                assert shown['uncertain_save'] is False
                assert list(Path(setup['journal_directory']).rglob('*')) == []
                """,
            )
        finally:
            with https_server.lock:
                transport = {"requests": list(https_server.requests),
                             "request_timings": list(https_server.request_timings)}
            descriptor = os.open(transport_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(transport, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
        assert https_server.request_count("GET", base + "/completion/history") == 1
        assert https_server.request_count("GET", old_statement_path) == 1
        assert [row["status"] for row in transport["request_timings"]
                if row["method"] == "GET" and row["path"] == old_statement_path] == [200]
        assert not [(method, path) for method, path in transport["requests"]
                    if method == "GET" and "/request-outcomes/" in path]
        assert not [(method, path) for method, path in transport["requests"]
                    if method in {"POST", "PUT", "PATCH", "DELETE"}
                    and path.startswith("/api/workspace/")]
        assert [(method, path) for method, path in transport["requests"]
                if "/completion/history/" in path and "/statement" in path] == [
                    ("GET", old_statement_path)]
        assert list(journal_directory.rglob("*")) == []


@pytest.mark.parametrize("case", ["confirm"])
@pytest.mark.parametrize("locale", ["en"])
def test_material_reopening_uses_captured_history_before_password(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, locale: str,
) -> None:
    journal_directory = tmp_path / "material-reopening-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    original_path = tmp_path / "canonical-original-finalization.json"
    prepared_path = tmp_path / "material-reopening-prepared.json"
    observation_path = tmp_path / "material-reopening-observation.json"
    transport_path = tmp_path / "material-reopening-transport.json"
    reason = "  Resume reviewed current work while retaining the signed first outcome.  "
    with reviewed_election_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        election_id = setup["election"]["id"]
        base = f"/api/workspace/elections/{election_id}"
        target = base + "/reopenings"
        response = supervisor.get(setup["completion_path"])
        assert response.status_code == 200, response.text
        reviewed = response.json()
        assert reviewed["can_finalize"] is True
        finalized = supervisor.post(base + "/finalizations", json={
            "request_id": str(uuid4()),
            "expected_election_revision": reviewed["election"]["revision"],
            "basis_digest": reviewed["basis_digest"], "password": BOX_READY_PASSWORD,
        })
        descriptor = os.open(original_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(finalized.content)
            output.flush()
            os.fsync(output.fileno())
        assert finalized.status_code == 201, finalized.text
        original = finalized.json()
        assert original["election"]["status"] == "finalized"
        assert original["election"]["revision"] == 3
        assert original["active_election_id"] is None
        https_server.clock.value = setup["clock"].value
        try:
            run_completion_material(
                {
                    "server": https_server.url,
                    "username": setup["accounts"]["supervisor"]["username"],
                    "password": BOX_READY_PASSWORD, "locale": locale, "case": case,
                    "station_id": setup["stations"]["N1"]["id"], "election_id": election_id,
                    "original_path": str(original_path), "reason": reason,
                    "prepared_path": str(prepared_path),
                    "observation_path": str(observation_path),
                    "journal_directory": str(journal_directory),
                },
                """
                import os
                import ssl
                from copy import deepcopy
                from uuid import uuid4
                import httpx
                from tests.test_physical_acceptance_recovery_desktop import (
                    assert_public_business_fields,
                )

                def write_evidence(path, value):
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                        json.dump(value, output, ensure_ascii=False, indent=2)
                        output.flush()
                        os.fsync(output.fileno())

                original = json.loads(Path(setup['original_path']).read_text('utf-8'))
                target = '/api/workspace/elections/' + str(setup['election_id']) + '/reopenings'
                assert workspace.property('state')['selected']['election'] == original['election']
                assert controller.property('state')['active_election'] is None
                click('electionCompletionNavigation')
                completion = controller.property('electionCompletion')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                click('electionCompletionHistoryRefresh')
                wait(lambda: not any(completion.property('state')[key]
                    for key in ('busy', 'refreshing')))
                loaded = completion.property('state')
                assert loaded['error'] == ''
                assert loaded['election'] == original['election']
                assert_public_business_fields(loaded['history'], {
                    'election': original['election'], 'active_election_id': None,
                    'events': [original['event']],
                })
                assert list(Path(setup['journal_directory']).rglob('*')) == []
                reopened_signal = QSignalSpy(completion.reopened)
                finalized_signal = QSignalSpy(completion.finalized)
                # First intended Material RED: the new reason/reopen controls are absent.
                enter('electionCompletionReopenReason', setup['reason'])
                reopen_button = focus('electionCompletionReopen')
                assert reopen_button.property('visible') and reopen_button.property('enabled')
                assert reopen_button.property('text').strip()
                assert _pointer_geometry(reopen_button) is not None
                assert completion.property('state')['can_reopen'] is True
                click('electionCompletionReopen')
                dialog = window.findChild(QObject, 'electionCompletionReopenPasswordDialog')
                assert dialog is not None
                wait(lambda: dialog.property('opened'))
                captured = deepcopy(completion.property('state')['reopening_review'])
                expected_review = {
                    'election_id': setup['election_id'],
                    'expected_election_revision': original['election']['revision'],
                    'previous_finalization_id': original['event']['id'],
                    'reason': setup['reason'].strip(),
                }
                write_evidence(setup['prepared_path'], {
                    'captured': captured, 'expected': expected_review,
                    'password_present': bool(
                        control('electionCompletionReopenPassword').property('text')),
                    'pending_request_id': completion.property('state')['pending_request_id'],
                })
                assert captured == expected_review
                assert completion.property('state')['reopening_changed'] is False
                assert completion.property('state')['pending_request_id'] == ''
                assert control('electionCompletionReopenPassword').property('text') == ''
                assert list(Path(setup['journal_directory']).rglob('*')) == []
                enter('electionCompletionReopenPassword', setup['password'])
                password = control('electionCompletionReopenPassword')
                confirm = control('electionCompletionReopenConfirm')
                assert confirm.property('enabled') is True and confirm.property('text').strip()
                assert setup['password'] not in json.dumps(completion.property('state'))

                if setup['case'] == 'confirm':
                    # Ordinary current reads cannot replace a preparation during password entry.
                    workspace.refresh()
                    wait(lambda: not any(workspace.property('state')[key]
                        for key in ('busy', 'refreshing')))
                    completion.loadHistory()
                    wait(lambda: not any(completion.property('state')[key]
                        for key in ('busy', 'refreshing')))
                    assert completion.property('state')['reopening_review'] == captured
                    assert completion.property('state')['reopening_changed'] is False
                    assert password.property('text') == setup['password']
                    assert confirm.property('enabled') is True
                    assert list(Path(setup['journal_directory']).rglob('*')) == []
                    click('electionCompletionReopenConfirm')
                    wait(lambda: not any(completion.property('state')[key]
                        for key in ('busy', 'refreshing')))
                    settled = completion.property('state')
                    wait(lambda: not dialog.property('visible'))
                    files = list(Path(setup['journal_directory']).rglob('*.json'))
                    durable = json.loads(files[0].read_text('utf-8')) if len(files) == 1 else None
                    write_evidence(setup['observation_path'], {
                        'case': setup['case'], 'captured': captured, 'state': settled,
                        'root_election': controller.property('state')['election'],
                        'active_election': controller.property('state')['active_election'],
                        'password_present': bool(password.property('text')),
                        'dialog_visible': dialog.property('visible'),
                        'reopened_signals': reopened_signal.count(),
                        'finalized_signals': finalized_signal.count(),
                        'durable_command': durable,
                    })
                    assert settled['error'] == ''
                    assert settled['pending_request_id'] == ''
                    assert settled['uncertain_save'] is False
                    assert settled['reopening_review'] == {}
                    assert settled['reopening_changed'] is False
                    assert password.property('text') == '' and not dialog.property('visible')
                    assert reopened_signal.count() == 1 and finalized_signal.count() == 0
                    assert settled['receipt']['event']['kind'] == 'reopening'
                    assert settled['receipt']['event']['previous_finalization_id'] == (
                        captured['previous_finalization_id'])
                    assert settled['receipt']['event']['reason'] == captured['reason']
                    assert settled['election']['status'] == 'active'
                    assert settled['election']['revision'] == (
                        captured['expected_election_revision'] + 1)
                    assert durable is not None
                    assert durable['namespace'] == 'election' and 'station_id' not in durable
                    assert durable['election_id'] == setup['election_id']
                    assert durable['path'] == target and durable['status'] == 'committed'
                    assert durable['payload'] == {
                        'request_id': durable['request_id'],
                        'expected_election_revision': captured['expected_election_revision'],
                        'previous_finalization_id': captured['previous_finalization_id'],
                        'reason': captured['reason'],
                    }
                    assert_public_business_fields(settled['receipt'], durable['receipt']['record'])
                    assert setup['password'] not in json.dumps(durable)
                else:
                    trust = ssl.create_default_context(
                        cafile=str(Path('.runtime/tls/ca.pem').resolve()))
                    with httpx.Client(base_url=setup['server'], verify=trust) as peer:
                        login = peer.post('/api/auth/login', json={
                            'username': setup['username'], 'password': setup['password'],
                        })
                        assert login.status_code == 200, 'Synthetic Supervisor peer login failed'
                        peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
                        try:
                            peer_response = peer.post(target, json={
                                'request_id': str(uuid4()),
                                'expected_election_revision': original['election']['revision'],
                                'previous_finalization_id': original['event']['id'],
                                'reason': 'Independent peer resumed the finalized election first.',
                                'password': setup['password'],
                            })
                            assert peer_response.status_code == 201, (
                                'Expected genuine peer reopening201')
                            peer_ack = peer_response.json()
                        finally:
                            logout = peer.delete('/api/auth/session')
                            assert logout.status_code == 204, 'Synthetic peer logout failed'
                    # Current entity metadata alone invalidates the old unsent review.
                    workspace.refresh()
                    wait(lambda: not any(workspace.property('state')[key]
                        for key in ('busy', 'refreshing')))
                    stale = completion.property('state')
                    changed = control('electionCompletionReopenChanged')
                    write_evidence(setup['observation_path'], {
                        'case': setup['case'], 'captured': captured, 'peer_ack': peer_ack,
                        'state': stale, 'root_election': controller.property('state')['election'],
                        'active_election': controller.property('state')['active_election'],
                        'password_present': bool(password.property('text')),
                        'confirm_enabled': confirm.property('enabled'),
                        'dialog_visible': dialog.property('visible'),
                        'changed_visible': changed.property('visible'),
                        'changed_text': changed.property('text'),
                        'reopened_signals': reopened_signal.count(),
                        'finalized_signals': finalized_signal.count(),
                        'journal_files': [str(path) for path in
                            Path(setup['journal_directory']).rglob('*')],
                    })
                    assert stale['reopening_review'] == captured
                    assert stale['reopening_changed'] is True
                    assert stale['election'] == peer_ack['election']
                    root_election = controller.property('state')['election']
                    assert {key: root_election[key] for key in peer_ack['election']} == (
                        peer_ack['election'])
                    assert password.property('text') == '' and confirm.property('enabled') is False
                    if dialog.property('visible'):
                        assert changed.property('visible') and changed.property('text').strip()
                    assert stale['can_reopen'] is False
                    assert stale['receipt'] == {} and stale['pending_request_id'] == ''
                    assert stale['uncertain_save'] is False
                    assert reopened_signal.count() == 0 and finalized_signal.count() == 0
                    assert list(Path(setup['journal_directory']).rglob('*')) == []
                """,
            )
        finally:
            with https_server.lock:
                transport = {"requests": list(https_server.requests),
                             "request_timings": list(https_server.request_timings)}
            descriptor = os.open(transport_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(transport, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
        assert https_server.request_count("POST", target) == 1
        assert [row["status"] for row in transport["request_timings"]
                if row["method"] == "POST" and row["path"] == target] == [201]
        assert not [path for method, path in transport["requests"]
                    if method == "GET" and "/request-outcomes/" in path]
        proof = json.loads(observation_path.read_text('utf-8'))
        if case == "confirm":
            command = proof["durable_command"]
            outcome_response = supervisor.get(
                base + f"/request-outcomes/{command['request_id']}?workflow=election_completion"
            )
            assert outcome_response.status_code == 200, outcome_response.text
            canonical = outcome_response.json()["record"]
            assert command["receipt"]["record"] == canonical
            assert_public_business_fields(proof["state"]["receipt"], canonical)
            assert canonical["event"]["previous_finalization_id"] == original["event"]["id"]
            assert canonical["event"]["reason"] == reason.strip()
            active_response = supervisor.get("/api/active-election")
            assert active_response.status_code == 200, active_response.text
            actual_active = active_response.json()["election"]
            assert proof["active_election"] == actual_active
            assert {key: proof["root_election"][key] for key in canonical["election"]} == (
                canonical["election"])
            post_index = transport["requests"].index(("POST", target))
            assert ("GET", "/api/active-election") in transport["requests"][post_index + 1:]
            assert len(list(journal_directory.rglob("*.json"))) == 1
        else:
            canonical = proof["peer_ack"]
            assert proof["state"]["reopening_review"] == proof["captured"]
            assert list(journal_directory.rglob("*")) == []
        history_response = supervisor.get(base + "/completion/history")
        assert history_response.status_code == 200, history_response.text
        assert history_response.json()["events"] == [canonical["event"], original["event"]]
