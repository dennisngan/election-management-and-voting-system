"""Build a fresh Windows 11 x64 onefile package from the reviewed locked environment."""

from __future__ import annotations

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
from typing import Any

from package_windows_release import (
    ReleaseError,
    build_identity,
    package_release,
    source_identity,
)

EXPECTED_PYTHON = (3, 14)
MIN_WINDOWS_BUILD = 22000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

RUN_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")

REQUIRED_BUILD_DEPS = (
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pyside6",
    "shiboken6",
)
SPEC_FILENAME = "election-desk.spec"
EXECUTABLE_NAME = "Election Desk.exe"


def parse_args() -> argparse.Namespace:
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

    if RUN_NAME_PATTERN.fullmatch(args.run_name) is None:
        parser.error("--run-name must match [A-Za-z0-9][A-Za-z0-9_-]{0,79} with no path separators")
    for flag_name, value in (
        ("--release-version", args.release_version),
        ("--backend-release", args.backend_release),
    ):
        if value is not None and LABEL_PATTERN.fullmatch(value) is None:
            parser.error(f"{flag_name} must be a simple label with no path separators or whitespace")

    return args


def validate_host_environment() -> int:
    """Ensure the script runs on native Windows 11 x64 with the expected Python version."""
    if sys.platform != "win32":
        raise SystemExit("Build this candidate only on an actual Windows 11 x64 host")
    if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Use a native x64 Windows Python, not x86 or ARM64")

    windows_build = sys.getwindowsversion().build
    if windows_build < MIN_WINDOWS_BUILD:
        raise SystemExit(f"Windows 11 (build >= {MIN_WINDOWS_BUILD}) is required for this candidate")
    if sys.version_info[:2] != EXPECTED_PYTHON:
        expected = ".".join(map(str, EXPECTED_PYTHON))
        raise SystemExit(f"Use the project's uv-managed Python {expected} build environment")

    return windows_build


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Missing required project file: {path}")
    with path.open("rb") as fp:
        return tomllib.load(fp)


def verify_locked_dependencies(locked: dict[str, Any]) -> dict[str, str]:
    """Verify uv.lock pins a win_amd64 PyInstaller wheel and matches installed build tools."""
    packages = {pkg["name"]: pkg for pkg in locked.get("package", []) if "name" in pkg}

    pyinstaller_wheels = packages.get("pyinstaller", {}).get("wheels", [])
    has_win64_wheel = any(
        "win_amd64" in (wheel.get("url") or wheel.get("filename") or "")
        for wheel in pyinstaller_wheels
    )
    if not has_win64_wheel:
        raise SystemExit("uv.lock does not pin a Windows x64 (win_amd64) PyInstaller wheel")

    tool_versions: dict[str, str] = {}
    for name in REQUIRED_BUILD_DEPS:
        locked_pkg = packages.get(name)
        if locked_pkg is None or "version" not in locked_pkg:
            raise SystemExit(f"Missing dependency entry in uv.lock: {name}")
        try:
            installed = version(name)
        except PackageNotFoundError as exc:
            raise SystemExit(f"Missing locked build dependency in environment: {name}") from exc
        if installed != locked_pkg["version"]:
            raise SystemExit(
                f"Installed version of {name} ({installed}) differs from uv.lock ({locked_pkg['version']})"
            )
        tool_versions[name] = installed

    return tool_versions


def assert_safe_directory(path: Path) -> None:
    """Reject symlinks, Windows junctions/reparse points, and non-directories."""
    details = path.lstat()
    is_reparse_point = bool(getattr(details, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    if path.is_symlink() or is_reparse_point or not stat.S_ISDIR(details.st_mode):
        raise SystemExit(f"Refusing redirected or non-directory build root: {path}")


def prepare_build_root(repo_root: Path, run_name: str) -> Path:
    """Safely create an isolated build directory under .runtime/."""
    runtime_root = repo_root / ".runtime"
    if runtime_root.exists() or runtime_root.is_symlink():
        assert_safe_directory(runtime_root)
    runtime_root.mkdir(mode=0o700, exist_ok=True)
    assert_safe_directory(runtime_root)

    build_root = runtime_root / f"windows-package-{run_name}"
    try:
        build_root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(
            f"Build directory already exists (choose a fresh --run-name): {build_root}"
        ) from exc
    return build_root


def run_pyinstaller(repo_root: Path, build_root: Path) -> Path:
    spec_path = repo_root / SPEC_FILENAME
    if not spec_path.is_file():
        raise SystemExit(f"Missing PyInstaller spec file: {spec_path}")

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
        str(spec_path),
    ]
    try:
        subprocess.run(command, cwd=repo_root, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"PyInstaller failed with exit code {exc.returncode}; inspect {build_root}"
        ) from exc

    executable = build_root / "dist" / EXECUTABLE_NAME
    if not executable.is_file():
        raise SystemExit(f"PyInstaller did not produce expected executable: {executable}")
    return executable


def main() -> None:
    args = parse_args()
    windows_build = validate_host_environment()

    repo_root = Path(__file__).resolve().parents[1]
    project = load_toml(repo_root / "pyproject.toml")
    locked = load_toml(repo_root / "uv.lock")
    tool_versions = verify_locked_dependencies(locked)

    src_identity = source_identity(repo_root)
    release_version = args.release_version or project["project"]["version"]
    backend_release = args.backend_release or f"source-{src_identity['inputs_sha256']}"

    build_root = prepare_build_root(repo_root, args.run_name)
    executable = run_pyinstaller(repo_root, build_root)
    print(executable)

    build = build_identity(native_windows_build=True, tool_versions=tool_versions)
    build.update(run_name=args.run_name, windows_build=windows_build)

    try:
        archive = package_release(
            executable.parent,
            build_root / "release",
            release_version=release_version,
            backend_release=backend_release,
            source_root=repo_root,
            source=src_identity,
            build=build,
        )
    except (OSError, ReleaseError) as exc:
        raise SystemExit(
            f"Release packaging failed ({exc}); retain {build_root} for review and use a fresh run name"
        ) from None

    print(archive)
    print("Build artifact only; Windows smoke/DACL/scaling/printer acceptance remains incomplete")


if __name__ == "__main__":
    main()
