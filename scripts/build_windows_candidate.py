"""Build a fresh Windows11x64 onedir package from the reviewed locked environment."""

import argparse
import platform
import re
import struct
import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from package_windows_release import (
    ReleaseError,
    build_identity,
    package_release,
    source_identity,
)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build this candidate only on the actual Windows11x64 host")
    if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Use a native x64 Windows Python, not x86 or ARM64")
    if sys.getwindowsversion().build < 22000:
        raise SystemExit("Windows11 is required for this delivery candidate")
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Use the project's uv-managed Python3.14 build environment")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument(
        "--release-version", help="Versioned ZIP label; defaults to project version",
    )
    parser.add_argument(
        "--backend-release", help="Intended backend pair label; Windows smoke stays INCOMPLETE",
    )
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_name) is None:
        parser.error("run-name must be a new simple name, with no path components")
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    with (root / "uv.lock").open("rb") as source:
        locked = tomllib.load(source)
    try:
        # packaging is already a locked PyInstaller dependency; do not add/install it here.
        from packaging.requirements import Requirement
    except ImportError as error:
        raise SystemExit(
            "The reviewed locked Windows build environment is not provisioned"
        ) from error
    requirements = [
        Requirement(value)
        for value in project["dependency-groups"].get("gui-validation", [])
        if isinstance(value, str)
    ]
    if not any(
        requirement.name.lower() == "pyinstaller"
        and (requirement.marker is None or requirement.marker.evaluate())
        for requirement in requirements
    ):
        raise SystemExit("Select Windows PyInstaller dependencies in the reviewed lock first")
    packages = {package["name"]: package for package in locked["package"]}
    if not any("win_amd64" in wheel["url"] for wheel in packages["pyinstaller"].get("wheels", [])):
        raise SystemExit("The lock does not yet pin a Windowsx64 PyInstaller wheel")
    tool_versions = {}
    for name in ("pyinstaller", "pyinstaller-hooks-contrib", "pyside6", "shiboken6"):
        try:
            installed = version(name)
        except PackageNotFoundError as error:
            raise SystemExit(f"Missing locked build dependency: {name}") from error
        if installed != packages[name]["version"]:
            raise SystemExit(f"Installed build dependency differs from uv.lock: {name}")
        tool_versions[name] = installed
    qml = root / "src/election/desktop/qml"
    qml_files = sorted(qml.rglob("*.qml"))
    if not (qml / "Main.qml").is_file() or not qml_files:
        raise SystemExit("The tracked desktop QML source is incomplete")
    for path in qml_files:
        if path.is_symlink() or not path.is_file():
            raise SystemExit("Refuse non-regular QML input")
    source = source_identity(root)
    release_version = args.release_version or project["project"]["version"]
    backend_release = args.backend_release or "source-" + source["inputs_sha256"]
    build_root = root / ".runtime" / ("windows-package-" + args.run_name)
    build_root.mkdir(parents=True, exist_ok=False)
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
        "Election Desk",
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root / "spec"),
        "--paths",
        str(root / "src"),
    ]
    for path in qml_files:
        # PyInstaller6.22.3 SourceDestAction recognizes the Windows drive separately.
        destination = (Path("election/desktop/qml") / path.relative_to(qml).parent).as_posix()
        command.extend(["--add-data", f"{path}:{destination}"])
    command.append(str(entry))
    # No project-root data collection, server entry, private TLS, .env or journals.
    # Installed locked PySide6 hooks collect Qt runtime/QML/network dependencies;
    # their actual Windows result still requires artifact and native smoke inspection.
    subprocess.run(command, cwd=root, check=True)
    executable = build_root / "dist/Election Desk/Election Desk.exe"
    if not executable.is_file():
        raise SystemExit("PyInstaller did not produce the expected onedir executable")
    print(executable)
    build = build_identity(native_windows_build=True, tool_versions=tool_versions)
    build.update(run_name=args.run_name, windows_build=sys.getwindowsversion().build)
    try:
        archive = package_release(
            executable.parent, build_root / "release", release_version=release_version,
            backend_release=backend_release, source_root=root, source=source, build=build,
        )
    except (OSError, ReleaseError):
        raise SystemExit(
            "Release packaging failed; retain this build for review and use a fresh run name"
        ) from None
    print(archive)
    print("Build artifact only; Windows smoke/DACL/scaling/printer acceptance remains incomplete")


if __name__ == "__main__":
    main()
