"""A Supervisor reads actionable election completion through the actual Material UI."""

from collections.abc import Iterator
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
