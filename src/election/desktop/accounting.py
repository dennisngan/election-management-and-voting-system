"""Source-station preparation and review through authenticated HTTP."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.lifecycle import HKT, TIME_FORMAT
from election.desktop.report_files import DownloadRequest, report_destination, save_report

SUMMARY_KEYS = (
    "received_quantity",
    "ordinary_received_quantity",
    "ordinary_central_unissued_quantity",
    "ordinary_at_desks_quantity",
    "replacement_unissued_quantity",
    "tendered_unissued_quantity",
    "ordinary_issued_quantity",
    "replacement_issued_quantity",
    "spoilt_original_quantity",
    "tendered_issued_quantity",
    "retrieved_refused_quantity",
    "retrieved_found_quantity",
    "retrieved_held_quantity",
    "retrieved_unused_quantity",
    "never_issued_quantity",
    "estimated_box_from_stock_quantity",
    "estimated_box_from_turnout_quantity",
    "observed_counted_quantity",
)


def empty_forms() -> dict[str, str]:
    return {
        "special_paper_id": "",
        "special_paper_revision": "",
        "turnout_period_index": "",
        "turnout_revision": "",
        "notes": "",
        "amendment_reason": "",
    }


def summary_display(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        **summary,
        **{
            key + "_display": "—" if summary.get(key) is None else str(summary[key])
            for key in SUMMARY_KEYS
        },
    }


def turnout_display(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = quantity_display(record)
    for key in (
        "supplied_hourly",
        "supplied_cumulative",
        "derived_hourly",
        "derived_cumulative_start",
        "derived_cumulative_end",
    ):
        result[key + "_display"] = "—" if record.get(key) is None else str(record[key])
    return result


class AccountingController(QObject):
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
        self._reviewed_current: dict[str, Any] = {}
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._reviewed = False
        self._reviewed_current = {}
        self._pending = None
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "current": {},
            "selected": {},
            "summary": summary_display({}),
            "turnout_display": {},
            "stock_display": {},
            "history": [],
            "special_options": [],
            "turnout_options": [],
            "forms": empty_forms(),
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "historical": False,
            "newer_revision": False,
            "reviewed": False,
            "error": "",
            "notice": "",
            "report": {},
            "report_text": "",
            "export_path": "",
            "server_time": None,
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

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/accounting"

    def _error(self, code: str) -> None:
        self._state.update(
            error="accounting_validation" if code == "validation_error" else code, notice=""
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
        approval: bool = False,
    ) -> None:
        generation = self._generation
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if approval:
                self.erasePassword.emit()
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if approval:
                self.erasePassword.emit()
            self._error(code)

        self._request(path, method, payload, done, failed)

    def _record(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("status") in ("draft", "submitted", "approved")
            and isinstance(row.get("notes"), str)
            and isinstance(row.get("summary"), dict)
            and all(
                key in row["summary"]
                and (row["summary"][key] is None or type(row["summary"][key]) is int)
                for key in SUMMARY_KEYS
            )
            and isinstance(row.get("special_papers"), dict)
            and isinstance(row.get("stock_snapshot"), dict)
            and isinstance(row.get("turnout"), dict)
            and type(row.get("source_current")) is bool
            and type(row.get("approval_valid")) is bool
        )

    def _accept(self, row: dict[str, Any], *, historical: bool = False) -> None:
        forms = empty_forms()
        if row:
            special, turnout = row["special_papers"], row["turnout"].get("record")
            forms.update(
                special_paper_id=str(special["id"]),
                special_paper_revision=str(special["revision"]),
                notes=row["notes"],
                amendment_reason="",
            )
            if turnout:
                forms.update(
                    turnout_period_index=str(turnout["period_index"]),
                    turnout_revision=str(turnout["revision"]),
                )
        self._reviewed = True
        self._reviewed_current = deepcopy(self._state["current"])
        self._state.update(
            selected=deepcopy(row),
            summary=summary_display(row.get("summary", {})),
            turnout_display=turnout_display(row.get("turnout", {}).get("record") or {}),
            stock_display=quantity_display(row.get("stock_snapshot", {})),
            forms=forms,
            historical=historical,
            dirty=False,
            newer_revision=False,
            reviewed=True,
            report={},
            report_text="",
            export_path="",
            error="",
            notice="",
        )
        self.erasePassword.emit()

    def _loaded(self, data: dict[str, Any], *, accept: bool) -> bool:
        row, history = data.get("record"), data.get("history")
        special, turnout = data.get("special_options"), data.get("turnout_options")
        if not (
            isinstance(data.get("station"), dict)
            and data["station"].get("id") == self._state["station_id"]
            and isinstance(data.get("election"), dict)
            and isinstance(data.get("constituency"), dict)
            and (row is None or self._record(row))
            and isinstance(history, list)
            and all(self._record(item) for item in history)
            and isinstance(special, list)
            and all(
                isinstance(item, dict)
                and item.get("station_id") == self._state["station_id"]
                and type(item.get("id")) is int
                and type(item.get("revision")) is int
                and type(item.get("source_current")) is bool
                for item in special
            )
            and isinstance(turnout, list)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("record"), dict)
                and item["record"].get("station_id") == self._state["station_id"]
                and type(item["record"].get("period_index")) is int
                and type(item["record"].get("revision")) is int
                and type(item.get("approval_valid")) is bool
                for item in turnout
            )
        ):
            self._error("request_failed")
            return False
        self._state.update(
            current=deepcopy(row or {}),
            history=deepcopy(history),
            special_options=quantity_display(special),
            turnout_options=quantity_display(turnout),
            server_time=data.get("server_time"),
            context={
                **self._state["context"],
                **{key: deepcopy(data[key]) for key in ("election", "constituency", "station")},
            },
        )
        if accept:
            self._accept(row or {})
        else:
            self._state["newer_revision"] = self._state["current"] != self._reviewed_current
            if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
                self._state["error"] = ""
        return True

    @Slot(result=bool)
    def open(self) -> bool:
        self._opened = True
        if not self._state["station_id"]:
            return True
        if not self._reviewed:
            return self.reload()
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

        self._send(self._path(), "GET", None, loaded, background=True)

    def _can_load(self, discard: bool) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_accounting_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, discard: bool = False) -> bool:
        if not self._can_load(discard):
            return False

        def loaded(data: dict[str, Any]) -> None:
            self._loaded(data, accept=True)

        self._send(self._path(), "GET", None, loaded)
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        current = self._state["current"]
        if not current or type(revision) is not int or revision < 1 or not self._can_load(discard):
            return False

        def loaded(data: dict[str, Any]) -> None:
            if not self._record(data) or data["revision"] != revision:
                self._error("request_failed")
                return
            self._accept(data, historical=revision != current["revision"])

        self._send(f"{self._path()}/revisions/{revision}", "GET", None, loaded)
        return True

    def _editable(self) -> bool:
        return bool(
            self._reviewed
            and self._state["role"] == "counting_officer"
            and not self._state["busy"]
            and not self._state["historical"]
            and self._state["context"].get("election", {}).get("status") == "active"
        )

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if self._editable() and name in ("notes", "amendment_reason"):
            self._change({name: value})

    def _change(self, fields: dict[str, str]) -> None:
        if any(self._state["forms"][key] != value for key, value in fields.items()):
            self._state["forms"].update(fields)
            self._state.update(
                dirty=True, error="", notice="", report={}, report_text="", export_path=""
            )
            self.stateChanged.emit()

    @Slot("qlonglong", int, result=bool)
    def selectSpecial(self, identity: int, revision: int) -> bool:
        if not self._editable():
            return False
        if not any(
            item["id"] == identity and item["revision"] == revision
            for item in self._state["special_options"]
        ):
            self._error("accounting_validation")
            return False
        self._change({"special_paper_id": str(identity), "special_paper_revision": str(revision)})
        return True

    @Slot("qlonglong", int, result=bool)
    def selectTurnout(self, period: int, revision: int) -> bool:
        if not self._editable():
            return False
        if period == 0 and revision == 0:
            self._change({"turnout_period_index": "", "turnout_revision": ""})
            return True
        if not any(
            item["record"]["period_index"] == period and item["record"]["revision"] == revision
            for item in self._state["turnout_options"]
        ):
            self._error("accounting_validation")
            return False
        self._change({"turnout_period_index": str(period), "turnout_revision": str(revision)})
        return True

    def _content(self) -> dict[str, Any] | None:
        form = self._state["forms"]
        try:
            content: dict[str, Any] = {}
            for key in (
                "special_paper_id",
                "special_paper_revision",
                "turnout_period_index",
                "turnout_revision",
            ):
                text = form[key]
                if not text and key.startswith("turnout_"):
                    content[key] = None
                elif not text.isascii() or not text.isdecimal() or int(text) < 1:
                    raise ValueError("Choose exact source revisions")
                else:
                    content[key] = int(text)
            if len(form["notes"]) > 2000 or len(form["amendment_reason"]) > 2000:
                raise ValueError("Accounting notes are too long")
            if (
                self._state["selected"].get("status") in ("submitted", "approved")
                and not form["amendment_reason"].strip()
            ):
                raise ValueError("A correction reason is required")
            return {**content, "notes": form["notes"], "amendment_reason": form["amendment_reason"]}
        except ValueError:
            self._error("accounting_validation")
            return None

    def _command(self, action: str, password: str = "") -> None:
        approval = action == "approve"
        if approval:
            self.erasePassword.emit()
        if not self._state["station_id"] or self._state["busy"]:
            return
        role = "supervisor" if approval else "counting_officer"
        if self._state["role"] != role:
            self._error(role + "_required")
            return
        if self._state["historical"] or (
            self._state["context"].get("election", {}).get("status") != "active"
        ):
            self._error("election_read_only")
            return
        if not self._reviewed:
            self._error("request_failed")
            return
        if action != "save" and self._state["dirty"]:
            self._error("unsaved_accounting_changes")
            return
        selected = self._state["selected"]
        if (action == "submit" and selected.get("status") != "draft") or (
            approval and selected.get("status") != "submitted"
        ):
            self._error("accounting_state_conflict")
            return
        content = self._content() if action == "save" else {}
        if content is None:
            return
        payload = {"expected_revision": selected.get("revision", 0), **content}
        signature = json.dumps(
            {"station": self._state["station_id"], "action": action, "data": payload},
            sort_keys=True,
        )
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        if approval:
            payload["password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._record(data):
                self._error("request_failed")
                return

            def reviewed(snapshot: dict[str, Any]) -> None:
                if self._loaded(snapshot, accept=True):
                    self._pending = None
                    self._state["notice"] = (
                        "accounting_"
                        + {
                            "save": "saved",
                            "submit": "submitted",
                            "approve": "approved",
                        }[action]
                    )

            self._send(self._path(), "GET", None, reviewed)

        self._send(
            self._path() + ("" if action == "save" else "/" + action),
            "PUT" if action == "save" else "POST",
            payload,
            saved,
            approval=approval,
        )

    @Slot()
    def save(self) -> None:
        self._command("save")

    @Slot()
    def submit(self) -> None:
        self._command("submit")

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

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if self._state["busy"]:
            return None
        selected = self._state["selected"]
        if not selected or not self._reviewed or locale not in ("tc", "sc", "en"):
            self._error("accounting_record_not_found")
            return None
        return (
            f"{self._path()}/revisions/{selected['revision']}/statement{extension}?locale={locale}"
        )

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None:
            return
        self._generation += 1
        self._state.update(
            refreshing=False, error="", notice="", report={}, report_text="", export_path=""
        )
        station_id = self._state["station_id"]
        revision = self._state["selected"]["revision"]

        def loaded(data: dict[str, Any]) -> None:
            lines = data.get("preview_lines")
            if not (
                data.get("station_id") == station_id
                and data.get("revision") == revision
                and data.get("locale") == locale
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("request_failed")
                return
            self._state.update(
                report=data, report_text="\n".join(lines), notice="accounting_report_ready"
            )

        self._send(path, "GET", None, loaded)

    @Slot(str, str, str)
    def download(self, format: str, filepath: str, locale: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("accounting_export_failed")
            return
        destination = report_destination(filepath)
        if destination is None:
            self._error("accounting_export_failed")
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
            if not save_report(data, destination, format):
                failed("accounting_export_failed")
                return
            self._state.update(busy=False, notice="accounting_exported", export_path=destination)
            self.stateChanged.emit()

        self._download(path, loaded, failed)
