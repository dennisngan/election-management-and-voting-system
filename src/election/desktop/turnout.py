"""Reviewed turnout forms, live period coverage and exact-revision approvals."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

MAX_TOTAL = 9223372036854775807
QUANTITIES = (
    "supplied_hourly",
    "supplied_cumulative",
    "derived_hourly",
    "derived_cumulative_start",
    "derived_cumulative_end",
)
STATUSES = ("draft", "submitted", "approved")


def empty_forms() -> dict[str, str]:
    return {
        "supplied_hourly": "",
        "supplied_cumulative": "",
        "event_time": "",
        "source_context": "",
        "amendment_reason": "",
    }


def record_display(row: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    for name in QUANTITIES:
        result[name + "_display"] = "—" if result[name] is None else str(result[name])
    result["period_index_display"] = str(result["period_index"])
    return result


def period_display(period: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(period)
    if result["record"] is not None:
        result["record"] = record_display(result["record"])
    result["period_index_display"] = str(result["period_index"])
    return result


def prefix_display(prefix: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(prefix)
    for name in ("periods", "hourly_total", "cumulative_end"):
        result[name + "_display"] = "—" if result[name] is None else str(result[name])
    return result


class TurnoutController(QObject):
    stateChanged = Signal()
    erasePassword = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject | None = None,
        *,
        download: DownloadRequest | None = None,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._download = download
        self._generation = 0
        self._opened = False
        self._reviewed = False
        self._reviewed_wrapper: dict[str, Any] = {}
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
        self._reviewed_wrapper = {}
        self._pending = None
        self._state = {
            "station_id": 0,
            "context": {},
            "role": "",
            "schedule": {},
            "items": [],
            "period_count": 0,
            "period_count_display": "0",
            "offset": 0,
            "limit": 100,
            "approved_prefix": prefix_display(
                {
                    "periods": 0,
                    "hourly_total": None,
                    "cumulative_end": None,
                    "covered_until": None,
                }
            ),
            "current": {},
            "selected_period": 0,
            "selected": {},
            "selected_period_context": {},
            "history": [],
            "forms": empty_forms(),
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "historical": False,
            "error": "",
            "notice": "",
            "report": {},
            "report_text": "",
            "export_path": "",
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
            station_id=station_id,
            context=deepcopy(context),
            role=context.get("account", {}).get("role", ""),
        )
        self.stateChanged.emit()
        if changed and station_id and self._opened:
            self.reload(True)

    def _error(self, code: str) -> None:
        self._state.update(
            error="turnout_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/turnout"

    def _page_path(self) -> str:
        return f"{self._path()}?offset={self._state['offset']}&limit={self._state['limit']}"

    def _send(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        background: bool = False,
        erase_password: bool = False,
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

    def _record(self, row: Any, period_index: int) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and row.get("period_index") == period_index
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("status") in STATUSES
            and all(row.get(name) is None or type(row.get(name)) is int for name in QUANTITIES)
            and isinstance(row.get("source_context"), str)
            and isinstance(row.get("start_at"), str)
            and isinstance(row.get("end_at"), str)
        )

    def _accept(
        self, row: dict[str, Any], wrapper: dict[str, Any], *, historical: bool = False
    ) -> None:
        forms = empty_forms()
        if row:
            for name in ("supplied_hourly", "supplied_cumulative"):
                forms[name] = "" if row[name] is None else str(row[name])
            if row.get("event_at"):
                forms["event_time"] = self.formatTime(row["event_at"]).removesuffix(" HKT")
            forms["source_context"] = row["source_context"]
            forms["amendment_reason"] = row["amendment_reason"]
        self._reviewed = True
        self._clear_report()
        self._reviewed_wrapper = deepcopy(wrapper)
        self._state.update(
            selected=record_display(row) if row else {},
            forms=forms,
            selected_period_context={
                "period_index": self._state["selected_period"],
                "start_at": row["start_at"] if row else wrapper["start_at"],
                "end_at": row["end_at"] if row else wrapper["end_at"],
            },
            dirty=False,
            historical=historical,
            newer_revision=False,
        )
        self.erasePassword.emit()

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> bool:
        items, schedule, context, prefix = (
            data.get(name) for name in ("items", "schedule", "context", "approved_prefix")
        )
        if not (
            isinstance(context, dict)
            and context.get("station", {}).get("id") == self._state["station_id"]
            and isinstance(schedule, dict)
            and type(schedule.get("revision")) is int
            and isinstance(items, list)
            and all(
                isinstance(item, dict)
                and type(item.get("period_index")) is int
                and item["period_index"] > 0
                and (
                    item.get("record") is None or self._record(item["record"], item["period_index"])
                )
                and type(item.get("approval_valid")) is bool
                and type(item.get("review_required")) is bool
                and isinstance(item.get("start_at"), str)
                and isinstance(item.get("end_at"), str)
                for item in items
            )
            and type(data.get("period_count")) is int
            and data["period_count"] >= 0
            and data.get("offset") == self._state["offset"]
            and isinstance(prefix, dict)
            and all(
                name in prefix and (prefix[name] is None or type(prefix[name]) is int)
                for name in ("periods", "hourly_total", "cumulative_end")
            )
        ):
            self._error("request_failed")
            return False
        self._state.update(
            items=[period_display(item) for item in items],
            schedule=deepcopy(schedule),
            context=deepcopy(context),
            period_count=data["period_count"],
            period_count_display=str(data["period_count"]),
            approved_prefix=prefix_display(prefix),
        )
        index = self._state["selected_period"]
        wrapper: dict[str, Any] = next(
            (item for item in items if item["period_index"] == index), {}
        )
        if accept and not wrapper and items:
            wrapper = items[0]
            self._state["selected_period"] = wrapper["period_index"]
        self._state["current"] = period_display(wrapper) if wrapper else {}
        if accept and wrapper:
            self._accept(wrapper["record"] or {}, wrapper)
        else:
            self._state["newer_revision"] = wrapper != self._reviewed_wrapper
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return bool(wrapper) if accept else True

    def _history(self) -> None:
        index = self._state["selected_period"]

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not isinstance(rows, list) or not all(self._record(row, index) for row in rows):
                self._error("request_failed")
                return
            self._state["history"] = [record_display(row) for row in rows]

        self._send(f"{self._path()}/{index}/history", "GET", None, loaded, background=True)

    def _can_load(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_turnout_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    def _load_page(self) -> None:
        def loaded(data: dict[str, Any]) -> None:
            if self._loaded(data, accept=True):
                self._history()

        self._send(self._page_path(), "GET", None, loaded)

    @Slot(result=bool)
    @Slot(int, str, result=bool)
    @Slot(int, str, bool, result=bool)
    def open(self, station_id: int | None = None, role: str = "", discard: bool = False) -> bool:
        if station_id is not None and station_id != self._state["station_id"]:
            if station_id != 0 and (self._state["busy"] or (self._state["dirty"] and not discard)):
                self._error("unsaved_turnout_changes")
                return False
            self.reset()
            self._state.update(station_id=station_id, role=role)
        elif role:
            self._state["role"] = role
        self._opened = True
        if not self._state["station_id"]:
            return True
        if not self._reviewed:
            return self.reload(discard)
        self.refresh()
        return True

    @Slot()
    def refresh(self) -> None:
        if (
            not self._opened
            or not self._state["station_id"]
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return

        def loaded(data: dict[str, Any]) -> None:
            self._loaded(data, accept=False)

        self._send(self._page_path(), "GET", None, loaded, background=True)

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, discard: bool = False) -> bool:
        if not self._can_load(discard):
            return False
        self._load_page()
        return True

    @Slot("qlonglong", result=bool)
    @Slot("qlonglong", bool, result=bool)
    def selectPeriod(self, index: int, discard: bool = False) -> bool:
        if type(index) is not int or not 1 <= index <= self._state["period_count"]:
            self._error("turnout_validation")
            return False
        if (
            index == self._state["selected_period"]
            and self._reviewed
            and not self._state["historical"]
        ):
            if discard:
                return self.reload(True)
            self.refresh()
            return True
        if not self._can_load(discard):
            return False
        if not any(row["period_index"] == index for row in self._state["items"]):
            self._state["offset"] = ((index - 1) // self._state["limit"]) * self._state["limit"]
        self._reviewed = False
        self._state.update(
            selected_period=index,
            selected={},
            history=[],
            forms=empty_forms(),
            dirty=False,
            historical=False,
        )
        self._load_page()
        return True

    @Slot("qlonglong", result=bool)
    @Slot("qlonglong", bool, result=bool)
    def setPage(self, offset: int, discard: bool = False) -> bool:
        if type(offset) is not int or not 0 <= offset < self._state["period_count"]:
            self._error("turnout_validation")
            return False
        if not self._can_load(discard):
            return False
        self._reviewed = False
        self._state.update(
            offset=offset,
            selected_period=offset + 1,
            selected={},
            history=[],
            forms=empty_forms(),
            dirty=False,
            historical=False,
        )
        self._load_page()
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        index = self._state["selected_period"]
        current = self._state["current"].get("record")
        if not current or revision < 1 or not self._can_load(discard):
            return False

        def loaded(data: dict[str, Any]) -> None:
            if not self._record(data, index) or data["revision"] != revision:
                self._error("request_failed")
                return
            wrapper = next(row for row in self._state["items"] if row["period_index"] == index)
            # Compare live refreshes with the live wrapper reviewed at this point,
            # while the separately selected old content remains explicitly read-only.
            raw_wrapper = deepcopy(wrapper)
            if raw_wrapper["record"]:
                raw_wrapper["record"] = {
                    key: value
                    for key, value in raw_wrapper["record"].items()
                    if not key.endswith("_display")
                }
            raw_wrapper.pop("period_index_display", None)
            self._accept(data, raw_wrapper, historical=revision < current["revision"])
            self._history()

        self._send(f"{self._path()}/{index}?revision={revision}", "GET", None, loaded)
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._state["role"] != "polling_officer"
            or self._state["busy"]
            or self._state["historical"]
            or not self._reviewed
            or self._state["context"].get("election", {}).get("status") != "active"
        ):
            return
        if name == "amendment_reason" and self._state["selected"].get("status") not in (
            "submitted",
            "approved",
        ):
            return
        if name in self._state["forms"] and self._state["forms"][name] != value:
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self.stateChanged.emit()

    def _content(self, *, amend: bool) -> dict[str, Any] | None:
        form = self._state["forms"]
        try:
            values: dict[str, Any] = {}
            for name in ("supplied_hourly", "supplied_cumulative"):
                text = form[name].strip()
                if not text:
                    values[name] = None
                else:
                    if not text.isascii() or not text.isdecimal():
                        raise ValueError("Use a nonnegative ASCII quantity")
                    values[name] = int(text)
                    if values[name] > MAX_TOTAL:
                        raise ValueError("Quantity exceeds signed64")
            text = form["event_time"].strip()
            original = self._state["selected"].get("event_at")
            if original and text == self.formatTime(original).removesuffix(" HKT"):
                # The minute form must not round a precise original on unrelated edits.
                values["event_at"] = original
            else:
                values["event_at"] = (
                    datetime.strptime(text, TIME_FORMAT).replace(tzinfo=HKT).isoformat()
                    if text
                    else None
                )
            if len(form["source_context"]) > 2000:
                raise ValueError("Source context is too long")
            values["source_context"] = form["source_context"]
            if amend:
                if not form["amendment_reason"].strip() or len(form["amendment_reason"]) > 2000:
                    raise ValueError("An amendment reason is required")
                values["amendment_reason"] = form["amendment_reason"]
            return values
        except ValueError:
            self._error("turnout_validation")
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
        if (
            self._state["historical"]
            or self._state["context"].get("election", {}).get("status") != "active"
        ):
            self._error("election_read_only")
            return
        if not self._reviewed:
            self._error("request_failed")
            return
        if action in ("submit", "approve") and self._state["dirty"]:
            self._error("unsaved_turnout_changes")
            return
        selected = self._state["selected"]
        status = selected.get("status", "missing")
        expected = {
            "save": ("missing", "draft"),
            "submit": ("draft",),
            "amend": ("submitted", "approved"),
            "approve": ("submitted",),
        }
        if status not in expected[action]:
            self._error(
                "turnout_review_required"
                if approval and self._state["current"].get("review_required")
                else "turnout_state_conflict"
            )
            return
        values = self._content(amend=action == "amend") if action in ("save", "amend") else {}
        if values is None:
            return
        payload = {
            "expected_revision": selected.get("revision", 0),
            "expected_schedule_revision": self._state["schedule"]["revision"],
            **values,
        }
        signature = json.dumps(
            {
                "station": self._state["station_id"],
                "period": self._state["selected_period"],
                "action": action,
                "data": payload,
            },
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        if approval:
            payload["password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        index = self._state["selected_period"]

        def saved(data: dict[str, Any]) -> None:
            if not self._record(data, index):
                self._error("request_failed")
                return

            def reviewed(snapshot: dict[str, Any]) -> None:
                if self._loaded(snapshot, accept=True):
                    self._pending = None
                    self._state["notice"] = {
                        "save": "turnout_saved",
                        "submit": "turnout_submitted",
                        "amend": "turnout_amended",
                        "approve": "turnout_approved",
                    }[action]
                    self._history()

            self._send(self._page_path(), "GET", None, reviewed)

        path = f"{self._path()}/{index}" + ("" if action == "save" else "/" + action)
        self._send(
            path, "PUT" if action == "save" else "POST", payload, saved, erase_password=approval
        )

    @Slot()
    def save(self) -> None:
        self._command("save")

    @Slot()
    def submit(self) -> None:
        self._command("submit")

    @Slot()
    def amend(self) -> None:
        self._command("amend")

    @Slot(str)
    def approve(self, password: str) -> None:
        self._command("approve", password=password)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(HKT).strftime(TIME_FORMAT) + " HKT" if parsed.tzinfo else "—"
        except ValueError, OverflowError:
            return "—"

    def _clear_report(self) -> None:
        self._state.update(report={}, report_text="", export_path="")

    def _report_path(
        self, locale: str, extension: str = "", *, station_report: bool = False
    ) -> str | None:
        if self._state["busy"]:
            return None
        if not self._state["station_id"] or locale not in ("tc", "sc", "en"):
            self._error("turnout_validation")
            return None
        if station_report:
            return f"{self._path()}/statement{extension}?locale={locale}"
        selected = self._state["selected"]
        if not selected or not self._reviewed:
            self._error("turnout_record_not_found")
            return None
        return (
            f"{self._path()}/{selected['period_index']}/statement{extension}"
            f"?revision={selected['revision']}&locale={locale}"
        )

    def _preview(self, locale: str, *, station_report: bool) -> None:
        path = self._report_path(locale, station_report=station_report)
        if path is None:
            return
        station_id = self._state["station_id"]
        selected = self._state["selected"]
        index, revision = selected.get("period_index"), selected.get("revision")
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="", export_path="")

        def loaded(data: dict[str, Any]) -> None:
            scope, lines = data.get("scope"), data.get("preview_lines")
            expected_scope = "station_current" if station_report else "period_revision"
            if not (
                isinstance(scope, dict)
                and isinstance(scope.get("station"), dict)
                and scope["station"].get("id") == station_id
                and data.get("report_scope") == expected_scope
                and data.get("locale") == locale
                and (
                    station_report
                    or (data.get("selected_period") == index and data.get("revision") == revision)
                )
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(
                report=data, report_text="\n".join(lines), notice="turnout_report_ready"
            )

        self._send(path, "GET", None, loaded)

    @Slot(str)
    def preview(self, locale: str) -> None:
        self._preview(locale, station_report=False)

    @Slot(str)
    def previewStation(self, locale: str) -> None:
        self._preview(locale, station_report=True)

    @Slot(str, str, str)
    @Slot(str, str, str, bool)
    def download(
        self, format: str, filepath: str, locale: str, station_report: bool = False
    ) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("turnout_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("turnout_export_failed")
            return
        path = self._report_path(locale, "." + format, station_report=station_report)
        if path is None:
            return
        self._generation += 1
        generation = self._generation
        self._state.update(refreshing=False, busy=True, error="", notice="", export_path="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state["busy"] = False
            self._error(code)

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not save_report(data, destination, format):
                failed("turnout_export_failed")
                return
            self._state.update(busy=False, notice="turnout_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(path, loaded, failed)
