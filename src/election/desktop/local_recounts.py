"""A Supervisor's recount instruction draft, separate from observed tally inputs."""

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.event_times import format_event_time, parse_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.operational_receipts import valid_operational_receipt
from election.desktop.recovery import RecoveryController

NETWORK_ERRORS = frozenset({
    "request_failed", "disconnected", "database_unavailable",
    "recovery_journal_outcome_unavailable",
})
STALE_ERRORS = frozenset({
    "count_scope_revision_conflict", "count_scope_not_ready", "local_recount_selection_stale",
    "local_recount_source_stale", "local_recount_pending",
})


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _aware(value: Any) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _same_time(first: Any, second: Any) -> bool:
    return bool(_aware(first) and _aware(second)
                and datetime.fromisoformat(first) == datetime.fromisoformat(second))


class LocalRecountsController(QObject):
    stateChanged = Signal()
    instructed = Signal()

    def __init__(
        self, request: AuthorizedRequest, parent: QObject | None = None,
        *, recovery: RecoveryController | None = None,
    ) -> None:
        super().__init__(parent)
        self._request, self._recovery = request, recovery
        self._generation = 0
        self._pending: dict[str, Any] | None = None
        self._read_allowed = False
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        view = qt_state(quantity_display(self._state))
        view["can_instruct"] = self._editable()
        return view

    def reset(self) -> None:
        self._generation += 1
        self._pending = None
        self._restored_request_id = ""
        self._restored_owns_draft = False
        self._read_allowed = False
        self._state = {
            "context": {}, "station_id": 0, "election_id": 0, "actor_id": 0,
            "role": "", "scope_id": 0, "scope": {}, "selection": {},
            "instructions": [], "latest_instruction": None, "pending": False,
            "forms": {"event_at": "", "reason": ""}, "dirty": False,
            "busy": False, "refreshing": False, "newer_basis": False,
            "uncertain_save": False, "pending_request_id": "", "error": "", "notice": "",
        }
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any], scope_id: int) -> None:
        station = context.get("station") or {}
        election = context.get("election") or {}
        account = context.get("account") or {}
        identity = {
            "station_id": station.get("id", 0), "election_id": election.get("id", 0),
            "actor_id": account.get("id", 0), "role": account.get("role", ""),
            "scope_id": scope_id,
        }
        changed = any(self._state[key] != value for key, value in identity.items())
        if changed:
            self.reset()
        self._state.update(context=deepcopy(context), **identity)
        if self._recovery is not None:
            self.sync_recovery(self._recovery.property("state")["commands"])
        self.stateChanged.emit()
        if changed and _positive(identity["station_id"]) and _positive(scope_id):
            self.reload()

    def activity(self) -> tuple[bool, bool]:
        return bool(self._state["busy"]), bool(self._state["refreshing"])

    def blocks_navigation(self) -> bool:
        return bool(self._state["dirty"] or self._state["busy"] or self._state["uncertain_save"])

    def outcome_unknown(self) -> bool:
        return bool(self._state["uncertain_save"])

    def blocks_context_change(self) -> bool:
        return self.outcome_unknown() or bool(self._pending is not None and self._state["busy"])

    def _path(self) -> str:
        return (
            f"/api/workspace/stations/{self._state['station_id']}/counting-scopes/"
            f"{self._state['scope_id']}/recounts"
        )

    def _editable(self) -> bool:
        return bool(
            self._read_allowed and self._state["role"] == "supervisor"
            and not (self._recovery is not None and self._recovery.recount_context_locked())
            and self._state["context"].get("election", {}).get("status") == "active"
            and not any(self._state[key] for key in (
                "busy", "newer_basis", "uncertain_save"
            ))
        )

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    @staticmethod
    def _basis(scope: dict[str, Any], selection: dict[str, Any], pending: bool) -> tuple[Any, ...]:
        return (
            scope.get("id"), scope.get("revision"), scope.get("revision_id"),
            selection.get("id"), selection.get("revision"), selection.get("round_id"),
            selection.get("round_revision"), selection.get("round_revision_id"),
            selection.get("valid"), selection.get("is_current"), pending,
        )

    def _valid_read(self, body: dict[str, Any]) -> bool:
        context, scope = body.get("context"), body.get("scope")
        return bool(
            isinstance(context, dict) and isinstance(scope, dict)
            and all(isinstance(context.get(key), dict)
                    for key in ("station", "election", "constituency"))
            and context["station"].get("id") == self._state["station_id"]
            and context["election"].get("id") == self._state["election_id"]
            and context["constituency"].get("id")
            == self._state["context"].get("constituency", {}).get("id")
            and scope.get("id") == self._state["scope_id"]
            and _positive(scope.get("revision")) and _positive(scope.get("revision_id"))
            and (body.get("selection") is None or isinstance(body.get("selection"), dict))
            and isinstance(body.get("instructions"), list)
            and all(isinstance(row, dict) for row in body["instructions"])
            and (body.get("latest_instruction") is None
                 or isinstance(body.get("latest_instruction"), dict))
            and type(body.get("pending")) is bool and type(body.get("can_instruct")) is bool
        )

    def _adopt_read(self, body: dict[str, Any]) -> None:
        # The read DTO has no account; retain the trusted parent context and actor.
        self._read_allowed = body["can_instruct"]
        self._state.update(
            scope=deepcopy(body["scope"]), selection=deepcopy(body.get("selection") or {}),
            instructions=deepcopy(body["instructions"]),
            latest_instruction=deepcopy(body["latest_instruction"]), pending=body["pending"],
        )

    def _load(self, *, background: bool, check: bool = False) -> None:
        if (not self._state["scope_id"] or self._state["busy"] or self._state["refreshing"]):
            return
        self._generation += 1
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        if not background:
            self._state.update(error="", notice="")
        self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if not self._valid_read(body):
                self._error("local_recount_invalid_response")
                return
            if check and self._pending is not None:
                matches = [row for row in body["instructions"]
                           if row.get("request_id") == self._pending["command"]["request_id"]]
                if len(matches) != 1 or not self._matches_instruction(matches[0]):
                    self._error("local_recount_outcome_unconfirmed")
                    return
                self._adopt_read(body)
                self._settled()
                return
            if self._restored_request_id and not self._state["scope"]:
                # This fresh read supplies display context, never the retained command body.
                self._adopt_read(body)
            elif (self._state["dirty"] or self._state["uncertain_save"]
                  or self._state["newer_basis"]):
                old = self._basis(
                    self._state["scope"], self._state["selection"], self._state["pending"]
                )
                latest = self._basis(body["scope"], body.get("selection") or {}, body["pending"])
                if old != latest or self._read_allowed != body["can_instruct"]:
                    self._state.update(newer_basis=True, notice="local_recount_newer_basis")
            else:
                self._adopt_read(body)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._error(code)

        self._request(self._path(), "GET", None, loaded, failed)

    @Slot()
    def reload(self) -> None:
        self._load(background=bool(self._state["dirty"] or self._state["uncertain_save"]))

    @Slot()
    def refresh(self) -> None:
        self._load(background=True)

    @Slot(str, str)
    def setField(self, field: str, value: str) -> None:
        if field not in self._state["forms"] or not self._editable():
            return
        if self._state["forms"][field] == value:
            return
        self._pending = None
        self._state["forms"][field] = value
        self._state.update(
            dirty=any(self._state["forms"].values()), pending_request_id="", error="", notice=""
        )
        self.stateChanged.emit()

    @Slot()
    def discardAndReload(self) -> None:
        if self._state["busy"] or self._state["refreshing"]:
            return
        if self._state["uncertain_save"]:
            self._error("local_recount_outcome_unconfirmed")
            return
        self._pending = None
        self._state.update(
            forms={"event_at": "", "reason": ""}, dirty=False, newer_basis=False,
            pending_request_id="", error="", notice="",
        )
        self.reload()

    @Slot()
    def checkOutcome(self) -> None:
        if not self._state["uncertain_save"]:
            return
        request_id = self._state["pending_request_id"]
        if self._recovery is not None and request_id:
            self._recovery.open()
            self._recovery.checkOutcome(request_id)
        elif self._pending is not None:
            self._load(background=False, check=True)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)

    def _matches_instruction(self, instruction: dict[str, Any]) -> bool:
        if self._pending is None:
            return False
        command = self._pending["command"]
        return bool(
            all(_positive(instruction.get(key)) for key in (
                "id", "new_round_id", "new_round_number", "actor_id", "scope_id",
                "scope_revision", "scope_revision_id", "source_round_id",
                "source_round_revision", "source_round_revision_id",
            ))
            and instruction["new_round_id"] != command["source_round_id"]
            and _positive(instruction.get("new_round_number"))
            and instruction["new_round_number"] > self._pending["source_round_number"]
            and instruction.get("actor_id") == self._state["actor_id"]
            and instruction.get("scope_id") == self._state["scope_id"]
            and instruction.get("scope_revision_id") == self._pending["scope_revision_id"]
            and instruction.get("source_round_revision_id") == self._pending["source_revision_id"]
            and all(instruction.get(key) == command[key] for key in (
                "request_id", "scope_revision", "source_round_id", "source_round_revision", "reason"
            ))
            and _same_time(instruction.get("event_at"), command["event_at"])
            and _aware(instruction.get("entered_at"))
            and instruction.get("status") in ("pending", "completed")
        )

    def _valid_ack(self, body: dict[str, Any]) -> bool:
        instruction, round = body.get("instruction"), body.get("round")
        if not isinstance(instruction, dict) or not isinstance(round, dict):
            return False
        if not self._matches_instruction(instruction):
            return False
        scope_basis = round.get("scope_basis")
        return bool(
            instruction.get("status") == "pending" and instruction.get("is_latest") is True
            and instruction.get("current_satisfied") is False
            and round.get("id") == instruction["new_round_id"]
            and round.get("round_number") == instruction["new_round_number"]
            and round.get("scope_id") == instruction["scope_id"]
            and round.get("scope_revision") == instruction["scope_revision"]
            and type(round.get("revision")) is int and round["revision"] == 1
            and _positive(round.get("revision_id"))
            and round.get("status") == "draft" and round.get("f1_complete") is False
            and round.get("selected") is False and round.get("approval_valid") is False
            and isinstance(scope_basis, dict)
            and scope_basis.get("revision_id") == instruction["scope_revision_id"]
            and round.get("event_at") is None and round.get("entered_at") is None
            and round.get("actor_id") is None
            and round.get("revision_actor_id") == instruction["actor_id"]
            and _same_time(round.get("revision_event_at"), instruction["event_at"])
            and _same_time(round.get("revision_entered_at"), instruction["entered_at"])
            and round.get("actual_counted_quantity") is None and round.get("f2") is None
            and round.get("questionable_quantity") is None
            and round.get("physical_decisions") == []
            and isinstance(round.get("candidate_votes"), list)
            and all(isinstance(row, dict) and row.get("quantity") is None
                    for row in round["candidate_votes"])
            and isinstance(round.get("invalid_papers"), list)
            and all(isinstance(row, dict) and row.get("quantity") is None
                    for row in round["invalid_papers"])
        )

    def _restore_recovery(self, commands: list[dict[str, Any]]) -> None:
        command = next((row for row in commands if (
            row.get("actor_id") == self._state["actor_id"]
            and row.get("station_id") == self._state["station_id"]
            and row.get("workflow") == "count" and row.get("method") == "POST"
            and row.get("path") == self._path()
            and isinstance(row.get("payload"), dict)
            and (row.get("request_id") == self._restored_request_id
                 if self._restored_request_id else row.get("status") in {"pending", "uncertain"})
        )), None)
        if command is None:
            return
        if command.get("status") in {"pending", "uncertain"}:
            payload = command["payload"]
            if not self._restored_request_id:
                self._restored_request_id = command["request_id"]
                self._restored_owns_draft = not self._state["dirty"]
                if self._restored_owns_draft:
                    self._state.update(forms={
                        "event_at": format_event_time(
                            payload.get("event_at", "")
                        ).removesuffix(" HKT"),
                        "reason": payload.get("reason", ""),
                    }, dirty=True)
            self._state.update(uncertain_save=True, pending_request_id=self._restored_request_id)
            self.stateChanged.emit()
            return
        receipt = command.get("receipt")
        body = receipt.get("record") if isinstance(receipt, dict) else None
        if command.get("status") == "committed" and valid_operational_receipt(command, body):
            if self._restored_owns_draft:
                self._state.update(dirty=False, forms={"event_at": "", "reason": ""})
            self._state.update(uncertain_save=False, pending_request_id="", error="", notice="")
        elif command.get("status") == "rejected":
            code = str(command.get("error") or "local_recount_not_ready")
            self._state.update(
                uncertain_save=False, pending_request_id="", error=code,
                newer_basis=code in STALE_ERRORS, notice="",
            )
        else:
            return
        self._restored_request_id = ""
        self._restored_owns_draft = False
        self.stateChanged.emit()

    def sync_recovery(self, commands: list[dict[str, Any]]) -> None:
        """Restore or settle only this actor/scope's exact retained command."""
        if self._pending is None:
            self._restore_recovery(commands)
            return
        if not self._state["uncertain_save"]:
            return
        original = self._pending["command"]
        command = next((row for row in commands if (
            row.get("request_id") == original["request_id"]
            and row.get("actor_id") == self._state["actor_id"]
            and row.get("station_id") == self._state["station_id"]
            and row.get("workflow") == "count" and row.get("method") == "POST"
            and row.get("path") == self._path()
            and isinstance(row.get("payload"), dict)
            and all(row["payload"].get(key) == value for key, value in original.items())
        )), None)
        if command is None:
            return
        if command.get("status") == "rejected":
            code = str(command.get("error") or "local_recount_not_ready")
            self._pending = None
            self._state.update(
                uncertain_save=False, pending_request_id="", newer_basis=code in STALE_ERRORS,
            )
            self._error(code)
            return
        if command.get("status") != "committed":
            return
        receipt = command.get("receipt")
        body = receipt.get("record") if isinstance(receipt, dict) else None
        if isinstance(body, dict) and self._valid_ack(body):
            self._instruction_saved(body["instruction"])

    def _instruction_saved(self, instruction: dict[str, Any]) -> None:
        self._read_allowed = False
        self._state["instructions"] = [
            deepcopy(instruction),
            *(row for row in self._state["instructions"]
              if row.get("request_id") != instruction["request_id"]),
        ]
        self._state["pending"] = True
        self._state["latest_instruction"] = deepcopy(instruction)
        self._settled()

    def _settled(self) -> None:
        self._pending = None
        self._state.update(
            busy=False, refreshing=False, dirty=False, uncertain_save=False, newer_basis=False,
            pending_request_id="", forms={"event_at": "", "reason": ""}, error="",
            notice="local_recount_instructed",
        )
        self.stateChanged.emit()
        self.instructed.emit()

    @Slot(str)
    def instruct(self, password: str) -> None:
        if not self._editable():
            self._error("local_recount_outcome_unconfirmed" if self._state["uncertain_save"]
                        else "local_recount_not_ready")
            return
        if not password:
            self._error("invalid_credentials")
            return
        form = self._state["forms"]
        if not form["reason"].strip() or len(form["reason"]) > 2000:
            self._error("local_recount_reason_required")
            return
        try:
            event_at = parse_event_time(form["event_at"])
        except ValueError:
            self._error("local_recount_event_required")
            return
        scope, selection = self._state["scope"], self._state["selection"]
        if not all(_positive(value) for value in (
            scope.get("revision"), scope.get("revision_id"), selection.get("revision"),
            selection.get("round_id"), selection.get("round_revision"),
            selection.get("round_revision_id"), selection.get("round_number"),
        )):
            self._error("local_recount_not_ready")
            return
        if self._pending is None:
            self._pending = {
                "scope_revision_id": scope["revision_id"],
                "source_revision_id": selection["round_revision_id"],
                "source_round_number": selection["round_number"],
                "command": {
                    "request_id": str(uuid4()), "scope_revision": scope["revision"],
                    "expected_selection_revision": selection["revision"],
                    "source_round_id": selection["round_id"],
                    "source_round_revision": selection["round_revision"],
                    "event_at": event_at, "reason": form["reason"],
                },
            }
        command = deepcopy(self._pending["command"])
        self._generation += 1
        generation = self._generation
        self._state.update(
            busy=True, refreshing=False, pending_request_id=command["request_id"],
            error="", notice="",
        )
        self.stateChanged.emit()

        def saved(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not self._valid_ack(body):
                self._state.update(busy=False, uncertain_save=True)
                self._error("local_recount_invalid_response")
                return
            self._instruction_saved(body["instruction"])

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state.update(
                    busy=False, uncertain_save=code in NETWORK_ERRORS,
                    newer_basis=code in STALE_ERRORS,
                )
                self._error(code)

        self._request(self._path(), "POST", {**command, "password": password}, saved, failed)
