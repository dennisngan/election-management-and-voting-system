"""Reviewed queue commands stay separate from live history and server reminders."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

BANDS = ("under_30", "30_59", "60_90", "over_90")
KINDS = ("observation", "unchanged_confirmation")


def empty_forms(band: str = "under_30") -> dict[str, str]:
    return {"band": band, "event_time": "", "reason": ""}


class QueueController(QObject):
    stateChanged = Signal()

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
        self._pending = None
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "items": [],
            "current": None,
            "revision": 0,
            "latest_current": None,
            "latest_revision": 0,
            "server_time": "",
            "missing": True,
            "due_at": None,
            "reminder_due": False,
            "overdue_periods": 0,
            "forms": empty_forms(),
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

    def _error(self, code: str) -> None:
        self._state.update(
            error="queue_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/queue"

    def _send(
        self,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        suffix: str = "",
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

        self._request(self._path() + suffix, method, payload, done, failed)

    def _event(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("band") in BANDS
            and row.get("kind") in KINDS
            and isinstance(row.get("event_at"), str)
            and isinstance(row.get("entered_at"), str)
        )

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> bool:
        items, current, revision = data.get("items"), data.get("current"), data.get("revision")
        context = data.get("context")
        if not (
            isinstance(context, dict)
            and isinstance(context.get("station"), dict)
            and context["station"].get("id") == self._state["station_id"]
            and isinstance(items, list)
            and all(self._event(row) for row in items)
            and (current is None or self._event(current))
            and type(revision) is int
            and revision == max((row["revision"] for row in items), default=0)
            and type(data.get("missing")) is bool
            and data["missing"] == (current is None)
            and isinstance(data.get("server_time"), str)
            and (data.get("due_at") is None or isinstance(data["due_at"], str))
            and type(data.get("reminder_due")) is bool
            and type(data.get("overdue_periods")) is int
            and data["overdue_periods"] >= 0
        ):
            self._error("request_failed")
            return False
        self._state.update(
            context=deepcopy(context),
            items=deepcopy(items),
            latest_current=deepcopy(current),
            latest_revision=revision,
            server_time=data["server_time"],
            missing=data["missing"],
            due_at=data["due_at"],
            reminder_due=data["reminder_due"],
            overdue_periods=data["overdue_periods"],
            newer_revision=revision != self._state["revision"],
        )
        if accept:
            self._reviewed = True
            self._state.update(
                current=deepcopy(current),
                revision=revision,
                forms=empty_forms(current["band"] if current else "under_30"),
                dirty=False,
                newer_revision=False,
                report={},
                report_text="",
                export_path="",
            )
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return True

    @Slot(int, str, result=bool)
    @Slot(int, str, bool, result=bool)
    def open(self, station_id: int, role: str, discard: bool = False) -> bool:
        if station_id == 0:
            self.reset()
            self._opened = True
            self._state["role"] = role
            self.stateChanged.emit()
            return True
        if station_id < 0 or self._state["busy"]:
            return False
        self._opened = True
        if station_id == self._state["station_id"]:
            self._state["role"] = role
            if not self._reviewed:
                return self.reload(discard)
            self.refresh()
            return True
        if self._state["dirty"] and not discard:
            self._error("unsaved_queue_changes")
            return False
        self.reset()
        self._opened = True
        self._state.update(station_id=station_id, role=role)
        return self.reload(True)

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

        self._send("GET", None, loaded, background=True)

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, discard: bool = False) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_queue_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            self._loaded(data, accept=True)

        self._send("GET", None, loaded)
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._state["role"] != "polling_officer"
            or self._state["busy"]
            or self._state["context"].get("election", {}).get("status") != "active"
        ):
            return
        if name in self._state["forms"] and self._state["forms"][name] != value:
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self.stateChanged.emit()

    def _payload(self, *, confirm: bool) -> dict[str, Any] | None:
        form = self._state["forms"]
        current = self._state["current"]
        if confirm:
            if not current:
                self._error("queue_observation_conflict")
                return None
            if form["band"] != current["band"] or form["reason"].strip():
                self._error("queue_confirmation_requires_current")
                return None
        try:
            event = datetime.strptime(form["event_time"].strip(), TIME_FORMAT).replace(tzinfo=HKT)
            if form["band"] not in BANDS or len(form["reason"]) > 1000:
                raise ValueError("Invalid queue form")
        except ValueError:
            self._error("queue_validation")
            return None
        payload: dict[str, Any] = {
            "expected_revision": self._state["revision"],
            "event_at": event.isoformat(),
        }
        if confirm:
            payload["current_event_id"] = current["id"]
        else:
            payload.update(band=form["band"], reason=form["reason"])
        return payload

    def _command(self, *, confirm: bool) -> None:
        if not self._state["station_id"] or self._state["busy"]:
            return
        if self._state["role"] != "polling_officer":
            self._error("polling_officer_required")
            return
        if self._state["context"].get("election", {}).get("status") != "active":
            self._error("active_election_required")
            return
        payload = self._payload(confirm=confirm)
        if payload is None:
            return
        action = "confirm" if confirm else "observation"
        signature = json.dumps(
            {"station_id": self._state["station_id"], "action": action, "payload": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._event(data):
                self._error("request_failed")
                return

            def reviewed(snapshot: dict[str, Any]) -> None:
                if self._loaded(snapshot, accept=True):
                    self._pending = None
                    self._state["notice"] = "queue_confirmed" if confirm else "queue_saved"

            self._send("GET", None, reviewed)

        self._send("POST", payload, saved, suffix="/confirm" if confirm else "")

    @Slot()
    def save(self) -> None:
        self._command(confirm=False)

    @Slot()
    def confirmUnchanged(self) -> None:
        self._command(confirm=True)

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
            self._error("queue_validation")
            return None
        return f"/statement{extension}?revision={self._state['revision']}&locale={locale}"

    @Slot(str)
    def preview(self, locale: str) -> None:
        suffix = self._report_path(locale)
        if suffix is None:
            return
        station_id, revision = self._state["station_id"], self._state["revision"]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            lines = data.get("preview_lines")
            scope = data.get("scope")
            if not (
                isinstance(scope, dict)
                and isinstance(scope.get("station"), dict)
                and scope["station"].get("id") == station_id
                and data.get("revision") == revision
                and data.get("locale") == locale
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(
                report=data, report_text="\n".join(lines), notice="queue_report_ready"
            )

        self._send("GET", None, loaded, suffix=suffix)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("queue_export_failed")
            return
        candidate = report_destination(filepath)
        if candidate is None:
            self._error("queue_export_failed")
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
            if not save_report(data, candidate, format):
                failed("queue_export_failed")
                return
            self._state.update(busy=False, notice="queue_exported", export_path=candidate)
            self.stateChanged.emit()

        self._download(self._path() + suffix, loaded, failed)
