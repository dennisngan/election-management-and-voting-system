"""Reviewed polling snapshots stay separate from background refresh and unsaved input."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT

KINDS = ("opening", "admission_closure", "queue_clear_estimate", "service_completion")


def empty_forms() -> dict[str, str]:
    return {"event_at": "", "estimated_clear_at": "", "reason": "", "amendment_reason": ""}


class PollingController(QObject):
    stateChanged = Signal()
    erasePassword = Signal()

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
            "schedule": {},
            "items": [],
            "kind": "opening",
            "record": {},
            "history": [],
            "forms": empty_forms(),
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            "newer_revision": False,
        }
        self.erasePassword.emit()
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        station_id = context.get("station", {}).get("id", 0)
        changed_station = station_id != self._state["station_id"]
        if changed_station:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._state.update(
            station_id=station_id,
            context=deepcopy(context),
            role=context.get("account", {}).get("role", ""),
        )
        self.stateChanged.emit()
        if self._opened and station_id and changed_station:
            self.reload(True)

    def _error(self, code: str) -> None:
        self._state.update(
            error="polling_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/polling"

    def _send(
        self,
        path: str,
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
            if generation != self._generation:
                return
            self._state[activity] = False
            self._error(code)

        self._request(path, method, payload, done, failed)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return "—"
            return parsed.astimezone(HKT).strftime(TIME_FORMAT) + " HKT"
        except ValueError:
            return "—"

    def _accept_record(self, row: dict[str, Any]) -> None:
        forms = empty_forms()
        for name in ("event_at", "estimated_clear_at"):
            if row.get(name):
                forms[name] = self.formatTime(row[name]).removesuffix(" HKT")
        forms["reason"] = row.get("reason", "")
        self._state.update(record=deepcopy(row), forms=forms, dirty=False, newer_revision=False)

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> None:
        items = data.get("items")
        if not isinstance(items, list) or not all(
            isinstance(row, dict)
            and row.get("kind") in KINDS
            and type(row.get("revision")) is int
            and row.get("station_id") == self._state["station_id"]
            for row in items
        ):
            self._error("request_failed")
            return
        self._state.update(items=items, schedule=data.get("schedule") or {})
        row: dict[str, Any] = next((row for row in items if row["kind"] == self._state["kind"]), {})
        if accept:
            self._accept_record(row)
        else:
            self._state["newer_revision"] = row != self._state["record"]

    @Slot()
    def open(self) -> None:
        self._opened = True
        if not self._state["record"] and not self._state["dirty"]:
            self.reload(True)
        else:
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
        self._send(
            self._path(),
            "GET",
            None,
            lambda data: self._loaded(data, accept=False),
            background=True,
        )

    @Slot(bool, result=bool)
    def reload(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_polling_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            self._loaded(data, accept=True)
            self._load_history()

        self._send(self._path(), "GET", None, loaded)
        return True

    @Slot(str, bool, result=bool)
    def setKind(self, kind: str, discard: bool) -> bool:
        if kind not in KINDS or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_polling_changes")
            return False
        self._state.update(kind=kind, dirty=False)
        return self.reload(True)

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if self._state["role"] != "polling_officer" or self._state["busy"]:
            return
        if name in self._state["forms"] and self._state["forms"][name] != value:
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self.stateChanged.emit()

    def _load_history(self) -> None:
        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not isinstance(rows, list):
                self._error("request_failed")
                return
            self._state["history"] = rows

        self._send(self._path() + f"/{self._state['kind']}/history", "GET", None, loaded)

    def _dates(self) -> dict[str, str | None] | None:
        result: dict[str, str | None] = {}
        for name in ("event_at", "estimated_clear_at"):
            value = self._state["forms"][name].strip()
            if not value:
                result[name] = None
                continue
            try:
                result[name] = datetime.strptime(value, TIME_FORMAT).replace(tzinfo=HKT).isoformat()
            except ValueError:
                self._error("polling_validation")
                return None
        return result

    def _command(self, action: str, values: dict[str, Any], notice: str) -> None:
        if not self._state["station_id"] or self._state["busy"]:
            return
        payload = {"revision": self._state["record"].get("revision", 0), **values}
        signature = json.dumps(
            {
                "station": self._state["station_id"],
                "kind": self._state["kind"],
                "action": action,
                "values": {k: v for k, v in payload.items() if k != "password"},
            },
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if (
                data.get("kind") != self._state["kind"]
                or data.get("station_id") != self._state["station_id"]
            ):
                self._error("request_failed")
                return
            self._pending = None
            self._accept_record(data)
            latest = {row["kind"]: row for row in self._state["items"]}
            latest[data["kind"]] = data
            self._state["items"] = [latest[kind] for kind in KINDS if kind in latest]
            self._state["notice"] = notice
            self._load_history()

        suffix = "" if action == "save" else "/" + action
        self._send(
            self._path() + "/" + self._state["kind"] + suffix,
            "PUT" if action == "save" else "POST",
            payload,
            saved,
        )

    @Slot()
    def save(self) -> None:
        if self._state["role"] != "polling_officer":
            return
        dates = self._dates()
        if dates is not None:
            self._command(
                "save", {**dates, "reason": self._state["forms"]["reason"]}, "polling_saved"
            )

    @Slot()
    def submit(self) -> None:
        if self._state["role"] != "polling_officer":
            return
        if self._state["dirty"]:
            self._error("unsaved_polling_changes")
            return
        self._command("submit", {}, "polling_submitted")

    @Slot()
    def amend(self) -> None:
        if self._state["role"] != "polling_officer":
            return
        dates = self._dates()
        if dates is not None:
            self._command(
                "amend",
                {
                    **dates,
                    "reason": self._state["forms"]["amendment_reason"],
                    "event_reason": self._state["forms"]["reason"],
                },
                "polling_amended",
            )

    @Slot(str)
    def approve(self, password: str) -> None:
        self.erasePassword.emit()
        if self._state["role"] == "supervisor":
            self._command("approve", {"password": password}, "polling_approved")
