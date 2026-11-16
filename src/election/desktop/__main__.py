import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from election import APP_NAME, APP_TITLE
from election.desktop.controller import DesktopController


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop client")
    parser.add_argument(
        "--server", default=os.getenv("ELECTION_SERVER_URL", "https://localhost:8443")
    )
    parser.add_argument("--ca", default=os.getenv("ELECTION_CA_FILE", ""))
    parser.add_argument(
        "--window-size",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        help="Initial window size in logical pixels",
    )
    args = parser.parse_args()
    if args.window_size and (args.window_size[0] < 900 or args.window_size[1] < 480):
        parser.error("The initial window must be at least 900 by 480 logical pixels")
    QQuickStyle.setStyle("Material")
    app = QGuiApplication(sys.argv[:1])
    app.styleHints().setTabFocusBehavior(Qt.TabFocusBehavior.TabFocusAllControls)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Election System Project")
    app.setApplicationDisplayName(APP_TITLE)
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "election-desk.png")))
    controller = DesktopController(args.server, args.ca)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        size = args.window_size or (1280, 800)
        engine.setInitialProperties(
            {"width": min(size[0], available.width()), "height": min(size[1], available.height())}
        )
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Main.qml")))
    if not engine.rootObjects():
        raise SystemExit("The desktop interface could not be loaded")
    app.aboutToQuit.connect(controller.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
