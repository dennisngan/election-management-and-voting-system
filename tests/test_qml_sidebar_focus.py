"""Focused sidebar choices stay visible through keyboard navigation and resizing."""

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_qml_boxes import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_qml_boxes import database_url as database_url


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
@pytest.mark.parametrize(
    ("width", "height"), [(1280, 800), (900, 480)], ids=["1280x800", "900x480"]
)
def test_sidebar_keyboard_focus_reveals_the_whole_choice_and_survives_height_changes(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    width: int,
    height: int,
) -> None:
    station, clock = box_stations(admin)["N2"], BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        _,
        account,
    ):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station["id"],
                "locale": locale,
                "width": width,
                "height": height,
            },
            """
            def sidebar_viewport(item):
                ancestor = item.parentItem()
                while ancestor is not None and not ancestor.inherits('QQuickFlickable'):
                    ancestor = ancestor.parentItem()
                assert ancestor is not None, 'Navigation choice has no scrolling viewport'
                return ancestor

            def entirely_visible(item):
                viewport = sidebar_viewport(item)
                start = item.mapToItem(viewport, QPointF(0, 0))
                end = item.mapToItem(viewport, QPointF(item.width(), item.height()))
                return (start.x() >= 0 and start.y() >= 0
                    and end.x() <= viewport.width() and end.y() <= viewport.height())

            def expect_visible_focus(item):
                wait(lambda: item.property('activeFocus'))
                try:
                    wait(lambda: entirely_visible(item))
                except AssertionError:
                    viewport = sidebar_viewport(item)
                    origin = item.mapToItem(viewport, QPointF(0, 0))
                    raise AssertionError((
                        'Focused sidebar choice is clipped', item.objectName(),
                        'top', origin.y(), 'bottom', origin.y() + item.height(),
                        'viewport height', viewport.height(),
                        'scroll position', viewport.property('contentY'),
                    )) from None
                frame()
                assert entirely_visible(item)

            window.setProperty('width', setup['width'])
            window.setProperty('height', setup['height'])
            frame()
            assert window.width() == setup['width'] and window.height() == setup['height']
            queue = control('queueNavigation')
            boxes = control('boxesNavigation')
            queue.forceActiveFocus(Qt.FocusReason.TabFocusReason)
            expect_visible_focus(queue)
            QTest.keyClick(window, Qt.Key.Key_Tab)
            expect_visible_focus(boxes)
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            expect_visible_focus(queue)

            account = control('accountNavigation')
            for _ in range(24):
                if account.property('activeFocus'):
                    break
                QTest.keyClick(window, Qt.Key.Key_Backtab)
                application.processEvents()
            assert account.property('activeFocus'), 'Reverse keyboard navigation missed Account'
            expect_visible_focus(account)

            boxes.forceActiveFocus(Qt.FocusReason.TabFocusReason)
            expect_visible_focus(boxes)
            window.setProperty('height', 800)
            expect_visible_focus(boxes)
            window.setProperty('height', 480)
            expect_visible_focus(boxes)
            assert window.property('currentPage') == 'account'
            """,
        )
        assert https_server.request_count(
            "POST", f"/api/workspace/stations/{station['id']}/boxes"
        ) == 0
