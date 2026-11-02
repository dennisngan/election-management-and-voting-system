"""Public ZIP packaging checks; synthetic runtimes do not prove Windows acceptance."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


def release_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    (source / "src/election/desktop/qml").mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "src/election/__init__.py").write_bytes(b"")
    (source / "src/election/desktop/qml/Main.qml").write_text("Window {}\n")
    (source / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    (source / "uv.lock").write_bytes(b"locked test dependencies\n")
    for name in ("build_windows_candidate.py", "package_windows_release.py"):
        (source / "scripts" / name).write_text("# synthetic build input\n")
    runtime = tmp_path / "Election Desk"
    (runtime / "_internal/PySide6/plugins").mkdir(parents=True)
    (runtime / "Election Desk.exe").write_bytes(b"synthetic executable")
    (runtime / "_internal/PySide6/plugins/Qt6Quick.dll").write_bytes(b"synthetic Qt runtime")
    (runtime / "_internal/base_library.zip").write_bytes(b"synthetic Python runtime")
    return source, runtime, tmp_path / "release"


def package(
    source: Path, runtime: Path, output: Path, *,
    release_version: str = "1.2.3", backend_release: str = "backend-1.2.3",
) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts/package_windows_release.py"
    return subprocess.run(
        [
            sys.executable, str(script), "--source-root", str(source),
            "--runtime-dir", str(runtime), "--output-dir", str(output),
            "--release-version", release_version, "--backend-release", backend_release,
        ],
        capture_output=True, text=True, check=False,
    )


def test_release_zip_preserves_complete_runtime_and_identifies_unverified_pair(
    tmp_path: Path,
) -> None:
    source, runtime, output = release_inputs(tmp_path)

    result = package(source, runtime, output)

    assert result.returncode == 0, result.stderr
    archive = output / "Election-Desk-1.2.3-windows-x64.zip"
    manifest = json.loads((output / "release-manifest.json").read_text())
    with ZipFile(archive) as release:
        assert set(release.namelist()) == {
            "Election-Desk-1.2.3/Election Desk/Election Desk.exe",
            "Election-Desk-1.2.3/Election Desk/_internal/PySide6/plugins/Qt6Quick.dll",
            "Election-Desk-1.2.3/Election Desk/_internal/base_library.zip",
            "Election-Desk-1.2.3/RELEASE.json",
            "Election-Desk-1.2.3/README.txt",
        }
        assert release.read(
            "Election-Desk-1.2.3/Election Desk/_internal/PySide6/plugins/Qt6Quick.dll"
        ) == b"synthetic Qt runtime"
        identity = json.loads(release.read("Election-Desk-1.2.3/RELEASE.json"))
        instructions = release.read("Election-Desk-1.2.3/README.txt").decode()
    assert identity["backend_pair"] == {
        "backend_release": "backend-1.2.3", "windows_smoke": "INCOMPLETE",
    }
    assert identity["build"]["native_windows_build"] == "NOT_VERIFIED"
    assert identity["source"]["lock_sha256"] == (
        "cca95e117d789224ad2f54e3b3c716221a6505a1a01e015c2dbc03899b62ef61"
    )
    assert manifest["archive"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["archive"]["size_bytes"] == archive.stat().st_size
    assert "--server" in instructions and "--ca" in instructions
    assert "recovery journal" in instructions and "INCOMPLETE" in instructions
    assert str(source) not in json.dumps(manifest)
    assert str(runtime) not in json.dumps(manifest)


@pytest.mark.parametrize("private_path", [
    ".env", ".env.production", "mysql.env", "backup.sql", "backup.sql.gz",
    "server-key.pem", "server.key", "native-private.log",
    "operational-commands/request.json", ".runtime/private-data.txt",
])
def test_release_refuses_private_runtime_material_without_publishing(
    tmp_path: Path, private_path: str,
) -> None:
    source, runtime, output = release_inputs(tmp_path)
    private = runtime / private_path
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("private sentinel must never be distributed")

    result = package(source, runtime, output)

    assert result.returncode != 0
    assert not output.exists()
    assert private.read_text() == "private sentinel must never be distributed"
    assert "private sentinel" not in result.stdout + result.stderr


@pytest.mark.parametrize("link_location", ["runtime_file", "runtime_directory", "source_file"])
def test_release_refuses_links_instead_of_reading_outside_inputs(
    tmp_path: Path, link_location: str,
) -> None:
    source, runtime, output = release_inputs(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "innocent.bin").write_text("outside input sentinel")
    if link_location == "runtime_file":
        (runtime / "_internal/alias.bin").symlink_to(external / "innocent.bin")
    elif link_location == "runtime_directory":
        (runtime / "_internal/alias").symlink_to(external, target_is_directory=True)
    else:
        (source / "src/election/alias.py").symlink_to(external / "innocent.bin")

    result = package(source, runtime, output)

    assert result.returncode != 0
    assert not output.exists()
    assert "outside input sentinel" not in result.stdout + result.stderr


@pytest.mark.parametrize("release_version,backend_release", [
    ("../outside", "backend-1.2.3"), ("1.2.3/other", "backend-1.2.3"),
    ("1.2.3", "https://example.invalid/?password=sentinel"),
    ("1.2.3", "backend\nprivate-sentinel"),
])
def test_release_rejects_path_or_connection_values_as_release_labels(
    tmp_path: Path, release_version: str, backend_release: str,
) -> None:
    source, runtime, output = release_inputs(tmp_path)

    result = package(
        source, runtime, output, release_version=release_version, backend_release=backend_release,
    )

    assert result.returncode != 0
    assert not output.exists()
    assert "sentinel" not in result.stdout + result.stderr


@pytest.mark.parametrize("unsafe_name", [
    "C:outside.txt", "outside\\file.txt", "Qt6Core.dll.", "CON", "line\nbreak.txt",
])
@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot create these adversarial names")
def test_release_rejects_names_that_are_unsafe_to_extract_on_windows(
    tmp_path: Path, unsafe_name: str,
) -> None:
    source, runtime, output = release_inputs(tmp_path)
    (runtime / "_internal" / unsafe_name).write_text("synthetic runtime input")

    result = package(source, runtime, output)

    assert result.returncode != 0
    assert not output.exists()
