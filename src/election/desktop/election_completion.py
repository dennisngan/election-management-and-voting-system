"""Reviewed election completion and durable original command acknowledgements."""

from collections.abc import Callable
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
    reopened = Signal(object)

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
        view = quantity_display(self._state)
        view["can_finalize"] = self._can_finalize(self._state["assessment"])
        receipt = self._state["receipt"]
        if (
            self._recovery is not None and receipt
            and not self._recovery.election_receipt_disclosed(receipt["request_id"])
        ):
            view["receipt"] = {}
        return qt_state(view)

    def _can_finalize(self, assessment: dict[str, Any]) -> bool:
        election_id = self._state["election_id"]
        reviewed = assessment.get("election") or {}
        current = self._state["election"]
        return bool(
            self._state["role"] == "supervisor"
            and type(election_id) is int and election_id > 0
            and assessment.get("can_finalize") is True
            and reviewed.get("id") == election_id and reviewed.get("status") == "active"
            and type(reviewed.get("revision")) is int and reviewed["revision"] > 0
            and current.get("id") == election_id and current.get("status") == "active"
            and ("name" not in current or current["name"] == reviewed.get("name"))
            and (type(current.get("revision")) is not int
                 or current["revision"] == reviewed["revision"])
        )

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._scope = None
        self._command: dict[str, Any] | None = None
        self._receipt_disclosed = True
        self._state = {
            "election_id": None, "actor_id": None, "role": "", "election": {},
            "assessment": {}, "busy": False, "refreshing": False, "error": "",
            "receipt": {}, "pending_request_id": "", "uncertain_save": False,
            "reconciling": False, "review": {}, "reviewing": False, "newer_basis": False,
            "history": {},
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
        if self._state["reviewing"] and not self._can_finalize(self._state["review"]):
            self._state["newer_basis"] = True
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
            incoming = data["election"]
            known = self._state["election"]
            if type(incoming.get("revision")) is int and (
                type(known.get("revision")) is not int
                or incoming["revision"] >= known["revision"]
            ):
                self._state["election"] = deepcopy(incoming)
            review = self._state["review"]
            if self._state["reviewing"] and (
                data["election"] != review["election"]
                or data.get("basis_digest") != review.get("basis_digest")
                or data["can_finalize"] is not True
            ):
                self._state["newer_basis"] = True
            self._state.update(assessment=deepcopy(data), refreshing=False, error="")
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion", "GET", None, loaded, failed
        )

    @Slot()
    def loadHistory(self) -> None:
        election_id = self._state["election_id"]
        if (
            self._state["role"] != "supervisor" or self._state["busy"]
            or self._state["refreshing"] or type(election_id) is not int or election_id <= 0
        ):
            return
        generation = self._generation
        self._state.update(refreshing=True, error="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, error=code)
            if code == "full_election_access_required":
                self._state["history"] = {}
            self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if (
                not isinstance(data.get("election"), dict)
                or data["election"].get("id") != election_id
                or not isinstance(data.get("events"), list)
                or not all(
                    isinstance(event, dict) and event.get("election_id") == election_id
                    and event.get("kind") in {"finalization", "reopening"}
                    and isinstance(event.get("outcome"), dict)
                    for event in data["events"]
                )
            ):
                failed("invalid_response")
                return
            self._state.update(history=deepcopy(data), refreshing=False, error="")
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion/history",
            "GET", None, loaded, failed,
        )

    def wait_for_current_lifecycle(self) -> Callable[[str], None]:
        """Keep settlement visibly working until an authoritative lifecycle read finishes."""
        generation = self._generation
        self._state.update(refreshing=True, reconciling=True)
        self.stateChanged.emit()

        def finished(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, reconciling=False, error=code)
            self.stateChanged.emit()

        return finished

    def _settled(self, body: dict[str, Any]) -> None:
        self._generation += 1
        self._command = None
        assessment = self._state["assessment"]
        election = assessment.get("election")
        # A recovered receipt must not replace an already observed live revision.
        if (
            not isinstance(election, dict) or election.get("id") != body["election"]["id"]
            or type(election.get("revision")) is not int
            or election["revision"] < body["election"]["revision"]
        ):
            election = body["election"]
            assessment = {
                **assessment, "election": deepcopy(election),
                "active_election_id": body["active_election_id"], "can_finalize": False,
            }
        self._state.update(
            busy=False, refreshing=False, receipt=deepcopy(body), pending_request_id="",
            uncertain_save=False, election=deepcopy(election), error="",
            assessment=deepcopy(assessment), review={}, reviewing=False, newer_basis=False,
        )
        # Start authoritative reconciliation before observers can see settlement as idle.
        if body["event"]["kind"] == "reopening":
            self.reopened.emit(body)
        else:
            self.finalized.emit(body)
        self.stateChanged.emit()

    def _sync_recovery(self) -> None:
        if self._recovery is None:
            return
        receipt = self._state["receipt"]
        disclosed = not receipt or self._recovery.election_receipt_disclosed(receipt["request_id"])
        if disclosed != self._receipt_disclosed:
            self._receipt_disclosed = disclosed
            self.stateChanged.emit()
        if self._state["role"] != "supervisor" or not self._scope:
            return
        pending_id = self._state["pending_request_id"]
        command = next((row for row in self._recovery.command_records() if (
            row.get("namespace") == "election" and row.get("workflow") == "election_completion"
            and row.get("election_id") == self._state["election_id"]
            and row.get("actor_id") == self._state["actor_id"]
            and row.get("server_url") == self._scope[0]
            and row.get("path") in {
                f"/api/workspace/elections/{self._state['election_id']}/finalizations",
                f"/api/workspace/elections/{self._state['election_id']}/reopenings",
            }
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

    @Slot(result=bool)
    def prepareFinalization(self) -> bool:
        assessment = self._state["assessment"]
        if (
            self._state["busy"] or self._state["refreshing"] or self._state["uncertain_save"]
            or not self._can_finalize(assessment)
        ):
            self._state["error"] = "election_completion_not_ready"
            self.stateChanged.emit()
            return False
        self._state.update(
            review=deepcopy(assessment), reviewing=True, newer_basis=False, error="",
        )
        self.stateChanged.emit()
        return True

    @Slot()
    def cancelReview(self) -> None:
        if (
            self._state["busy"] or self._state["uncertain_save"]
            or not self._state["reviewing"]
        ):
            return
        self._state.update(review={}, reviewing=False, newer_basis=False, error="")
        self.stateChanged.emit()

    @Slot(str)
    def finalize(self, password: str) -> None:
        if self._state["newer_basis"]:
            self._state["error"] = "election_completion_review_changed"
            self.stateChanged.emit()
            return
        assessment = (
            self._state["review"] if self._state["reviewing"] else self._state["assessment"]
        )
        if (
            self._state["busy"] or self._state["refreshing"] or self._state["uncertain_save"]
            or not self._can_finalize(assessment)
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
        self._save_election_command("finalizations", payload, password)

    @Slot(str, str)
    def reopen(self, reason: str, password: str) -> None:
        election_id = self._state["election_id"]
        current = self._state["election"]
        history = self._state["history"]
        election = history.get("election") or {}
        events = history.get("events") or []
        previous = events[0] if events else {}
        if (
            self._state["role"] != "supervisor" or self._state["busy"]
            or self._state["refreshing"] or self._state["uncertain_save"]
            or type(election_id) is not int or election_id <= 0
            or current.get("status") != "finalized"
            or election.get("id") != election_id or election.get("status") != "finalized"
            or type(election.get("revision")) is not int
            or type(current.get("revision")) is int
            and current["revision"] != election["revision"]
            or previous.get("election_id") != election_id
            or previous.get("kind") != "finalization"
            or previous.get("election_revision") != election["revision"]
            or type(previous.get("id")) is not int or previous["id"] <= 0
        ):
            self._state["error"] = "election_reopening_not_ready"
            self.stateChanged.emit()
            return
        reason = reason.strip()
        if not reason or not password:
            self._state["error"] = "reason_required" if not reason else "invalid_credentials"
            self.stateChanged.emit()
            return
        payload = {
            "request_id": str(uuid4()), "expected_election_revision": election["revision"],
            "previous_finalization_id": previous["id"], "reason": reason,
        }
        self._save_election_command("reopenings", payload, password)

    def _save_election_command(
        self, action: str, payload: dict[str, Any], password: str,
    ) -> None:
        election_id = self._state["election_id"]
        path = f"/api/workspace/elections/{election_id}/{action}"
        command = {
            "namespace": "election", "election_id": election_id,
            "workflow": "election_completion", "method": "POST", "path": path,
            "actor_id": self._state["actor_id"], "request_id": payload["request_id"],
            "payload": deepcopy(payload),
        }
        self._command = command
        self._generation += 1
        generation = self._generation
        self._state.update(
            busy=True, error="", pending_request_id=payload["request_id"],
            review={}, reviewing=False, newer_basis=False,
        )
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
