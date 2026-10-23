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

    def _editable(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._state["role"] == "polling_officer"
            and self._state["context"].get("election", {}).get("status") in ("draft", "active")
            and not self._state["busy"]
            and not self._state["selected"]
        )

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

        self._request(self._path(), method, payload, done, failed)

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
            return {
                "counter_id": counter_id,
                "series": form["series"],
                "serial_from": form["serial_from"],
                "serial_to": form["serial_to"],
                "event_at": event.isoformat(),
            }
        except ValueError:
            self._error("counter_return_validation")
            return None

    def _matches_command(self, data: dict[str, Any], payload: dict[str, Any]) -> bool:
        return bool(
            self._record(data)
            and data["revision"] == 1
            and data["counter"]["id"] == payload["counter_id"]
            and all(data[key] == payload[key] for key in ("series", "serial_from", "serial_to"))
            and datetime.fromisoformat(data["event_at"])
            == datetime.fromisoformat(payload["event_at"])
            and data["reason"] == ""
        )

    def _accept(self, data: dict[str, Any]) -> None:
        local = datetime.fromisoformat(data["event_at"]).astimezone(HKT)
        precision = (
            "microseconds" if local.microsecond else "seconds" if local.second else "minutes"
        )
        self._state.update(
            selected=deepcopy(data),
            dirty=False,
            quantity_display=str(data["quantity"]),
            forms={
                "counter_id": str(data["counter"]["id"]),
                "series": data["series"],
                "serial_from": data["serial_from"],
                "serial_to": data["serial_to"],
                "event_time": local.isoformat(sep=" ", timespec=precision)[:-6],
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
        signature = json.dumps(
            {"station": self._state["station_id"], "data": payload}, sort_keys=True
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._matches_command(data, payload):
                self._error("request_failed")
                return
            self._accept(data)
            self._pending = None
            self._state["notice"] = "counter_return_saved"
            self.refresh()

        self._send("POST", payload, saved)
