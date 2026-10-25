"""Private, credential-free operational command identity across client restarts."""

import hashlib
import json
import os
import re
import stat
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

UNRESOLVED = {"pending", "uncertain"}
SENSITIVE_KEYS = {
    "password",
    "current_password",
    "new_password",
    "temporary_password",
    "token",
    "authorization",
    "secret",
    "secret_key",
    "access_token",
    "refresh_token",
}
STATION_PATH = re.compile(r"^/api/workspace/stations/([1-9][0-9]*)/([^?]+)$")


class JournalError(RuntimeError):
    """A safe public recovery code; never contains filesystem paths or payloads."""


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe(item) for key, item in value.items() if key.lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return deepcopy(value)


def command_workflow(path: str) -> tuple[int, str] | None:
    matched = STATION_PATH.fullmatch(path)
    if matched is None:
        return None
    station_id, resource = int(matched[1]), matched[2]
    if resource.startswith("counting-scopes/") and "/rounds" in resource:
        return station_id, "count"
    if resource.startswith("turnout/"):
        return station_id, "turnout"
    if resource == "allocations" or resource.startswith("allocations/"):
        return station_id, "allocation"
    return None


def _origin(server_url: str) -> str:
    parsed = urlsplit(server_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise JournalError("recovery_journal_unavailable")
    return server_url.rstrip("/")


def _target(path: str) -> str:
    # Completion/approval and F1/F2 writes address the same count identity.
    matched = re.match(r"(.*/rounds/[1-9][0-9]*)(?:/|$)", path)
    return matched[1] if matched else path


class CommandJournal:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _directory(self, *, create: bool) -> bool:
        if not self.directory.exists():
            if not create:
                return False
            self.directory.mkdir(mode=0o700, parents=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise JournalError("recovery_journal_unavailable")
        if stat.S_IMODE(self.directory.stat().st_mode) != 0o700:
            raise JournalError("recovery_journal_unavailable")
        return True

    def _path(self, server_url: str, actor_id: int, request_id: str) -> Path:
        identity = json.dumps([_origin(server_url), actor_id, str(UUID(request_id))])
        return self.directory / (hashlib.sha256(identity.encode()).hexdigest() + ".json")

    def _write(self, path: Path, row: dict[str, Any]) -> None:
        self._directory(create=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".command-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o600)
                json.dump(_safe(row), output, ensure_ascii=False, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def commands(self, server_url: str, actor_id: int, station_id: int) -> list[dict[str, Any]]:
        if not self._directory(create=False):
            return []
        origin = _origin(server_url)
        rows = []
        for path in self.directory.glob("*.json"):
            if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise JournalError("recovery_journal_unavailable")
            row = json.loads(path.read_text())
            if (row.get("server_url"), row.get("actor_id"), row.get("station_id")) != (
                origin,
                actor_id,
                station_id,
            ):
                continue
            if (
                path != self._path(origin, actor_id, row["request_id"])
                or command_workflow(row["path"]) != (station_id, row["workflow"])
                or row["method"] not in ("POST", "PUT", "PATCH")
                or row["payload"].get("request_id") != row["request_id"]
                or row["status"] not in {"pending", "uncertain", "committed", "rejected"}
            ):
                raise JournalError("recovery_journal_unavailable")
            rows.append(_safe(row))
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def prepare(
        self,
        server_url: str,
        actor_id: int,
        station_id: int,
        workflow: str,
        path: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        origin, request_id = _origin(server_url), str(UUID(payload["request_id"]))
        safe_payload = _safe(payload)
        rows = self.commands(origin, actor_id, station_id)
        previous = next((row for row in rows if row["request_id"] == request_id), None)
        if previous and previous["status"] != "rejected":
            if (previous["path"], previous["method"], previous["payload"]) != (
                path,
                method,
                safe_payload,
            ):
                raise JournalError("recovery_command_conflict")
            return previous
        if any(
            row["request_id"] != request_id
            and row["status"] in UNRESOLVED
            and row["target"] == _target(path)
            for row in rows
        ):
            raise JournalError("recovery_pending_command")
        row = {
            "request_id": request_id,
            "server_url": origin,
            "actor_id": actor_id,
            "station_id": station_id,
            "workflow": workflow,
            "path": path,
            "method": method,
            "payload": safe_payload,
            "confirmation_required": "password" in payload,
            "target": _target(path),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pending",
            "receipt": None,
            "error": "",
        }
        self._write(self._path(origin, actor_id, request_id), row)
        return deepcopy(row)

    def record_outcome(
        self,
        server_url: str,
        actor_id: int,
        request_id: str,
        status: str,
        *,
        record: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        path = self._path(server_url, actor_id, request_id)
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise JournalError("recovery_journal_unavailable")
        row = json.loads(path.read_text())
        if row["status"] == "committed":
            return
        if row["status"] == "uncertain" and error == "invalid_credentials":
            status = "uncertain"
        row.update(status=status, error=error, updated_at=datetime.now(UTC).isoformat())
        if record is not None:
            row["receipt"] = {"record": _safe(record)}
        self._write(path, row)
