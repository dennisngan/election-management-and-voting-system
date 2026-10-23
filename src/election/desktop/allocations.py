"""Counter allocation forms retain exact serials and shared availability."""

import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler, positive_integer
from election.desktop.lifecycle import HKT
from election.desktop.report_files import DownloadRequest, report_destination, save_report
from election.desktop.stock import serial


def empty_forms() -> dict[str, str]:
    return dict.fromkeys(
        ("counter_id", "series", "serial_from", "serial_to", "event_at", "reason"), ""
    )


def allocation_display(value: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(value)
    row["quantity_display"] = str(row["quantity"])
    return row


def availability_display(value: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(value)
    for name in ("ordinary_received", "allocated", "available", "replacement", "tendered"):
        row[name + "_display"] = str(row[name + "_quantity"])
    for line in row["ranges"]:
        line["quantity_display"] = str(line["quantity"])
    return row


class AllocationController(QObject):
    stateChanged = Signal()

    def __init__(
        self, request: AuthorizedRequest, download: DownloadRequest, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._download = download
        self._generation = 0
        self._opened = False
        self._report_active = False
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._report_active = False
        self._pending = None
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "items": [],
            "counters": [],
            "availability": [],
            "selected": {},
            "forms": empty_forms(),
            "quantity_display": "—",
            "history": [],
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            "newer_revision": False,
            "historical": False,
            "editing": False,
            "report": {},
            "report_scope": "station_current",
            "report_text": "",
            "export_path": "",
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

    def _writable(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._state["role"] == "polling_officer"
            and self._state["context"].get("election", {}).get("status") in ("draft", "active")
            and not self._state["historical"]
        )

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/allocations"

    def _error(self, code: str) -> None:
        self._state.update(
            error="allocation_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

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
            self._report_active = False
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._report_active = False
                self._error(code)

        self._request(path, method, payload, done, failed)

    def _allocation(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        try:
            return bool(
                type(data["id"]) is int
                and data["id"] > 0
                and type(data["revision"]) is int
                and data["revision"] > 0
                and data["station_id"] == self._state["station_id"]
                and isinstance(data["counter"], dict)
                and type(data["counter"]["id"]) is int
                and isinstance(data["series"], str)
                and isinstance(data["serial_from"], str)
                and isinstance(data["serial_to"], str)
                and type(data["quantity"]) is int
                and data["quantity"] > 0
                and data["quantity"] == serial(data["serial_to"]) - serial(data["serial_from"]) + 1
                and self.formatTime(data["event_at"]) != "—"
                and self.formatTime(data["entered_at"]) != "—"
                and isinstance(data["receipt_basis"], list)
            )
        except KeyError, TypeError, ValueError:
            return False

    def _loaded(self, data: dict[str, Any]) -> None:
        rows, counters, balances = (
            data.get("items"),
            data.get("counters"),
            data.get("availability"),
        )
        scope = data.get("scope")
        if (
            not isinstance(scope, dict)
            or scope.get("station", {}).get("id") != self._state["station_id"]
            or not isinstance(rows, list)
            or not all(self._allocation(row) for row in rows)
            or not isinstance(counters, list)
            or not all(
                isinstance(row, dict)
                and type(row.get("id")) is int
                and isinstance(row.get("code"), str)
                and isinstance(row.get("name"), str)
                for row in counters
            )
            or not isinstance(balances, list)
        ):
            self._error("request_failed")
            return
        try:
            displayed_balances = [availability_display(row) for row in balances]
        except KeyError, TypeError:
            self._error("request_failed")
            return
        self._state.update(
            items=[allocation_display(row) for row in rows],
            counters=deepcopy(counters),
            availability=displayed_balances,
            context={**self._state["context"], **scope},
        )
        selected = self._state["selected"]
        if selected and not self._state["historical"]:
            latest: dict[str, Any] = next(
                (row for row in self._state["items"] if row["id"] == selected["id"]), {}
            )
            self._state["newer_revision"] = latest != selected

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
        self._send(self._path(), "GET", None, self._loaded, background=True)

    def _clear_report(self) -> None:
        self._state.update(report={}, report_text="", export_path="")

    def _can_load(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_allocation_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    def _history(self, *, refresh_after: bool = False) -> None:
        allocation_id = self._state["selected"]["id"]

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if (
                data.get("allocation_id") != allocation_id
                or not isinstance(rows, list)
                or not rows
                or not all(self._allocation(row) and row["id"] == allocation_id for row in rows)
                or len({row["revision"] for row in rows}) != len(rows)
            ):
                self._error("request_failed")
                return
            self._state["history"] = [allocation_display(row) for row in rows]
            head = allocation_display(max(rows, key=lambda row: row["revision"]))
            selected = self._state["selected"]
            # The current GET may have raced a subsequent amendment. History is
            # authoritative for whether the pinned selected revision is historical.
            self._state["historical"] = selected["revision"] < head["revision"]
            self._state["newer_revision"] = selected != head
            items = {row["id"]: row for row in self._state["items"]}
            items[allocation_id] = head
            self._state["items"] = [items[key] for key in sorted(items)]
            if refresh_after:
                self.refresh()

        self._send(f"{self._path()}/{allocation_id}/history", "GET", None, loaded)

    @Slot(int, bool, result=bool)
    def loadAllocation(self, allocation_id: int, discard: bool) -> bool:
        if allocation_id < 0 or not self._can_load(discard):
            return False
        if allocation_id == 0:
            self._state.update(
                selected={},
                forms=empty_forms(),
                quantity_display="—",
                history=[],
                dirty=False,
                newer_revision=False,
                historical=False,
                editing=False,
            )
            self._clear_report()
            self._send(self._path(), "GET", None, self._loaded)
        else:

            def loaded(data: dict[str, Any]) -> None:
                if not self._allocation(data) or data["id"] != allocation_id:
                    self._error("request_failed")
                    return
                self._accept(data)
                self._history()

            self._send(f"{self._path()}/{allocation_id}", "GET", None, loaded)
        return True

    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool) -> bool:
        selected = self._state["selected"]
        if not selected or revision < 1 or not self._can_load(discard):
            return False
        allocation_id = selected["id"]

        def loaded(data: dict[str, Any]) -> None:
            if (
                not self._allocation(data)
                or data["id"] != allocation_id
                or data["revision"] != revision
            ):
                self._error("request_failed")
                return
            self._accept(data)
            self._history()

        self._send(f"{self._path()}/{allocation_id}?revision={revision}", "GET", None, loaded)
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._writable()
            and not self._state["busy"]
            and name in self._state["forms"]
            and self._state["forms"][name] != value
        ):
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self._clear_report()
            self._calculate()
            self.stateChanged.emit()

    def _calculate(self) -> None:
        form = self._state["forms"]
        try:
            quantity = serial(form["serial_to"]) - serial(form["serial_from"]) + 1
            if quantity < 1:
                raise ValueError("Range is reversed")
            self._state["quantity_display"] = str(quantity)
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
            first, last = serial(form["serial_from"]), serial(form["serial_to"])
            if last < first:
                raise ValueError("Range is reversed")
            event_text = form["event_at"].strip()
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", event_text
            ):
                raise ValueError("Use a local Hong Kong date and time")
            event = datetime.fromisoformat(event_text).replace(tzinfo=HKT)
            payload: dict[str, Any] = {
                "counter_id": counter_id,
                "series": form["series"],
                "serial_from": form["serial_from"],
                "serial_to": form["serial_to"],
                "event_at": event.isoformat(),
            }
            if self._state["selected"]:
                if not form["reason"].strip() or len(form["reason"]) > 1000:
                    raise ValueError("A correction reason is required")
                payload.update(revision=self._state["selected"]["revision"], reason=form["reason"])
            return payload
        except ValueError:
            self._error("allocation_validation")
            return None

    def _accept(self, data: dict[str, Any]) -> None:
        self._state.update(
            selected=allocation_display(data),
            forms={
                "counter_id": str(data["counter"]["id"]),
                "series": data["series"],
                "serial_from": data["serial_from"],
                "serial_to": data["serial_to"],
                "event_at": self.formatTime(data["event_at"]).removesuffix(" HKT"),
                "reason": "",
            },
            editing=True,
            dirty=False,
            newer_revision=False,
            historical=False,
        )
        self._calculate()
        self._clear_report()

    @Slot()
    def save(self) -> None:
        if self._state["busy"]:
            return
        if not self._writable():
            self._error("election_read_only")
            return
        payload = self._payload()
        if payload is None:
            return
        allocation_id = self._state["selected"].get("id", 0)
        signature = json.dumps(
            {"station": self._state["station_id"], "allocation": allocation_id, "data": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if (
                not self._allocation(data)
                or (allocation_id and data["id"] != allocation_id)
                or data["revision"] != payload.get("revision", 0) + 1
                or data["counter"]["id"] != payload["counter_id"]
                or any(data[key] != payload[key] for key in ("series", "serial_from", "serial_to"))
                or datetime.fromisoformat(data["event_at"])
                != datetime.fromisoformat(payload["event_at"])
            ):
                self._error("request_failed")
                return
            self._pending = None
            self._accept(data)
            rows = {row["id"]: row for row in self._state["items"]}
            rows[data["id"]] = allocation_display(data)
            self._state["items"] = [rows[key] for key in sorted(rows)]
            self._state["notice"] = "allocation_saved"
            self._history(refresh_after=True)

        self._send(
            self._path() + (f"/{allocation_id}" if allocation_id else ""),
            "PUT" if allocation_id else "POST",
            payload,
            saved,
        )

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return "—"
            local = parsed.astimezone(HKT)
            precision = (
                "microseconds" if local.microsecond else "seconds" if local.second else "minutes"
            )
            return local.isoformat(sep=" ", timespec=precision).removesuffix("+08:00") + " HKT"
        except TypeError, ValueError:
            return "—"

    @Slot(str)
    def setReportScope(self, scope: str) -> None:
        if scope not in ("station_current", "allocation_revision"):
            self._error("allocation_validation")
            return
        if self._state["report_scope"] == scope:
            return
        if self._state["busy"] and not self._report_active:
            return
        # A scope change can supersede a report request, but never an active save.
        self._generation += 1
        self._report_active = False
        self._state.update(report_scope=scope, busy=False, refreshing=False, error="", notice="")
        self._clear_report()
        self.stateChanged.emit()

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if self._state["busy"]:
            return None
        if not self._state["station_id"] or locale not in ("tc", "sc", "en"):
            self._error("allocation_validation")
            return None
        if self._state["dirty"]:
            self._error("unsaved_allocation_changes")
            return None
        path = f"{self._path()}/statement{extension}?locale={locale}"
        if self._state["report_scope"] == "allocation_revision":
            selected = self._state["selected"]
            if not selected:
                self._error("allocation_validation")
                return None
            path += f"&allocation_id={selected['id']}&revision={selected['revision']}"
        return path

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None:
            return
        station_id, report_scope = self._state["station_id"], self._state["report_scope"]
        selected = self._state["selected"]
        allocation_id = selected.get("id") if report_scope == "allocation_revision" else None
        revision = selected.get("revision") if report_scope == "allocation_revision" else None
        self._generation += 1
        self._report_active = True
        self._state.update(refreshing=False, error="", notice="", export_path="")

        def loaded(data: dict[str, Any]) -> None:
            scope, lines = data.get("scope"), data.get("preview_lines")
            if not (
                isinstance(scope, dict)
                and isinstance(scope.get("station"), dict)
                and scope["station"].get("id") == station_id
                and data.get("locale") == locale
                and data.get("report_scope") == report_scope
                and data.get("allocation_id") == allocation_id
                and data.get("revision") == revision
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(
                report=deepcopy(data),
                report_text="\n".join(lines),
                notice="allocation_report_ready",
            )

        self._send(path, "GET", None, loaded)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv"):
            self._error("allocation_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("allocation_export_failed")
            return
        path = self._report_path(locale, "." + format)
        if path is None:
            return
        self._generation += 1
        generation = self._generation
        self._report_active = True
        self._state.update(refreshing=False, busy=True, error="", notice="", export_path="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._report_active = False
            self._state["busy"] = False
            self._error(code)

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not save_report(data, destination, format):
                failed("allocation_export_failed")
                return
            self._report_active = False
            self._state.update(busy=False, notice="allocation_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(path, loaded, failed)
