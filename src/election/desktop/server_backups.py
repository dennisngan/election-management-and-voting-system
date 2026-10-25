"""Explicit server-side backup requests through authenticated public HTTP."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.exact_numbers import qt_state

AuthorizedRequest = Callable[
    [str, str, dict[str, Any] | None, Callable[[dict[str, Any]], None], Callable[[str], None]],
    None,
]
BACKUP_FIELDS = {
    "id",
    "request_id",
    "status",
    "requested_at",
    "completed_at",
    "cutoff_start",
    "cutoff_end",
    "sha256",
    "size_bytes",
    "error_code",
}
TERMINAL_STATUSES = {"succeeded", "failed"}


def empty_state() -> dict[str, Any]:
    return {
        "role": "",
        "account_id": 0,
        "jobs": [],
        "busy": False,
        "refreshing": False,
        "error": "",
        "notice": "",
        "pending_request_id": None,
        "uncertain_save": False,
    }


class ServerBackupsController(QObject):
    """Manage explicit backup requests and public job metadata for one account."""

    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._opened = False
        self._loaded = False
        self._state = empty_state()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(self._state)

    @staticmethod
    def _valid_job(row: Any) -> bool:
        if not isinstance(row, dict) or set(row) != BACKUP_FIELDS:
            return False
        try:
            UUID(row["id"])
            UUID(row["request_id"])
        except ValueError, TypeError, AttributeError:
            return False
        if row["status"] not in ("running", "succeeded", "failed"):
            return False
        if not isinstance(row["requested_at"], str) or not row["requested_at"]:
            return False
        if any(
            value is not None and not isinstance(value, str)
            for value in (row["completed_at"], row["cutoff_start"], row["cutoff_end"])
        ):
            return False
        if row["size_bytes"] is not None and (
            type(row["size_bytes"]) is not int or row["size_bytes"] < 0
        ):
            return False
        if row["sha256"] is not None and (
            not isinstance(row["sha256"], str)
            or len(row["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in row["sha256"])
        ):
            return False
        if row["error_code"] is not None and not isinstance(row["error_code"], str):
            return False
        if row["status"] == "succeeded" and (
            row["completed_at"] is None
            or row["sha256"] is None
            or row["size_bytes"] is None
            or row["size_bytes"] <= 0
            or row["error_code"] is not None
        ):
            return False
        if row["status"] == "failed" and (
            row["completed_at"] is None
            or row["sha256"] is not None
            or row["size_bytes"] is not None
            or row["error_code"] is None
        ):
            return False
        return True

    def set_account(self, account: dict[str, Any]) -> None:
        account_id = account.get("id", 0)
        role = account.get("role", "")
        if type(account_id) is not int or account_id < 1:
            account_id = 0
        if not isinstance(role, str):
            role = ""
        if (account_id, role) != (self._state["account_id"], self._state["role"]):
            self._generation += 1
            self._opened = False
            self._loaded = False
            self._state = empty_state()
            self._state.update(account_id=account_id, role=role)
        self.stateChanged.emit()

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    def _authorized(self) -> bool:
        if self._state["role"] != "administrator" or not self._state["account_id"]:
            self._error("administrator_required")
            return False
        return True

    def _upsert(self, row: dict[str, Any]) -> None:
        jobs = self._state["jobs"]
        self._state["jobs"] = [deepcopy(row) if old.get("id") == row["id"] else old for old in jobs]
        if not any(old.get("id") == row["id"] for old in jobs):
            self._state["jobs"].insert(0, deepcopy(row))

    def _apply_terminal_outcome(self, row: dict[str, Any]) -> None:
        if (
            row["status"] in TERMINAL_STATUSES
            and row["request_id"] == self._state["pending_request_id"]
        ):
            self._state.update(
                pending_request_id=None,
                uncertain_save=False,
                notice="backup_succeeded" if row["status"] == "succeeded" else "backup_failed",
            )

    def _load(self, *, explicit_outcome: bool = False) -> bool:
        if not self._authorized() or not self._opened:
            return False
        if self._state["busy"] or self._state["refreshing"]:
            return False
        generation = self._generation
        self._state.update(refreshing=True, error="", notice="")
        self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state["refreshing"] = False
            rows = data.get("backups")
            if not (
                isinstance(rows, list)
                and all(self._valid_job(row) for row in rows)
                and len({row["id"] for row in rows}) == len(rows)
            ):
                self._error("invalid_response")
                return
            self._state["jobs"] = deepcopy(rows)
            self._loaded = True
            pending = self._state["pending_request_id"]
            if pending:
                match = next((row for row in rows if row["request_id"] == pending), None)
                if match and match["status"] in TERMINAL_STATUSES:
                    self._apply_terminal_outcome(match)
                elif match and explicit_outcome and match["status"] == "running":
                    self._state["notice"] = "backup_running_unconfirmed"
            if self._state["error"]:
                self._state["error"] = ""
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state["refreshing"] = False
            self._error(code)

        self._request("/api/backups", "GET", None, loaded, failed)
        return True

    @Slot(result=bool)
    def open(self) -> bool:
        if not self._authorized():
            return False
        self._opened = True
        return self._load()

    @Slot(result=bool)
    def refresh(self) -> bool:
        return self._load()

    @Slot(result=bool)
    def reload(self) -> bool:
        return self._load()

    @Slot()
    def requestBackup(self) -> None:
        if not self._authorized() or not self._opened:
            if self._state["role"] == "administrator":
                self._error("backup_list_not_open")
            return
        if self._state["busy"] or self._state["refreshing"]:
            return
        request_id = self._state["pending_request_id"] or str(uuid4())
        generation = self._generation
        self._state.update(
            busy=True,
            error="",
            notice="",
            pending_request_id=request_id,
        )
        self.stateChanged.emit()

        def saved(row: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state["busy"] = False
            if not self._valid_job(row) or row["request_id"] != request_id:
                self._state.update(uncertain_save=True, error="invalid_response", notice="")
                self.stateChanged.emit()
                return
            self._upsert(row)
            self._state["error"] = ""
            if row["status"] in TERMINAL_STATUSES:
                self._apply_terminal_outcome(row)
            else:
                self._state.update(uncertain_save=False, notice="backup_running")
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state["busy"] = False
            self._state.update(
                error=code,
                notice="",
                uncertain_save=code
                in {"disconnected", "request_failed", "certificate_error", "invalid_response"},
            )
            self.stateChanged.emit()

        self._request("/api/backups", "POST", {"request_id": request_id}, saved, failed)

    @Slot(result=bool)
    def checkPendingOutcome(self) -> bool:
        if not self._state["pending_request_id"]:
            return False
        return self._load(explicit_outcome=True)
