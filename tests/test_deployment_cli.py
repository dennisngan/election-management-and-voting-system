"""Operator CLI and generated deployment artifacts; no retained database access."""

import os
import stat
import subprocess
import sys
from pathlib import Path

from cryptography import x509

ROOT = Path(__file__).resolve().parents[1]


def deployment(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "election.deployment", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prepare_creates_private_independent_configuration_and_host_certificate(tmp_path):
    directory = tmp_path / "deployment"
    result = deployment("prepare", "--root", str(directory), "--host", "election.example")
    assert result.returncode == 0, result.stderr
    assert all((directory / name).is_dir() for name in ("mysql", "backups", "config", "tls"))
    server = directory / "config/server.env"
    assert stat.S_IMODE(server.stat().st_mode) == 0o600
    assert "@db:3306/election" in server.read_text()
    assert "13307" not in server.read_text()
    assert "password" not in result.stdout.lower()
    certificate = x509.load_pem_x509_certificate((directory / "tls/server.pem").read_bytes())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert names.get_values_for_type(x509.DNSName) == ["election.example"]
    assert (directory / "tls/ca-key.pem").is_file()
    assert stat.S_IMODE((directory / "tls/ca-key.pem").stat().st_mode) == 0o600


def test_prepare_rerun_preserves_material_and_refuses_partial_or_unrelated_state(tmp_path):
    directory = tmp_path / "deployment"
    arguments = ("prepare", "--root", str(directory), "--host", "127.0.0.1")
    assert deployment(*arguments).returncode == 0
    before = {path: path.read_bytes() for path in directory.rglob("*") if path.is_file()}
    assert deployment(*arguments).returncode == 0
    assert all(path.read_bytes() == content for path, content in before.items())
    (directory / "config/server.env").unlink()
    assert deployment(*arguments).returncode != 0
    assert not (directory / "config/server.env").exists()
    unrelated = tmp_path / "retained"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("preserve")
    refused = deployment("prepare", "--root", str(unrelated), "--host", "127.0.0.1")
    assert refused.returncode != 0
    assert (unrelated / "keep.txt").read_text() == "preserve"
