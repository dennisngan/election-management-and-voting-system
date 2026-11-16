"""Build the native Election Desk desktop app and a versioned distribution ZIP."""

import argparse
import hashlib
import json
import platform
import re
import struct
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from scripts.package_windows_release import (
    ReleaseError,
    build_identity,
    package_release,
    source_identity,
)


def _hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _label(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", value)) and not value.endswith(
        "."
    )


def _build_environment(root: Path) -> dict[str, str]:
    if sys.version_info[:2] != (3, 14):
        raise ReleaseError("Use the project's uv-managed Python 3.14 build environment")
    if sys.platform == "win32":
        if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise ReleaseError("Build Windows with native x64 Python, not x86 or ARM64")
        if sys.getwindowsversion().build < 22000:
            raise ReleaseError("Windows 11 is required for the Windows desktop build")
    with (root / "uv.lock").open("rb") as source:
        packages = {item["name"]: item for item in tomllib.load(source)["package"]}
    tools = {}
    for name in ("pyinstaller", "pyinstaller-hooks-contrib", "pyside6", "shiboken6"):
        try:
            installed = version(name)
        except PackageNotFoundError as error:
            raise ReleaseError(f"Missing build dependency: {name}; run uv sync --locked") from error
        if installed != packages.get(name, {}).get("version"):
            raise ReleaseError(f"Installed build dependency differs from uv.lock: {name}")
        tools[name] = installed
    return tools


def _package_macos(
    root: Path,
    output: Path,
    release_version: str,
    architecture: str,
    backend_release: str,
    source: dict,
    tools: dict[str, str],
) -> Path:
    app = output / "Election Desk.app"
    if not (app / "Contents/MacOS/Election Desk").is_file():
        raise ReleaseError("PyInstaller did not produce Election Desk.app")
    if source_identity(root) != source:
        raise ReleaseError("Application/build inputs changed during the native build")
    release = output / "release"
    release.mkdir()
    archive = release / f"Election-Desk-{release_version}-macos-{architecture}.zip"
    # ditto retains the symlinks used by Qt frameworks and PyInstaller app bundles.
    subprocess.run(
        ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)],
        check=True,
    )
    manifest = {
        "format": "election-macos-release-v1",
        "release_version": release_version,
        "platform": f"macos-{architecture}",
        "source": source,
        "build": {
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": architecture,
            },
            "python": platform.python_version(),
            "tools": tools,
            "signing": "PyInstaller ad-hoc signing; not Developer ID signed or notarized",
        },
        "backend_pair": {"backend_release": backend_release, "macos_smoke": "INCOMPLETE"},
        "archive": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": _hash(archive),
        },
    }
    manifest_path = release / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (release / "SHA256SUMS").write_text(
        f"{manifest['archive']['sha256']}  {archive.name}\n"
        f"{_hash(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-name", help="Optional fresh build name; previous builds are retained"
    )
    parser.add_argument(
        "--backend-release", help="Intended backend pair label; smoke stays INCOMPLETE"
    )
    args = parser.parse_args(argv)
    if sys.platform not in {"darwin", "win32"}:
        parser.error("Build on macOS for the .app or Windows 11 x64 for the .exe")
    root = Path(__file__).resolve().parent
    with (root / "pyproject.toml").open("rb") as source_file:
        release_version = tomllib.load(source_file)["project"]["version"]
    if not isinstance(release_version, str) or not _label(release_version):
        parser.error("project.version must be a simple release version")
    if args.run_name and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_name):
        parser.error("run-name must be a simple name without path components")
    if args.backend_release and not _label(args.backend_release):
        parser.error("backend-release must be a simple version or source label")
    icons = root / "src/election/desktop/assets"
    for suffix in ("png", "ico", "icns"):
        if not (icons / f"election-desk.{suffix}").is_file():
            raise ReleaseError(
                f"Missing app icon: src/election/desktop/assets/election-desk.{suffix}"
            )
    tools = _build_environment(root)
    source = source_identity(root)
    backend_release = args.backend_release or "source-" + source["inputs_sha256"]
    target = "macos" if sys.platform == "darwin" else "windows"
    architecture = platform.machine().lower() if target == "macos" else "x64"
    run_name = args.run_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    build_name = f"{release_version}-{architecture}-{run_name}"
    output = root / "dist" / target / build_name
    work = root / "build" / target / build_name
    if output.exists() or work.exists():
        raise ReleaseError("Build name already exists; use a fresh --run-name or omit it")
    output.mkdir(parents=True)
    work.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(output),
            "--workpath",
            str(work),
            str(root / "election-desk.spec"),
        ],
        cwd=root,
        check=True,
    )
    if target == "windows":
        build = build_identity(native_windows_build=True, tool_versions=tools)
        build.update(run_name=run_name, windows_build=sys.getwindowsversion().build)
        archive = package_release(
            output,
            output / "release",
            release_version=release_version,
            backend_release=backend_release,
            source_root=root,
            source=source,
            build=build,
        )
        print(f"Executable: {output / 'Election Desk.exe'}")
    else:
        archive = _package_macos(
            root, output, release_version, architecture, backend_release, source, tools
        )
        print(f"Application: {output / 'Election Desk.app'}")
    print(f"Distribution ZIP: {archive}")
    print(f"Release manifest and SHA256SUMS: {archive.parent}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
