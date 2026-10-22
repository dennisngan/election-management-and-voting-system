"""Build a local native bundle so Computer can inspect the macOS development client."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "This helper is for macOS GUI validation; it does not build the Windows release"
        )
    root = Path(__file__).resolve().parents[1]
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    entry = runtime / "desktop-entry.py"
    entry.write_text("from election.desktop.__main__ import main\nmain()\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--windowed",
            "--onedir",
            "--noconfirm",
            "--name",
            "Election Desk",
            "--osx-bundle-identifier",
            "org.electionprototype.native",
            "--distpath",
            str(runtime / "native"),
            "--workpath",
            str(runtime / "pyinstaller-work"),
            "--specpath",
            str(runtime),
            "--paths",
            str(root / "src"),
            "--add-data",
            f"{root / 'src/election/desktop/qml'}:election/desktop/qml",
            str(entry),
        ],
        cwd=root,
        check=True,
    )
    print(runtime / "native/Election Desk.app")


if __name__ == "__main__":
    main()
