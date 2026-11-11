"""One constituency instruction draft, with an immutable recoverable command."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.event_times import format_event_time, parse_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.operational_receipts import valid_operational_receipt
from election.desktop.recovery import NETWORK_ERRORS, RecoveryController

STALE_ERRORS = frozenset(
    {
        "constituency_result_basis_stale",
        "constituency_result_incomplete",
        "constituency_recount_sources_stale",
        "active_election_required",
    }
)


class ConstituencyRecountsController(QObject):
    stateChanged = Signal()
    instructed = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject,
        recovery: RecoveryController | None,
    ) -> None:
        super().__init__(parent)
        self._request, self._recovery = request, recovery
        self._generation = 0
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
        self._command: dict[str, Any] | None = None
        self._state = {
            "context": {},
            "constituency_id": 0,
            "account_id": 0,
            "station_id": 0,
            "role": "",
            "basis_digest": "",
            "scope_sources": [],
            "instructions": [],
            "forms": {"event_at": "", "reason": ""},
            "can_instruct": False,
            "dirty": False,
            "newer_basis": False,
            "uncertain_save": False,
            "pending_request_id": "",
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
        }
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        identity = {
            "constituency_id": (context.get("constituency") or {}).get("id", 0),
            "account_id": (context.get("account") or {}).get("id", 0),
            "station_id": (context.get("station") or {}).get("id", 0),
            "role": (context.get("account") or {}).get("role", ""),
        }
        changed = any(self._state[key] != value for key, value in identity.items())
        opened = self._opened
        if changed:
            self.reset()
            self._opened = opened
        self._state.update(context=deepcopy(context), **identity)
        self._sync_recovery()
        self.stateChanged.emit()
        if changed and self._opened:
            self.reload()

    def blocks_navigation(self) -> bool:
        return any(
            self._state[key]
            for key in (
                "dirty",
                "busy",
                "uncertain_save",
                "newer_basis",
            )
        )

    def blocks_context_change(self) -> bool:
        return bool(self._state["uncertain_save"] or (self._command and self._state["busy"]))

    def _path(self) -> str:
        return f"/api/workspace/constituencies/{self._state['constituency_id']}/recounts"

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    def _editable(self) -> bool:
        return bool(
            self._state["role"] == "supervisor"
            and self._state["constituency_id"]
            and self._state["context"].get("election", {}).get("status") == "active"
            and not any(self._state[key] for key in ("busy", "uncertain_save", "newer_basis"))
        )

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.reload()

    @Slot()
    def reload(self) -> None:
        self._load(background=False)

    @Slot()
    def refresh(self) -> None:
        if self._opened:
            self._load(background=True)

    def _load(self, *, background: bool) -> None:
        if (
            not self._state["constituency_id"]
            or self._state["role"] != "supervisor"
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return
        self._generation += 1
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            context = body.get("context")
            if not (
                isinstance(context, dict)
                and isinstance(context.get("constituency"), dict)
                and isinstance(context.get("election"), dict)
                and context["constituency"].get("id") == self._state["constituency_id"]
                and context.get("election", {}).get("id")
                == self._state["context"].get("election", {}).get("id")
                and isinstance(body.get("basis_digest"), str)
                and isinstance(body.get("scope_sources"), list)
                and all(isinstance(row, dict) for row in body["scope_sources"])
                and isinstance(body.get("instructions"), list)
                and all(isinstance(row, dict) for row in body["instructions"])
                and type(body.get("can_instruct")) is bool
            ):
                self._error("constituency_recount_invalid_response")
                return
            protected = self._state["dirty"] or self._state["uncertain_save"]
            if protected and self._state["basis_digest"]:
                if (
                    self._state["basis_digest"] != body["basis_digest"]
                    or self._state["scope_sources"] != body["scope_sources"]
                ):
                    self._state.update(newer_basis=True)
            else:
                self._state.update(
                    basis_digest=body["basis_digest"],
                    scope_sources=deepcopy(body["scope_sources"]),
                    newer_basis=False,
                )
            self._state.update(
                instructions=deepcopy(body["instructions"]), can_instruct=body["can_instruct"]
            )
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._error(code)

        self._request(self._path(), "GET", None, loaded, failed)

    @Slot(str, str)
    def setField(self, field: str, value: str) -> None:
        if field not in self._state["forms"] or not self._editable():
            return
        if self._state["forms"][field] == value:
            return
        self._command = None
        self._state["forms"][field] = value
        self._state.update(
            dirty=any(self._state["forms"].values()), pending_request_id="", error="", notice=""
        )
        self.stateChanged.emit()

    @Slot()
    def discardDraft(self) -> None:
        if self._state["busy"] or self._state["uncertain_save"]:
            return
        self._command = None
        self._state.update(
            forms={"event_at": "", "reason": ""},
            dirty=False,
            newer_basis=False,
            pending_request_id="",
            error="",
            notice="",
        )
        self.reload()

    @Slot()
    def checkOutcome(self) -> None:
        if self._recovery is not None and self._state["pending_request_id"]:
            self._recovery.open()
            self._recovery.checkOutcome(self._state["pending_request_id"])

    def _settled(self) -> None:
        self._command = None
        self._state.update(
            busy=False,
            refreshing=False,
            forms={"event_at": "", "reason": ""},
            dirty=False,
            uncertain_save=False,
            pending_request_id="",
            newer_basis=True,
            can_instruct=False,
            error="",
            notice="constituency_recount_saved",
        )
        self.stateChanged.emit()
        self.instructed.emit()
        self.refresh()

    def _sync_recovery(self) -> None:
        if self._recovery is None:
            return
        command = next(
            (
                row
                for row in self._recovery.property("state")["commands"]
                if (
                    row.get("workflow") == "constituency_recount"
                    and row.get("path") == self._path()
                    and row.get("actor_id") == self._state["account_id"]
                    and row.get("station_id") == self._state["station_id"]
                    and (
                        row.get("request_id") == self._state["pending_request_id"]
                        if self._state["pending_request_id"]
                        else row.get("status") in {"pending", "uncertain"}
                    )
                )
            ),
            None,
        )
        if command is None:
            return
        if command.get("status") in {"pending", "uncertain"}:
            if self._command is None:
                self._command = deepcopy(command)
                payload = command["payload"]
                self._state.update(
                    basis_digest=payload["basis_digest"],
                    scope_sources=deepcopy(payload["scope_sources"]),
                    forms={
                        "event_at": format_event_time(payload["event_at"]).removesuffix(" HKT"),
                        "reason": payload["reason"],
                    },
                    dirty=True,
                )
            self._state.update(uncertain_save=True, pending_request_id=command["request_id"])
            self.stateChanged.emit()
        elif command.get("status") == "committed":
            receipt = command.get("receipt") or {}
            if valid_operational_receipt(command, receipt.get("record")):
                self._settled()
        elif command.get("status") == "rejected":
            code = command.get("error") or "constituency_recount_not_ready"
            self._command = None
            self._state.update(
                uncertain_save=False, pending_request_id="", newer_basis=code in STALE_ERRORS
            )
            self._error(code)

    @Slot(str)
    def instruct(self, password: str) -> None:
        if not self._editable() or not self._state["can_instruct"]:
            self._error("constituency_recount_not_ready")
            return
        if not password:
            self._error("invalid_credentials")
            return
        form = self._state["forms"]
        if not form["reason"].strip() or len(form["reason"]) > 2000:
            self._error("constituency_recount_reason_required")
            return
        try:
            event_at = parse_event_time(form["event_at"])
        except ValueError:
            self._error("constituency_recount_event_required")
            return
        payload = {
            "request_id": str(uuid4()),
            "basis_digest": self._state["basis_digest"],
            "scope_sources": deepcopy(self._state["scope_sources"]),
            "event_at": event_at,
            "reason": form["reason"],
        }
        command = {
            "workflow": "constituency_recount",
            "method": "POST",
            "path": self._path(),
            "request_id": payload["request_id"],
            "payload": payload,
            "actor_id": self._state["account_id"],
            "station_id": self._state["station_id"],
        }
        self._command = command
        self._generation += 1
        generation = self._generation
        self._state.update(
            busy=True,
            refreshing=False,
            error="",
            notice="",
            pending_request_id=payload["request_id"],
        )
        self.stateChanged.emit()

        def saved(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not valid_operational_receipt(command, body):
                self._state.update(busy=False, uncertain_save=True)
                self._error("constituency_recount_invalid_response")
                return
            self._settled()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            uncertain = code in NETWORK_ERRORS - {"recovery_journal_unavailable"}
            self._state.update(
                busy=False, uncertain_save=uncertain, newer_basis=code in STALE_ERRORS
            )
            if not uncertain:
                self._command = None
                self._state["pending_request_id"] = ""
            self._error(code)

        self._request(self._path(), "POST", {**payload, "password": password}, saved, failed)
