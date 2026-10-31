"""Main.qml must keep a focused editable recount note visible after layout growth."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_focused_recount_reason_stays_fully_visible_after_deferred_text_growth(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "wide-focused-growth-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        supervisor = setup["clients"]["supervisor"]
        result_path = f"/api/workspace/constituencies/{setup['constituency_id']}/results"
        wide_path = f"/api/workspace/constituencies/{setup['constituency_id']}/recounts"
        before_result, before_wide = supervisor.get(result_path), supervisor.get(wide_path)
        assert before_result.status_code == before_wide.status_code == 200
        assert before_result.json()["complete"] is False
        assert before_wide.json()["can_instruct"] is False
        assert before_wide.json()["instructions"] == []
        assert setup["scope"]["id"] != setup["n3_scope"]["id"]
        https_server.clock.value = setup["clock"].value
        note = "\n".join(
            f"Line {number:02d}: retain this focused recount note after the form grows."
            for number in range(1, 11)
        )
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"], "locale": "en",
                "constituency_id": setup["constituency_id"],
                "election_id": setup["election"]["id"],
                "actor_id": setup["accounts"]["supervisor"]["id"], "note": note,
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
            assert child.property('state')['can_instruct'] is False
            field = control('constituencyRecountReason')
            assert field.property('visible') is True
            assert field.property('readOnly') is False
            assert field.property('enabled') is True
            enter('constituencyRecountReason', 'Initial focused recount note.')
            frame()
            assert field.property('activeFocus') is True
            heading = control('constituencyRecountTitle')
            viewport = heading.parentItem()
            while viewport is not None and not viewport.inherits('QQuickFlickable'):
                viewport = viewport.parentItem()
            assert viewport is not None, 'Expected the actual Main.qml scrolling viewport'
            assert field.height() + 24 < viewport.height()
            original_height = field.height()
            bottom = field.mapToItem(viewport, QPointF(field.width(), field.height()))
            origin = float(viewport.property('originY'))
            maximum = origin + float(viewport.property('contentHeight')) - viewport.height()
            target_y = float(viewport.property('contentY')) + bottom.y() - viewport.height() + 12
            viewport.setProperty('contentY', max(origin, min(maximum, target_y)))
            frame()

            def geometry():
                top = field.mapToItem(viewport, QPointF(0, 0))
                bottom = field.mapToItem(viewport, QPointF(field.width(), field.height()))
                cursor = field.property('cursorRectangle')
                caret_top = field.mapToItem(viewport, QPointF(cursor.x(), cursor.y()))
                caret_bottom = field.mapToItem(viewport,
                    QPointF(cursor.x() + cursor.width(), cursor.y() + cursor.height()))
                focused = window.activeFocusItem()
                return {
                    'field_height': field.height(), 'viewport_height': viewport.height(),
                    'content_y': float(viewport.property('contentY')),
                    'content_height': float(viewport.property('contentHeight')),
                    'field_top': top.y(), 'field_bottom': bottom.y(),
                    'field_visible': bool(field.property('visible') and top.y() >= 0
                        and bottom.y() <= viewport.height() and top.x() >= 0
                        and bottom.x() <= viewport.width()),
                    'caret_visible': bool(caret_top.y() >= 0
                        and caret_bottom.y() <= viewport.height()
                        and caret_top.x() >= 0 and caret_bottom.x() <= viewport.width()),
                    'focus_name': focused.objectName() if focused is not None else '',
                }

            positioned = geometry()
            assert positioned['field_visible'] is True
            assert 0 <= viewport.height() - positioned['field_bottom'] <= 16, positioned
            assert field.property('activeFocus') is True
            center = field.mapToScene(QPointF(field.width()/2, field.height()/2))
            QTest.mouseMove(window, center.toPoint())
            # enter() retains an already-focused item. No explicit reveal call,
            # focus reset or cursor-position change may repair the later layout.
            enter('constituencyRecountReason', setup['note'])
            wait(lambda: field.height() > original_height + 1)
            frame()
            grown = geometry()
            assert grown['field_height'] + 24 < grown['viewport_height'], grown
            wait(lambda: geometry()['field_visible'] and geometry()['caret_visible'])
            after = geometry()
            assert after['field_visible'] is True and after['caret_visible'] is True
            assert after['focus_name'] == positioned['focus_name']
            assert field.property('activeFocus') is True
            assert field.property('readOnly') is False
            assert field.property('text') == setup['note']
            assert field.property('cursorPosition') == len(setup['note'])
            state = child.property('state')
            assert state['forms']['reason'] == setup['note']
            assert state['forms']['event_at'] == '' and state['dirty'] is True
            assert state['uncertain_save'] is False and state['pending_request_id'] == ''
            assert state['account_id'] == setup['actor_id']
            assert state['station_id'] == setup['station_id']
            assert state['constituency_id'] == setup['constituency_id']
            assert state['context']['election']['id'] == setup['election_id']
            assert state['role'] == 'supervisor' and state['instructions'] == []
            assert results.property('state')['dirty'] is False
            assert setup['password'] not in json.dumps(state)
            """,
        )
        assert https_server.request_count("POST", wide_path) == 0
        assert list(journal_directory.glob("*.json")) == []
        after_result, after_wide = supervisor.get(result_path), supervisor.get(wide_path)
        assert after_result.status_code == after_wide.status_code == 200
        assert after_result.json() == before_result.json()
        assert after_wide.json() == before_wide.json()
