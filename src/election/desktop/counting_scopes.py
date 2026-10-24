"""Received-box counting scopes through the authenticated desktop API."""

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

DEFINITIVE_ERRORS = frozenset(
    {
        "validation_error",
        "scope_reason_required",
        "scope_reference_conflict",
        "box_already_in_scope",
        "scope_membership_conflict",
        "scope_incomplete",
        "scope_accounting_origin_mismatch",
        "accounting_source_stale",
        "accounting_not_found",
        "accounting_receipt_required",
        "box_not_found",
        "counting_scope_not_found",
        "scope_reference_immutable",
        "box_revision_conflict",
        "revision_conflict",
        "request_conflict",
        "scope_state_conflict",
        "event_time_in_future",
        "counting_station_required",
        "counting_officer_required",
    }
)


def empty_forms() -> dict[str, str]:
    return {"reference": "", "event_at": "", "notes": "", "amendment_reason": ""}


class CountingScopesController(QObject):
    """Editor for box-set provenance and its pinned source-accounting revisions."""

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
        self._selection_generation = 0
        self._report_generation = 0
        self._opened = False
        self._pending_request_id = ""
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(quantity_display(self._state))

    def reset(self) -> None:
        self._generation += 1
        self._selection_generation += 1
        self._report_generation += 1
        self._pending_request_id = ""
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "counting_applicable": False,
            "boxes": [],
            "source_accounting": [],
            "scopes": [],
            "history": [],
            "selected": {},
            "historical": False,
            "forms": empty_forms(),
            "selected_box_ids": [],
            "accounting_selection": {},
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "error": "",
            "error_origin": "",
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
            self.reload()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/counting-scopes"

    def _send(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        background: bool = False,
        guard: Callable[[], bool] | None = None,
    ) -> None:
        if not background:
            self._generation += 1
            self._state["refreshing"] = False
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation != self._generation or (guard is not None and not guard()):
                return
            self._state[activity] = False
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation or (guard is not None and not guard()):
                return
            self._state[activity] = False
            if code in DEFINITIVE_ERRORS:
                self._pending_request_id = ""
            self._state.update(
                error=code,
                notice="",
                error_origin="write" if method != "GET" else "read",
            )
            self.stateChanged.emit()

        self._request(path, method, payload, done, failed)

    @staticmethod
    def _valid_view(row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("status") in ("draft", "submitted")
            and isinstance(row.get("reference"), str)
            and isinstance(row.get("box_basis"), list)
            and isinstance(row.get("accounting_basis"), list)
            and isinstance(row.get("blockers"), list)
            and type(row.get("source_current")) is bool
            and type(row.get("is_current")) is bool
            and type(row.get("count_ready")) is bool
        )

    def _clear_read_error(self) -> None:
        if self._state["error_origin"] == "read":
            self._state.update(error="", error_origin="", notice="")

    def _refresh_historical_revision(
        self, scope_id: int, revision: int, selection_generation: int
    ) -> None:
        def still_selected() -> bool:
            selected = self._state["selected"]
            return bool(
                self._selection_generation == selection_generation
                and selected.get("id") == scope_id
                and selected.get("revision") == revision
                and self._state["historical"]
            )

        def loaded(row: dict[str, Any]) -> None:
            if not (
                self._valid_view(row)
                and row.get("id") == scope_id
                and row.get("revision") == revision
            ):
                self._state.update(error="invalid_response", error_origin="read", notice="")
                return
            self._state.update(
                selected=deepcopy(row),
                historical=True,
                newer_revision=False,
            )
            self._state["history"] = [
                row if item.get("revision") == revision else item for item in self._state["history"]
            ]
            self._clear_read_error()

        self._send(
            f"{self._path()}/{scope_id}/revisions/{revision}",
            "GET",
            None,
            loaded,
            background=True,
            guard=still_selected,
        )

    def _accept(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or not all(
            key in data
            for key in ("context", "counting_applicable", "boxes", "source_accounting", "scopes")
        ):
            self._state.update(error="invalid_response", error_origin="read", notice="")
            return
        if not (
            isinstance(data["context"], dict)
            and type(data["counting_applicable"]) is bool
            and isinstance(data["boxes"], list)
            and isinstance(data["source_accounting"], list)
            and isinstance(data["scopes"], list)
            and all(self._valid_view(row) for row in data["scopes"])
        ):
            self._state.update(error="invalid_response", error_origin="read", notice="")
            return

        old_scopes = self._state["scopes"]
        old_selected = deepcopy(self._state["selected"])
        selected_id = old_selected.get("id")
        selected_revision = old_selected.get("revision")
        was_dirty = self._state["dirty"]
        was_historical = self._state["historical"]
        feedback_protected = bool(
            self._state["error"] and self._state["error_origin"] not in ("", "read")
        )
        scopes = deepcopy(data["scopes"])
        latest: dict[str, Any] = next((row for row in scopes if row["id"] == selected_id), {})
        head_changed = bool(
            latest
            and old_selected
            and (
                latest.get("revision") != selected_revision
                or latest.get("status") != old_selected.get("status")
            )
        )
        catalog_changed = old_scopes != scopes
        self._state.update(
            context=deepcopy(data["context"]),
            counting_applicable=data["counting_applicable"],
            boxes=deepcopy(data["boxes"]),
            source_accounting=deepcopy(data["source_accounting"]),
            scopes=scopes,
        )
        self._clear_read_error()

        if not old_selected:
            self._state.update(selected={}, newer_revision=False)
            return
        if not latest:
            self._state.update(selected=old_selected, newer_revision=catalog_changed)
            return
        if was_historical:
            selection_generation = self._selection_generation
            self._state.update(
                selected=old_selected,
                historical=True,
                newer_revision=False,
            )
            self._refresh_historical_revision(
                old_selected["id"], old_selected["revision"], selection_generation
            )
            return

        if was_dirty or (head_changed and feedback_protected):
            selected = deepcopy(old_selected)
            if not head_changed:
                for key in ("source_current", "is_current", "count_ready", "blockers"):
                    if key in latest:
                        selected[key] = deepcopy(latest[key])
            self._state.update(
                selected=selected,
                historical=False,
                newer_revision=head_changed or catalog_changed,
            )
            return

        if head_changed:
            self._selection_generation += 1
            self._state.update(history=[])
            self._state["selected"] = deepcopy(latest)
            self._load_selected(latest)
            return

        self._state.update(
            selected=deepcopy(latest),
            historical=False,
            newer_revision=False,
        )

    @staticmethod
    def _time_form(value: Any) -> str:
        if not isinstance(value, str) or not value:
            return ""
        try:
            return datetime.fromisoformat(value).astimezone(HKT).strftime(TIME_FORMAT)
        except ValueError:
            return ""

    def _load_selected(self, row: dict[str, Any]) -> None:
        selected_box_ids = [
            box["id"] for box in row.get("box_basis", []) if type(box.get("id")) is int
        ]
        accounting_selection = {
            str(item["station_id"]): item["revision"]
            for item in row.get("accounting_basis", [])
            if type(item.get("station_id")) is int and type(item.get("revision")) is int
        }
        self._state.update(
            forms={
                "reference": row.get("reference", ""),
                "event_at": self._time_form(row.get("event_at")),
                "notes": row.get("notes", ""),
                "amendment_reason": "",
            },
            selected_box_ids=selected_box_ids,
            accounting_selection=accounting_selection,
            historical=not row.get("is_current", True),
            dirty=False,
            newer_revision=False,
            error="",
            error_origin="",
            notice="",
        )
        self._clear_report()

    def _clear_report(self) -> None:
        self._report_generation += 1
        self._state.update(report={}, report_text="", export_path="")

    def _sync_membership(self, row: dict[str, Any]) -> None:
        scope_id = row["id"]
        selected_ids = {box.get("id") for box in row.get("box_basis", [])}
        for box in self._state["boxes"]:
            if box.get("scope_id") == scope_id and box.get("id") not in selected_ids:
                box["scope_id"] = None
            if box.get("id") in selected_ids:
                box["scope_id"] = scope_id

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.reload()

    @Slot()
    def reload(self) -> None:
        if not self._state["station_id"] or self._state["busy"] or self._state["refreshing"]:
            return
        self._send(self._path(), "GET", None, self._accept, background=bool(self._state["scopes"]))

    @Slot()
    def refresh(self) -> None:
        self.reload()

    @Slot()
    def discardAndReload(self) -> None:
        if self._state["busy"]:
            return
        self._selection_generation += 1
        selected_id = self._state["selected"].get("id")
        latest: dict[str, Any] = next(
            (row for row in self._state["scopes"] if row.get("id") == selected_id), {}
        )
        self._state.update(
            dirty=False,
            newer_revision=False,
            error="",
            error_origin="",
            notice="",
            history=[],
            report={},
            report_text="",
            export_path="",
        )
        if latest:
            self._state["selected"] = deepcopy(latest)
            self._load_selected(latest)
        else:
            self._state.update(
                selected={}, forms=empty_forms(), selected_box_ids=[], accounting_selection={}
            )
        self.stateChanged.emit()
        if self._state["station_id"]:
            self._send(self._path(), "GET", None, self._accept)

    @Slot(int)
    def selectScope(self, scope_id: int) -> None:
        if self._state["busy"]:
            return
        row = next((item for item in self._state["scopes"] if item.get("id") == scope_id), None)
        if not row or (self._state["dirty"] and not self._state["historical"]):
            self._state.update(error="unsaved_changes", error_origin="local", notice="")
            self.stateChanged.emit()
            return
        self._selection_generation += 1
        selection_generation = self._selection_generation
        self._state.update(selected=deepcopy(row), error="", error_origin="", notice="")
        self._load_selected(row)

        def loaded(data: dict[str, Any]) -> None:
            if self._selection_generation != selection_generation:
                return
            record, history = data.get("record"), data.get("history")
            if (
                self._valid_view(record)
                and isinstance(history, list)
                and all(self._valid_view(item) for item in history)
            ):
                latest = next((item for item in history if item.get("is_current")), record)
                self._state.update(selected=deepcopy(latest), history=deepcopy(history))
                self._load_selected(self._state["selected"])
            else:
                self._state.update(error="invalid_response", error_origin="read", notice="")

        self._send(
            f"{self._path()}/{scope_id}",
            "GET",
            None,
            loaded,
            guard=lambda: self._selection_generation == selection_generation,
        )

    @Slot(int)
    def loadRevision(self, revision: int) -> None:
        if self._state["busy"]:
            return
        scope = self._state["selected"]
        if not self._valid_view(scope) or type(revision) is not int or revision < 1:
            return
        if self._state["dirty"] or self._state["newer_revision"]:
            self._state.update(
                error="revision_conflict" if self._state["newer_revision"] else "unsaved_changes",
                error_origin="local",
                notice="",
            )
            self.stateChanged.emit()
            return
        self._selection_generation += 1
        selection_generation = self._selection_generation

        def loaded(row: dict[str, Any]) -> None:
            if self._selection_generation != selection_generation:
                return
            if (
                self._valid_view(row)
                and row.get("id") == scope["id"]
                and row.get("revision") == revision
            ):
                self._state.update(
                    selected=deepcopy(row), historical=not row.get("is_current", False), error=""
                )
                self._load_selected(row)
            else:
                self._state.update(error="invalid_response", error_origin="read", notice="")

        self._send(
            f"{self._path()}/{scope['id']}/revisions/{revision}",
            "GET",
            None,
            loaded,
            guard=lambda: self._selection_generation == selection_generation,
        )

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        row = self._state["selected"]
        if self._state["busy"] or not self._valid_view(row) or locale not in ("tc", "sc", "en"):
            self._state.update(error="counting_scope_not_found", error_origin="local", notice="")
            self.stateChanged.emit()
            return None
        if self._state["dirty"] or self._state["newer_revision"]:
            self._state.update(
                error="revision_conflict" if self._state["newer_revision"] else "unsaved_changes",
                error_origin="local",
                notice="",
            )
            self.stateChanged.emit()
            return None
        return (
            f"{self._path()}/{row['id']}/revisions/{row['revision']}/statement"
            f"{extension}?locale={locale}"
        )

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None:
            return
        row = self._state["selected"]
        scope_id, revision, station_id = row["id"], row["revision"], self._state["station_id"]
        self._clear_report()
        report_generation = self._report_generation
        self._generation += 1
        self._state.update(error="", error_origin="", notice="")

        def loaded(data: dict[str, Any]) -> None:
            if report_generation != self._report_generation:
                return
            lines = data.get("preview_lines")
            if not (
                data.get("station_id") == station_id
                and data.get("scope_id") == scope_id
                and data.get("revision") == revision
                and data.get("locale") == locale
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._state.update(error="request_failed", error_origin="read", notice="")
                return
            self._state.update(
                report=data,
                report_text="\n".join(lines),
                notice="counting_scope_report_ready",
                error="",
            )

        self._send(path, "GET", None, loaded)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._state.update(
                error="counting_scope_export_failed", error_origin="local", notice=""
            )
            self.stateChanged.emit()
            return
        destination = report_destination(filepath)
        path = self._report_path(locale, "." + format)
        if path is None:
            return
        if destination is None:
            self._state.update(
                error="counting_scope_export_failed", error_origin="local", notice=""
            )
            self.stateChanged.emit()
            return
        self._generation += 1
        generation = self._generation
        report_generation = self._report_generation
        self._state.update(refreshing=False, busy=True, error="", notice="", export_path="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation and report_generation == self._report_generation:
                self._state.update(busy=False, error=code, error_origin="write", notice="")
                self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation or report_generation != self._report_generation:
                return
            if not save_report(data, destination, format):
                failed("counting_scope_export_failed")
                return
            self._state.update(
                busy=False, notice="counting_scope_exported", export_path=destination
            )
            self.stateChanged.emit()

        self._download(path, loaded, failed)

    @Slot()
    def newScope(self) -> None:
        if self._state["dirty"] or self._state["busy"]:
            self._state.update(error="unsaved_changes", error_origin="local", notice="")
        else:
            if self._state["refreshing"]:
                self._generation += 1
                self._state["refreshing"] = False
            self._selection_generation += 1
            self._state.update(
                selected={},
                historical=False,
                forms=empty_forms(),
                selected_box_ids=[],
                accounting_selection={},
                dirty=False,
                newer_revision=False,
                error="",
                notice="",
            )
            self._clear_report()
        self.stateChanged.emit()

    @Slot(int, bool)
    def setBoxSelected(self, box_id: int, checked: bool) -> None:
        rows = self._state["selected_box_ids"]
        if not any(box.get("id") == box_id for box in self._state["boxes"]):
            return
        selected = list(rows)
        if checked and box_id not in selected:
            selected.append(box_id)
        if not checked and box_id in selected:
            selected.remove(box_id)
        self._state.update(
            selected_box_ids=selected, dirty=True, error="", error_origin="", notice=""
        )
        self.stateChanged.emit()

    @Slot(int, int)
    def chooseAccounting(self, station_id: int, revision: int) -> None:
        selection = dict(self._state["accounting_selection"])
        if revision > 0:
            selection[str(station_id)] = revision
        else:
            selection.pop(str(station_id), None)
        self._state.update(
            accounting_selection=selection, dirty=True, error="", error_origin="", notice=""
        )
        self.stateChanged.emit()

    @Slot(str, str)
    def setForm(self, name: str, value: str) -> None:
        if name not in empty_forms():
            return
        forms = dict(self._state["forms"])
        forms[name] = value
        self._state.update(forms=forms, dirty=True, error="", error_origin="", notice="")
        self.stateChanged.emit()

    def _payload(self) -> dict[str, Any] | None:
        forms = self._state["forms"]
        try:
            event = datetime.strptime(forms["event_at"].strip(), TIME_FORMAT).replace(tzinfo=HKT)
        except ValueError:
            self._state.update(error="counting_scope_validation", error_origin="local", notice="")
            self.stateChanged.emit()
            return None
        reference = forms["reference"].strip()
        if not reference or len(reference) > 80:
            self._state.update(error="counting_scope_validation", error_origin="local", notice="")
            self.stateChanged.emit()
            return None
        selected = self._state["selected"]
        basis = {box.get("id"): box for box in self._state["boxes"]}
        box_revisions = [
            {"box_id": box_id, "revision": basis[box_id]["revision"]}
            for box_id in self._state["selected_box_ids"]
            if box_id in basis and type(basis[box_id].get("revision")) is int
        ]
        source_by_id = {
            str(source.get("station", {}).get("id")): source
            for source in self._state["source_accounting"]
        }
        accounting_revisions = []
        for station_id, revision in self._state["accounting_selection"].items():
            source = source_by_id.get(station_id, {})
            record = source.get("record") or {}
            if type(revision) is int and record.get("revision") == revision:
                accounting_revisions.append({"station_id": int(station_id), "revision": revision})
        payload: dict[str, Any] = {
            "request_id": self._pending_request_id or str(uuid4()),
            "expected_revision": selected.get("revision", 0),
            "reference": selected.get("reference", reference),
            "event_at": event.isoformat(),
            "box_revisions": box_revisions,
            "accounting_revisions": accounting_revisions,
            "notes": forms["notes"].strip(),
            "amendment_reason": forms["amendment_reason"].strip(),
        }
        return payload

    @Slot()
    def save(self) -> None:
        if self._state["busy"] or self._state["historical"] or self._state["newer_revision"]:
            self._state.update(
                error="revision_conflict" if self._state["newer_revision"] else "",
                error_origin="local",
                notice="",
            )
            self.stateChanged.emit()
            return
        payload = self._payload()
        if payload is None:
            return
        self._pending_request_id = payload["request_id"]
        selected = self._state["selected"]
        path = f"{self._path()}/{selected['id']}" if selected else self._path()
        method = "PUT" if selected else "POST"

        def saved(row: dict[str, Any]) -> None:
            if self._valid_view(row):
                self._pending_request_id = ""
                self._sync_membership(row)
                scopes = [item for item in self._state["scopes"] if item.get("id") != row["id"]]
                scopes.insert(0, row)
                self._state.update(
                    scopes=scopes,
                    selected=deepcopy(row),
                    history=[],
                    error="",
                    error_origin="",
                    notice="counting_scope_saved",
                )
                self._load_selected(row)
            else:
                self._state.update(error="invalid_response", error_origin="write", notice="")

        self._send(path, method, payload, saved)

    @Slot()
    def submit(self) -> None:
        row = self._state["selected"]
        if (
            not self._valid_view(row)
            or row.get("status") != "draft"
            or not row.get("is_current")
            or not row.get("source_current")
            or row.get("blockers")
        ):
            self._state.update(error="counting_scope_not_ready", error_origin="local", notice="")
            self.stateChanged.emit()
            return
        if self._state["dirty"] or self._state["historical"] or self._state["newer_revision"]:
            self._state.update(
                error="revision_conflict" if self._state["newer_revision"] else "unsaved_changes",
                error_origin="local",
                notice="",
            )
            self.stateChanged.emit()
            return
        request_id = self._pending_request_id or str(uuid4())
        self._pending_request_id = request_id
        path = f"{self._path()}/{row['id']}/submit"

        def submitted(data: dict[str, Any]) -> None:
            result = data.get("scope", data) if isinstance(data, dict) else {}
            if self._valid_view(result):
                self._pending_request_id = ""
                scopes = [item for item in self._state["scopes"] if item.get("id") != result["id"]]
                scopes.insert(0, result)
                self._state.update(
                    scopes=scopes,
                    selected=deepcopy(result),
                    history=[],
                    notice="counting_scope_submitted",
                    error="",
                    error_origin="",
                )
                self._load_selected(result)
            else:
                self._state.update(error="invalid_response", error_origin="write", notice="")

        self._send(
            path,
            "POST",
            {"request_id": request_id, "expected_revision": row["revision"]},
            submitted,
        )
