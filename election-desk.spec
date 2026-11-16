"""Shared native Qt Quick GUI build for macOS and Windows."""

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
with (root / "pyproject.toml").open("rb") as source:
    build_version = tomllib.load(source)["project"]["version"]

desktop = root / "src/election/desktop"
qml = desktop / "qml"
if not (qml / "Main.qml").is_file():
    raise SystemExit("The desktop QML source is incomplete")
datas = []
for path in sorted(qml.rglob("*.qml")):
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Refuse non-regular QML input")
    destination = (Path("election/desktop/qml") / path.relative_to(qml).parent).as_posix()
    datas.append((str(path), destination))
datas.append((str(desktop / "assets/election-desk.png"), "election/desktop/assets"))
datas.extend(collect_data_files("tzdata"))

a = Analysis(
    [str(root / "scripts/desktop_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    # QtQuick's built-in hook collects the Qt QML tree, including Material and Dialogs.
    hiddenimports=["PySide6.QtQuick", "PySide6.QtQuickControls2", "PySide6.QtSvg", "tzdata"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
onefile = sys.platform == "win32"
exe = EXE(
    pyz,
    a.scripts,
    a.binaries if onefile else [],
    a.datas if onefile else [],
    [],
    exclude_binaries=not onefile,
    name="Election Desk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(desktop / "assets/election-desk.ico") if sys.platform == "win32" else None,
)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        a.binaries,
        a.datas,
        name="Election Desk.app",
        icon=str(desktop / "assets/election-desk.icns"),
        bundle_identifier="local.election.desk",
        version=build_version,
        info_plist={
            "CFBundleName": "Election Desk",
            "CFBundleDisplayName": "Election Desk",
            "CFBundleShortVersionString": build_version,
            "CFBundleVersion": build_version,
            "NSHighResolutionCapable": True,
        },
    )
