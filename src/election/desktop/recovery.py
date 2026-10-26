"""Explicit inspection and retry of journaled operational requests."""

from copy import deepcopy
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.exact_numbers import qt_state
from election.desktop.operational_receipts import valid_operational_receipt

ROLES = frozenset({"polling_officer", "counting_officer", "supervisor"})
NETWORK_ERRORS = frozenset({
    "request_failed", "disconnected", "database_unavailable", "certificate_error",
    "invalid_response", "invalid_credentials", "session_expired", "access_changed",
    "recovery_outcome_check_required", "recovery_journal_unavailable",
})


class CommandJournal(Protocol):
    def commands(self, server_url: str, actor_id: int, station_id: int) -> list[dict[str, Any]]: ...

    def record_outcome(
        self,
        server_url: str,
        actor_id: int,
        request_id: str,
        status: str,
        *,
        record: dict[str, Any] | None = None,
        error: str = "",
    ) -> None: ...


class RecoveryController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        journal: CommandJournal,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._request, self._journal = request, journal
        self._generation = 0
        self._opened = False
        self._server_url = ""
        self._account_id = 0
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._server_url = ""
        self._account_id = 0
        self._state = {
            "station_id": 0,
            "role": "",
            "commands": [],
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
        }
        self.stateChanged.emit()

    @staticmethod
    def _origin(server_url: str) -> str:
        normalized = server_url.strip()
        parsed = urlsplit(normalized)
        try:
            hostname, _ = parsed.hostname, parsed.port
        except ValueError:
            return ""
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            return ""
        return normalized.rstrip("/")

    def set_context(self, station_id: int, role: str, server_url: str, account_id: int) -> None:
        origin = self._origin(server_url)
        values = {
            "station_id": station_id if type(station_id) is int and station_id > 0 else 0,
            "role": role if role in ROLES else "",
        }
        normalized_account_id = account_id if type(account_id) is int and account_id > 0 else 0
        changed = (
            any(self._state.get(key) != value for key, value in values.items())
            or self._server_url != origin
            or self._account_id != normalized_account_id
        )
        opened = self._opened
        if changed:
            self.reset()
            self._opened = opened
        self._state.update(values)
        self._server_url = origin
        self._account_id = normalized_account_id
        self.stateChanged.emit()
        if changed and self._opened:
            self.reload()

    def _context_ready(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._account_id
            and self._state["role"] in ROLES
            and self._server_url
        )

    def _workflow_allowed(self, workflow: Any) -> bool:
        role = self._state["role"]
        if workflow == "count":
            return role in ("counting_officer", "supervisor")
        if workflow in ("turnout", "allocation"):
            return role in ("polling_officer", "supervisor")
        return False

    def _current_commands(self) -> list[dict[str, Any]]:
        rows = self._journal.commands(self._server_url, self._account_id, self._state["station_id"])
        return [
            deepcopy(row)
            for row in rows
            if row.get("server_url") == self._server_url
            and row.get("actor_id") == self._account_id
            and row.get("station_id") == self._state["station_id"]
            and self._workflow_allowed(row.get("workflow"))
            and row.get("status") in ("pending", "uncertain", "committed", "rejected")
        ]

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.reload()

    @Slot()
    def reload(self) -> None:
        if not self._context_ready():
            self._error("recovery_context_unavailable")
            return
        if self._state["busy"]:
            return
        self._generation += 1
        generation = self._generation
        self._state.update(busy=True, error="", notice="")
        self.stateChanged.emit()
        try:
            commands = self._current_commands()
        except OSError, ValueError, RuntimeError:
            if generation == self._generation:
                self._state.update(busy=False, error="recovery_journal_unavailable")
                self.stateChanged.emit()
            return
        if generation == self._generation:
            self._state.update(busy=False, commands=commands, error="")
            self.stateChanged.emit()

    @Slot(str)
    def checkOutcome(self, request_id: str) -> None:
        if not self._context_ready() or self._state["role"] not in ROLES:
            self._error("recovery_context_unavailable")
            return
        if self._state["busy"]:
            return
        command = next(
            (row for row in self._state["commands"] if row.get("request_id") == request_id),
            None,
        )
        if command is None or not self._workflow_allowed(command.get("workflow")):
            self._error("recovery_command_not_found")
            return
        try:
            UUID(request_id)
        except ValueError, TypeError, AttributeError:
            self._error("recovery_command_not_found")
            return
        path = (
            f"/api/workspace/stations/{self._state['station_id']}"
            f"/request-outcomes/{request_id}?workflow={command['workflow']}"
        )
        self._send(path, "GET", None, command, request_id, retry=False)

    @Slot(str, str)
    def retry(self, request_id: str, password: str) -> None:
        if not self._context_ready() or self._state["role"] not in ROLES:
            self._error("recovery_context_unavailable")
            return
        if self._state["busy"]:
            return
        command = next(
            (row for row in self._state["commands"] if row.get("request_id") == request_id),
            None,
        )
        if command is None or not self._workflow_allowed(command.get("workflow")):
            self._error("recovery_command_not_found")
            return
        if command.get("status") != "uncertain" or command.get("error") != "request_not_found":
            self._error("recovery_retry_unavailable")
            return
        if command.get("confirmation_required") and not password:
            self._error("invalid_credentials")
            return
        path, method = command.get("path"), command.get("method")
        payload = command.get("payload")
        if (
            not isinstance(path, str)
            or not path.startswith(f"/api/workspace/stations/{self._state['station_id']}/")
            or method not in ("POST", "PUT")
            or not isinstance(payload, dict)
        ):
            self._error("recovery_command_invalid")
            return
        original = deepcopy(payload)
        original["request_id"] = request_id
        if command.get("confirmation_required"):
            original["password"] = password
        self._send(path, method, original, command, request_id, retry=True)

    def _send(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        command: dict[str, Any],
        request_id: str,
        *,
        retry: bool,
    ) -> None:
        self._generation += 1
        generation = self._generation
        server_url = self._server_url
        account_id = self._account_id
        self._state.update(busy=True, refreshing=False, error="", notice="")
        self.stateChanged.emit()

        def finish(status: str, *, record: dict[str, Any] | None = None, error: str = "") -> None:
            self._journal.record_outcome(
                server_url, account_id, request_id, status, record=record, error=error
            )
            commands = self._current_commands()
            self._state.update(
                busy=False,
                commands=commands,
                error=error if status in ("uncertain", "rejected") else "",
                notice="recovery_request_not_found" if error == "request_not_found" else "",
            )

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if method == "GET":
                if (
                    body.get("request_id") != request_id
                    or body.get("workflow") != command.get("workflow")
                    or body.get("status") not in ("committed", "not_found")
                    or (
                        body.get("status") == "committed"
                        and not valid_operational_receipt(command, body.get("record"))
                    )
                ):
                    try:
                        finish("uncertain", error="recovery_outcome_invalid")
                    except OSError, ValueError, RuntimeError:
                        self._state.update(busy=False, error="recovery_journal_unavailable")
                else:
                    try:
                        status = "committed" if body["status"] == "committed" else "uncertain"
                        finish(
                            status,
                            record=body.get("record"),
                            error=("" if status == "committed" else "request_not_found"),
                        )
                    except OSError, ValueError, RuntimeError:
                        self._state.update(busy=False, error="recovery_journal_unavailable")
                self.stateChanged.emit()
                return
            try:
                if valid_operational_receipt(command, body):
                    finish("committed", record=body)
                else:
                    finish("uncertain", error="recovery_outcome_invalid")
            except OSError, ValueError, RuntimeError:
                self._state.update(busy=False, error="recovery_journal_unavailable")
            if not self._state["error"]:
                self._state["notice"] = "recovery_retry_committed" if retry else ""
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            previous_status = command.get("status")
            status = (
                "uncertain"
                if method == "GET"
                or code in NETWORK_ERRORS
                or (previous_status == "uncertain" and not retry)
                else "rejected"
            )
            try:
                finish(status, error=code)
            except OSError, ValueError, RuntimeError:
                self._state.update(busy=False, error="recovery_journal_unavailable")
            self.stateChanged.emit()

        self._request(path, method, payload, loaded, failed)
