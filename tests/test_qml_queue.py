"""Real queue QML controls load, expose role actions and route keyboard/report events."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.queue_support import (
    READY_PASSWORD,
    QueueClock,
    active_queue_stations,
    observation,
    queue_account,
    queue_client,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize(
    ("role", "locale"),
    [
        ("polling_officer", "tc"),
        ("polling_officer", "sc"),
        ("polling_officer", "en"),
        ("counting_officer", "tc"),
        ("supervisor", "tc"),
    ],
)
def test_queue_qml_preserves_current_provenance_and_exposes_working_role_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer, role: str, locale: str
) -> None:
    station_id = active_queue_stations(admin)[0]["station"]["id"]
    writer = queue_account(admin, [station_id])
    clock = QueueClock()
    clock.value += timedelta(minutes=10)
    https_server.clock.value = clock.value
    with queue_client(database_url, writer, clock) as client:
        path = f"/api/workspace/stations/{station_id}/queue"
        current = client.post(
            path,
            json=observation(
                clock, band="60_90", event_at=(clock.value - timedelta(minutes=5)).isoformat()
            ),
        )
        assert current.status_code == 201
        backdated = client.post(
            path,
            json=observation(
                clock,
                expected_revision=1,
                event_at=(clock.value - timedelta(minutes=10)).isoformat(),
            ),
        )
        assert backdated.status_code == 201
    viewer = writer
    if role != "polling_officer":
        viewer = queue_account(admin, [station_id], role)
        with queue_client(database_url, viewer, clock):
            pass
    setup = {
        "server": https_server.url,
        "username": viewer["username"],
        "password": READY_PASSWORD,
        "station_id": station_id,
        "role": role,
        "locale": locale,
    }
    script = """
import json
import sys
import time
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
import election.desktop.__main__ as desktop_entry
from election.desktop.controller import DesktopController

setup = json.loads(sys.argv[1])
QQuickStyle.setStyle('Material')
application = QGuiApplication([])
application.styleHints().setTabFocusBehavior(Qt.TabFocusBehavior.TabFocusAllControls)
controller = DesktopController(setup['server'], '.runtime/tls/ca.pem')
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty('controller', controller)
engine.load(QUrl.fromLocalFile(str(Path(desktop_entry.__file__).with_name('qml') / 'Main.qml')))
assert engine.rootObjects(), 'Material QML failed to load'
window = engine.rootObjects()[0]

def wait(predicate):
    deadline = time.monotonic() + 8
    while not predicate():
        application.processEvents()
        assert time.monotonic() < deadline, 'Queue QML did not reach the expected state'
        time.sleep(.005)
    application.processEvents()

try:
    controller.signIn(setup['server'], setup['username'], setup['password'])
    wait(lambda: controller.property('state')['phase'] == 'workspace')
    controller.setLocale(setup['locale'])
    queue = controller.property('queue')
    queue.open(setup['station_id'], setup['role'])
    wait(lambda: not queue.property('state')['busy'])
    window.setProperty('currentPage', 'queue')
    application.processEvents()
    current_revision = window.findChild(QQuickItem, 'queueCurrentRevision')
    assert current_revision.property('value') == '1', (
        'Backdated history changed observation provenance'
    )
    assert queue.property('state')['latest_revision'] == 2
    reload_button = window.findChild(QQuickItem, 'queueReload')
    assert reload_button.property('visible') is True, 'All readers need to reload reviewed history'
    save = window.findChild(QQuickItem, 'queueSave')
    reason = window.findChild(QQuickItem, 'queueReason')
    event = window.findChild(QQuickItem, 'queueEventTime')
    writable = setup['role'] == 'polling_officer'
    assert save.property('visible') is writable
    assert event.property('visible') is writable
    if writable:
        queue.setField('reason', '保留輸入 Preserve input')
        queue.setField('event_time', '2026-11-15 08:10')
        application.processEvents()
        reason.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
        wait(lambda: reason.property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Tab)
        wait(lambda: save.property('activeFocus'))
        assert reason.property('text') == '保留輸入 Preserve input'
        QTest.keyClick(window, Qt.Key.Key_Backtab)
        wait(lambda: reason.property('activeFocus'))
    preview = window.findChild(QQuickItem, 'queuePreview')
    assert preview.property('visible') is True
    preview.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
    wait(lambda: preview.property('activeFocus'))
    center = preview.mapToScene(QPointF(preview.width() / 2, preview.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    wait(lambda: bool(queue.property('state').get('report_text')))
    report = window.findChild(QObject, 'queueReportPreview')
    assert report.property('text') == queue.property('state')['report_text']
    assert '2026-11-15 08:05:00 HKT' in report.property('text')
    assert queue.property('state')['report']['locale'] == setup['locale']
    if writable:
        assert queue.property('state')['forms']['reason'] == '保留輸入 Preserve input'
        assert queue.property('state')['dirty'] is True
finally:
    window.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    controller.shutdown()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(setup)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
    )
    assert result.returncode == 0, result.stderr
