"""Record never-issued ordinary stock returned from a counter to the PRO."""

import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler, positive_integer
from election.desktop.lifecycle import HKT
from election.desktop.stock import serial


def empty_forms() -> dict[str, str]:
    return dict.fromkeys(
        ("counter_id", "series", "serial_from", "serial_to", "event_time", "reason"), ""
    )


def counter_row(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and type(value.get("id")) is int
        and value["id"] > 0
        and isinstance(value.get("code"), str)
        and isinstance(value.get("name"), str)
    )


class CounterReturnsController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._opened = False
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._pending = None
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "scope": {},
            "items": [],
            "counters": [],
            "selected": {},
            "forms": empty_forms(),
            "quantity_display": "—",
            "history": [],
            "history_verified": False,
            "historical": False,
            "newer_revision": False,
            "editing": False,
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
        }
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        station_id = context.get("station", {}).get("id", 0)
        changed = station_id != self._state["station_id"]
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._state.update(
            station_id=station_id,
            context=deepcopy(context),
            role=context.get("account", {}).get("role", ""),
        )
        self.stateChanged.emit()
        if changed and station_id and self._opened:
            self.refresh()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/stock-returns"

    def _writable(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._state["role"] == "polling_officer"
            and self._state["context"].get("election", {}).get("status") in ("draft", "active")
            and not self._state["busy"]
            and not self._state["historical"]
            and (not self._state["selected"] or self._state["history_verified"])
        )

    def _editable(self) -> bool:
        return self._writable() and bool(not self._state["selected"] or self._state["editing"])

    def _error(self, code: str) -> None:
        self._state.update(
            error="counter_return_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _send(
        self,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        background: bool = False,
        suffix: str = "",
    ) -> None:
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._error(code)

        self._request(self._path() + suffix, method, payload, done, failed)

    def _record(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        try:
            if not (
                type(value["id"]) is int
                and value["id"] > 0
                and type(value["station_id"]) is int
                and value["station_id"] == self._state["station_id"]
                and type(value["revision"]) is int
                and value["revision"] > 0
                and value["status"] == "recorded"
                and value["kind"] == "unissued_counter_to_pro"
                and counter_row(value["counter"])
                and isinstance(value["series"], str)
                and value["series"].strip()
                and len(value["series"]) <= 64
                and isinstance(value["serial_from"], str)
                and isinstance(value["serial_to"], str)
                and type(value["quantity"]) is int
                and value["quantity"] > 0
                and value["quantity"]
                == serial(value["serial_to"]) - serial(value["serial_from"]) + 1
                and type(value["actor_id"]) is int
                and value["actor_id"] > 0
                and isinstance(value["reason"], str)
                and len(value["reason"]) <= 1000
                and isinstance(value["allocation_basis"], list)
                and value["allocation_basis"]
            ):
                return False
            for name in ("event_at", "entered_at"):
                parsed = datetime.fromisoformat(value[name])
                if parsed.utcoffset() is None:
                    return False
                parsed.astimezone(HKT)
            return all(
                isinstance(part, dict)
                and type(part["allocation_id"]) is int
                and part["allocation_id"] > 0
                and type(part["revision"]) is int
                and part["revision"] > 0
                and isinstance(part["serial_from"], str)
                and isinstance(part["serial_to"], str)
                and type(part["quantity"]) is int
                and part["quantity"] > 0
                and serial(part["serial_from"]) <= serial(part["serial_to"])
                for part in value["allocation_basis"]
            )
        except KeyError, TypeError, ValueError, OverflowError:
            return False

    def _loaded(self, data: dict[str, Any]) -> None:
        if not all(key in data for key in ("scope", "items", "counters")):
            self._error("request_failed")
            return
        scope, items, counters = data["scope"], data["items"], data["counters"]
        if not (
            isinstance(scope, dict)
            and isinstance(scope.get("station"), dict)
            and scope["station"].get("id") == self._state["station_id"]
            and isinstance(scope.get("election"), dict)
            and scope["election"].get("status") in ("draft", "active", "finalized")
            and isinstance(items, list)
            and all(self._record(row) for row in items)
            and len({row["id"] for row in items}) == len(items)
            and isinstance(counters, list)
            and all(counter_row(row) for row in counters)
            and len({row["id"] for row in counters}) == len(counters)
        ):
            self._error("request_failed")
            return
        self._state.update(
            scope=deepcopy(scope),
            context={**self._state["context"], **scope},
            items=deepcopy(items),
            counters=deepcopy(counters),
        )
        selected = self._state["selected"]
        if selected:
            head = next((row for row in items if row["id"] == selected["id"]), None)
            history = self._state["history"]
            known = [selected, *history, *([head] if head is not None else [])]
            historical = selected["revision"] < max(row["revision"] for row in known)
            self._state.update(
                historical=historical,
                newer_revision=historical or head is None or head != selected,
            )
            if head is None or not any(row == head for row in history):
                self._state["history_verified"] = False
            if historical:
                self._state["editing"] = False

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if (
            not self._opened
            or not self._state["station_id"]
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return
        self._send("GET", None, self._loaded, background=True)

    def _begin_selection(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_counter_return_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(
            refreshing=False, error="", notice="", history_verified=False, editing=False
        )
        return True

    def _history(self, *, refresh_after: bool = False) -> None:
        return_id = self._state["selected"]["id"]

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            selected = self._state["selected"]
            known = [
                selected,
                *self._state["history"],
                *[row for row in self._state["items"] if row["id"] == return_id],
            ]
            if not (
                isinstance(rows, list)
                and rows
                and all(
                    self._record(row) and row["id"] == return_id and row["revision"] == index
                    for index, row in enumerate(rows, 1)
                )
                and all(
                    saved["revision"] <= len(rows) and rows[saved["revision"] - 1] == saved
                    for saved in known
                )
            ):
                self._error("request_failed")
                return
            head = rows[-1]
            self._state.update(
                history=deepcopy(rows),
                history_verified=True,
                historical=selected["revision"] < head["revision"],
                newer_revision=selected != head,
            )
            if self._state["historical"]:
                self._state["editing"] = False
            items = {row["id"]: row for row in self._state["items"]}
            items[return_id] = deepcopy(head)
            self._state["items"] = sorted(items.values(), key=lambda row: row["id"])
            if refresh_after:
                self.refresh()

        self._send("GET", None, loaded, suffix=f"/{return_id}/history")

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadReturn(self, return_id: int, discard: bool = False) -> bool:
        if return_id < 1 or not self._begin_selection(discard):
            return False

        def loaded(data: dict[str, Any]) -> None:
            if not self._record(data) or data["id"] != return_id:
                self._error("request_failed")
                return
            self._accept(data)
            self._history()

        self._send("GET", None, loaded, suffix=f"/{return_id}")
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        selected = self._state["selected"]
        if not selected or revision < 1 or not self._begin_selection(discard):
            return False
        return_id = selected["id"]

        def loaded(data: dict[str, Any]) -> None:
            if (
                not self._record(data)
                or data["id"] != return_id
                or data["revision"] != revision
            ):
                self._error("request_failed")
                return
            self._accept(data)
            self._history()

        self._send("GET", None, loaded, suffix=f"/{return_id}?revision={revision}")
        return True

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def newReturn(self, discard: bool = False) -> bool:
        if not self._begin_selection(discard):
            return False
        self._state.update(
            selected={},
            forms=empty_forms(),
            quantity_display="—",
            history=[],
            history_verified=False,
            dirty=False,
            historical=False,
            newer_revision=False,
            editing=False,
        )
        self.stateChanged.emit()
        self.refresh()
        return True

    @Slot(result=bool)
    def editSelected(self) -> bool:
        if not self._state["selected"] or not self._writable():
            self._error("election_read_only")
            return False
        self._state.update(editing=True, error="", notice="")
        self.stateChanged.emit()
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._editable()
            and name in self._state["forms"]
            and self._state["forms"][name] != value
        ):
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self._calculate()
            self.stateChanged.emit()

    def _calculate(self) -> None:
        form = self._state["forms"]
        try:
            quantity = serial(form["serial_to"]) - serial(form["serial_from"]) + 1
            self._state["quantity_display"] = str(quantity) if quantity > 0 else "—"
        except ValueError:
            self._state["quantity_display"] = "—"

    def _payload(self) -> dict[str, Any] | None:
        form = self._state["forms"]
        try:
            counter_id = positive_integer(form["counter_id"])
            if counter_id is None or not any(
                row["id"] == counter_id for row in self._state["counters"]
            ):
                raise ValueError("Choose an assigned station counter")
            if not form["series"].strip() or len(form["series"]) > 64:
                raise ValueError("A ballot series is required")
            if serial(form["serial_to"]) < serial(form["serial_from"]):
                raise ValueError("Range is reversed")
            event_text = form["event_time"].strip()
            if not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?",
                event_text,
            ):
                raise ValueError("Use a local Hong Kong date and time")
            event = datetime.fromisoformat(event_text).replace(tzinfo=HKT)
            selected = self._state["selected"]
            original = selected.get("event_at")
            unchanged_minute = bool(
                original
                and event_text
                == datetime.fromisoformat(original).astimezone(HKT).strftime("%Y-%m-%d %H:%M")
            )
            payload = {
                "counter_id": counter_id,
                "series": form["series"],
                "serial_from": form["serial_from"],
                "serial_to": form["serial_to"],
                "event_at": original if unchanged_minute else event.isoformat(),
            }
            if selected:
                reason = form["reason"]
                if not reason.strip() or len(reason) > 1000:
                    raise ValueError("A correction reason is required")
                payload.update(revision=selected["revision"], reason=reason)
            return payload
        except ValueError:
            self._error("counter_return_validation")
            return None

    def _matches_command(
        self, data: dict[str, Any], payload: dict[str, Any], return_id: int
    ) -> bool:
        return bool(
            self._record(data)
            and data["revision"] == payload.get("revision", 0) + 1
            and (not return_id or data["id"] == return_id)
            and data["counter"]["id"] == payload["counter_id"]
            and all(data[key] == payload[key] for key in ("series", "serial_from", "serial_to"))
            and datetime.fromisoformat(data["event_at"])
            == datetime.fromisoformat(payload["event_at"])
            and data["reason"] == payload.get("reason", "")
        )

    def _accept(self, data: dict[str, Any]) -> None:
        local = datetime.fromisoformat(data["event_at"]).astimezone(HKT)
        previous = self._state["selected"]
        same_return = previous.get("id") == data["id"]
        history = deepcopy(self._state["history"]) if same_return else []
        known = history + [row for row in self._state["items"] if row["id"] == data["id"]]
        if same_return:
            known.append(previous)
        head_revision = max([data["revision"], *[row["revision"] for row in known]])
        self._state.update(
            selected=deepcopy(data),
            dirty=False,
            editing=False,
            historical=data["revision"] < head_revision,
            newer_revision=data["revision"] < head_revision,
            history=history,
            history_verified=False,
            quantity_display=str(data["quantity"]),
            forms={
                "counter_id": str(data["counter"]["id"]),
                "series": data["series"],
                "serial_from": data["serial_from"],
                "serial_to": data["serial_to"],
                "event_time": local.strftime("%Y-%m-%d %H:%M"),
                "reason": "",
            },
        )

    @Slot()
    def save(self) -> None:
        if self._state["busy"]:
            return
        if not self._editable():
            self._error("election_read_only")
            return
        payload = self._payload()
        if payload is None:
            return
        return_id = self._state["selected"].get("id", 0)
        signature = json.dumps(
            {"station": self._state["station_id"], "return": return_id, "data": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._matches_command(data, payload, return_id):
                self._error("request_failed")
                return
            self._accept(data)
            self._pending = None
            self._state["notice"] = "counter_return_saved"
            self._history(refresh_after=True)

        self._send(
            "PUT" if return_id else "POST",
            payload,
            saved,
            suffix=f"/{return_id}" if return_id else "",
        )
