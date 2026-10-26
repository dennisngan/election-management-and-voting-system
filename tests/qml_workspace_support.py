"""Exercise the actual Material window in an isolated, offscreen Qt process."""

import json
import os
import subprocess
import sys
from textwrap import dedent, indent

HEADER = """
import json
import sys
import time
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlProperty
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QSignalSpy, QTest
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
assert engine.rootObjects(), 'The actual Material workspace failed to load'
window = engine.rootObjects()[0]

def wait(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        application.processEvents()
        assert time.monotonic() < deadline, 'Material controls did not reach the expected state'
        time.sleep(.005)
    application.processEvents()

def frame():
    rendered = QSignalSpy(window.frameSwapped)
    window.requestUpdate()
    wait(lambda: rendered.count() > 0)

def control(name):
    item = window.findChild(QQuickItem, name)
    if item is None:
        # Repeater delegates have a visual parent independent of QObject ownership.
        pending = list(window.contentItem().childItems())
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name:
                item = candidate
                break
            pending.extend(candidate.childItems())
    assert item is not None, 'Missing Material control: ' + name
    return item

def _pointer_geometry(item, point=None):
    if not item.property('visible') or item.width() <= 0 or item.height() <= 0:
        return None
    if point is None:
        point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
    if not (0 < point.x() < window.width() and 0 < point.y() < window.height()):
        return None
    clips = []
    ancestor = item.parentItem()
    while ancestor is not None:
        if ancestor.property('clip'):
            local = ancestor.mapFromScene(QPointF(point))
            if not (0 <= local.x() < ancestor.width() and 0 <= local.y() < ancestor.height()):
                return None
            clips.append((local.x(), local.y(), ancestor.width(), ancestor.height(),
                ancestor.property('contentY'), ancestor.property('contentHeight')))
        ancestor = ancestor.parentItem()
    return (point.x(), point.y(), item.width(), item.height(),
        window.width(), window.height(), tuple(clips))

def _wait_in_focus_budget(predicate, deadline, name):
    while True:
        application.processEvents()
        ready = predicate()
        assert time.monotonic() < deadline, 'Material pointer readiness timed out: ' + name
        if ready:
            return
        time.sleep(min(.005, max(0, deadline - time.monotonic())))

def _focus_until(name, deadline):
    item = control(name)
    assert item.property('visible'), 'Control is hidden: ' + name
    rendered = QSignalSpy(window.frameSwapped)
    item.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
    geometry = None
    frame_goal = rendered.count() + 1

    def ready():
        nonlocal geometry, frame_goal
        current = _pointer_geometry(item)
        if not item.property('activeFocus') or current is None:
            geometry = None
            frame_goal = rendered.count() + 1
            window.requestUpdate()
            return False
        if current != geometry:
            geometry = current
            frame_goal = rendered.count() + 1
            window.requestUpdate()
            return False
        return rendered.count() >= frame_goal

    window.requestUpdate()
    _wait_in_focus_budget(ready, deadline, name)
    return item

def focus(name):
    return _focus_until(name, time.monotonic() + 8)

def assert_multiline_inside_border(name):
    field = control(name)
    field.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
    wait(lambda: field.property('activeFocus'))
    background = field.property('background')
    for position in (0, len(field.property('text'))):
        field.setProperty('cursorPosition', position)
        frame()
        cursor = field.property('cursorRectangle')
        inside = field.mapToItem(background, QPointF(cursor.x(), cursor.y()))
        assert inside.y() >= 8, name + ' crosses its visible top border'
        assert inside.y() + cursor.height() <= background.height() - 8
        assert inside.x() >= 8, name + ' crosses its visible left border'
        assert inside.x() + cursor.width() <= background.width() - 8

def click(name):
    deadline = time.monotonic() + 8
    item = _focus_until(name, deadline)
    assert item.property('enabled'), 'Control is disabled: ' + name
    clicked = None
    if item.inherits('QQuickAbstractButton'):
        index = item.metaObject().indexOfSignal('clicked()')
        assert index >= 0, 'Button has no observable clicked signal: ' + name
        clicked = QSignalSpy(item, item.metaObject().method(index))
        assert clicked.isValid(), 'Button clicked signal is unavailable: ' + name
    center = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    assert _pointer_geometry(item, center) is not None, (
        'Control moved outside its viewport: ' + name)
    assert time.monotonic() < deadline, 'Material pointer readiness timed out: ' + name
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    if clicked is not None:
        _wait_in_focus_budget(lambda: clicked.count() > 0, deadline, name)
        assert clicked.count() == 1, 'Pointer did not emit exactly one click: ' + name
    else:
        application.processEvents()
        assert time.monotonic() < deadline, 'Material pointer readiness timed out: ' + name

def click_confirmation(dialog, label):
    wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
    pending = list(dialog.property('footer').childItems())
    buttons = []
    while pending:
        item = pending.pop()
        if item.inherits('QQuickAbstractButton') and item.property('text') == label:
            buttons.append(item)
        pending.extend(item.childItems())
    assert len(buttons) == 1, 'The confirmation button is missing or ambiguous'
    button = buttons[0]
    center = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    wait(lambda: not dialog.property('visible'))

def enter(name, text):
    item = focus(name)
    assert QMetaObject.invokeMethod(item, 'selectAll'), 'Text control cannot select its contents'
    QCoreApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, 0,
        Qt.KeyboardModifier.NoModifier, text))
    QCoreApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyRelease, 0,
        Qt.KeyboardModifier.NoModifier, ''))
    application.processEvents()
    assert item.property('text') == text, 'Text entry did not reach the visible field'

def choose(name, index):
    item = focus(name)
    QTest.keyClick(window, Qt.Key.Key_Space)
    application.processEvents()
    QTest.keyClick(window, Qt.Key.Key_Home)
    for position in range(index):
        QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    popup_visible = QQmlProperty(item, 'popup.visible')
    assert popup_visible.isValid(), 'Selection control has no observable popup state'
    wait(lambda: not popup_visible.read())
    frame()

try:
    controller.signIn(setup['server'], setup['username'], setup['password'])
    wait(lambda: controller.property('state')['phase'] == 'workspace')
    controller.setLocale(setup.get('locale', 'tc'))
    workspace = controller.property('workspace')
    workspace.open()
    wait(lambda: not workspace.property('state')['busy'])
    workspace.selectStation(setup['station_id'])
    wait(lambda: not workspace.property('state')['busy'])
    frame()
"""

FOOTER = """
finally:
    window.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    controller.shutdown()
"""


def run_workspace_qml(setup: dict, scenario: str, *, timeout: int = 45) -> None:
    script = HEADER + indent(dedent(scenario), "    ") + FOOTER
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(setup)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
