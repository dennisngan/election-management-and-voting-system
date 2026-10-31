"""Build a fresh local macOS bundle for native validation of the locked desktop."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "This helper builds macOS validation bundles; use the Windows builder on Windows"
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument(
        "--peer", action="store_true", help="Build a separately identified second client"
    )
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.run_name) is None:
        parser.error("run-name must use lowercase letters, digits and hyphens only")
    root = Path(__file__).resolve().parents[1]
    qml = root / "src/election/desktop/qml"
    inputs = sorted(qml.rglob("*.qml"))
    if not (qml / "Main.qml").is_file() or not inputs:
        raise SystemExit("Desktop QML source is incomplete")
    if any(path.is_symlink() or not path.is_file() for path in inputs):
        raise SystemExit("Refuse non-regular QML inputs")
    suffix = "-peer" if args.peer else ""
    build_root = root / ".runtime" / ("macos-package-" + args.run_name + suffix)
    build_root.mkdir(parents=True, mode=0o700, exist_ok=False)
    name = "Election Desk Peer" if args.peer else "Election Desk"
    bundle = "org.electionprototype.native." + args.run_name + suffix
    entry = build_root / "desktop-entry.py"
    with entry.open("x", encoding="utf-8") as output:
        output.write("from election.desktop.__main__ import main\nmain()\n")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--windowed",
        "--onedir",
        "--noconfirm",
        "--name",
        name,
        "--osx-bundle-identifier",
        bundle,
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root / "spec"),
        "--paths",
        str(root / "src"),
    ]
    for path in inputs:
        destination = (Path("election/desktop/qml") / path.relative_to(qml).parent).as_posix()
        command.extend(["--add-data", f"{path}:{destination}"])
    command.append(str(entry))
    subprocess.run(command, cwd=root, check=True)
    app = build_root / "dist" / (name + ".app")
    if not app.is_dir():
        raise SystemExit("PyInstaller did not produce the expected validation bundle")
    print(app)
    print("macOS validation artifact; actual Windows verification remains incomplete")


if __name__ == "__main__":
    main()
