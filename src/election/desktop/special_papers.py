"""Saved special-paper observations keep explicit counts and frozen source revisions."""

import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.event_times import format_event_time, parse_event_time
from election.desktop.lifecycle import HKT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

INPUTS = (
    "replacement_issued_quantity",
    "spoilt_original_quantity",
    "tendered_issued_quantity",
    "retrieved_refused_quantity",
    "retrieved_found_quantity",
    "retrieved_held_quantity",
)
QUANTITIES = (
    "received_quantity",
    "ordinary_issued_quantity",
    *INPUTS,
    "retrieved_unused_quantity",
    "ordinary_unissued_quantity",
    "replacement_unissued_quantity",
    "tendered_unissued_quantity",
    "never_issued_quantity",
    "estimated_box_papers_quantity",
)


def _qt_value(value: Any) -> Any:
    if type(value) is int and not -(2**63) <= value < 2**63:
        return str(value)
    if isinstance(value, dict):
        return {key: _qt_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_qt_value(item) for item in value]
    return deepcopy(value)


def _totals(value: dict[str, Any]) -> dict[str, str]:
    return {
        key.removesuffix("_quantity") + "_display": str(value[key]) if key in value else "—"
        for key in QUANTITIES
    }


class SpecialPapersController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject,
        *,
        download: DownloadRequest | None = None,
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
        result: dict[str, Any] = _qt_value(self._state)
        return result

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
            "latest": None,
            "latest_basis_current": None,
            "selected": {},
            "history": [],
            "history_verified": False,
            "historical": False,
            "newer_revision": False,
            "editing": False,
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "forms": {"event_time": "", "reason": ""},
            "basis": {},
            "basis_options": [],
            "receipts": [],
            "source_changed": False,
            "series_reports": [],
            "totals": _totals({}),
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
            self.refresh()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/special-papers"

    def _writable(self) -> bool:
        return bool(
            self._state["station_id"]
            and self._state["role"] == "polling_officer"
            and self._state["context"].get("election", {}).get("status") in ("draft", "active")
            and not self._state["busy"]
            and not self._state["historical"]
            and (not self._state["selected"] or self._state["history_verified"])
        )

    def _editable(self) -> bool:
        return self._writable() and bool(not self._state["selected"] or self._state["editing"])

    def _error(self, code: str) -> None:
        self._state.update(
            error="special_paper_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _send(
        self,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        suffix: str = "",
        background: bool = False,
        path: str = "",
    ) -> None:
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation == self._generation:
                self._state[activity] = False
                success(data)
                self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._error(code)

        self._request(path or self._path() + suffix, method, payload, done, failed)

    def _scope(self, value: Any) -> bool:
        return bool(
            isinstance(value, dict)
            and all(
                isinstance(value.get(key), dict)
                and type(value[key].get("id")) is int
                and value[key]["id"] == self._state["context"].get(key, {}).get("id")
                for key in ("election", "constituency", "station")
            )
        )

    def _snapshot(self, value: Any) -> bool:
        try:
            if not (
                isinstance(value, dict)
                and self._scope(value["scope"])
                and all(
                    type(value[key]) is int and value[key] > 0
                    for key in (
                        "id",
                        "revision",
                        "actor_id",
                        "stock_snapshot_id",
                        "stock_snapshot_revision",
                    )
                )
                and value["station_id"] == self._state["station_id"]
                and value["status"] == "recorded"
                and isinstance(value["reason"], str)
                and isinstance(value["series"], list)
                and all(type(value[key]) is int and value[key] >= 0 for key in QUANTITIES)
            ):
                return False
            for key in ("event_at", "entered_at", "stock_snapshot_event_at"):
                if datetime.fromisoformat(value[key]).utcoffset() is None:
                    return False
            series = value["series"]
            if not all(
                isinstance(row, dict)
                and isinstance(row.get("series"), str)
                and row["series"].strip()
                and len(row["series"]) <= 64
                and all(type(row[key]) is int and row[key] >= 0 for key in QUANTITIES)
                for row in series
            ):
                return False
            if len({row["series"] for row in series}) != len(series):
                return False
            if any(sum(row[key] for row in series) != value[key] for key in QUANTITIES):
                return False
            return bool(
                isinstance(value["stock_snapshot_data"], dict)
                and isinstance(value["receipt_basis"], list)
                and isinstance(value["received_ranges"], list)
            )
        except KeyError, TypeError, ValueError, OverflowError:
            return False

    def _loaded(self, data: dict[str, Any]) -> None:
        items, latest, current = (
            data.get("items"),
            data.get("latest"),
            data.get("latest_basis_current"),
        )
        if not (
            self._scope(data.get("scope"))
            and isinstance(items, list)
            and all(self._snapshot(row) for row in items)
            and (
                latest == items[-1] and type(current) is bool
                if items
                else latest is None and current is None
            )
        ):
            self._error("request_failed")
            return
        self._state.update(
            scope=deepcopy(data["scope"]),
            items=deepcopy(items),
            latest=deepcopy(latest),
            latest_basis_current=current,
        )
        self._state["context"] = {**self._state["context"], **data["scope"]}
        selected = self._state["selected"]
        if selected:
            head = next((row for row in items if row["id"] == selected["id"]), None)
            if head is None or head != selected:
                self._state["newer_revision"] = True
                if head and head["revision"] > selected["revision"]:
                    self._state.update(historical=True, editing=False)
            if head is None or head not in self._state["history"]:
                self._state["history_verified"] = False
        self._send(
            "GET",
            None,
            self._receipts_loaded,
            background=True,
            path=self._path().removesuffix("special-papers") + "stock",
        )

    def _receipts_loaded(self, data: dict[str, Any]) -> None:
        rows = data.get("items")
        try:
            valid = (
                self._scope(data.get("scope"))
                and isinstance(rows, list)
                and all(
                    isinstance(row, dict)
                    and row["station_id"] == self._state["station_id"]
                    and isinstance(row["series"], str)
                    and row["series"].strip()
                    and datetime.fromisoformat(row["event_at"]).utcoffset() is not None
                    for row in rows
                )
            )
        except KeyError, TypeError, ValueError:
            valid = False
        if not valid:
            self._error("request_failed")
            return
        if not self._state["selected"] and self._state["dirty"]:
            if rows != self._state["receipts"]:
                self._state["source_changed"] = True
        self._state["receipts"] = deepcopy(rows)
        if not self._state["selected"] and not self._state["dirty"]:
            self._series_for_time()
        self._send(
            "GET",
            None,
            self._basis_loaded,
            background=True,
            path=self._path().removesuffix("special-papers") + "stock-snapshots",
        )

    def _basis_loaded(self, data: dict[str, Any]) -> None:
        rows = data.get("items")
        if not (
            self._scope(data.get("scope"))
            and isinstance(rows, list)
            and all(
                isinstance(row, dict)
                and type(row.get("id")) is int
                and row.get("station_id") == self._state["station_id"]
                and type(row.get("revision")) is int
                and type(row.get("complete")) is bool
                for row in rows
            )
        ):
            self._error("request_failed")
            return
        self._state["basis_options"] = deepcopy([row for row in rows if row["complete"]])

    def _series_for_time(self) -> None:
        try:
            event = datetime.fromisoformat(parse_event_time(self._state["forms"]["event_time"]))
        except ValueError:
            return
        names = sorted(
            {
                row["series"]
                for row in self._state["receipts"]
                if datetime.fromisoformat(row["event_at"]) <= event
            }
        )
        previous = {row["series"]: row for row in self._state["series_reports"]}
        self._state["series_reports"] = [
            previous.get(name, {"series": name, **dict.fromkeys(INPUTS, "")}) for name in names
        ]

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if (
            self._opened
            and self._state["station_id"]
            and not (self._state["busy"] or self._state["refreshing"])
        ):
            self._send("GET", None, self._loaded, background=True)

    def _begin_selection(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_special_paper_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(
            refreshing=False,
            history_verified=False,
            editing=False,
            error="",
            notice="",
            report={},
            report_text="",
            export_path="",
        )
        return True

    def _accept(self, value: dict[str, Any]) -> None:
        known = [row for row in self._state["items"] if row["id"] == value["id"]]
        if self._state["selected"].get("id") == value["id"]:
            known += self._state["history"] + [self._state["selected"]]
        historical = any(row["revision"] > value["revision"] for row in known)
        basis = next(
            (
                row
                for row in self._state["basis_options"]
                if row["id"] == value["stock_snapshot_id"]
                and row["revision"] == value["stock_snapshot_revision"]
            ),
            None,
        )
        self._state.update(
            selected=deepcopy(value),
            historical=historical,
            newer_revision=historical,
            forms={
                "event_time": datetime.fromisoformat(value["event_at"])
                .astimezone(HKT)
                .strftime("%Y-%m-%d %H:%M"),
                "reason": "",
            },
            series_reports=[
                {"series": row["series"], **{key: str(row[key]) for key in INPUTS}}
                for row in value["series"]
            ],
            basis=deepcopy(basis)
            if basis
            else {
                **deepcopy(value["stock_snapshot_data"]),
                "id": value["stock_snapshot_id"],
                "revision": value["stock_snapshot_revision"],
                "event_at": value["stock_snapshot_event_at"],
            },
            totals=_totals(value),
            source_changed=False,
            dirty=False,
            editing=False,
            history_verified=False,
            report={},
            report_text="",
            export_path="",
        )

    def _history(self, *, refresh_after: bool = False) -> None:
        selected = deepcopy(self._state["selected"])
        snapshot_id = selected["id"]

        def loaded(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not (
                isinstance(rows, list)
                and rows
                and all(
                    self._snapshot(row) and row["id"] == snapshot_id and row["revision"] == index
                    for index, row in enumerate(rows, 1)
                )
                and selected["revision"] <= len(rows)
                and rows[selected["revision"] - 1] == selected
            ):
                self._error("request_failed")
                return
            self._state.update(
                history=deepcopy(rows),
                history_verified=True,
                historical=selected["revision"] < rows[-1]["revision"],
                newer_revision=selected != rows[-1],
            )
            items = {row["id"]: row for row in self._state["items"]}
            items[snapshot_id] = deepcopy(rows[-1])
            self._state["items"] = sorted(
                items.values(), key=lambda row: (datetime.fromisoformat(row["event_at"]), row["id"])
            )
            if self._state["historical"]:
                self._state["editing"] = False
            if refresh_after:
                self.refresh()

        self._send("GET", None, loaded, suffix=f"/{snapshot_id}/history")

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadSnapshot(self, snapshot_id: int, discard: bool = False) -> bool:
        if snapshot_id < 1 or not self._begin_selection(discard):
            return False

        def loaded(data: dict[str, Any]) -> None:
            if not self._snapshot(data) or data["id"] != snapshot_id:
                self._error("request_failed")
                return
            self._accept(data)
            self._history()

        self._send("GET", None, loaded, suffix=f"/{snapshot_id}")
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        selected = self._state["selected"]
        if not selected or revision < 1 or not self._begin_selection(discard):
            return False
        snapshot_id = selected["id"]

        def loaded(data: dict[str, Any]) -> None:
            if (
                not self._snapshot(data)
                or data["id"] != snapshot_id
                or data["revision"] != revision
            ):
                self._error("request_failed")
                return
            self._accept(data)
            self._history()

        self._send("GET", None, loaded, suffix=f"/{snapshot_id}?revision={revision}")
        return True

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def newSnapshot(self, discard: bool = False) -> bool:
        if not self._begin_selection(discard):
            return False
        self._state.update(
            selected={},
            forms={"event_time": "", "reason": ""},
            basis={},
            series_reports=[],
            totals=_totals({}),
            source_changed=False,
            history=[],
            dirty=False,
            historical=False,
            newer_revision=False,
        )
        self.stateChanged.emit()
        self.refresh()
        return True

    @Slot(result=bool)
    def editSelected(self) -> bool:
        if not self._state["selected"] or not self._writable():
            self._error("election_read_only")
            return False
        self._state.update(editing=True, error="", notice="")
        self.stateChanged.emit()
        return True

    def _changed(self) -> None:
        self._state.update(dirty=True, error="", notice="")
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            self._editable()
            and name in self._state["forms"]
            and self._state["forms"][name] != value
        ):
            self._state["forms"][name] = value
            if name == "event_time":
                self._series_for_time()
            self._changed()

    @Slot(int)
    def selectBasis(self, snapshot_id: int) -> None:
        if not self._editable():
            return
        basis = next(
            (row for row in self._state["basis_options"] if row["id"] == snapshot_id), None
        )
        if basis is not None and basis != self._state["basis"]:
            self._state["basis"] = deepcopy(basis)
            self._changed()

    @Slot(str, str, str)
    def setSeriesField(self, series: str, name: str, value: str) -> None:
        if not self._editable() or name not in INPUTS:
            return
        row = next((row for row in self._state["series_reports"] if row["series"] == series), None)
        if row is not None and row[name] != value:
            row[name] = value
            self._changed()

    @Slot()
    def zeroAll(self) -> None:
        if self._editable():
            for row in self._state["series_reports"]:
                row.update(dict.fromkeys(INPUTS, "0"))
            self._changed()

    def _payload(self) -> dict[str, Any] | None:
        try:
            selected, basis = self._state["selected"], self._state["basis"]
            event = parse_event_time(self._state["forms"]["event_time"], selected.get("event_at"))
            if not basis or basis.get("complete") is not True:
                raise ValueError("Select a complete saved revision")
            rows = []
            for row in self._state["series_reports"]:
                if not all(
                    re.fullmatch(r"[0-9]{1,19}", row[key]) and int(row[key]) <= 2**63 - 1
                    for key in INPUTS
                ):
                    raise ValueError("Report every count explicitly using ASCII digits")
                rows.append({"series": row["series"], **{key: int(row[key]) for key in INPUTS}})
            payload = {
                "event_at": event,
                "stock_snapshot_id": basis["id"],
                "stock_snapshot_revision": basis["revision"],
                "series": rows,
            }
            if selected:
                reason = self._state["forms"]["reason"]
                if not reason.strip() or len(reason) > 1000:
                    raise ValueError("A correction reason is required")
                payload.update(revision=selected["revision"], reason=reason)
            return payload
        except ValueError:
            self._error("special_paper_validation")
            return None

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
        snapshot_id = self._state["selected"].get("id", 0)
        signature = json.dumps(
            {"station": self._state["station_id"], "id": snapshot_id, "data": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not (
                self._snapshot(data)
                and data["revision"] == payload.get("revision", 0) + 1
                and (not snapshot_id or data["id"] == snapshot_id)
                and data["stock_snapshot_id"] == payload["stock_snapshot_id"]
                and data["stock_snapshot_revision"] == payload["stock_snapshot_revision"]
                and datetime.fromisoformat(data["event_at"])
                == datetime.fromisoformat(payload["event_at"])
                and data["reason"] == payload.get("reason", "")
                and [
                    {"series": row["series"], **{key: row[key] for key in INPUTS}}
                    for row in data["series"]
                ]
                == payload["series"]
            ):
                self._error("request_failed")
                return
            self._accept(data)
            self._pending = None
            self._state["notice"] = "special_paper_saved"
            self._history(refresh_after=True)

        self._send(
            "PUT" if snapshot_id else "POST",
            payload,
            saved,
            suffix=f"/{snapshot_id}" if snapshot_id else "",
        )

    def _clear_report(self) -> None:
        self._state.update(report={}, report_text="", export_path="")

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if self._state["busy"]:
            return None
        selected = self._state["selected"]
        if locale not in ("tc", "sc", "en") or not self._state["station_id"] or not selected:
            self._error("special_paper_validation")
            return None
        return (
            f"/statement{extension}?locale={locale}"
            f"&snapshot_id={selected['id']}&revision={selected['revision']}"
        )

    def _valid_report(self, data: dict[str, Any], selected: dict[str, Any], locale: str) -> bool:
        scope, lines = data.get("scope"), data.get("preview_lines")
        try:
            generated = datetime.fromisoformat(data["generated_at"])
            return bool(
                isinstance(scope, dict)
                and all(
                    isinstance(scope.get(key), dict)
                    and type(scope[key].get("id")) is int
                    and scope[key]["id"] == self._state["context"].get(key, {}).get("id")
                    for key in ("election", "constituency")
                )
                and isinstance(scope.get("station"), dict)
                and type(scope["station"].get("id")) is int
                and scope["station"]["id"] == selected["station_id"]
                and data.get("locale") == locale
                and data.get("report_scope") == "snapshot_revision"
                and type(data.get("snapshot_id")) is int
                and data["snapshot_id"] == selected["id"]
                and type(data.get("revision")) is int
                and data["revision"] == selected["revision"]
                and data.get("revision_state") in ("current", "historical")
                and data.get("items") == [selected]
                and "availability" in data
                and data["availability"] is None
                and data.get("generation_timezone") == "Asia/Hong_Kong"
                and generated.utcoffset() is not None
                and isinstance(data.get("title"), str)
                and data["title"].strip()
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
                and lines[0] == data["title"]
            )
        except KeyError, TypeError, ValueError, OverflowError:
            return False

    @Slot(str)
    def preview(self, locale: str) -> None:
        suffix = self._report_path(locale)
        if suffix is None:
            return
        selected = deepcopy(self._state["selected"])
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="", export_path="")

        def loaded(data: dict[str, Any]) -> None:
            if not self._valid_report(data, selected, locale):
                self._error("request_failed")
                return
            self._state.update(
                report=deepcopy(data),
                report_text="\n".join(data["preview_lines"]),
                notice="stock_report_ready",
            )

        self._send("GET", None, loaded, suffix=suffix)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("stock_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("stock_export_failed")
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
                failed("stock_export_failed")
                return
            self._state.update(busy=False, notice="stock_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(self._path() + suffix, loaded, failed)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)
