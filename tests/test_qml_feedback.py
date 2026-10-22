"""Real Qt feedback preserves typing focus for background updates."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_feedback_scenario(scenario: str) -> None:
    script = """
import sys
from pathlib import Path
from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

QQuickStyle.setStyle('Material')
application = QGuiApplication([])
engine = QQmlApplicationEngine()
source = b'''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: window
    visible: true
    width: 480
    height: 260
    property int revealCount: 0
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        TextField {
            objectName: "editableField"
            Layout.fillWidth: true
            text: "unsaved observation note"
        }
        FormNotice {
            objectName: "feedback"
            words: ({background: "A newer revision is available",
                saved: "Saved", invalid: "Invalid"})
            onReveal: control => window.revealCount += 1
        }
    }
}
'''
qml_directory = Path(sys.argv[2])
engine.loadData(source, QUrl.fromLocalFile(str(qml_directory / 'FeedbackHarness.qml')))
assert engine.rootObjects(), 'The actual FormNotice did not load'
window = engine.rootObjects()[0]
field = window.findChild(QObject, 'editableField')
feedback = window.findChild(QObject, 'feedback')
assert field is not None and feedback is not None

def drain():
    loop = QEventLoop()
    QTimer.singleShot(30, loop.quit)
    loop.exec()

window.requestActivate()
drain()
field.forceActiveFocus()
drain()
assert field.property('activeFocus') is True, 'The text field did not receive initial focus'
scenario = sys.argv[1]
if scenario == 'background':
    feedback.setProperty('autoReveal', False)
    feedback.setProperty('notice', 'background')
elif scenario == 'success':
    feedback.setProperty('notice', 'saved')
else:
    feedback.setProperty('error', 'invalid')
drain()
assert field.property('text') == 'unsaved observation note'
if scenario == 'background':
    assert field.property('activeFocus') is True, 'Background feedback stole typing focus'
    assert window.property('revealCount') == 0, 'Background feedback requested a scroll reveal'
else:
    assert feedback.property('activeFocus') is True, 'User-action feedback did not receive focus'
    assert window.property('revealCount') == 1, 'User-action feedback did not request reveal'
window.close()
"""
    qml_directory = Path(__file__).resolve().parents[1] / "src/election/desktop/qml"
    result = subprocess.run(
        [sys.executable, "-c", script, scenario, str(qml_directory)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_background_feedback_keeps_typing_focus_and_does_not_request_scroll() -> None:
    run_feedback_scenario("background")


@pytest.mark.parametrize("scenario", ["success", "error"])
def test_user_action_feedback_still_receives_focus_and_requests_reveal(scenario: str) -> None:
    run_feedback_scenario(scenario)
