"""A Supervisor reads actionable election completion through the actual Material UI."""

import json
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
