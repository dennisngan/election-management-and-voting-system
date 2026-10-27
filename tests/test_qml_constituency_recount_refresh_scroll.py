"""Unchanged real workspace refresh must preserve a user's wide-panel scroll position."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, event_command, prepared_box
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_recount_expanded_api import _prepare_extra_zero_scope
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _prepare_two_additional_sources(setup: dict) -> list[dict]:
    polling, receiver = setup["clients"]["polling"], setup["clients"]["receiveronly"]
    boxes = []
    for number in (1, 2):
        path = setup["paths"]["n1_boxes"]
        created = polling.post(path, json=prepared_box(
            box_reference=f"Scroll regression additional box {number}",
            seal_reference=f"Scroll regression additional seal {number}",
        ))
        assert created.status_code == 201, created.text
        received = receiver.post(f"{path}/{created.json()['id']}/receipt", json=event_command(
            1, "2026-11-15T22:46:00+08:00",
        ))
        assert received.status_code == 201, received.text
        boxes.append(received.json())
    # Adding physical boxes changes frozen source-box coverage. Rebase the
    # original mixed scope explicitly before entering its first source count.
    scope = setup["scope"]
    path = f"{setup['scope_path']}/{scope['id']}"
    revised = receiver.put(path, json={
        "request_id": str(uuid4()), "expected_revision": scope["revision"],
        "reference": scope["reference"], "event_at": scope["event_at"],
        "box_revisions": [{"box_id": row["id"], "revision": row["revision"]}
                          for row in scope["box_basis"]],
        "accounting_revisions": [{"station_id": row["station_id"], "revision": row["revision"]}
                                 for row in scope["accounting_basis"]],
        "amendment_reason": "Review two additional N1 boxes as separate physical counting scopes.",
    })
    assert revised.status_code == 200, revised.text
    submitted = receiver.post(path + "/submit", json={
        "request_id": str(uuid4()), "expected_revision": revised.json()["revision"],
    })
    assert submitted.status_code == 200 and submitted.json()["count_ready"] is True
    setup["scope"] = submitted.json()
    return [_prepare_extra_zero_scope(setup, box, number)
            for number, box in enumerate(boxes, 1)]


@pytest.mark.parametrize("scope_count", [2, 4], ids=["two-pending", "four-pending"])
def test_normal_workspace_refresh_keeps_wide_recount_heading_in_the_user_viewport(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    scope_count: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-scroll-regression-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        extra_sources = _prepare_two_additional_sources(setup) if scope_count == 4 else []
        mixed = save_result_round(setup, [6, 4], approve_and_select=True)
        supervisor = setup["clients"]["supervisor"]
        base = f"/api/workspace/constituencies/{setup['constituency_id']}"
        result_path, wide_path = base + "/results", base + "/recounts"
        baseline = supervisor.get(result_path)
        assert baseline.status_code == 200, baseline.text
        assert baseline.json()["complete"] is True and baseline.json()["pending"] == []
        assert len(baseline.json()["contributions"]) == scope_count
        assert [row["quantity"] for row in baseline.json()["candidate_totals"]] == [6, 4]
        options = supervisor.get(wide_path)
        assert options.status_code == 200, options.text
        assert options.json()["can_instruct"] is True
        sources = options.json()["scope_sources"]
        assert len(sources) == scope_count
        assert {row["source_round_id"] for row in sources} == {
            mixed["selected"]["id"], setup["n3_round"]["selected"]["id"],
            *(row["selected"]["id"] for row in extra_sources),
        }
        setup["clock"].value += timedelta(minutes=10)
        local_views = {}
        for source in sources:
            path = (
                f"/api/workspace/stations/{source['station_id']}"
                f"/counting-scopes/{source['scope_id']}/recounts"
            )
            response = supervisor.post(path, json={
                "request_id": str(uuid4()),
                **{key: value for key, value in source.items()
                   if key not in {"station_id", "scope_id"}},
                "event_at": "2026-11-16T00:05:42.123456+08:00",
                "reason": "Leave this required replacement incomplete for the scroll regression.",
                "password": READY_PASSWORD,
            })
            assert response.status_code == 201, response.text
            local = supervisor.get(path)
            assert local.status_code == 200, local.text
            assert len(local.json()["instructions"]) == 1
            local_views[path] = local.json()
        pending = supervisor.get(result_path)
        assert pending.status_code == 200, pending.text
        result = pending.json()
        assert result["complete"] is False and result["provisional"] is True
        assert result["contributions"] == [] and len(result["pending"]) == scope_count
        assert {row["scope_id"] for row in result["pending"]} == {
            row["scope_id"] for row in sources
        }
        assert {row["code"] for row in result["pending"]} == {"recount_pending"}
        assert [row["quantity"] for row in result["candidate_totals"]] == [None, None]
        before_wide = supervisor.get(wide_path)
        assert before_wide.status_code == 200, before_wide.text
        assert before_wide.json()["can_instruct"] is False
        assert before_wide.json()["instructions"] == []
        https_server.clock.value = setup["clock"].value
        before_result_reads = https_server.request_count("GET", result_path)
        before_wide_reads = https_server.request_count("GET", wide_path)
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"], "locale": "en",
                "constituency_id": setup["constituency_id"], "scope_count": scope_count,
                "actor_id": setup["accounts"]["supervisor"]["id"],
                "election_id": setup["election"]["id"],
                "basis_digest": result["basis_digest"],
                "pending_scope_ids": [row["scope_id"] for row in sources],
            },
            """
            results = controller.property('constituencyResults')
            click('constituencyResultsNavigation')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            child = results.property('recounts')
            assert isinstance(child, QObject)
            wait(lambda: not any(child.property('state')[key]
                for key in ('busy', 'refreshing')))
            record = results.property('state')['result']
            assert record['basis_digest'] == setup['basis_digest']
            assert len(record['pending']) == setup['scope_count']
            assert {row['scope_id'] for row in record['pending']} == set(setup['pending_scope_ids'])
            assert {row['code'] for row in record['pending']} == {'recount_pending'}
            assert child.property('state')['can_instruct'] is False
            assert child.property('state')['instructions'] == []
            original_result = json.loads(json.dumps(record))
            # Use the real mouse/focus helper on the right-hand results button.
            # Scrolling afterward must not erase this valid keyboard focus.
            click('constituencyResultsRefresh')
            wait(lambda: not any(results.property('state')[key]
                for key in ('busy', 'refreshing')))
            refresh_button = control('constituencyResultsRefresh')
            assert refresh_button.property('activeFocus') is True
            heading = control('constituencyRecountTitle')
            viewport = heading.parentItem()
            while viewport is not None and not viewport.inherits('QQuickFlickable'):
                viewport = viewport.parentItem()
            assert viewport is not None, 'The wide heading has no real scrolling viewport'
            assert viewport.property('contentHeight') > viewport.height()
            frame()
            origin = float(viewport.property('originY'))
            maximum = origin + float(viewport.property('contentHeight')) - viewport.height()
            top = heading.mapToItem(viewport, QPointF(0, 0))
            target_y = float(viewport.property('contentY')) + top.y() - viewport.height() / 3
            viewport.setProperty('contentY', max(origin, min(maximum, target_y)))
            frame()
            mouse_point = heading.mapToScene(QPointF(heading.width()/2, heading.height()/2))
            QTest.mouseMove(window, mouse_point.toPoint())
            frame()

            def view_snapshot():
                top = heading.mapToItem(viewport, QPointF(0, 0))
                bottom = heading.mapToItem(viewport, QPointF(heading.width(), heading.height()))
                focused = window.activeFocusItem()
                return {
                    'content_y': float(viewport.property('contentY')),
                    'content_height': float(viewport.property('contentHeight')),
                    'viewport_height': viewport.height(),
                    'heading_top': top.y(), 'heading_bottom': bottom.y(),
                    'heading_visible': bool(heading.property('visible') and top.y() >= 0
                        and bottom.y() <= viewport.height() and top.x() >= 0
                        and bottom.x() <= viewport.width()),
                    'focus_object': focused.objectName() if focused is not None else '',
                    'refreshing': bool(results.property('state')['refreshing']),
                }

            anchored = view_snapshot()
            assert anchored['heading_visible'] is True
            assert anchored['focus_object'] == 'constituencyResultsRefresh'
            assert anchored['content_y'] > origin
            def public_signal_spy(item, signature):
                index = item.metaObject().indexOfSignal(signature)
                assert index >= 0, 'Missing public UI signal: ' + signature
                spy = QSignalSpy(item, item.metaObject().method(index))
                assert spy.isValid()
                return spy
            for refresh_number in (1, 2):
                trace = []
                refreshing_seen = [False]
                y_changes = public_signal_spy(viewport, 'contentYChanged()')
                height_changes = public_signal_spy(viewport, 'contentHeightChanged()')
                focus_changes = public_signal_spy(window, 'activeFocusItemChanged()')
                def observe(*_arguments):
                    observation = view_snapshot()
                    trace.append(observation)
                    if observation['refreshing']:
                        refreshing_seen[0] = True
                results.stateChanged.connect(observe)
                try:
                    # This public slot is also called by the actual five-second
                    # application poll. It includes real auth/workspace reads.
                    controller.refresh()
                    wait(lambda: refreshing_seen[0]
                        and not any(results.property('state')[key]
                            for key in ('busy', 'refreshing'))
                        and not any(workspace.property('state')[key]
                            for key in ('busy', 'refreshing')))
                    frame()
                    after = view_snapshot()
                    diagnostic = {'refresh_number': refresh_number,
                        'before': anchored, 'after': after, 'trace': trace[-16:],
                        'content_y_changes': y_changes.count(),
                        'content_height_changes': height_changes.count(),
                        'focus_changes': focus_changes.count()}
                    assert results.property('state')['result'] == original_result
                    assert results.property('state')['context']['constituency']['id'] == (
                        setup['constituency_id'])
                    assert child.property('state')['basis_digest'] == setup['basis_digest']
                    assert child.property('state')['account_id'] == setup['actor_id']
                    assert child.property('state')['station_id'] == setup['station_id']
                    assert child.property('state')['role'] == 'supervisor'
                    assert child.property('state')['context']['election']['id'] == (
                        setup['election_id'])
                    # Intended genuine RED: normal unchanged refresh re-reveals
                    # the offscreen focus target and scrolls away from this heading.
                    assert abs(after['content_y'] - anchored['content_y']) <= 1.0, diagnostic
                    assert after['heading_visible'] is True, diagnostic
                    assert abs(after['content_height'] - anchored['content_height']) <= 1.0, (
                        diagnostic)
                    assert after['focus_object'] == anchored['focus_object'], diagnostic
                    assert child.property('state')['forms'] == {'event_at': '', 'reason': ''}
                    assert child.property('state')['dirty'] is False
                    assert child.property('state')['uncertain_save'] is False
                    assert results.property('state')['dirty'] is False
                finally:
                    results.stateChanged.disconnect(observe)
            """,
        )
        # Positive lower bounds allow valid extra timer refreshes; these include
        # actual initial/foreground reads plus both workspace refresh cycles.
        assert https_server.request_count("GET", result_path) >= before_result_reads + 3
        assert https_server.request_count("GET", wide_path) >= before_wide_reads + 3
        assert https_server.request_count("POST", wide_path) == 0
        assert list(journal_directory.glob("*.json")) == []
        after_result, after_wide = supervisor.get(result_path), supervisor.get(wide_path)
        assert after_result.status_code == after_wide.status_code == 200
        assert after_result.json() == result
        assert after_wide.json() == before_wide.json()
        for path, expected in local_views.items():
            response = supervisor.get(path)
            assert response.status_code == 200 and response.json() == expected
