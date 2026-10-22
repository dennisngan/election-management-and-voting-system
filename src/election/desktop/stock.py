"""Received-stock forms, reviewed revisions and authenticated statement exports."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

POOLS = ("ordinary", "replacement", "tendered")
MAX_QUANTITY = 9223372036854775807


def empty_forms() -> dict[str, str]:
    return {
        "series": "",
        "event_at": "",
        "ordinary_quantity": "0",
        "replacement_quantity": "0",
        "tendered_quantity": "0",
        "reason": "",
    }


def blank_range() -> dict[str, str]:
    return {"pool": "ordinary", "serial_from": "", "serial_to": "", "quantity_display": "—"}


def serial(value: str) -> int:
    if not 1 <= len(value) <= 18 or not value.isascii() or not value.isdecimal():
        raise ValueError("Use 1–18 ASCII serial digits")
    return int(value)


def receipt_display(value: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(value)
    for pool in POOLS:
        row[pool + "_display"] = str(row[pool + "_quantity"])
    row["total_display"] = str(row["total_quantity"])
    for line in row["ranges"]:
        line["quantity_display"] = str(line["quantity"])
    return row


class StockController(QObject):
    stateChanged = Signal()

    def __init__(
        self, request: AuthorizedRequest, download: DownloadRequest, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._download = download
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
            "items": [],
            "selected": {},
            "forms": empty_forms(),
            "ranges": [blank_range()],
            "calculated_total_display": "—",
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
            self.loadReceipt(0, True)

    def _writable(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._state["role"] == "polling_officer"
            and self._state["context"].get("election", {}).get("status") in ("draft", "active")
            and not self._state["historical"]
        )

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/stock"

    def _error(self, code: str) -> None:
        self._state.update(
            error="stock_validation" if code == "validation_error" else code, notice=""
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
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._error(code)

        self._request(path, method, payload, done, failed)

    def _receipt(self, data: Any) -> bool:
        return bool(
            isinstance(data, dict)
            and type(data.get("id")) is int
            and type(data.get("revision")) is int
            and data["revision"] > 0
            and data.get("station_id") == self._state["station_id"]
            and isinstance(data.get("ranges"), list)
            and all(type(data.get(pool + "_quantity")) is int for pool in POOLS)
            and type(data.get("total_quantity")) is int
            and all(
                isinstance(line, dict) and type(line.get("quantity")) is int
                for line in data["ranges"]
            )
        )

    def _loaded(self, data: dict[str, Any]) -> None:
        rows = data.get("items")
        if not isinstance(rows, list) or not all(self._receipt(row) for row in rows):
            self._error("request_failed")
            return
        self._state["items"] = [receipt_display(row) for row in rows]
        scope = data.get("scope")
        if isinstance(scope, dict):
            self._state["context"] = {**self._state["context"], **scope}
        selected = self._state["selected"]
        if selected and not self._state["historical"]:
            latest: dict[str, Any] = next(
                (row for row in self._state["items"] if row["id"] == selected["id"]), {}
            )
            self._state["newer_revision"] = latest != selected

    @Slot()
    def open(self) -> None:
        self._opened = True
        if not self._state["selected"] and not self._state["dirty"]:
            self.loadReceipt(0, True)
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
        self._send(self._path(), "GET", None, self._loaded, background=True)

    def _clear_report(self) -> None:
        self._state.update(report={}, report_text="", export_path="")

    def _accept(self, data: dict[str, Any], *, historical: bool = False) -> None:
        forms = empty_forms()
        forms["series"] = data["series"]
        forms["event_at"] = (
            datetime.fromisoformat(data["event_at"]).astimezone(HKT).strftime(TIME_FORMAT)
        )
        for pool in POOLS:
            forms[pool + "_quantity"] = str(data[pool + "_quantity"])
        self._state.update(
            selected=receipt_display(data),
            forms=forms,
            ranges=[
                {key: line[key] for key in ("pool", "serial_from", "serial_to")}
                for line in data["ranges"]
            ],
            editing=True,
            dirty=False,
            newer_revision=False,
            historical=historical,
        )
        self._calculate()
        self._clear_report()

    def _history(self, *, review_revision: bool = False) -> None:
        receipt_id = self._state["selected"]["id"]

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not isinstance(rows, list) or not all(self._receipt(row) for row in rows):
                self._error("request_failed")
                return
            self._state["history"] = [receipt_display(row) for row in rows]
            if rows:
                head = receipt_display(max(rows, key=lambda row: row["revision"]))
                items = {row["id"]: row for row in self._state["items"]}
                items[receipt_id] = head
                self._state["items"] = [items[key] for key in sorted(items)]
                selected = self._state["selected"]
                if review_revision:
                    self._state["historical"] = selected["revision"] < head["revision"]
                elif not self._state["historical"]:
                    self._state["newer_revision"] = selected != head

        self._send(f"{self._path()}/{receipt_id}/history", "GET", None, loaded)

    def _can_load(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_stock_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    @Slot(int, bool, result=bool)
    def loadReceipt(self, receipt_id: int, discard: bool) -> bool:
        if not self._can_load(discard):
            return False
        if receipt_id == 0:
            self._state.update(
                selected={},
                forms=empty_forms(),
                ranges=[blank_range()],
                history=[],
                dirty=False,
                newer_revision=False,
                historical=False,
                editing=False,
                calculated_total_display="—",
            )
            self._clear_report()
            self._send(self._path(), "GET", None, self._loaded)
        else:

            def loaded(data: dict[str, Any]) -> None:
                if not self._receipt(data) or data["id"] != receipt_id:
                    self._error("request_failed")
                    return
                self._accept(data)
                self._history()

            self._send(f"{self._path()}/{receipt_id}", "GET", None, loaded)
        return True

    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool) -> bool:
        selected = self._state["selected"]
        if not selected or revision < 1 or not self._can_load(discard):
            return False
        receipt_id = selected["id"]
        latest = next((row for row in self._state["items"] if row["id"] == receipt_id), selected)

        def loaded(data: dict[str, Any]) -> None:
            if not self._receipt(data) or data["id"] != receipt_id or data["revision"] != revision:
                self._error("request_failed")
                return
            self._accept(data, historical=revision < latest["revision"])
            self._history(review_revision=True)

        self._send(f"{self._path()}/{receipt_id}?revision={revision}", "GET", None, loaded)
        return True

    def _changed(self) -> None:
        self._state.update(dirty=True, error="", notice="")
        self._clear_report()
        self._calculate()
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if self._writable() and not self._state["busy"] and name in self._state["forms"]:
            if self._state["forms"][name] != value:
                self._state["forms"][name] = value
                self._changed()

    @Slot()
    def addRange(self) -> None:
        if self._writable() and not self._state["busy"]:
            self._state["ranges"].append(blank_range())
            self._changed()

    @Slot(int)
    def removeRange(self, index: int) -> None:
        if self._writable() and not self._state["busy"] and 0 <= index < len(self._state["ranges"]):
            del self._state["ranges"][index]
            self._changed()

    @Slot(int, str, str)
    def setRange(self, index: int, name: str, value: str) -> None:
        if (
            self._writable()
            and not self._state["busy"]
            and 0 <= index < len(self._state["ranges"])
            and name in ("pool", "serial_from", "serial_to")
        ):
            if self._state["ranges"][index][name] != value:
                self._state["ranges"][index][name] = value
                self._changed()

    def _calculate(self) -> None:
        total = 0
        valid = bool(self._state["ranges"])
        for line in self._state["ranges"]:
            try:
                quantity = serial(line["serial_to"]) - serial(line["serial_from"]) + 1
                if quantity < 1 or line["pool"] not in POOLS:
                    raise ValueError("Invalid range")
                line["quantity_display"] = str(quantity)
                total += quantity
            except ValueError:
                line["quantity_display"] = "—"
                valid = False
        self._state["calculated_total_display"] = str(total) if valid else "—"

    def _payload(self) -> dict[str, Any] | None:
        form = self._state["forms"]
        try:
            if not form["series"].strip() or len(form["series"]) > 64:
                raise ValueError("A ballot series is required")
            event = datetime.strptime(form["event_at"].strip(), TIME_FORMAT).replace(tzinfo=HKT)
            declared = {}
            for pool in POOLS:
                value = form[pool + "_quantity"].strip()
                if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
                    raise ValueError("A nonnegative quantity is required")
                declared[pool] = int(value)
                if declared[pool] > MAX_QUANTITY:
                    raise ValueError("Quantity exceeds supported bounds")
            ranges = []
            totals = dict.fromkeys(POOLS, 0)
            for line in self._state["ranges"]:
                if line["pool"] not in POOLS:
                    raise ValueError("Invalid pool")
                first, last = serial(line["serial_from"]), serial(line["serial_to"])
                if last < first:
                    raise ValueError("Range is reversed")
                totals[line["pool"]] += last - first + 1
                ranges.append({key: line[key] for key in ("pool", "serial_from", "serial_to")})
            if not ranges or totals != declared or not 1 <= sum(totals.values()) <= MAX_QUANTITY:
                raise ValueError("Declared pools must match ranges")
            payload = {
                "series": form["series"],
                "event_at": event.isoformat(),
                "ranges": ranges,
                **{pool + "_quantity": declared[pool] for pool in POOLS},
            }
            if self._state["selected"]:
                if not form["reason"].strip() or len(form["reason"]) > 1000:
                    raise ValueError("A correction reason is required")
                payload.update(revision=self._state["selected"]["revision"], reason=form["reason"])
            return payload
        except ValueError:
            self._error("stock_validation")
            return None

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
        receipt_id = self._state["selected"].get("id", 0)
        signature = json.dumps(
            {"station": self._state["station_id"], "receipt": receipt_id, "data": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._receipt(data):
                self._error("request_failed")
                return
            self._pending = None
            self._accept(data)
            rows = {row["id"]: row for row in self._state["items"]}
            rows[data["id"]] = receipt_display(data)
            self._state["items"] = [rows[key] for key in sorted(rows)]
            self._state["notice"] = "stock_saved"
            self._history()

        self._send(
            self._path() + (f"/{receipt_id}" if receipt_id else ""),
            "PUT" if receipt_id else "POST",
            payload,
            saved,
        )

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(HKT).strftime(TIME_FORMAT) + " HKT" if parsed.tzinfo else "—"
        except ValueError:
            return "—"

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if self._state["busy"]:
            return None
        if self._state["dirty"]:
            self._error("unsaved_stock_changes")
            return None
        selected = self._state["selected"]
        if not selected or locale not in ("tc", "sc", "en"):
            self._error("stock_validation")
            return None
        return (
            f"{self._path()}/{selected['id']}/statement{extension}"
            f"?revision={selected['revision']}&locale={locale}"
        )

    def _report_text(self, report: dict[str, Any]) -> str:
        labels, scope, receipt = report["labels"], report["scope"], report["items"][0]
        rows = [
            ("election", scope["election"]["name"]),
            ("election_status", labels[scope["election"]["status"]]),
            ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
            ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
            ("receipt_id", str(receipt["id"])),
            ("revision", str(receipt["revision"])),
            ("revision_state", labels[report["revision_state"]]),
            ("status", labels[receipt["status"]]),
            ("series", receipt["series"]),
            ("event_at", self.formatTime(receipt["event_at"])),
            ("entered_at", self.formatTime(receipt["entered_at"])),
            ("actor_id", str(receipt["actor_id"])),
            ("reason", receipt["reason"] or labels["none"]),
            *[(pool + "_quantity", str(receipt[pool + "_quantity"])) for pool in POOLS],
            ("total_quantity", str(receipt["total_quantity"])),
            ("generated_at", self.formatTime(report["generated_at"])),
            ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
        ]
        lines = [
            report["title"],
            *[labels[key] + ": " + value for key, value in rows],
            "",
            labels["ranges"],
        ]
        lines.append(
            " · ".join(labels[key] for key in ("pool", "serial_from", "serial_to", "quantity"))
        )
        for row in receipt["ranges"]:
            lines.append(
                " · ".join(
                    [
                        labels[row["pool"] + "_quantity"],
                        row["serial_from"],
                        row["serial_to"],
                        str(row["quantity"]),
                    ]
                )
            )
        return "\n".join(lines)

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None:
            return
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            try:
                text = self._report_text(data)
            except KeyError, TypeError, IndexError:
                self._error("request_failed")
                return
            self._state.update(report=data, report_text=text, notice="stock_report_ready")

        self._send(path, "GET", None, loaded)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv"):
            self._error("stock_export_failed")
            return
        candidate = report_destination(filepath)
        if candidate is None:
            self._error("stock_export_failed")
            return
        path = self._report_path(locale, "." + format)
        if path is None:
            return
        self._generation += 1
        generation = self._generation
        self._state.update(refreshing=False, busy=True, error="", notice="", export_path="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state["busy"] = False
                self._error(code)

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not save_report(data, candidate, format):
                failed("stock_export_failed")
                return
            self._state.update(busy=False, notice="stock_exported", export_path=candidate)
            self.stateChanged.emit()

        self._download(path, loaded, failed)
