"""Reviewed EPR fallback and recovery commands through the authenticated public API."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.event_times import format_event_time
from election.desktop.lifecycle import HKT

MAX_QUANTITY = 9223372036854775807


def empty_forms() -> dict[str, str]:
    return {
        "kind": "activation", "event_time": "", "cumulative_quantity": "",
        "stock_snapshot_id": "", "stock_snapshot_revision": "", "source_context": "",
        "activation_id": "", "activation_revision": "", "reason": "",
    }


def event_text(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(HKT)
    return parsed.replace(tzinfo=None).isoformat(sep=" ")


def record_display(row: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    result["cumulative_quantity_display"] = str(row["cumulative_quantity"])
    return result


class FallbackController(QObject):
    stateChanged = Signal()
    erasePassword = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._opened = False
        self._reviewed = False
        self._selection_id = 0
        self._current_raw: dict[str, Any] = {}
        self._reviewed_current: dict[str, Any] = {}
        self._reviewed_schedule_revision = 0
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._reviewed = False
        self._selection_id = 0
        self._current_raw = {}
        self._reviewed_current = {}
        self._reviewed_schedule_revision = 0
        self._pending = None
        self._state = {
            "context": {}, "role": "", "station_id": 0, "schedule_revision": 0,
            "items": [], "current": {}, "selected": {}, "history": [],
            "forms": empty_forms(), "dirty": False, "busy": False, "refreshing": False,
            "newer_revision": False, "historical": False, "editing": False,
            "error": "", "notice": "",
            "mode": "normal", "active_activation_id": None,
        }
        self.erasePassword.emit()
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        station_id = context.get("station", {}).get("id", 0)
        changed = station_id != self._state["station_id"]
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._state.update(
            context=deepcopy(context), station_id=station_id,
            role=context.get("account", {}).get("role", ""),
        )
        self.stateChanged.emit()
        if changed and station_id and self._opened:
            self.reload(True)

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/fallback"

    def _error(self, code: str) -> None:
        self._state.update(
            error="fallback_validation" if code == "validation_error" else code, notice="",
        )
        self.stateChanged.emit()

    def _send(
        self, path: str, method: str, payload: dict[str, Any] | None, success: ResultHandler,
        *, background: bool = False, erase_password: bool = False,
    ) -> None:
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if erase_password:
                self.erasePassword.emit()
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if erase_password:
                self.erasePassword.emit()
            self._error(code)

        self._request(path, method, payload, done, failed)

    def _record(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and type(row.get("id")) is int and row["id"] > 0
            and type(row.get("revision")) is int and row["revision"] > 0
            and row.get("kind") in ("activation", "recovery")
            and row.get("status") in ("draft", "submitted", "approved")
            and type(row.get("cumulative_quantity")) is int
            and 0 <= row["cumulative_quantity"] <= MAX_QUANTITY
            and isinstance(row.get("source_context"), str)
            and isinstance(row.get("event_at"), str)
            and isinstance(row.get("stock_snapshot"), dict)
            and type(row.get("stock_snapshot_id")) is int
            and type(row.get("stock_snapshot_revision")) is int
        )

    def _accept(self, row: dict[str, Any], *, historical: bool = False) -> None:
        forms = empty_forms()
        if row:
            forms.update(
                kind=row["kind"], event_time=event_text(row["event_at"]),
                cumulative_quantity=str(row["cumulative_quantity"]),
                stock_snapshot_id=str(row["stock_snapshot_id"]),
                stock_snapshot_revision=str(row["stock_snapshot_revision"]),
                source_context=row["source_context"], reason=row.get("reason", ""),
                activation_id=str(row["activation_id"]) if row.get("activation_id") else "",
                activation_revision=(
                    str(row["activation_revision"]) if row.get("activation_revision") else ""
                ),
            )
        self._reviewed = True
        self._reviewed_current = deepcopy(self._current_raw)
        self._reviewed_schedule_revision = self._state["schedule_revision"]
        self._state.update(
            selected=record_display(row) if row else {}, forms=forms,
            dirty=False, newer_revision=False, historical=historical, editing=False,
        )
        self.erasePassword.emit()

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> bool:
        items, scope = data.get("items"), data.get("scope")
        if not (
            isinstance(scope, dict)
            and scope.get("station", {}).get("id") == self._state["station_id"]
            and isinstance(items, list) and all(self._record(row) for row in items)
            and data.get("mode") in ("normal", "fallback")
            and (data.get("active_activation_id") is None
                 or type(data.get("active_activation_id")) is int)
        ):
            self._error("request_failed")
            return False
        if accept and not self._selection_id and items:
            self._selection_id = items[-1]["id"]
        self._current_raw = next((row for row in items if row["id"] == self._selection_id), {})
        self._state.update(
            items=[record_display(row) for row in items],
            current=record_display(self._current_raw) if self._current_raw else {},
            mode=data["mode"], active_activation_id=data["active_activation_id"],
        )
        if accept:
            self._accept(self._current_raw)
        else:
            self._state["newer_revision"] = (
                self._current_raw != self._reviewed_current
                or self._state["schedule_revision"] != self._reviewed_schedule_revision
            )
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return True

    def _history(self) -> None:
        if not self._selection_id:
            self._state["history"] = []
            return
        identity = self._selection_id

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not (
                isinstance(rows, list)
                and all(self._record(row) and row["id"] == identity for row in rows)
            ):
                self._error("request_failed")
                return
            self._state["history"] = [record_display(row) for row in rows]

        self._send(f"{self._path()}/{identity}/history", "GET", None, loaded, background=True)

    def _load(self, *, accept: bool, background: bool = False, notice: str = "") -> None:
        def collection(data: dict[str, Any]) -> None:
            if self._loaded(data, accept=accept) and accept:
                self._pending = None
                self._state["notice"] = notice
                self._history()

        def schedule(data: dict[str, Any]) -> None:
            configured = data.get("schedule")
            context = data.get("context")
            if not (
                isinstance(configured, dict) and type(configured.get("revision")) is int
                and isinstance(context, dict)
                and context.get("station", {}).get("id") == self._state["station_id"]
            ):
                self._error("request_failed")
                return
            self._state["schedule_revision"] = configured["revision"]
            self._state["context"].update(deepcopy(context))
            self._send(self._path(), "GET", None, collection, background=background)

        self._send(
            f"/api/workspace/stations/{self._state['station_id']}/turnout", "GET", None,
            schedule, background=background,
        )

    def _can_load(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_fallback_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    @Slot(result=bool)
    def open(self) -> bool:
        self._opened = True
        if not self._state["station_id"]:
            return True
        if not self._reviewed:
            return self.reload()
        self.refresh()
        return True

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, force: bool = False) -> bool:
        if not self._can_load(force):
            return False
        self._load(accept=True)
        return True

    @Slot()
    def refresh(self) -> None:
        if (not self._opened or not self._state["station_id"]
                or self._state["busy"] or self._state["refreshing"]):
            return
        self._load(accept=False, background=True)

    @Slot(result=bool)
    @Slot(str, result=bool)
    @Slot(str, bool, result=bool)
    def newRecord(self, kind: str = "activation", discard: bool = False) -> bool:
        if self._state["role"] != "polling_officer":
            self._error("polling_officer_required")
            return False
        if self._state["context"].get("election", {}).get("status") != "active":
            self._error("election_read_only")
            return False
        if kind not in ("activation", "recovery"):
            self._error("fallback_validation")
            return False
        if not self._reviewed:
            self._error("request_failed")
            return False
        activation = next((
            row for row in self._state["items"]
            if row["id"] == self._state["active_activation_id"]
            and row["kind"] == "activation" and row["status"] == "approved"
        ), None)
        if kind == "recovery" and activation is None:
            self._error("fallback_source_conflict")
            return False
        if not self._can_load(discard):
            return False
        forms = empty_forms()
        forms["kind"] = kind
        if kind == "recovery":
            assert activation is not None
            forms["activation_id"] = str(activation["id"])
            forms["activation_revision"] = str(activation["revision"])
        self._selection_id = 0
        self._current_raw = {}
        self._reviewed_current = {}
        self._reviewed_schedule_revision = self._state["schedule_revision"]
        self._state.update(
            current={}, selected={}, history=[], forms=forms,
            dirty=False, historical=False, newer_revision=False, editing=False,
        )
        self.erasePassword.emit()
        self.stateChanged.emit()
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def selectRecord(self, identity: int, discard: bool = False) -> bool:
        if type(identity) is not int or identity < 1:
            self._error("fallback_validation")
            return False
        if not any(row["id"] == identity for row in self._state["items"]):
            self._error("fallback_record_not_found")
            return False
        if not self._can_load(discard):
            return False
        self._selection_id = identity
        self._load(accept=True)
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        if not self._selection_id or type(revision) is not int or revision < 1:
            return False
        if not self._can_load(discard):
            return False
        identity = self._selection_id

        def loaded(data: dict[str, Any]) -> None:
            if not self._record(data) or data["id"] != identity or data["revision"] != revision:
                self._error("request_failed")
                return
            self._accept(data, historical=revision != self._current_raw.get("revision"))
            self._history()

        self._send(f"{self._path()}/{identity}?revision={revision}", "GET", None, loaded)
        return True

    @Slot(result=bool)
    def beginAmend(self) -> bool:
        if self._state["busy"]:
            return False
        if self._state["role"] != "polling_officer":
            self._error("polling_officer_required")
            return False
        if (self._state["historical"]
                or self._state["context"].get("election", {}).get("status") != "active"):
            self._error("election_read_only")
            return False
        if not self._reviewed:
            self._error("request_failed")
            return False
        if self._state["newer_revision"]:
            self._error("fallback_review_required")
            return False
        selected = self._state["selected"]
        if (selected.get("status") not in ("submitted", "approved")
                or selected.get("id") != self._current_raw.get("id")
                or selected.get("revision") != self._current_raw.get("revision")):
            self._error("fallback_state_conflict")
            return False
        if not self._state["editing"]:
            self._state["forms"]["reason"] = ""
            self._state.update(editing=True, dirty=False, error="", notice="")
            self._pending = None
            self.stateChanged.emit()
        return True

    @Slot(str, str)
    def setField(self, name: str, text: str) -> None:
        if (name not in self._state["forms"] or name == "kind"
                or self._state["role"] != "polling_officer"
                or self._state["busy"] or self._state["historical"] or not self._reviewed
                or (self._state["selected"] and not self._state["editing"])
                or self._state["context"].get("election", {}).get("status") != "active"):
            return
        self._state["forms"][name] = text
        self._state.update(dirty=True, notice="", error="")
        self.stateChanged.emit()

    def _content(self, *, amend: bool = False) -> dict[str, Any] | None:
        form = self._state["forms"]
        try:
            kind = form["kind"]
            if kind not in ("activation", "recovery"):
                raise ValueError("Select an activation or recovery")
            values: dict[str, Any] = {"kind": kind}
            quantities: tuple[str, ...] = (
                "cumulative_quantity", "stock_snapshot_id", "stock_snapshot_revision",
            )
            if kind == "recovery":
                quantities += ("activation_id", "activation_revision")
            for name in quantities:
                text = form[name].strip()
                if not text or not text.isascii() or not text.isdecimal():
                    raise ValueError("Use an exact nonnegative ASCII integer")
                quantity = int(text)
                if quantity > MAX_QUANTITY or (name != "cumulative_quantity" and quantity < 1):
                    raise ValueError("Quantity is outside the supported range")
                values[name] = quantity
            event_at = datetime.fromisoformat(form["event_time"].strip())
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=HKT)
            values["event_at"] = event_at.isoformat()
            if not form["source_context"].strip() or len(form["source_context"]) > 2000:
                raise ValueError("A supplied source context is required")
            values["source_context"] = form["source_context"]
            if kind == "recovery" or amend:
                if not form["reason"].strip() or len(form["reason"]) > 2000:
                    raise ValueError("Explain the recovery or reasoned correction")
                values["reason"] = form["reason"]
            return values
        except (ValueError, OverflowError):
            self._error("fallback_validation")
            return None

    def _command(self, action: str, *, password: str = "") -> None:
        approval = action == "approve"
        if approval:
            self.erasePassword.emit()
        if not self._state["station_id"] or self._state["busy"]:
            return
        role = "supervisor" if approval else "polling_officer"
        if self._state["role"] != role:
            self._error(role + "_required")
            return
        if (self._state["historical"]
                or self._state["context"].get("election", {}).get("status") != "active"):
            self._error("election_read_only")
            return
        if not self._reviewed:
            self._error("request_failed")
            return
        if action not in ("save", "amend") and self._state["dirty"]:
            self._error("unsaved_fallback_changes")
            return
        if self._state["newer_revision"]:
            self._error("fallback_review_required")
            return
        selected = self._state["selected"]
        status = selected.get("status", "missing")
        expected = {
            "save": ("missing",), "submit": ("draft",), "approve": ("submitted",),
            "amend": ("submitted", "approved"),
        }
        if status not in expected[action] or (action == "amend" and not self._state["editing"]):
            self._error("fallback_state_conflict")
            return
        values = self._content(amend=action == "amend") if action in ("save", "amend") else {}
        if values is None:
            return
        payload = {"expected_schedule_revision": self._state["schedule_revision"], **values}
        if action != "save":
            payload["expected_revision"] = selected["revision"]
        signature = json.dumps({
            "station_id": self._state["station_id"], "record_id": selected.get("id"),
            "action": action, "data": payload,
        }, sort_keys=True)
        if self._pending is None or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        if approval:
            payload["password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._record(data):
                self._error("request_failed")
                return
            self._selection_id = data["id"]
            self._load(accept=True, notice={
                "save": "fallback_saved", "submit": "fallback_submitted",
                "approve": "fallback_approved", "amend": "fallback_amended",
            }[action])

        path = self._path() + (f"/{selected['id']}/{action}" if action != "save" else "")
        self._send(path, "POST", payload, saved, erase_password=approval)

    @Slot()
    def save(self) -> None:
        self._command("save")

    @Slot()
    def amend(self) -> None:
        self._command("amend")

    @Slot()
    def submit(self) -> None:
        self._command("submit")

    @Slot(str)
    def approve(self, existingPassword: str) -> None:
        self._command("approve", password=existingPassword)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)
