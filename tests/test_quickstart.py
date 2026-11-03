"""Noninteractive Compose bootstrap through its public configuration/artifact seam."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def quickstart(tmp_path, config, *extra):
    path = tmp_path / "config.yml"
    path.write_text(config)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "election.deployment.quickstart",
            "prepare",
            "--config",
            str(path),
            "--bootstrap",
            str(tmp_path / "bootstrap"),
            "--runtime",
            str(tmp_path / "runtime"),
            "--database-secrets",
            str(tmp_path / "database-secrets"),
            "--backups",
            str(tmp_path / "backups"),
            *extra,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )


def test_prepare_generates_private_runtime_without_exposing_ca_signing_key(tmp_path):
    result = quickstart(tmp_path, "x-election:\n  server:\n    host: localhost\n")
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert (runtime / "server.env").is_file()
    assert (runtime / "tls/ca.pem").is_file()
    assert (runtime / "tls/server-key.pem").is_file()
    assert not (runtime / "tls/ca-key.pem").exists()
    assert not (runtime / "mysql-root-password").exists()
    assert (tmp_path / "bootstrap/tls/ca-key.pem").is_file()
    assert (tmp_path / "database-secrets/root-password").is_file()
    assert "password" not in result.stdout.lower()


def test_prepare_rerun_preserves_material_and_refuses_a_different_database_path(tmp_path):
    original = "x-election:\n  server:\n    host: localhost\n"
    assert quickstart(tmp_path, original).returncode == 0
    key = (tmp_path / "runtime/tls/server-key.pem").read_bytes()
    assert quickstart(tmp_path, original).returncode == 0
    assert (tmp_path / "runtime/tls/server-key.pem").read_bytes() == key
    refused = quickstart(tmp_path, original + "  storage:\n    mysql: ./different/mysql\n")
    assert refused.returncode != 0
    assert "quickstart_database_path_changed" in refused.stderr
    assert (tmp_path / "runtime/tls/server-key.pem").read_bytes() == key


def test_new_install_refuses_a_populated_database_directory(tmp_path):
    data = tmp_path / "unrelated-db"
    data.mkdir()
    (data / "preserve").write_text("existing data")
    result = quickstart(tmp_path, "x-election: {}\n", "--mysql-data", str(data))
    assert result.returncode != 0
    assert "quickstart_database_directory_not_empty" in result.stderr
    assert (data / "preserve").read_text() == "existing data"
    assert not (tmp_path / "bootstrap/config/server.env").exists()
