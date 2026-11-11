"""Private, credential-free operational command identity across client restarts."""

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from election.private_paths import (
    private_directory,
    private_file,
    private_file_descriptor,
)

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
        if not all(isinstance(key, str) for key in value):
            raise JournalError("recovery_journal_unavailable")
        return {
            key: _safe(item) for key, item in value.items() if key.lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return deepcopy(value)


def command_workflow(path: str, namespace_station_id: int = 0) -> tuple[int, str] | None:
    if re.fullmatch(r"/api/workspace/constituencies/[1-9][0-9]*/recounts", path):
        return namespace_station_id, "constituency_recount"
    matched = STATION_PATH.fullmatch(path)
    if matched is None:
        return None
    station_id, resource = int(matched[1]), matched[2]
    if resource.startswith("counting-scopes/") and "/rounds" in resource:
        return station_id, "count"
    if re.fullmatch(r"counting-scopes/[1-9][0-9]*/recounts", resource):
        return station_id, "count"
    if resource.startswith("turnout/"):
        return station_id, "turnout"
    if resource == "allocations" or resource.startswith("allocations/"):
        return station_id, "allocation"
    return None


def election_command_workflow(path: str) -> tuple[int, str] | None:
    matched = re.fullmatch(
        r"/api/workspace/elections/([1-9][0-9]*)/(?:finalizations|reopenings)",
        path,
    )
    return (int(matched[1]), "election_completion") if matched is not None else None


def _origin(server_url: str) -> str:
    parsed = urlsplit(server_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise JournalError("recovery_journal_unavailable")
    return server_url.rstrip("/")


def _target(path: str) -> str:
    election = election_command_workflow(path)
    if election is not None:
        return f"/api/workspace/elections/{election[0]}"
    # Completion/approval and F1/F2 writes address the same count identity.
    matched = re.match(r"(.*/rounds/[1-9][0-9]*)(?:/|$)", path)
    if matched:
        return matched[1]
    matched = re.match(r"(.*/turnout/[1-9][0-9]*)(?:/|$)", path)
    return matched[1] if matched else path


class CommandJournal:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _directory(self, *, create: bool) -> bool:
        if not self.directory.exists():
            if not create:
                return False
            self.directory.mkdir(mode=0o700, parents=True)
        if not private_directory(self.directory):
            raise JournalError("recovery_journal_unavailable")
        return True

    def _path(self, server_url: str, actor_id: int, request_id: str) -> Path:
        try:
            normalized_id = str(UUID(request_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise JournalError("recovery_journal_unavailable") from exc
        identity = json.dumps([_origin(server_url), actor_id, normalized_id])
        return self.directory / (hashlib.sha256(identity.encode()).hexdigest() + ".json")

    def _read_row(self, path: Path) -> dict[str, Any]:
        """Read and validate the common shape of a private command journal row."""
        if not private_file(path):
            raise JournalError("recovery_journal_unavailable")
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict):
                raise JournalError("recovery_journal_unavailable")
            request_id = row.get("request_id")
            created_at = row.get("created_at")
            if not (
                isinstance(request_id, str)
                and str(UUID(request_id)) == request_id
                and isinstance(row.get("server_url"), str)
                and type(row.get("actor_id")) is int
                and row["actor_id"] > 0
                and isinstance(row.get("path"), str)
                and isinstance(row.get("workflow"), str)
                and row["workflow"]
                and row.get("method") in {"POST", "PUT", "PATCH"}
                and isinstance(row.get("payload"), dict)
                and row["payload"].get("request_id") == request_id
                and row.get("status") in {"pending", "uncertain", "committed", "rejected"}
                and isinstance(created_at, str)
            ):
                raise JournalError("recovery_journal_unavailable")
            datetime.fromisoformat(created_at)
        except JournalError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
            raise JournalError("recovery_journal_unavailable") from exc
        return row

    def _validate_scoped_row(
        self,
        path: Path,
        row: dict[str, Any],
        server_url: str,
        actor_id: int,
    ) -> None:
        if (
            row["server_url"] != server_url
            or row["actor_id"] != actor_id
            or path != self._path(server_url, actor_id, row["request_id"])
        ):
            raise JournalError("recovery_journal_unavailable")

    def _write(self, path: Path, row: dict[str, Any]) -> None:
        self._directory(create=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".command-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o600)
                if not private_file_descriptor(output.fileno()):
                    raise JournalError("recovery_journal_unavailable")
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
            row = self._read_row(path)
            if (row.get("server_url"), row.get("actor_id"), row.get("station_id")) != (
                origin,
                actor_id,
                station_id,
            ):
                continue
            self._validate_scoped_row(path, row, origin, actor_id)
            if type(row.get("station_id")) is not int or command_workflow(
                row["path"], station_id
            ) != (station_id, row["workflow"]):
                raise JournalError("recovery_journal_unavailable")
            row["target"] = _target(row["path"])
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
        if (
            type(station_id) is not int
            or station_id <= 0
            or command_workflow(path, station_id) != (station_id, workflow)
        ):
            raise JournalError("recovery_command_invalid")
        return self._prepare_scoped(
            server_url,
            actor_id,
            {"station_id": station_id, "workflow": workflow},
            path,
            method,
            payload,
        )

    def election_commands(
        self,
        server_url: str,
        actor_id: int,
        election_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if election_id is not None and (type(election_id) is not int or election_id <= 0):
            raise JournalError("recovery_command_invalid")
        if not self._directory(create=False):
            return []
        origin = _origin(server_url)
        rows = []
        for path in self.directory.glob("*.json"):
            row = self._read_row(path)
            if (row.get("server_url"), row.get("actor_id"), row.get("namespace")) != (
                origin,
                actor_id,
                "election",
            ):
                continue
            target_id = row.get("election_id")
            if election_id is not None and target_id != election_id:
                continue
            self._validate_scoped_row(path, row, origin, actor_id)
            if (
                type(target_id) is not int
                or target_id <= 0
                or "station_id" in row
                or election_command_workflow(row["path"]) != (target_id, row["workflow"])
                or row["method"] != "POST"
            ):
                raise JournalError("recovery_journal_unavailable")
            row["target"] = _target(row["path"])
            rows.append(_safe(row))
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def prepare_election(
        self,
        server_url: str,
        actor_id: int,
        election_id: int,
        path: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            type(election_id) is not int
            or election_id <= 0
            or method != "POST"
            or election_command_workflow(path) != (election_id, "election_completion")
        ):
            raise JournalError("recovery_command_invalid")
        return self._prepare_scoped(
            server_url,
            actor_id,
            {
                "namespace": "election",
                "election_id": election_id,
                "workflow": "election_completion",
            },
            path,
            method,
            payload,
        )

    def _prepare_scoped(
        self,
        server_url: str,
        actor_id: int,
        scope: dict[str, Any],
        path: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        origin, request_id = _origin(server_url), str(UUID(payload["request_id"]))
        safe_payload = _safe(payload)
        election_scope = scope.get("namespace") == "election"
        rows = (
            self.election_commands(origin, actor_id, scope["election_id"])
            if election_scope
            else self.commands(origin, actor_id, scope["station_id"])
        )
        previous = next((row for row in rows if row["request_id"] == request_id), None)
        if previous is None and self._path(origin, actor_id, request_id).exists():
            raise JournalError("recovery_command_conflict")
        if previous and (election_scope or previous["status"] != "rejected"):
            if (previous["path"], previous["method"], previous["payload"]) != (
                path,
                method,
                safe_payload,
            ):
                raise JournalError("recovery_command_conflict")
        if previous and previous["status"] != "rejected":
            if previous["status"] in UNRESOLVED:
                if previous.get("error") != "request_not_found":
                    raise JournalError("recovery_outcome_check_required")
                previous.update(status="uncertain", error="")
                self._write(self._path(origin, actor_id, request_id), previous)
                return {**deepcopy(previous), "retry_after_not_found": True}
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
            **scope,
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
        row = self._read_row(path)
        origin = _origin(server_url)
        self._validate_scoped_row(path, row, origin, actor_id)
        if row["request_id"] != str(UUID(request_id)):
            raise JournalError("recovery_journal_unavailable")
        if row["status"] == "committed":
            return
        if row["status"] == "uncertain" and error == "invalid_credentials":
            status = "uncertain"
        row.update(status=status, error=error, updated_at=datetime.now(UTC).isoformat())
        if record is not None:
            row["receipt"] = {"record": _safe(record)}
        self._write(path, row)
