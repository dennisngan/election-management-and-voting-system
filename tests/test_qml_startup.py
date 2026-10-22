"""Load the real Material QML window in Qt, including inactive feature pages."""

import os
import subprocess
import sys

from tests.desktop_support import HttpsServer


def test_material_workspace_qml_loads_with_all_feature_components(
    https_server: HttpsServer,
) -> None:
    script = """
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
import election.desktop.__main__ as desktop_entry
from election.desktop.controller import DesktopController

QQuickStyle.setStyle('Material')
application = QGuiApplication([])
application.styleHints().setTabFocusBehavior(Qt.TabFocusBehavior.TabFocusAllControls)
controller = DesktopController(sys.argv[1], '.runtime/tls/ca.pem')
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty('controller', controller)
engine.load(QUrl.fromLocalFile(str(Path(desktop_entry.__file__).with_name('qml') / 'Main.qml')))
assert engine.rootObjects(), 'The Material workspace did not create its native window'
window = engine.rootObjects()[0]
assert window.property('visible') is True
assert window.property('currentPage') == 'account'
window.close()
controller.shutdown()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, https_server.url],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
