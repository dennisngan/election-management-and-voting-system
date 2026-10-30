"""Reviewed election completion and durable original command acknowledgements."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.operational_receipts import valid_operational_receipt
from election.desktop.recovery import NETWORK_ERRORS, RecoveryController


class ElectionCompletionController(QObject):
    stateChanged = Signal()
    finalized = Signal(object)

    def __init__(
        self, request: AuthorizedRequest, parent: QObject | None = None, *,
        recovery: RecoveryController | None = None,
    ) -> None:
        super().__init__(parent)
        self._request, self._recovery = request, recovery
        self._generation = 0
        self._opened = False
        self._scope: tuple[Any, ...] | None = None
        self._state: dict[str, Any] = {}
        self.reset()
        if recovery is not None:
            recovery.stateChanged.connect(self._sync_recovery)

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(quantity_display(self._state))

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._scope = None
        self._command: dict[str, Any] | None = None
        self._state = {
            "election_id": None, "actor_id": None, "role": "", "election": {},
            "assessment": {}, "busy": False, "refreshing": False, "error": "",
            "receipt": {}, "pending_request_id": "", "uncertain_save": False,
        }
        self.stateChanged.emit()

    def set_context(
        self, account: dict[str, Any], election: dict[str, Any] | None, origin: str
    ) -> None:
        target = election or {}
        election_id = target.get("id")
        scope = (origin, account.get("id"), election_id, account.get("role", ""))
        changed = scope != self._scope
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._scope = scope
        self._state.update(
            election_id=election_id, actor_id=account.get("id"),
            role=account.get("role", ""), election=deepcopy(target),
        )
        self._sync_recovery()
        self.stateChanged.emit()
        if changed and self._opened:
            self.refresh()

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        election_id = self._state["election_id"]
        if (
            not self._opened or self._state["busy"] or self._state["refreshing"]
            or self._state["role"] != "supervisor"
            or type(election_id) is not int or election_id <= 0
            or type(self._state["actor_id"]) is not int
        ):
            return
        generation = self._generation
        self._state.update(refreshing=True, error="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, error=code)
            self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if (
                not isinstance(data.get("election"), dict)
                or data["election"].get("id") != election_id
                or type(data.get("can_finalize")) is not bool
                or not isinstance(data.get("blockers"), list)
                or not all(isinstance(row, dict) for row in data["blockers"])
                or not isinstance(data.get("sources"), dict)
            ):
                failed("request_failed")
                return
            self._state.update(assessment=deepcopy(data), refreshing=False, error="")
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion", "GET", None, loaded, failed
        )

    def _settled(self, body: dict[str, Any]) -> None:
        self._generation += 1
        self._command = None
        self._state.update(
            busy=False, refreshing=False, receipt=deepcopy(body), pending_request_id="",
            uncertain_save=False, election=deepcopy(body["election"]), error="",
            assessment={
                **self._state["assessment"], "election": deepcopy(body["election"]),
                "active_election_id": body["active_election_id"], "can_finalize": False,
            },
        )
        self.stateChanged.emit()
        self.finalized.emit(body)

    def _sync_recovery(self) -> None:
        if self._recovery is None or self._state["role"] != "supervisor" or not self._scope:
            return
        pending_id = self._state["pending_request_id"]
        command = next((row for row in self._recovery.command_records() if (
            row.get("namespace") == "election" and row.get("workflow") == "election_completion"
            and row.get("election_id") == self._state["election_id"]
            and row.get("actor_id") == self._state["actor_id"]
            and row.get("server_url") == self._scope[0]
            and row.get("path") == (
                f"/api/workspace/elections/{self._state['election_id']}/finalizations"
            )
            and (row.get("request_id") == pending_id if pending_id
                 else row.get("status") in {"pending", "uncertain"})
        )), None)
        if command is None:
            return
        if command.get("status") in {"pending", "uncertain"}:
            if self._command is None:
                self._command = deepcopy(command)
            self._state.update(
                uncertain_save=True, pending_request_id=command["request_id"],
                error=command.get("error") or "",
            )
            self.stateChanged.emit()
        elif command.get("status") == "committed":
            receipt = (command.get("receipt") or {}).get("record")
            if isinstance(receipt, dict) and valid_operational_receipt(
                self._command or command, receipt,
            ):
                self._settled(receipt)
        elif command.get("status") == "rejected":
            self._command = None
            self._state.update(
                uncertain_save=False, pending_request_id="",
                error=command.get("error") or "election_completion_not_ready",
            )
            self.stateChanged.emit()

    @Slot(str)
    def finalize(self, password: str) -> None:
        assessment = self._state["assessment"]
        election_id = self._state["election_id"]
        if (
            self._state["role"] != "supervisor" or self._state["busy"]
            or self._state["refreshing"] or self._state["uncertain_save"]
            or assessment.get("can_finalize") is not True
            or type(election_id) is not int or election_id <= 0
            or (assessment.get("election") or {}).get("id") != election_id
        ):
            self._state["error"] = "election_completion_not_ready"
            self.stateChanged.emit()
            return
        if not password:
            self._state["error"] = "invalid_credentials"
            self.stateChanged.emit()
            return
        payload = {
            "request_id": str(uuid4()),
            "expected_election_revision": assessment["election"]["revision"],
            "basis_digest": assessment["basis_digest"],
        }
        path = f"/api/workspace/elections/{election_id}/finalizations"
        command = {
            "namespace": "election", "election_id": election_id,
            "workflow": "election_completion", "method": "POST", "path": path,
            "actor_id": self._state["actor_id"], "request_id": payload["request_id"],
            "payload": deepcopy(payload),
        }
        self._command = command
        self._generation += 1
        generation = self._generation
        self._state.update(busy=True, error="", pending_request_id=payload["request_id"])
        self.stateChanged.emit()

        def saved(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not valid_operational_receipt(command, body):
                self._state.update(busy=False, uncertain_save=True, error="invalid_response")
                self.stateChanged.emit()
                return
            self._settled(body)

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            uncertain = code in NETWORK_ERRORS - {"recovery_journal_unavailable"}
            self._state.update(busy=False, uncertain_save=uncertain, error=code)
            if not uncertain:
                self._command = None
                self._state["pending_request_id"] = ""
            self.stateChanged.emit()

        self._request(path, "POST", {**payload, "password": password}, saved, failed)
