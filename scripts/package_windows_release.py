"""Package a standalone Windows onefile executable; packaging does not prove Windows smoke."""

import argparse
import hashlib
import json
import platform
import re
import stat
import subprocess
from pathlib import Path
from typing import IO, Any
from zipfile import ZIP_DEFLATED, ZipFile


class ReleaseError(ValueError):
    """A safe packaging failure without local paths, contents or connection settings."""


def _regular_object(path: Path) -> bool:
    details = path.lstat()
    if getattr(details, "st_file_attributes", 0) & 0x400:
        raise ReleaseError("Refuse symbolic links, junctions and other reparse inputs")
    if not (stat.S_ISREG(details.st_mode) or stat.S_ISDIR(details.st_mode)):
        raise ReleaseError("Refuse nonregular release input")
    return stat.S_ISREG(details.st_mode)


def _tree(root: Path) -> list[Path]:
    if _regular_object(root):
        raise ReleaseError("Release input must be a directory")
    paths = sorted(root.rglob("*"))
    for path in paths:
        _regular_object(path)
    return paths


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _stream_hash(source: IO[bytes]) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def _hash(path: Path) -> str:
    with path.open("rb") as source:
        return _stream_hash(source)


def source_identity(root: Path) -> dict[str, Any]:
    """Identify only public application/build inputs, never repository runtime state."""
    root = root.absolute()
    if _regular_object(root):
        raise ReleaseError("Source input must be a directory")
    inputs = [
        root / name
        for name in (
            "pyproject.toml",
            "uv.lock",
            "build.py",
            "election-desk.spec",
            "scripts/desktop_entry.py",
            "scripts/generate_app_icons.py",
            "scripts/build_windows_candidate.py",
            "scripts/package_windows_release.py",
            "src/election/desktop/assets/election-desk.png",
            "src/election/desktop/assets/election-desk.ico",
            "src/election/desktop/assets/election-desk.icns",
        )
    ]
    inputs.extend(
        path
        for path in _tree(root / "src/election")
        if path.suffix in {".py", ".qml"}
        and not any(
            part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts
        )
    )
    for path in inputs:
        for part in [path, *path.relative_to(root).parents]:
            if part == Path("."):
                continue
            _regular_object(part if part.is_absolute() else root / part)
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _hash(path),
        }
        for path in sorted(inputs)
    ]
    revision = "UNAVAILABLE"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        candidate = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", candidate):
            revision = candidate
    except OSError:
        pass
    return {
        "git_head": revision,
        "scope": (
            "Application Python/QML/icons, native build/spec/package helpers, "
            "pyproject.toml and uv.lock"
        ),
        "inputs_sha256": hashlib.sha256(_json(files)).hexdigest(),
        "lock_sha256": next(row["sha256"] for row in files if row["path"] == "uv.lock"),
        "files": files,
    }


def build_identity(
    *, native_windows_build: bool = False, tool_versions: dict[str, str] | None = None
) -> dict[str, Any]:
    """Record host/tool facts separately from unavailable native acceptance evidence."""
    return {
        "native_windows_build": "Windows_x64" if native_windows_build else "NOT_VERIFIED",
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": platform.python_version(),
        "tools": tool_versions or {},
    }


def package_release(
    runtime: Path,
    output: Path,
    *,
    release_version: str,
    backend_release: str,
    source_root: Path,
    source: dict[str, Any] | None = None,
    build: dict[str, Any] | None = None,
) -> Path:
    """Publish a fresh versioned ZIP, manifest and checksum without changing client state."""
    for label in (release_version, backend_release):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", label) is None or label.endswith("."):
            raise ReleaseError("Release labels must be simple version or source labels")
    current_source = source_identity(source_root)
    if source is not None and current_source != source:
        raise ReleaseError("Application/build inputs changed during the native build")
    source = current_source
    runtime, output = runtime.absolute(), output.absolute()
    if output == runtime:
        raise ReleaseError("Keep release output separate from the input directory")
    entries = _tree(runtime)
    executable = runtime / "Election Desk.exe"
    # Accept only the onefile artifact, so sidecar runtime or private files cannot ship.
    if entries != [executable] or not executable.is_file():
        raise ReleaseError("Input directory must contain only the onefile Election Desk.exe")
    paths = [executable]
    files = [
        {
            "path": path.relative_to(runtime).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _hash(path),
        }
        for path in paths
    ]
    identity = {
        "format": "election-windows-release-v1",
        "release_version": release_version,
        "platform": "Windows11_x64",
        "bundle_mode": "onefile",
        "source": source,
        "build": build or build_identity(),
        "backend_pair": {"backend_release": backend_release, "windows_smoke": "INCOMPLETE"},
        "acceptance": {
            "clean_client": "INCOMPLETE",
            "journal_upgrade": "INCOMPLETE",
            "dacl_scaling_languages_printer": "INCOMPLETE",
        },
        "runtime_files": files,
        "runtime_empty_directories": [],
    }
    instructions = f"""Election Desk {release_version} — Windows 11 native x64

Extract Election Desk.exe to a new versioned installation folder, then launch outside
the source checkout. The EXE includes its runtime; no _internal folder is needed.
It unpacks support files to a temporary directory on launch, which can take a moment.
Client PCs need no separate Python, MySQL or Docker installation. This package contains
no deployment-specific server or CA.

Configure the stable private-network HTTPS endpoint and public CA separately:
  & ".\\Election Desk.exe" `
    --server "https://<trusted-server>:8443" `
    --ca "C:\\ElectionClientTrust\\public-ca.pem"
The existing ELECTION_SERVER_URL and ELECTION_CA_FILE environment options also apply.
Keep certificate name, trust and expiry failures visible; never bypass verification.

Backend pair label: {backend_release}
Windows smoke: INCOMPLETE. A ZIP alone is not a verified release pair. Record the exact
backend source/image identity and actual Windows build/clean-client smoke evidence before
declaring this pair tested. Verify sign-in/password change, save/read and PDF/CSV export.

Coordinate backend/client upgrades in one maintenance window. Resolve uncertain saves,
then close clients. Replace the executable and preserve the configured
stable endpoint, public CA and each user's private recovery journal. The normal journal
lives in the per-user application-data operational-commands directory, outside installed
runtime folders; preserve any ELECTION_CLIENT_STATE_DIR override separately. Never copy a
user journal into this package or blindly replay an uncertain save after replacement.
Check uncertain outcomes explicitly and retain their original request identities.

Actual Windows clean-client, journal-upgrade, DACL, scaling, languages and printer
acceptance remain INCOMPLETE until their evidence is recorded separately.
"""
    output.mkdir(parents=True, exist_ok=False)
    archive = output / f"Election-Desk-{release_version}-windows-x64.zip"
    prefix = f"Election-Desk-{release_version}"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as release:
        for path in paths:
            release.write(path, f"{prefix}/{path.relative_to(runtime).as_posix()}")
        release.writestr(f"{prefix}/RELEASE.json", _json(identity))
        release.writestr(f"{prefix}/README.txt", instructions)
    # Verify delivered bytes against the recorded input map before publishing the receipt.
    with ZipFile(archive) as release:
        for row in files:
            info = release.getinfo(f"{prefix}/{row['path']}")
            with release.open(info) as delivered:
                actual = _stream_hash(delivered)
            if info.file_size != row["size_bytes"] or actual != row["sha256"]:
                raise ReleaseError("Runtime changed during packaging; receipt not published")
    manifest: dict[str, Any] = {
        **identity,
        "archive": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": _hash(archive),
        },
    }
    manifest_path = output / "release-manifest.json"
    manifest_path.write_bytes(_json(manifest))
    (output / "SHA256SUMS").write_text(
        f"{manifest['archive']['sha256']}  {archive.name}\n"
        f"{_hash(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        required=True,
        help="Directory containing only Election Desk.exe",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--backend-release", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        archive = package_release(
            args.runtime_dir,
            args.output_dir,
            release_version=args.release_version,
            backend_release=args.backend_release,
            source_root=args.source_root,
        )
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
    except OSError:
        raise SystemExit("Release packaging failed; no Windows acceptance is claimed") from None
    print(archive)
    print("Windows smoke/clean-client acceptance: INCOMPLETE")


if __name__ == "__main__":
    main()
