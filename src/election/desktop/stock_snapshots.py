"""Remaining-stock entry retains exact ranges and server-derived issuance."""

import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT
from election.desktop.stock import serial

QUANTITIES = (
    "ordinary_allocated_quantity",
    "ordinary_returned_quantity",
    "ordinary_net_allocated_quantity",
    "ordinary_remaining_quantity",
    "ordinary_issued_quantity",
)


def display_totals(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        key.removesuffix("_quantity") + "_display": "—"
        if snapshot.get(key) is None
        else str(snapshot[key])
        for key in QUANTITIES
    }


def range_display(value: dict[str, Any]) -> dict[str, str]:
    row = {key: value[key] for key in ("series", "serial_from", "serial_to")}
    try:
        quantity = serial(row["serial_to"]) - serial(row["serial_from"]) + 1
        row["quantity_display"] = str(quantity) if quantity > 0 else "—"
    except ValueError:
        row["quantity_display"] = "—"
    return row


class StockSnapshotsController(QObject):
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
            "counters": [],
            "items": [],
            "latest": None,
            "snapshot_state": "missing",
            "latest_basis_current": None,
            "current_ordinary_issued_quantity": None,
            "current_ordinary_issued_display": "—",
            "selected": {},
            "forms": {"event_time": "", "reason": ""},
            "counter_reports": [],
            "totals": display_totals({}),
            "history": [],
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
        return f"/api/workspace/stations/{self._state['station_id']}/stock-snapshots"

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
            error="stock_snapshot_validation" if code == "validation_error" else code, notice=""
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

    @staticmethod
    def _identity(value: Any) -> bool:
        return bool(
            isinstance(value, dict)
            and type(value.get("id")) is int
            and value["id"] > 0
            and isinstance(value.get("code"), str)
            and isinstance(value.get("name"), str)
        )

    @staticmethod
    def _quantities(value: dict[str, Any], measured: bool) -> bool:
        return all(
            type(value[key]) is int and value[key] >= 0
            if measured or key not in ("ordinary_remaining_quantity", "ordinary_issued_quantity")
            else value[key] is None
            for key in QUANTITIES
        )

    @staticmethod
    def _ranges(value: Any) -> bool:
        if not isinstance(value, list):
            return False
        for row in value:
            if not (
                isinstance(row, dict)
                and isinstance(row.get("series"), str)
                and row["series"].strip()
                and len(row["series"]) <= 64
                and isinstance(row.get("serial_from"), str)
                and isinstance(row.get("serial_to"), str)
                and type(row.get("quantity")) is int
                and row["quantity"] > 0
                and serial(row["serial_from"]) <= serial(row["serial_to"])
            ):
                return False
        return True

    def _snapshot(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        try:
            if not (
                type(value["id"]) is int
                and value["id"] > 0
                and type(value["revision"]) is int
                and value["revision"] > 0
                and type(value["station_id"]) is int
                and value["station_id"] == self._state["station_id"]
                and value["status"] == "recorded"
                and value["provenance"] == "stock_derived"
                and type(value["actor_id"]) is int
                and value["actor_id"] > 0
                and isinstance(value["reason"], str)
                and len(value["reason"]) <= 1000
                and type(value["complete"]) is bool
                and isinstance(value["counters"], list)
                and self._quantities(value, value["complete"])
            ):
                return False
            for name in ("event_at", "entered_at"):
                parsed = datetime.fromisoformat(value[name])
                if parsed.utcoffset() is None:
                    return False
                parsed.astimezone(HKT)
            identities = []
            for row in value["counters"]:
                if not (
                    isinstance(row, dict)
                    and self._identity(row.get("counter"))
                    and type(row["reported"]) is bool
                    and self._quantities(row, row["reported"])
                    and self._ranges(row["issued_ranges"])
                    and (
                        self._ranges(row["ranges"])
                        if row["reported"]
                        else row["ranges"] is None and row["issued_ranges"] == []
                    )
                ):
                    return False
                identities.append(row["counter"]["id"])
            if len(identities) != len(set(identities)) or value["complete"] != bool(
                identities and all(row["reported"] for row in value["counters"])
            ):
                return False
            for name, key in (
                ("receipt_basis", "receipt_id"),
                ("allocation_basis", "allocation_id"),
                ("return_basis", "return_id"),
            ):
                if not isinstance(value[name], list) or not all(
                    isinstance(row, dict)
                    and type(row.get(key)) is int
                    and row[key] > 0
                    and type(row.get("revision")) is int
                    and row["revision"] > 0
                    for row in value[name]
                ):
                    return False
            return True
        except KeyError, TypeError, ValueError, OverflowError:
            return False

    def _matches_command(self, data: dict[str, Any], payload: dict[str, Any]) -> bool:
        if not self._snapshot(data) or data["revision"] != 1:
            return False
        required = {row["id"] for row in self._state["counters"]}
        identities = {row["counter"]["id"] for row in data["counters"]}
        reported = {row["counter"]["id"]: row for row in data["counters"] if row["reported"]}
        if not required <= identities or set(reported) != {
            row["counter_id"] for row in payload["counters"]
        }:
            return False
        for command in payload["counters"]:
            actual = [
                {key: row[key] for key in ("series", "serial_from", "serial_to")}
                for row in reported[command["counter_id"]]["ranges"]
            ]
            if actual != command["ranges"]:
                return False
        return bool(
            datetime.fromisoformat(data["event_at"]) == datetime.fromisoformat(payload["event_at"])
            and data["reason"] == ""
        )

    def _loaded(self, data: dict[str, Any]) -> None:
        required = (
            "scope",
            "counters",
            "items",
            "latest",
            "snapshot_state",
            "latest_basis_current",
            "current_ordinary_issued_quantity",
        )
        if not all(key in data for key in required):
            self._error("request_failed")
            return
        scope, counters, items, latest = (
            data["scope"],
            data["counters"],
            data["items"],
            data["latest"],
        )
        if not (
            isinstance(scope, dict)
            and isinstance(scope.get("station"), dict)
            and scope["station"].get("id") == self._state["station_id"]
            and isinstance(scope.get("election"), dict)
            and scope["election"].get("status") in ("draft", "active", "finalized")
            and isinstance(counters, list)
            and all(self._identity(row) for row in counters)
            and len({row["id"] for row in counters}) == len(counters)
            and isinstance(items, list)
            and all(self._snapshot(row) for row in items)
            and (latest is None if not items else self._snapshot(latest) and latest == items[-1])
            and (
                type(data["latest_basis_current"]) is bool
                if latest is not None
                else data["latest_basis_current"] is None
            )
            and (
                data["current_ordinary_issued_quantity"] is None
                or type(data["current_ordinary_issued_quantity"]) is int
                and data["current_ordinary_issued_quantity"] >= 0
            )
        ):
            self._error("request_failed")
            return
        expected_state = (
            "missing" if latest is None else "complete" if latest["complete"] else "incomplete"
        )
        expected_issued = (
            latest["ordinary_issued_quantity"]
            if latest is not None and data["latest_basis_current"]
            else None
        )
        if (
            data["snapshot_state"] != expected_state
            or data["current_ordinary_issued_quantity"] != expected_issued
        ):
            self._error("request_failed")
            return
        current = data["current_ordinary_issued_quantity"]
        self._state.update(
            scope=deepcopy(scope),
            context={**self._state["context"], **scope},
            counters=deepcopy(counters),
            items=deepcopy(items),
            latest=deepcopy(latest),
            snapshot_state=data["snapshot_state"],
            latest_basis_current=data["latest_basis_current"],
            current_ordinary_issued_quantity=current,
            current_ordinary_issued_display="—" if current is None else str(current),
        )
        existing = {row["counter"]["id"]: row for row in self._state["counter_reports"]}
        self._state["counter_reports"] = [
            existing.get(row["id"], {"counter": deepcopy(row), "reported": False, "ranges": []})
            for row in counters
        ]

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

    def _counter(self, counter_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in self._state["counter_reports"] if row["counter"]["id"] == counter_id),
            None,
        )

    def _changed(self) -> None:
        self._state.update(dirty=True, error="", notice="")
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if self._editable() and name in self._state["forms"]:
            if self._state["forms"][name] != value:
                self._state["forms"][name] = value
                self._changed()

    @Slot(int, bool)
    def setCounterReported(self, counter_id: int, reported: bool) -> None:
        row = self._counter(counter_id)
        if self._editable() and row is not None and row["reported"] != reported:
            row["reported"] = reported
            self._changed()

    @Slot(int)
    def addRange(self, counter_id: int) -> None:
        row = self._counter(counter_id)
        if self._editable() and row is not None and row["reported"]:
            row["ranges"].append(range_display({"series": "", "serial_from": "", "serial_to": ""}))
            self._changed()

    @Slot(int, int, str, str)
    def setRangeField(self, counter_id: int, index: int, name: str, value: str) -> None:
        row = self._counter(counter_id)
        if (
            self._editable()
            and row is not None
            and row["reported"]
            and 0 <= index < len(row["ranges"])
            and name in ("series", "serial_from", "serial_to")
        ):
            updated = {**row["ranges"][index], name: value}
            row["ranges"][index] = range_display(updated)
            self._changed()

    @Slot(int, int)
    def removeRange(self, counter_id: int, index: int) -> None:
        row = self._counter(counter_id)
        if (
            self._editable()
            and row is not None
            and row["reported"]
            and 0 <= index < len(row["ranges"])
        ):
            row["ranges"].pop(index)
            self._changed()

    def _payload(self) -> dict[str, Any] | None:
        try:
            event_text = self._state["forms"]["event_time"].strip()
            if not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?",
                event_text,
            ):
                raise ValueError("Use a local Hong Kong date and time")
            event = datetime.fromisoformat(event_text).replace(tzinfo=HKT)
            counters = []
            for row in self._state["counter_reports"]:
                if not row["reported"]:
                    continue
                ranges = []
                for line in row["ranges"]:
                    if not line["series"].strip() or len(line["series"]) > 64:
                        raise ValueError("A ballot series is required")
                    if serial(line["serial_to"]) < serial(line["serial_from"]):
                        raise ValueError("Range is reversed")
                    ranges.append(
                        {key: line[key] for key in ("series", "serial_from", "serial_to")}
                    )
                counters.append({"counter_id": row["counter"]["id"], "ranges": ranges})
            return {"event_at": event.isoformat(), "counters": counters}
        except ValueError:
            self._error("stock_snapshot_validation")
            return None

    def _accept(self, data: dict[str, Any]) -> None:
        local = datetime.fromisoformat(data["event_at"]).astimezone(HKT)
        precision = (
            "microseconds" if local.microsecond else "seconds" if local.second else "minutes"
        )
        self._state.update(
            selected=deepcopy(data),
            totals=display_totals(data),
            dirty=False,
            forms={"event_time": local.isoformat(sep=" ", timespec=precision)[:-6], "reason": ""},
            counter_reports=[
                {
                    "counter": deepcopy(row["counter"]),
                    "reported": row["reported"],
                    "ranges": [range_display(line) for line in row["ranges"] or []],
                }
                for row in data["counters"]
            ],
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
            self._state["notice"] = "stock_snapshot_saved"
            self.refresh()

        self._send("POST", payload, saved)
