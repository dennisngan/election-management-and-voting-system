"""Build a fresh Windows11x64 onefile package from the reviewed locked environment."""

import argparse
import platform
import re
import stat
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
        "--release-version",
        help="Versioned ZIP label; defaults to project version",
    )
    parser.add_argument(
        "--backend-release",
        help="Intended backend pair label; Windows smoke stays INCOMPLETE",
    )
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_name) is None:
        parser.error("run-name must be a new simple name, with no path components")
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    with (root / "uv.lock").open("rb") as source:
        locked = tomllib.load(source)
    packages = {package["name"]: package for package in locked["package"]}
    if not any(
        "win_amd64" in wheel["url"] for wheel in packages.get("pyinstaller", {}).get("wheels", [])
    ):
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
    source = source_identity(root)
    release_version = args.release_version or project["project"]["version"]
    backend_release = args.backend_release or "source-" + source["inputs_sha256"]
    runtime_root = root / ".runtime"
    runtime_root.mkdir(mode=0o700, exist_ok=True)
    details = runtime_root.lstat()
    if (
        runtime_root.is_symlink()
        or getattr(details, "st_file_attributes", 0) & 0x400
        or not stat.S_ISDIR(details.st_mode)
    ):
        raise SystemExit("Refuse a redirected or non-directory .runtime build root")
    build_root = runtime_root / ("windows-package-" + args.run_name)
    build_root.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        str(root / "election-desk.spec"),
    ]
    subprocess.run(command, cwd=root, check=True)
    executable = build_root / "dist/Election Desk.exe"
    if not executable.is_file():
        raise SystemExit("PyInstaller did not produce the expected onefile executable")
    print(executable)
    build = build_identity(native_windows_build=True, tool_versions=tool_versions)
    build.update(run_name=args.run_name, windows_build=sys.getwindowsversion().build)
    try:
        archive = package_release(
            executable.parent,
            build_root / "release",
            release_version=release_version,
            backend_release=backend_release,
            source_root=root,
            source=source,
            build=build,
        )
    except OSError, ReleaseError:
        raise SystemExit(
            "Release packaging failed; retain this build for review and use a fresh run name"
        ) from None
    print(archive)
    print("Build artifact only; Windows smoke/DACL/scaling/printer acceptance remains incomplete")


if __name__ == "__main__":
    main()
