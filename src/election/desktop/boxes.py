"""Reviewed box handovers and milestones remain separate from live station records."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

MILESTONES = ("conversion_complete", "first_box_opening", "questionable_determination_start")


def box_forms(box: dict[str, Any] | None = None) -> dict[str, str]:
    box = box or {}
    prepared = box.get("prepared_at", "")
    return {
        "box_reference": box.get("box_reference", ""),
        "seal_reference": box.get("seal_reference", ""),
        "prepared_time": datetime.fromisoformat(prepared).astimezone(HKT).strftime(TIME_FORMAT)
        if prepared
        else "",
        "event_time": "",
        "reason": "",
    }


def milestone_forms(row: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        "event_time": "",
        "reason": "",
        "box_id": str(row["box_id"]) if row and row.get("box_id") is not None else "",
    }


class BoxesController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject | None = None,
        *,
        download: DownloadRequest | None = None,
    ) -> None:
        super().__init__(parent)
        self._request, self._download = request, download
        self._generation = 0
        self._opened = False
        self._reviewed = False
        self._box_dirty = False
        self._milestone_dirty = False
        self._pending: dict[str, tuple[str, str]] = {}
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = self._reviewed = False
        self._box_dirty = self._milestone_dirty = False
        self._pending = {}
        self._state = {
            "station_id": 0,
            "context": {},
            "role": "",
            "items": [],
            "milestones": [],
            "milestone_history": [],
            "counting_applicable": False,
            "count_completion": None,
            "selected": {},
            "history": [],
            "selected_milestone": {},
            "milestone_kind": MILESTONES[0],
            "forms": box_forms(),
            "milestone_forms": milestone_forms(),
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "error": "",
            "notice": "",
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
            self.reload(True)

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/boxes"

    def _error(self, code: str) -> None:
        self._state.update(
            error="box_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _send(
        self,
        suffix: str,
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

        self._request(self._path() + suffix, method, payload, done, failed)

    def _box(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and type(row.get("id")) is int
            and row["id"] > 0
            and self._state["station_id"]
            in (row.get("origin_station_id"), row.get("destination_station_id"))
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("mode") in ("local", "send")
            and row.get("status") in ("prepared", "departed", "received")
            and all(
                isinstance(row.get(key), str)
                for key in (
                    "box_reference",
                    "seal_reference",
                    "prepared_at",
                    "entered_at",
                )
            )
        )

    def _milestone(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and row.get("kind") in MILESTONES
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and isinstance(row.get("event_at"), str)
            and isinstance(row.get("entered_at"), str)
        )

    def _dirty(self) -> None:
        self._state["dirty"] = self._box_dirty or self._milestone_dirty

    def _newer(self) -> None:
        selected, milestone = self._state["selected"], self._state["selected_milestone"]
        current: dict[str, Any] = next(
            (row for row in self._state["items"] if row["id"] == selected.get("id")), {}
        )
        latest: dict[str, Any] = next(
            (
                row
                for row in self._state["milestones"]
                if row["kind"] == self._state["milestone_kind"]
            ),
            {},
        )
        self._state["newer_revision"] = bool(
            (selected and current.get("revision") != selected["revision"])
            or latest.get("revision", 0) != milestone.get("revision", 0)
        )

    def _accept_box(self, box: dict[str, Any]) -> None:
        self._state.update(selected=deepcopy(box), forms=box_forms(box))
        self._box_dirty = False
        self._dirty()

    def _accept_milestone(self) -> None:
        row: dict[str, Any] = next(
            (
                row
                for row in self._state["milestones"]
                if row["kind"] == self._state["milestone_kind"]
            ),
            {},
        )
        self._state.update(selected_milestone=deepcopy(row), milestone_forms=milestone_forms(row))
        self._milestone_dirty = False
        self._dirty()

    def _loaded(self, data: dict[str, Any], *, accept: bool = False) -> bool:
        context = data.get("context")
        if not (
            isinstance(context, dict)
            and isinstance(context.get("station"), dict)
            and context["station"].get("id") == self._state["station_id"]
            and isinstance(data.get("items"), list)
            and all(self._box(row) for row in data["items"])
            and isinstance(data.get("milestones"), list)
            and all(self._milestone(row) for row in data["milestones"])
            and isinstance(data.get("milestone_history"), list)
            and all(self._milestone(row) for row in data["milestone_history"])
            and type(data.get("counting_applicable")) is bool
            and data.get("count_completion") is None
        ):
            self._error("request_failed")
            return False
        self._state.update(
            context={**self._state["context"], **deepcopy(context)},
            items=deepcopy(data["items"]),
            milestones=deepcopy(data["milestones"]),
            milestone_history=deepcopy(data["milestone_history"]),
            counting_applicable=data["counting_applicable"],
            count_completion=None,
        )
        if accept:
            selected_id = self._state["selected"].get("id")
            self._accept_box(next((row for row in data["items"] if row["id"] == selected_id), {}))
            self._accept_milestone()
            self._reviewed = True
        self._newer()
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return True

    @Slot(result=bool)
    @Slot(int, str, result=bool)
    @Slot(int, str, bool, result=bool)
    def open(self, station_id: int | None = None, role: str = "", discard: bool = False) -> bool:
        station_id = self._state["station_id"] if station_id is None else station_id
        role = role or self._state["role"]
        if self._state["busy"] or station_id < 0:
            return False
        if station_id != self._state["station_id"]:
            if self._state["dirty"] and not discard:
                self._error("unsaved_box_changes")
                return False
            self.reset()
            self._state.update(station_id=station_id, role=role)
        self._opened = True
        if not station_id:
            self.stateChanged.emit()
            return True
        self._state["role"] = role
        if not self._reviewed:
            return self.reload(discard)
        self.refresh()
        return True

    @Slot()
    def refresh(self) -> None:
        if (
            self._opened
            and self._state["station_id"]
            and not self._state["busy"]
            and not self._state["refreshing"]
        ):

            def loaded(data: dict[str, Any]) -> None:
                self._loaded(data)

            self._send("", "GET", None, loaded, background=True)

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, discard: bool = False) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_box_changes")
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            if self._loaded(data, accept=True) and self._state["selected"]:
                self._history()

        self._send("", "GET", None, loaded)
        return True

    def _history(self, *, accept: bool = False, box_id: int | None = None) -> None:
        box_id = box_id or self._state["selected"]["id"]

        def loaded(data: dict[str, Any]) -> None:
            box, items = data.get("box"), data.get("items")
            if (
                not isinstance(box, dict)
                or not self._box(box)
                or box["id"] != box_id
                or not isinstance(items, list)
                or not all(
                    isinstance(row, dict)
                    and row.get("box_id") == box_id
                    and type(row.get("revision")) is int
                    for row in items
                )
            ):
                self._error("request_failed")
                return
            if accept:
                self._accept_box(box)
            heads = {row["id"]: row for row in self._state["items"]}
            heads[box_id] = deepcopy(box)
            self._state["items"] = [heads[key] for key in sorted(heads)]
            self._state["history"] = deepcopy(
                [row for row in items if row["revision"] <= self._state["selected"]["revision"]]
            )
            self._newer()

        self._send(f"/{box_id}/history", "GET", None, loaded)

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadBox(self, box_id: int, discard: bool = False) -> bool:
        if not self._state["station_id"] or self._state["busy"] or box_id < 0:
            return False
        if self._box_dirty and not discard:
            self._error("unsaved_box_changes")
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        if box_id:
            self._history(accept=True, box_id=box_id)
        else:
            self._accept_box({})
            self._state["history"] = []
            self._newer()
            self.stateChanged.emit()
        return True

    def _writable(self, role: str) -> bool:
        if self._state["busy"] or not self._state["station_id"]:
            return False
        if self._state["role"] != role:
            self._error(role + "_required")
            return False
        if self._state["context"].get("election", {}).get("status") != "active":
            self._error("active_election_required")
            return False
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._state["role"] not in ("polling_officer", "counting_officer")
            or self._state["busy"]
        ):
            return
        if self._state["context"].get("election", {}).get("status") != "active":
            return
        if name in self._state["forms"] and self._state["forms"][name] != value:
            self._state["forms"][name] = value
            self._box_dirty = True
            self._dirty()
            self._state.update(error="", notice="")
            self.stateChanged.emit()

    @Slot(str, result=bool)
    @Slot(str, bool, result=bool)
    def setKind(self, kind: str, discard: bool = False) -> bool:
        if self._state["busy"]:
            return False
        if kind not in MILESTONES:
            self._error("box_validation")
            return False
        if self._milestone_dirty and not discard:
            self._error("unsaved_box_changes")
            return False
        self._generation += 1
        self._state.update(milestone_kind=kind, refreshing=False, error="", notice="")
        self._accept_milestone()
        self._newer()
        self.stateChanged.emit()
        return True

    @Slot(str, str)
    def setMilestoneField(self, name: str, value: str) -> None:
        if (
            self._state["busy"]
            or self._state["role"] != "counting_officer"
            or self._state["context"].get("election", {}).get("status") != "active"
            or not self._state["counting_applicable"]
        ):
            return
        if name == "box_id" and self._state["milestone_kind"] != "first_box_opening":
            return
        if name in self._state["milestone_forms"] and self._state["milestone_forms"][name] != value:
            self._state["milestone_forms"][name] = value
            self._milestone_dirty = True
            self._dirty()
            self._state.update(error="", notice="")
            self.stateChanged.emit()

    @Slot()
    def saveMilestone(self) -> None:
        if not self._writable("counting_officer"):
            return
        if not self._state["counting_applicable"]:
            self._error("counting_station_required")
            return
        kind = self._state["milestone_kind"]
        current, form = self._state["selected_milestone"], self._state["milestone_forms"]
        try:
            if len(form["reason"]) > 1000:
                raise ValueError("Reason exceeds supported length")
            if current and not form["reason"].strip():
                self._error("box_correction_reason_required")
                return
            box_id = None
            if kind == "first_box_opening":
                value = form["box_id"].strip()
                if not value.isascii() or not value.isdecimal() or len(value) > 10:
                    raise ValueError("A received box is required")
                box_id = int(value)
                if not 1 <= box_id <= 2147483647:
                    raise ValueError("A received box is required")
            payload = {
                "expected_revision": current.get("revision", 0),
                "event_at": self._time(form["event_time"]),
                "reason": form["reason"],
                "box_id": box_id,
            }
        except ValueError:
            self._error("box_validation")
            return
        action = "milestone_" + kind
        signature = json.dumps(
            {"station": self._state["station_id"], "kind": kind, "body": payload}, sort_keys=True
        )
        previous = self._pending.get(action)
        if not previous or previous[0] != signature:
            previous = signature, str(uuid4())
            self._pending[action] = previous
        payload["request_id"] = previous[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._milestone(data) or data["kind"] != kind:
                self._error("request_failed")
                return
            self._pending.pop(action, None)
            self._state.update(
                selected_milestone=deepcopy(data),
                milestone_forms=milestone_forms(data),
                notice="box_milestone_saved",
                report={},
                report_text="",
                export_path="",
            )
            self._milestone_dirty = False
            self._dirty()

            def loaded(snapshot: dict[str, Any]) -> None:
                self._loaded(snapshot)

            self._send("", "GET", None, loaded)

        self._send(f"/milestones/{kind}", "PUT", payload, saved)

    def _time(self, value: str) -> str:
        return datetime.strptime(value.strip(), TIME_FORMAT).replace(tzinfo=HKT).isoformat()

    def _write(
        self, action: str, suffix: str, method: str, payload: dict[str, Any], notice: str
    ) -> None:
        signature = json.dumps(
            {
                "station": self._state["station_id"],
                "path": suffix,
                "method": method,
                "body": payload,
            },
            sort_keys=True,
        )
        previous = self._pending.get(action)
        if not previous or previous[0] != signature:
            previous = signature, str(uuid4())
            self._pending[action] = previous
        payload["request_id"] = previous[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._box(data):
                self._error("request_failed")
                return
            self._pending.pop(action, None)
            self._accept_box(data)
            self._state.update(notice=notice, report={}, report_text="", export_path="")
            self._history()

        self._send(suffix, method, payload, saved)

    @Slot()
    def create(self) -> None:
        if not self._writable("polling_officer"):
            return
        form = self._state["forms"]
        try:
            if (
                self._state["selected"]
                or not form["box_reference"].strip()
                or not form["seal_reference"].strip()
            ):
                raise ValueError("New box references required")
            if len(form["box_reference"]) > 64 or len(form["seal_reference"]) > 128:
                raise ValueError("Reference exceeds supported length")
            payload = {
                "box_reference": form["box_reference"],
                "seal_reference": form["seal_reference"],
                "prepared_at": self._time(form["prepared_time"]),
            }
        except ValueError:
            self._error("box_validation")
            return
        self._write("create", "", "POST", payload, "box_saved")

    def _handover(self, action: str, *, correction: bool = False) -> None:
        role = "polling_officer" if action == "departure" else "counting_officer"
        if not self._writable(role):
            return
        selected, form = self._state["selected"], self._state["forms"]
        side = "origin_station_id" if action == "departure" else "destination_station_id"
        if not selected or selected[side] != self._state["station_id"]:
            self._error("box_state_conflict")
            return
        try:
            if len(form["reason"]) > 1000:
                raise ValueError("Reason exceeds supported length")
            if correction and not form["reason"].strip():
                self._error("box_correction_reason_required")
                return
            payload = {
                "expected_revision": selected["revision"],
                "event_at": self._time(form["event_time"]),
                "reason": form["reason"],
            }
        except ValueError:
            self._error("box_validation")
            return
        self._write(
            action,
            f"/{selected['id']}/{action}",
            "PUT" if correction else "POST",
            payload,
            "box_corrected"
            if correction
            else "box_departed"
            if action == "departure"
            else "box_received",
        )

    @Slot()
    def depart(self) -> None:
        self._handover("departure")

    @Slot()
    def receive(self) -> None:
        self._handover("receipt")

    @Slot()
    def correctDeparture(self) -> None:
        self._handover("departure", correction=True)

    @Slot()
    def correctReceipt(self) -> None:
        self._handover("receipt", correction=True)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(HKT).strftime(TIME_FORMAT) + " HKT" if parsed.tzinfo else "—"
        except ValueError, OverflowError:
            return "—"

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if self._state["busy"]:
            return None
        if not self._state["station_id"] or not self._reviewed or locale not in ("tc", "sc", "en"):
            self._error("box_validation")
            return None
        return f"/statement{extension}?locale={locale}"

    @Slot(str)
    def preview(self, locale: str) -> None:
        suffix = self._report_path(locale)
        if suffix is None:
            return
        station_id = self._state["station_id"]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            scope, lines = data.get("scope"), data.get("preview_lines")
            if not (
                isinstance(scope, dict)
                and isinstance(scope.get("station"), dict)
                and scope["station"].get("id") == station_id
                and data.get("locale") == locale
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(report=data, report_text="\n".join(lines), notice="box_report_ready")

        self._send(suffix, "GET", None, loaded)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("box_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("box_export_failed")
            return
        suffix = self._report_path(locale, "." + format)
        if suffix is None:
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
            if not save_report(data, destination, format):
                failed("box_export_failed")
                return
            self._state.update(busy=False, notice="box_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(self._path() + suffix, loaded, failed)
