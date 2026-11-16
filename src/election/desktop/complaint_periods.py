"""Reviewed periods remain separate from live cohort and approval changes."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

COUNTS = ("total_received", "total_completed", "total_in_progress")
SUMMARY = ("required", "approved_current", "missing")
STATUSES = ("draft", "submitted", "approved")
IMMUTABLE_RECORD = COUNTS + (
    "id",
    "revision",
    "station_id",
    "period_index",
    "schedule_revision",
    "start_at",
    "end_at",
    "basis_at",
    "entered_at",
    "actor_id",
    "amendment_reason",
    "members",
    "group_counts",
)


def count_display(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    result = deepcopy(row)
    for name in fields:
        result[name + "_display"] = str(result[name])
    return result


def record_display(row: dict[str, Any]) -> dict[str, Any]:
    result = count_display(row, COUNTS)
    result["period_index_display"] = str(result["period_index"])
    result["group_counts"] = [count_display(group, COUNTS) for group in result["group_counts"]]
    return result


def wrapper_display(wrapper: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(wrapper)
    result["period_index_display"] = str(result["period_index"])
    if result["record"] is not None:
        result["record"] = record_display(result["record"])
    return result


def positive(value: Any) -> bool:
    return type(value) is int and value > 0


def aware_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def valid_counts(row: Any) -> bool:
    return bool(
        isinstance(row, dict)
        and all(type(row.get(name)) is int and row[name] >= 0 for name in COUNTS)
        and row["total_received"] == row["total_completed"] + row["total_in_progress"]
    )


class ComplaintPeriodsController(QObject):
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
        self._reviewed_schedule_revision = 0
        self._live_wrappers: dict[int, dict[str, Any]] = {}
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
        self._reviewed_schedule_revision = 0
        self._live_wrappers = {}
        self._pending = None
        self._state = {
            "station_id": 0,
            "context": {},
            "role": "",
            "schedule": {},
            "schedule_state": "unavailable",
            "items": [],
            "current": {},
            "selected": {},
            "selected_period": 0,
            "selected_period_context": {},
            "history": [],
            "summary": count_display({"required": 0, "approved_current": 0, "missing": 0}, SUMMARY),
            "outside_coverage_case_count": 0,
            "period_count": 0,
            "period_count_display": "0",
            "outside_coverage_case_count_display": "0",
            "offset": 0,
            "limit": 100,
            "forms": {"reason": ""},
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
            error="complaint_period_validation" if code == "validation_error" else code,
            notice="",
        )
        self.stateChanged.emit()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/complaint-periods"

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
        uncertain: bool = False,
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
            if uncertain and code in (
                "request_failed",
                "disconnected",
                "database_unavailable",
                "request_timeout",
            ):
                self._state["dirty"] = True
            self._error(code)

        self._request(path, method, payload, done, failed)

    def _record(self, row: Any, index: int) -> bool:
        return bool(
            valid_counts(row)
            and row.get("station_id") == self._state["station_id"]
            and positive(row.get("period_index"))
            and row.get("period_index") == index
            and all(
                positive(row.get(name))
                for name in ("id", "revision", "schedule_revision", "actor_id")
            )
            and row.get("status") in STATUSES
            and all(
                aware_time(row.get(name))
                for name in ("start_at", "end_at", "basis_at", "entered_at")
            )
            and all(
                type(row.get(name)) is bool
                for name in (
                    "basis_current",
                    "is_latest_revision",
                    "approval_valid",
                    "review_required",
                )
            )
            and isinstance(row.get("amendment_reason"), str)
            and all(
                row.get(name) is None or aware_time(row[name])
                for name in ("submitted_at", "approved_at")
            )
            and all(
                row.get(name) is None or positive(row[name])
                for name in ("submitted_by", "approved_by")
            )
            and isinstance(row.get("members"), list)
            and len(row["members"]) == row["total_received"]
            and all(
                isinstance(member, dict)
                and all(
                    positive(member.get(name))
                    for name in (
                        "case_id",
                        "case_revision_id",
                        "revision",
                        "actor_id",
                        "category_id",
                        "category_revision",
                    )
                )
                and isinstance(member.get("case_reference"), str)
                and member.get("work_status") in ("in_progress", "completed")
                and all(aware_time(member.get(name)) for name in ("received_at", "entered_at"))
                and (member.get("completed_at") is None or aware_time(member["completed_at"]))
                and all(
                    isinstance(member.get("category_" + label), str)
                    for label in (
                        "code",
                        "label_en",
                        "label_tc",
                        "label_sc",
                    )
                )
                for member in row["members"]
            )
            and isinstance(row.get("group_counts"), list)
            and all(
                valid_counts(group)
                and all(
                    isinstance(group.get(label), str)
                    for label in (
                        "code",
                        "label_en",
                        "label_tc",
                        "label_sc",
                        "source",
                        "source_english",
                        "translation_provenance",
                    )
                )
                and all(
                    positive(group.get(name))
                    for name in (
                        "category_id",
                        "category_revision_id",
                        "category_revision",
                    )
                )
                and type(group.get("verified_source")) is bool
                and type(group.get("is_other")) is bool
                and (group.get("reference_page") is None or positive(group["reference_page"]))
                for group in row["group_counts"]
            )
            and all(
                sum(group[name] for group in row["group_counts"]) == row[name] for name in COUNTS
            )
        )

    def _accept(
        self,
        row: dict[str, Any],
        wrapper: dict[str, Any],
        *,
        historical: bool = False,
    ) -> None:
        self._reviewed = True
        self._clear_report()
        self._reviewed_wrapper = deepcopy(wrapper)
        self._reviewed_schedule_revision = self._state["schedule"].get("revision", 0)
        self._state.update(
            selected=record_display(row) if row else {},
            forms={"reason": row.get("amendment_reason", "")},
            selected_period_context={
                "period_index": self._state["selected_period"],
                "period_index_display": str(self._state["selected_period"]),
                "start_at": row["start_at"] if row else wrapper["start_at"],
                "end_at": row["end_at"] if row else wrapper["end_at"],
            },
            dirty=False,
            historical=historical,
            newer_revision=False,
        )
        self.erasePassword.emit()

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> bool:
        context, schedule, items, summary = (
            data.get(name)
            for name in (
                "context",
                "schedule",
                "items",
                "summary",
            )
        )
        if not (
            isinstance(context, dict)
            and isinstance(context.get("station"), dict)
            and context.get("station", {}).get("id") == self._state["station_id"]
            and data.get("schedule_state") in ("configured", "unavailable")
            and (
                (
                    isinstance(schedule, dict)
                    and positive(schedule.get("revision"))
                    and all(
                        aware_time(schedule.get(name))
                        for name in ("planned_opening_at", "planned_closing_at")
                    )
                    and positive(schedule.get("reporting_interval_minutes"))
                )
                if data["schedule_state"] == "configured"
                else schedule is None
            )
            and type(data.get("period_count")) is int
            and data["period_count"] >= 0
            and data.get("offset") == self._state["offset"]
            and data.get("limit") == self._state["limit"]
            and isinstance(items, list)
            and [item.get("period_index") for item in items if isinstance(item, dict)]
            == list(
                range(
                    self._state["offset"] + 1,
                    min(data["period_count"], self._state["offset"] + self._state["limit"]) + 1,
                )
            )
            and all(
                isinstance(item, dict)
                and all(aware_time(item.get(name)) for name in ("start_at", "end_at"))
                and all(
                    type(item.get(name)) is bool
                    for name in ("basis_current", "approval_valid", "review_required")
                )
                and (
                    (item.get("record") is None and item.get("status") == "missing")
                    or (
                        self._record(item.get("record"), item["period_index"])
                        and item.get("status") == item["record"]["status"]
                    )
                )
                for item in items
            )
            and isinstance(summary, dict)
            and all(type(summary.get(name)) is int and summary[name] >= 0 for name in SUMMARY)
            and summary["required"] == data["period_count"]
            and type(data.get("outside_coverage_case_count")) is int
            and data["outside_coverage_case_count"] >= 0
        ):
            self._error("request_failed")
            return False
        self._live_wrappers = {item["period_index"]: deepcopy(item) for item in items}
        self._state.update(
            items=[wrapper_display(item) for item in items],
            schedule=deepcopy(schedule or {}),
            schedule_state=data["schedule_state"],
            context=deepcopy(context),
            summary=count_display(summary, SUMMARY),
            period_count=data["period_count"],
            period_count_display=str(data["period_count"]),
            outside_coverage_case_count=data["outside_coverage_case_count"],
            outside_coverage_case_count_display=str(data["outside_coverage_case_count"]),
        )
        wrapper = self._live_wrappers.get(self._state["selected_period"], {})
        if accept and not wrapper and items:
            wrapper = items[0]
            self._state["selected_period"] = wrapper["period_index"]
        self._state["current"] = wrapper_display(wrapper) if wrapper else {}
        if accept:
            if wrapper:
                self._accept(wrapper["record"] or {}, wrapper)
            else:
                self._reviewed = True
                self._reviewed_wrapper = {}
                self._state.update(
                    selected_period=0,
                    selected={},
                    selected_period_context={},
                    forms={"reason": ""},
                    history=[],
                    dirty=False,
                    historical=False,
                    newer_revision=False,
                )
        else:
            self._state["newer_revision"] = wrapper != self._reviewed_wrapper
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return True

    def _history(self) -> None:
        index = self._state["selected_period"]
        if not index:
            return

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
            self._error("unsaved_complaint_period_changes")
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
            if station_id and (self._state["busy"] or (self._state["dirty"] and not discard)):
                self._error("unsaved_complaint_period_changes")
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
            self._error("complaint_period_validation")
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
        if index not in self._live_wrappers:
            self._state["offset"] = ((index - 1) // self._state["limit"]) * self._state["limit"]
        self._reviewed = False
        self._state.update(
            selected_period=index,
            selected={},
            history=[],
            forms={"reason": ""},
            dirty=False,
            historical=False,
        )
        self._load_page()
        return True

    @Slot("qlonglong", result=bool)
    @Slot("qlonglong", bool, result=bool)
    def setPage(self, offset: int, discard: bool = False) -> bool:
        if type(offset) is not int or not 0 <= offset < self._state["period_count"]:
            self._error("complaint_period_validation")
            return False
        if not self._can_load(discard):
            return False
        self._reviewed = False
        self._state.update(
            offset=offset,
            selected_period=offset + 1,
            selected={},
            history=[],
            forms={"reason": ""},
            dirty=False,
            historical=False,
        )
        self._load_page()
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        index = self._state["selected_period"]
        if (
            type(revision) is not int
            or revision < 1
            or not self._state["current"].get("record")
            or not self._can_load(discard)
        ):
            return False

        def loaded(record: dict[str, Any]) -> None:
            if not self._record(record, index) or record["revision"] != revision:
                self._error("request_failed")
                return

            def current(snapshot: dict[str, Any]) -> None:
                if not self._loaded(snapshot, accept=False):
                    return
                wrapper = self._live_wrappers.get(index, {})
                head = wrapper.get("record") or {}
                if head.get("revision", 0) < revision:
                    self._error("request_failed")
                    return
                self._accept(record, wrapper, historical=revision < head["revision"])
                self._history()

            self._send(self._page_path(), "GET", None, current)

        self._send(f"{self._path()}/{index}?revision={revision}", "GET", None, loaded)
        return True

    @Slot(str)
    def setReason(self, reason: str) -> None:
        if (
            self._state["role"] != "polling_officer"
            or self._state["busy"]
            or self._state["historical"]
            or not self._reviewed
            or self._state["context"].get("election", {}).get("status") != "active"
            or self._state["selected"].get("status") not in ("submitted", "approved")
        ):
            return
        if self._state["forms"]["reason"] != reason:
            self._state["forms"]["reason"] = reason
            self._state.update(dirty=True, error="", notice="")
            self.stateChanged.emit()

    def _command(self, action: str, password: str = "") -> None:
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
        if (
            not self._reviewed
            or not self._state["selected_period"]
            or not self._reviewed_schedule_revision
        ):
            self._error("schedule_required")
            return
        selected = self._state["selected"]
        expected = {
            "prepare": ("missing", "draft"),
            "submit": ("draft",),
            "amend": ("submitted", "approved"),
            "approve": ("submitted",),
        }
        if selected.get("status", "missing") not in expected[action]:
            self._error("complaint_period_state_conflict")
            return
        payload = {
            "expected_revision": selected.get("revision", 0),
            "expected_schedule_revision": self._reviewed_schedule_revision,
        }
        if action == "amend":
            reason = self._state["forms"]["reason"]
            if not reason.strip() or len(reason) > 1000:
                self._error("complaint_period_validation")
                return
            payload["reason"] = reason
        signature = json.dumps(
            {
                "station_id": self._state["station_id"],
                "period_index": self._state["selected_period"],
                "action": action,
                "data": payload,
            },
            sort_keys=True,
        )
        retry = self._pending is not None and self._pending[0] == signature
        if action in ("submit", "approve") and not retry:
            if self._state["dirty"]:
                self._error("unsaved_complaint_period_changes")
                return
            current = self._state["current"].get("record") or {}
            if current.get("revision") != selected.get("revision"):
                self._error("revision_conflict")
                return
            if (
                not self._state["current"].get("basis_current")
                or self._live_wrappers.get(self._state["selected_period"], {})
                != self._reviewed_wrapper
            ):
                self._error("complaint_period_review_required")
                return
        if not retry:
            self._pending = signature, str(uuid4())
        assert self._pending is not None
        payload["request_id"] = self._pending[1]
        if approval:
            payload["password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        index = self._state["selected_period"]
        revision = selected.get("revision", 0) + int(action in ("prepare", "amend"))
        expected_status = {
            "prepare": "draft",
            "submit": "submitted",
            "amend": "draft",
            "approve": "approved",
        }[action]

        def invalid_response() -> None:
            self._state["dirty"] = True
            self._error("request_failed")

        def saved(data: dict[str, Any]) -> None:
            if (
                not self._record(data, index)
                or data["revision"] != revision
                or data["status"] != expected_status
            ):
                invalid_response()
                return
            self._state["dirty"] = True

            def confirmed(record: dict[str, Any]) -> None:
                if (
                    not self._record(record, index)
                    or any(record[name] != data[name] for name in IMMUTABLE_RECORD)
                    or STATUSES.index(record["status"]) < STATUSES.index(expected_status)
                ):
                    invalid_response()
                    return

                def reviewed(snapshot: dict[str, Any]) -> None:
                    if not self._loaded(snapshot, accept=False):
                        return
                    wrapper = self._live_wrappers.get(index, {})
                    head = wrapper.get("record") or {}
                    if head.get("revision", 0) < revision:
                        invalid_response()
                        return
                    self._accept(record, wrapper, historical=head["revision"] > revision)
                    self._pending = None
                    self._state["notice"] = {
                        "prepare": "complaint_period_prepared",
                        "submit": "complaint_period_submitted",
                        "amend": "complaint_period_amended",
                        "approve": "complaint_period_approved",
                    }[action]
                    self._history()

                self._send(self._page_path(), "GET", None, reviewed, uncertain=True)

            self._send(
                f"{self._path()}/{index}?revision={revision}",
                "GET",
                None,
                confirmed,
                uncertain=True,
            )

        path = f"{self._path()}/{index}" + ("" if action == "prepare" else "/" + action)
        self._send(
            path,
            "PUT" if action == "prepare" else "POST",
            payload,
            saved,
            erase_password=approval,
            uncertain=True,
        )

    @Slot()
    def prepare(self) -> None:
        self._command("prepare")

    @Slot()
    def submit(self) -> None:
        self._command("submit")

    @Slot()
    def amend(self) -> None:
        self._command("amend")

    @Slot(str)
    def approve(self, password: str) -> None:
        self._command("approve", password)

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
        self,
        locale: str,
        extension: str = "",
        *,
        station_report: bool = False,
    ) -> str | None:
        if self._state["busy"]:
            return None
        if not self._state["station_id"] or locale not in ("tc", "sc", "en"):
            self._error("complaint_period_validation")
            return None
        if station_report:
            return f"{self._path()}/statement{extension}?locale={locale}"
        selected = self._state["selected"]
        if not selected or not self._reviewed:
            self._error("complaint_period_record_not_found")
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
            scope, lines, items = data.get("scope"), data.get("preview_lines"), data.get("items")
            expected_scope = "station_current" if station_report else "period_revision"
            if not (
                isinstance(scope, dict)
                and isinstance(scope.get("station"), dict)
                and scope["station"].get("id") == station_id
                and data.get("report_scope") == expected_scope
                and data.get("locale") == locale
                and data.get("revision_state") in ("current", "historical")
                and aware_time(data.get("generated_at"))
                and isinstance(items, list)
                and all(
                    isinstance(item, dict)
                    and positive(item.get("period_index"))
                    and self._record(item, item["period_index"])
                    for item in items
                )
                and (
                    station_report
                    or (
                        data.get("selected_period") == index
                        and data.get("revision") == revision
                        and len(items) == 1
                        and items[0]["period_index"] == index
                        and items[0]["revision"] == revision
                    )
                )
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(
                report=deepcopy(data), report_text="\n".join(lines), notice="complaint_report_ready"
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
            self._error("complaint_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("complaint_export_failed")
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
                failed("complaint_export_failed")
                return
            self._state.update(busy=False, notice="complaint_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(path, loaded, failed)
