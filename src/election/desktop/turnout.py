"""Reviewed turnout forms, live period coverage and exact-revision approvals."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.event_times import format_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.paper_reentry import paper_options, paper_record_fields
from election.desktop.recovery import RecoveryController
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
UNCERTAIN_PAPER_ERRORS = frozenset({
    "request_failed",
    "request_timeout",
    "disconnected",
    "database_unavailable",
    "certificate_error",
    "invalid_response",
    "session_expired",
    "access_changed",
    "recovery_outcome_check_required",
    "recovery_journal_unavailable",
})


def empty_forms() -> dict[str, str]:
    return {
        "supplied_hourly": "",
        "supplied_cumulative": "",
        "event_time": "",
        "source_context": "",
        "amendment_reason": "",
        "mode": "normal",
        "fallback_activation_id": "", "fallback_activation_revision": "",
        "stock_snapshot_id": "", "stock_snapshot_revision": "",
        "fallback_recovery_id": "", "fallback_recovery_revision": "",
    }


def record_display(row: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    if isinstance(row.get("source_basis"), dict):
        result["source_basis_display"] = quantity_display(row["source_basis"])
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
        self._paper_generation = 0
        self._opened = False
        self._reviewed = False
        self._reviewed_wrapper: dict[str, Any] = {}
        self._raw_items: list[dict[str, Any]] = []
        self._pending: tuple[str, str] | None = None
        self._paper_pending_request_id = ""
        self._paper_pending_identity: dict[str, Any] = {}
        self._recovery = (
            cast(RecoveryController | None, parent.property("recovery")) if parent else None
        )
        if self._recovery is not None:
            self._recovery.stateChanged.connect(self._recovery_state_changed)
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._paper_generation += 1
        self._opened = False
        self._reviewed = False
        self._reviewed_wrapper = {}
        self._raw_items = []
        self._pending = None
        self._paper_pending_request_id = ""
        self._paper_pending_identity = {}
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
            "paper_records": [],
            "paper_record": {},
            "paper_refreshing": False,
            "paper_error": "",
            "paper_pending_request_id": "",
            "uncertain_save": False,
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
            pending_request_id = self._paper_pending_request_id
            pending_identity = deepcopy(self._paper_pending_identity)
            self.reset()
            if pending_request_id:
                self._paper_pending_request_id = pending_request_id
                self._paper_pending_identity = pending_identity
                self._state.update(
                    paper_pending_request_id=pending_request_id,
                    uncertain_save=True,
                )
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

    def _clear_paper_binding(self, *, settled: bool = False) -> None:
        changed = bool(self._state["paper_record"])
        if settled:
            changed = changed or self._state["uncertain_save"] or bool(
                self._paper_pending_request_id
            ) or self._state["paper_refreshing"] or bool(self._state["paper_records"])
            self._paper_pending_request_id = ""
            self._paper_pending_identity = {}
            self._invalidate_paper_read()
            self._state.update(
                paper_pending_request_id="",
                uncertain_save=False,
            )
        if self._state["paper_record"]:
            self._state["paper_record"] = {}
        if changed:
            self.stateChanged.emit()

    def _lock_paper_command(
        self,
        request_id: str,
        paper_record_id: int,
        period_index: int,
        action: str,
        method: str,
        path: str,
    ) -> None:
        self._paper_pending_request_id = request_id
        self._paper_pending_identity = {
            "request_id": request_id,
            "station_id": self._state["station_id"],
            "period_index": period_index,
            "paper_record_id": paper_record_id,
            "action": action,
            "method": method,
            "path": path,
        }
        self._state.update(
            paper_pending_request_id=request_id,
            uncertain_save=False,
        )

    def _recovery_state_changed(self) -> None:
        request_id = self._paper_pending_request_id
        if not request_id or self._recovery is None:
            return
        recovery_state = self._recovery.property("state")
        commands = recovery_state.get("commands", []) if isinstance(recovery_state, dict) else []
        command = next(
            (
                row for row in commands
                if isinstance(row, dict)
                and row.get("request_id") == request_id
                and row.get("workflow") == "turnout"
            ),
            None,
        )
        if command is None:
            # Recovery commands are actor, server, station and role scoped. Missing
            # evidence cannot release the binding for this operation.
            return
        identity = self._paper_pending_identity
        payload = command.get("payload")
        if not (
            command.get("station_id") == identity.get("station_id")
            and isinstance(payload, dict)
            and payload.get("paper_record_id") == identity.get("paper_record_id")
            and command.get("path") == identity.get("path")
            and command.get("method") == identity.get("method")
        ):
            return
        status = command.get("status")
        if status in ("pending", "uncertain"):
            if not self._state["uncertain_save"]:
                self._state.update(
                    uncertain_save=True,
                    paper_pending_request_id=request_id,
                )
                self.stateChanged.emit()
            return
        if status not in ("committed", "rejected"):
            return
        self._paper_pending_request_id = ""
        self._paper_pending_identity = {}
        self._pending = None
        self._state.update(
            uncertain_save=False,
            paper_pending_request_id="",
            error=command.get("error", "") if status == "rejected" else "",
            notice="",
        )
        if status == "committed":
            receipt = command.get("receipt")
            result = receipt.get("record") if isinstance(receipt, dict) else None
            if not self._record(result, identity["period_index"]):
                self._state.update(uncertain_save=True, paper_pending_request_id=request_id)
                self._paper_pending_request_id = request_id
                self._paper_pending_identity = identity
                self._error("recovery_outcome_invalid")
                return
            self._state.update(paper_record={}, dirty=False)
        else:
            self._state["paper_pending_request_id"] = ""
        self.stateChanged.emit()
        if status == "committed" and identity.get("station_id") == self._state["station_id"]:
            self.reload(True)

    def _paper_record_options(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        return paper_options(
            snapshot,
            station_id=self._state["station_id"],
            workflow="turnout",
            target={"period_index": self._state["selected_period"]},
            actions=("save", "submit"),
        )

    def _invalidate_paper_read(self) -> None:
        self._paper_generation += 1
        self._state.update(paper_records=[], paper_refreshing=False, paper_error="")

    @Slot(result=bool)
    def refreshPaperRecords(self) -> bool:
        if (
            not self._state["station_id"]
            or self._state["paper_refreshing"]
            or self._state["busy"]
        ):
            return False
        self._paper_generation += 1
        generation = self._paper_generation
        station_id = self._state["station_id"]
        period_index = self._state["selected_period"]
        path = f"/api/workspace/stations/{station_id}/outages"
        self._state.update(paper_refreshing=True, paper_error="")
        self.stateChanged.emit()

        def loaded(snapshot: dict[str, Any]) -> None:
            if generation != self._paper_generation:
                return
            if station_id != self._state["station_id"] or period_index != self._state[
                "selected_period"
            ]:
                self._invalidate_paper_read()
                self.stateChanged.emit()
                return
            try:
                rows = self._paper_record_options(snapshot)
            except (KeyError, TypeError, ValueError):
                self._state.update(
                    paper_refreshing=False,
                    paper_error="paper_reentry_load_failed",
                    error="paper_reentry_load_failed",
                )
                self.stateChanged.emit()
                return
            selected_id = self._state["paper_record"].get("id")
            selected = next((row for row in rows if row["id"] == selected_id), None)
            if selected is not None:
                self._state["paper_record"] = deepcopy(selected)
            elif selected_id and not self._state["uncertain_save"]:
                self._state["paper_record"] = {}
            self._state.update(paper_records=rows, paper_refreshing=False, paper_error="")
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._paper_generation:
                return
            if station_id != self._state["station_id"] or period_index != self._state[
                "selected_period"
            ]:
                self._invalidate_paper_read()
                self.stateChanged.emit()
                return
            self._state.update(
                paper_refreshing=False,
                paper_error="paper_reentry_load_failed",
                error=code,
                notice="",
            )
            self.stateChanged.emit()

        self._request(path, "GET", None, loaded, failed)
        return True

    @Slot(int, result=bool)
    def selectPaperRecord(self, paper_id: int) -> bool:
        if self._state["busy"]:
            return False
        if self._state["uncertain_save"] or self._paper_pending_request_id:
            self._error("paper_reentry_uncertain")
            return False
        if type(paper_id) is not int or paper_id < 0:
            self._error("paper_reentry_invalid")
            return False
        if paper_id == 0:
            self._clear_paper_binding()
            self._state.update(error="", notice="")
            self.stateChanged.emit()
            return True
        if (
            self._state["role"] != "polling_officer"
            or self._state["context"].get("election", {}).get("status") != "active"
            or not self._reviewed
            or self._state["historical"]
        ):
            self._error("polling_officer_required")
            return False
        paper = next(
            (row for row in self._state["paper_records"] if row.get("id") == paper_id),
            None,
        )
        if paper is None:
            self._error("paper_reentry_invalid")
            return False
        self._state["paper_record"] = deepcopy(paper)
        if paper.get("action") == "save":
            event_time = format_event_time(
                paper["original_event_at"]
            ).removesuffix(" HKT")
            if self._state["forms"]["event_time"] != event_time:
                self._state["forms"]["event_time"] = event_time
                self._state["dirty"] = True
        self._state.update(error="", notice="")
        self.stateChanged.emit()
        return True

    @Slot(str, result=str)
    def formatPaperTime(self, value: str) -> str:
        return format_event_time(value)

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
            if (
                payload is not None
                and payload.get("paper_record_id")
                and payload.get("request_id") == self._paper_pending_request_id
            ):
                if code in UNCERTAIN_PAPER_ERRORS:
                    self._state.update(
                        uncertain_save=True,
                        paper_pending_request_id=self._paper_pending_request_id,
                    )
                    if self._recovery is not None:
                        self._recovery.reload()
                else:
                    self._paper_pending_request_id = ""
                    self._paper_pending_identity = {}
                    self._state.update(
                        uncertain_save=False,
                        paper_pending_request_id="",
                    )
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
            basis = row.get("source_basis")
            if isinstance(basis, dict):
                if "recovery_id" in basis:
                    forms["mode"] = "recovery"
                    forms["fallback_recovery_id"] = str(basis["recovery_id"])
                    forms["fallback_recovery_revision"] = str(basis["recovery_revision"])
                else:
                    forms["mode"] = "fallback"
                    forms["fallback_activation_id"] = str(basis["activation_id"])
                    forms["fallback_activation_revision"] = str(basis["activation_revision"])
                    forms["stock_snapshot_id"] = str(basis["stock_snapshot_id"])
                    forms["stock_snapshot_revision"] = str(basis["stock_snapshot_revision"])
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
        self._raw_items = deepcopy(items)
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
        if self._state["uncertain_save"]:
            self._error("paper_reentry_uncertain")
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
                self.refreshPaperRecords()

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
        self.refreshPaperRecords()
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
        self._clear_paper_binding()
        self._invalidate_paper_read()
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
        self._clear_paper_binding()
        self._invalidate_paper_read()
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
        self._clear_paper_binding()
        self._invalidate_paper_read()

        def loaded(data: dict[str, Any]) -> None:
            if not self._record(data, index) or data["revision"] != revision:
                self._error("request_failed")
                return
            wrapper = next((row for row in self._raw_items if row["period_index"] == index), {})
            if not wrapper:
                self._error("request_failed")
                return
            # Keep the reviewed basis raw even when its Qt view has nested display fields.
            self._accept(data, wrapper, historical=revision < current["revision"])
            self._history()
            self.refreshPaperRecords()

        self._send(f"{self._path()}/{index}?revision={revision}", "GET", None, loaded)
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._state["role"] != "polling_officer"
            or self._state["busy"]
            or self._state["uncertain_save"]
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
            if name == "mode" and value == "fallback":
                self._state["forms"]["supplied_hourly"] = ""
                self._state["forms"]["supplied_cumulative"] = ""
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
            mode = form["mode"]
            if mode not in ("normal", "fallback", "recovery"):
                raise ValueError("Select a supported turnout source mode")
            if mode in ("fallback", "recovery"):
                if mode == "fallback" and (
                    values["supplied_hourly"] is not None
                    or values["supplied_cumulative"] is not None
                ):
                    raise ValueError("Fallback turnout is calculated from ordinary stock")
                values["mode"] = mode
                source_fields = (
                    ("fallback_activation_id", "fallback_activation_revision",
                     "stock_snapshot_id", "stock_snapshot_revision")
                    if mode == "fallback"
                    else ("fallback_recovery_id", "fallback_recovery_revision")
                )
                for name in source_fields:
                    text = form[name].strip()
                    if not text or not text.isascii() or not text.isdecimal():
                        raise ValueError("Select an exact positive source identity")
                    identity = int(text)
                    if not 1 <= identity <= MAX_TOTAL:
                        raise ValueError("Source identity is outside the supported range")
                    values[name] = identity
            text = form["event_time"].strip()
            paper = self._state["paper_record"]
            original = (
                paper.get("original_event_at")
                if paper.get("action") == "save"
                else self._state["selected"].get("event_at")
            )
            if original and text == self.formatTime(original).removesuffix(" HKT"):
                # The minute form must not round a precise saved or paper event time.
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
        if self._state["uncertain_save"]:
            self._error("paper_reentry_uncertain")
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
        paper = self._state["paper_record"]
        if action in ("amend", "approve") and paper:
            self._error("paper_reentry_invalid")
            return
        paper_fields: dict[str, int] = {}
        if action in ("save", "submit"):
            try:
                paper_fields = paper_record_fields(
                    paper,
                    station_id=self._state["station_id"],
                    workflow="turnout",
                    action=action,
                    target={"period_index": self._state["selected_period"]},
                )
            except ValueError:
                self._error("paper_reentry_invalid")
                return
        values = self._content(amend=action == "amend") if action in ("save", "amend") else {}
        if values is None:
            return
        payload = {
            "expected_revision": selected.get("revision", 0),
            "expected_schedule_revision": self._state["schedule"]["revision"],
            **values,
            **paper_fields,
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
        paper_id = paper_fields.get("paper_record_id", 0)
        if paper_id:
            command_path = f"{self._path()}/{self._state['selected_period']}" + (
                "" if action == "save" else "/" + action
            )
            self._lock_paper_command(
                self._pending[1],
                paper_id,
                self._state["selected_period"],
                action,
                "PUT" if action == "save" else "POST",
                command_path,
            )
        if approval:
            payload["password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        index = self._state["selected_period"]

        def saved(data: dict[str, Any]) -> None:
            if not self._record(data, index):
                if paper_id:
                    self._state.update(uncertain_save=True, dirty=True)
                    self._error("request_failed")
                    return
                self._error("request_failed")
                return
            if paper_id:
                self._clear_paper_binding(settled=True)

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
                    self.refreshPaperRecords()

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
