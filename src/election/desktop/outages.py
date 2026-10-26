"""Editable, revision-bound application outage and paper reconciliation state."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any, TypeGuard
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler, positive_integer
from election.desktop.event_times import format_event_time, parse_event_time
from election.desktop.exact_numbers import qt_state

OUTAGE_KINDS = ("network", "backend", "database", "unknown")
PAPER_WORKFLOWS = ("count", "turnout", "allocation")
OPERATIONAL_ROLES = ("polling_officer", "counting_officer")
READ_ROLES = ("polling_officer", "counting_officer", "supervisor")
UNCERTAIN_ERRORS = {
    "certificate_error",
    "database_unavailable",
    "disconnected",
    "invalid_response",
    "request_failed",
    "request_timeout",
}
OUTAGE_CONFLICTS = {
    "outage_revision_conflict",
    "outage_reconciliation_revision_conflict",
    "outage_paper_revision_conflict",
    "outage_paper_records_missing",
    "outage_papers_pending",
    "paper_reference_conflict",
    "paper_revision_conflict",
    "paper_already_entered",
    "paper_target_conflict",
    "paper_target_not_found",
}


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _aware(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except (TypeError, ValueError, OverflowError):
        return False


def _event_form(value: str, original: str | None = None) -> str:
    return format_event_time(original or value).removesuffix(" HKT") if original else (
        format_event_time(value).removesuffix(" HKT") if value else ""
    )


def _empty_outage_form() -> dict[str, str]:
    return {
        "reference": "",
        "kind": "network",
        "started_at": "",
        "ended_at": "",
        "notes": "",
        "amendment_reason": "",
    }


def _empty_paper_form() -> dict[str, str]:
    return {
        "paper_reference": "",
        "workflow": "count",
        "action": "submit",
        "original_event_at": "",
        "target_scope_id": "",
        "target_round_id": "",
        "target_period_index": "",
        "target_counter_id": "",
        "target_allocation_id": "",
        "notes": "",
        "amendment_reason": "",
    }


def _paper_record(row: Any, station_id: int) -> TypeGuard[dict[str, Any]]:
    if not (
        isinstance(row, dict)
        and _positive(row.get("id"))
        and row.get("station_id") == station_id
        and _positive(row.get("outage_id"))
        and _positive(row.get("revision"))
        and isinstance(row.get("paper_reference"), str)
        and row.get("workflow") in PAPER_WORKFLOWS
        and isinstance(row.get("action"), str)
        and _aware(row.get("original_event_at"))
        and isinstance(row.get("target"), dict)
        and row.get("status") in ("pending", "entered")
        and isinstance(row.get("notes"), str)
        and isinstance(row.get("amendment_reason"), str)
        and isinstance(row.get("history"), list)
    ):
        return False
    if row["status"] == "entered":
        reentry = row.get("reentry")
        if not (
            isinstance(reentry, dict)
            and reentry.get("workflow") == row["workflow"]
            and isinstance(reentry.get("request_id"), str)
            and isinstance(reentry.get("record"), dict)
            and _positive(reentry.get("actor_id"))
            and _aware(reentry.get("entered_at"))
        ):
            return False
        try:
            UUID(reentry["request_id"])
        except (ValueError, TypeError, AttributeError):
            return False
    elif row.get("reentry") is not None:
        return False
    return all(
        isinstance(item, dict)
        and _positive(item.get("revision"))
        and _positive(item.get("actor_id"))
        and _aware(item.get("entered_at"))
        for item in row["history"]
    )


def _outage_record(row: Any, station_id: int) -> TypeGuard[dict[str, Any]]:
    return bool(
        isinstance(row, dict)
        and _positive(row.get("id"))
        and row.get("station_id") == station_id
        and _positive(row.get("revision"))
        and isinstance(row.get("reference"), str)
        and row.get("kind") in OUTAGE_KINDS
        and _aware(row.get("started_at"))
        and _aware(row.get("ended_at"))
        and _positive(row.get("actor_id"))
        and _aware(row.get("entered_at"))
        and isinstance(row.get("notes"), str)
        and isinstance(row.get("amendment_reason"), str)
        and isinstance(row.get("paper_records"), list)
        and all(_paper_record(paper, station_id) for paper in row["paper_records"])
        and type(row.get("reconciled")) is bool
        and (
            row.get("reconciliation") is None
            or (
                isinstance(row.get("reconciliation"), dict)
                and _positive(row["reconciliation"].get("revision"))
                and _positive(row["reconciliation"].get("actor_id"))
                and type(row["reconciliation"].get("valid")) is bool
                and type(row["reconciliation"].get("is_current")) is bool
            )
        )
        and isinstance(row.get("reconciliation_history"), list)
    )


def _form_from_outage(row: dict[str, Any]) -> dict[str, str]:
    return {
        "reference": row["reference"],
        "kind": row["kind"],
        "started_at": _event_form(row["started_at"]),
        "ended_at": _event_form(row["ended_at"]),
        "notes": row["notes"],
        "amendment_reason": "",
    }


def _form_from_paper(row: dict[str, Any]) -> dict[str, str]:
    target = row.get("target", {})
    return {
        "paper_reference": row["paper_reference"],
        "workflow": row["workflow"],
        "action": row["action"],
        "original_event_at": _event_form(row["original_event_at"]),
        "target_scope_id": str(target.get("scope_id", "")),
        "target_round_id": str(target.get("round_id", "")),
        "target_period_index": str(target.get("period_index", "")),
        "target_counter_id": str(target.get("counter_id", "")),
        "target_allocation_id": str(target.get("allocation_id", "")),
        "notes": row["notes"],
        "amendment_reason": "",
    }


class OutagesController(QObject):
    """Public desktop controller for outage records and delayed paper references."""

    stateChanged = Signal()
    erasePassword = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._opened = False
        self._pending: dict[str, Any] | None = None
        self._outage_form_base = _empty_outage_form()
        self._paper_form_base = _empty_paper_form()
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._pending = None
        self._outage_form_base = _empty_outage_form()
        self._paper_form_base = _empty_paper_form()
        self._state = {
            "station_id": 0,
            "role": "",
            "writable": False,
            "items": [],
            "selected": {},
            "history": [],
            "forms": _empty_outage_form(),
            "paper_forms": _empty_paper_form(),
            "selected_paper_id": 0,
            "paper_editable": False,
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "uncertain_save": False,
            "pending_request_id": "",
            "newer_revision": False,
            "error": "",
            "notice": "",
        }
        self.erasePassword.emit()
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        station_id = context.get("station", {}).get("id", 0)
        role = context.get("account", {}).get("role", "")
        changed = (station_id, role) != (self._state["station_id"], self._state["role"])
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._state.update(
            station_id=station_id if _positive(station_id) else 0,
            role=role if role in READ_ROLES else "",
            writable=context.get("election", {}).get("status") == "active",
        )
        self.stateChanged.emit()
        if changed and self._opened and self._state["station_id"]:
            self.reload()

    def _error(self, code: str, *, newer: bool = False) -> None:
        self._state.update(error=code, notice="")
        if newer:
            self._state["newer_revision"] = True
        self.stateChanged.emit()

    def _path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/outages"

    def _context_ready(self) -> bool:
        return _positive(self._state["station_id"]) and self._state["role"] in READ_ROLES

    def _dirty(self) -> bool:
        return bool(
            self._state["forms"] != self._outage_form_base
            or self._state["paper_forms"] != self._paper_form_base
        )

    def _set_dirty(self) -> None:
        self._state.update(dirty=self._dirty(), error="", notice="")
        self.stateChanged.emit()

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        papers = row["paper_records"]
        return {
            key: row[key]
            for key in (
                "id",
                "station_id",
                "revision",
                "reference",
                "kind",
                "started_at",
                "ended_at",
                "entered_at",
                "actor_id",
                "reconciled",
            )
        } | {
            "paper_count": len(papers),
            "pending_paper_count": sum(paper["status"] == "pending" for paper in papers),
            "reconciliation_revision": (
                row["reconciliation"]["revision"] if row["reconciliation"] else 0
            ),
        }

    @staticmethod
    def _same_version(left: dict[str, Any], right: dict[str, Any]) -> bool:
        def token(row: dict[str, Any]) -> tuple[Any, ...]:
            reconciliation = row.get("reconciliation") or {}
            papers = tuple(
                (
                    paper.get("id"),
                    paper.get("revision"),
                    paper.get("status"),
                    (paper.get("reentry") or {}).get("request_id"),
                )
                for paper in row.get("paper_records", [])
            )
            return (
                row.get("revision"),
                papers,
                reconciliation.get("revision"),
                reconciliation.get("valid"),
            )

        return token(left) == token(right)

    def _accept_list(self, data: dict[str, Any]) -> bool:
        rows = data.get("outages")
        if not isinstance(rows, list) or not all(
            _outage_record(row, self._state["station_id"]) for row in rows
        ):
            self._error("request_failed")
            return False
        self._state["items"] = [self._summary(row) for row in rows]
        selected_id = self._state["selected"].get("id")
        current = next((row for row in rows if row["id"] == selected_id), None)
        if current is not None and not self._same_version(current, self._state["selected"]):
            self._state["newer_revision"] = True
        return True

    def _accept_detail(self, data: dict[str, Any], outage_id: int) -> bool:
        row, history = data.get("record"), data.get("history")
        if not (
            _outage_record(row, self._state["station_id"])
            and row["id"] == outage_id
            and isinstance(history, list)
            and all(
                isinstance(item, dict)
                and item.get("id") == outage_id
                and _positive(item.get("revision"))
                and _positive(item.get("actor_id"))
                and item.get("kind") in OUTAGE_KINDS
                and isinstance(item.get("reference"), str)
                and _aware(item.get("started_at"))
                and _aware(item.get("ended_at"))
                and _aware(item.get("entered_at"))
                for item in history
            )
        ):
            self._error("request_failed")
            return False
        self._state.update(
            selected=deepcopy(row),
            history=deepcopy(history),
            forms=_form_from_outage(row),
            paper_forms=_empty_paper_form(),
            selected_paper_id=0,
            paper_editable=False,
            newer_revision=False,
        )
        self._outage_form_base = deepcopy(self._state["forms"])
        self._paper_form_base = deepcopy(self._state["paper_forms"])
        self._state["dirty"] = False
        return True

    def _send(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        background: bool = False,
        uncertain: bool = False,
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
                uncertain
                and code == "invalid_credentials"
                and self._state["uncertain_save"]
                and self._pending is not None
                and self._pending["kind"] == "approve"
            ):
                # The server checks a fresh Supervisor password before replaying
                # an approval receipt. Keep the uncertain command identity so a
                # corrected password can retry the same immutable request.
                self._error(code)
                return
            if uncertain and code in UNCERTAIN_ERRORS:
                self._state.update(uncertain_save=True, dirty=True)
            elif code in OUTAGE_CONFLICTS:
                self._pending = None
                self._state.update(uncertain_save=False, dirty=True, newer_revision=True)
            elif uncertain:
                self._pending = None
                self._state["uncertain_save"] = False
            self._error(code, newer=code in OUTAGE_CONFLICTS)

        self._request(path, method, payload, done, failed)

    def _pending_command(
        self,
        kind: str,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]] | None:
        body = deepcopy(payload)
        body.pop("request_id", None)
        body.pop("password", None)
        signature = json.dumps(
            [self._state["station_id"], kind, method, path, body],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if self._state["uncertain_save"]:
            if self._pending is None or self._pending["signature"] != signature:
                self._error("outage_uncertain_save_pending")
                return None
            return self._pending["request_id"], deepcopy(self._pending["payload"])
        request_id = str(uuid4())
        command = {**deepcopy(payload), "request_id": request_id}
        self._pending = {
            "signature": signature,
            "request_id": request_id,
            "method": method,
            "path": path,
            "payload": deepcopy(command),
            "kind": kind,
        }
        self._state["pending_request_id"] = request_id
        return request_id, command

    def _finish_command(self, notice: str) -> None:
        self._pending = None
        self._state.update(
            pending_request_id="",
            uncertain_save=False,
            dirty=False,
            error="",
            notice=notice,
            newer_revision=False,
        )

    def _outage_role_allowed(self) -> bool:
        return self._state["writable"] and self._state["role"] in OPERATIONAL_ROLES

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.reload()

    @Slot()
    def refresh(self) -> None:
        if (
            not self._opened
            or not self._context_ready()
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return

        def loaded(data: dict[str, Any]) -> None:
            self._accept_list(data)

        self._send(self._path(), "GET", None, loaded, background=True)

    @Slot(result=bool)
    def reload(self) -> bool:
        if not self._context_ready() or self._state["busy"]:
            self._error("outage_context_unavailable")
            return False
        if self._state["dirty"] or self._state["uncertain_save"]:
            self._error("unsaved_outage_changes")
            return False
        self._generation += 1
        self._state.update(error="", notice="", newer_revision=False)

        def loaded(data: dict[str, Any]) -> None:
            self._accept_list(data)

        self._send(self._path(), "GET", None, loaded)
        return True

    @Slot(int, bool, result=bool)
    @Slot(int, result=bool)
    def loadOutage(self, outage_id: int, discard: bool = False) -> bool:
        if not self._context_ready() or self._state["busy"]:
            self._error("outage_context_unavailable")
            return False
        if outage_id == 0:
            if (self._state["dirty"] or self._state["uncertain_save"]) and not discard:
                self._error("unsaved_outage_changes")
                return False
            if self._state["uncertain_save"]:
                self._error("outage_uncertain_save_pending")
                return False
            self._generation += 1
            self._state.update(
                selected={},
                history=[],
                forms=_empty_outage_form(),
                paper_forms=_empty_paper_form(),
                selected_paper_id=0,
                paper_editable=False,
                dirty=False,
                newer_revision=False,
                error="",
                notice="",
            )
            self._outage_form_base = _empty_outage_form()
            self._paper_form_base = _empty_paper_form()
            self.stateChanged.emit()
            return True
        if not _positive(outage_id):
            self._error("outage_not_found")
            return False
        if self._state["uncertain_save"]:
            self._error("outage_uncertain_save_pending")
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_outage_changes")
            return False
        self._generation += 1
        self._state.update(error="", notice="", newer_revision=False)

        def loaded(data: dict[str, Any]) -> None:
            if self._accept_detail(data, outage_id):
                self._finish_command("")
                self._state.update(dirty=False, pending_request_id="")

        self._send(f"{self._path()}/{outage_id}", "GET", None, loaded)
        return True

    @Slot()
    def discardAndReload(self) -> bool:
        if self._state["uncertain_save"]:
            self._error("outage_uncertain_save_pending")
            return False
        outage_id = self._state["selected"].get("id", 0)
        if outage_id:
            return self.loadOutage(outage_id, True)
        self._state.update(
            forms=_empty_outage_form(),
            paper_forms=_empty_paper_form(),
            dirty=False,
            selected_paper_id=0,
            paper_editable=False,
        )
        self._outage_form_base = _empty_outage_form()
        self._paper_form_base = _empty_paper_form()
        self.stateChanged.emit()
        return self.reload()

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if (
            not self._outage_role_allowed()
            or self._state["busy"]
            or self._state["uncertain_save"]
            or name not in self._state["forms"]
        ):
            return
        if name == "kind" and value not in OUTAGE_KINDS:
            self._error("outage_validation")
            return
        self._state["forms"][name] = value
        self._set_dirty()

    def _time(self, name: str, original: str | None = None) -> str:
        try:
            return parse_event_time(self._state["forms"][name], original=original)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError("outage_validation") from None

    def _outage_payload(self) -> tuple[str, str, dict[str, Any]] | None:
        form = self._state["forms"]
        selected = self._state["selected"]
        reference = form["reference"].strip()
        if not reference or len(reference) > 160 or form["kind"] not in OUTAGE_KINDS:
            self._error("outage_validation")
            return None
        if len(form["notes"]) > 2000:
            self._error("outage_validation")
            return None
        try:
            started = self._time("started_at", selected.get("started_at"))
            ended = self._time("ended_at", selected.get("ended_at"))
            if datetime.fromisoformat(started) > datetime.fromisoformat(ended):
                self._error("outage_interval_invalid")
                return None
        except ValueError as error:
            self._error(str(error))
            return None
        payload: dict[str, Any] = {
            "reference": reference,
            "kind": form["kind"],
            "started_at": started,
            "ended_at": ended,
            "notes": form["notes"],
        }
        if selected:
            reason = form["amendment_reason"].strip()
            if not reason or len(reason) > 2000:
                self._error("outage_amendment_reason_required")
                return None
            payload["expected_revision"] = selected["revision"]
            payload["amendment_reason"] = reason
            return "PUT", f"{self._path()}/{selected['id']}", payload
        return "POST", self._path(), payload

    @Slot()
    def save(self) -> None:
        if self._state["busy"] or not self._outage_role_allowed():
            if not self._state["busy"]:
                self._error("election_read_only")
            return
        if self._dirty_paper():
            self._error("unsaved_outage_paper_changes")
            return
        command = self._outage_payload()
        if command is None:
            return
        method, path, payload = command
        pending = self._pending_command("outage", method, path, payload)
        if pending is None:
            return
        _, body = pending
        if self._pending is not None:
            body = deepcopy(self._pending["payload"])
        self._generation += 1
        self._state.update(error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not _outage_record(data, self._state["station_id"]):
                self._state.update(uncertain_save=True, dirty=True)
                self._error("outage_response_invalid")
                return
            self._state.update(selected=deepcopy(data), forms=_form_from_outage(data), history=[])
            self._outage_form_base = deepcopy(self._state["forms"])
            self._finish_command("outage_saved")
            self._load_detail(data["id"])

        self._send(path, method, body, saved, uncertain=True)

    def _dirty_paper(self) -> bool:
        return bool(self._state["paper_forms"] != self._paper_form_base)

    @Slot(int)
    def beginPaper(self, paper_id: int) -> bool:
        if not self._state["selected"] or self._state["busy"]:
            self._error("outage_not_selected")
            return False
        if self._state["uncertain_save"] or self._dirty_outage():
            self._error("unsaved_outage_changes")
            return False
        if self._dirty_paper():
            self._error("unsaved_outage_paper_changes")
            return False
        if paper_id == 0:
            self._state.update(
                paper_forms=_empty_paper_form(), selected_paper_id=0,
                paper_editable=self._can_register_any_paper(),
            )
            self._paper_form_base = _empty_paper_form()
        elif _positive(paper_id):
            paper = next(
                (row for row in self._state["selected"]["paper_records"] if row["id"] == paper_id),
                None,
            )
            if paper is None:
                self._error("outage_paper_not_found")
                return False
            self._state.update(
                paper_forms=_form_from_paper(paper),
                selected_paper_id=paper_id,
                paper_editable=(
                    paper["status"] == "pending" and self._workflow_role(paper["workflow"])
                ),
            )
            self._paper_form_base = deepcopy(self._state["paper_forms"])
        else:
            self._error("outage_paper_not_found")
            return False
        self._state.update(dirty=self._dirty(), error="", notice="")
        self.stateChanged.emit()
        return bool(self._state["paper_editable"])

    def _can_register_any_paper(self) -> bool:
        return self._state["writable"] and self._state["role"] in OPERATIONAL_ROLES

    def _workflow_role(self, workflow: str) -> bool:
        if not self._state["writable"]:
            return False
        return (workflow == "count" and self._state["role"] == "counting_officer") or (
            workflow in ("turnout", "allocation") and self._state["role"] == "polling_officer"
        )

    @Slot(str, str)
    def setPaperField(self, name: str, value: str) -> None:
        form = self._state["paper_forms"]
        if (
            not self._state["paper_editable"]
            or self._state["busy"]
            or self._state["uncertain_save"]
            or name not in form
        ):
            return
        if self._state["selected_paper_id"] and name in (
            "paper_reference", "workflow", "action"
        ):
            return
        if name == "workflow" and value in PAPER_WORKFLOWS:
            form[name] = value
            form["action"] = {"count": "submit", "turnout": "save", "allocation": "create"}[value]
        else:
            form[name] = value
        self._state.update(dirty=self._dirty(), error="", notice="")
        self.stateChanged.emit()

    def _paper_target(self) -> dict[str, int] | None:
        form = self._state["paper_forms"]
        workflow, action = form["workflow"], form["action"]
        if workflow not in PAPER_WORKFLOWS or not self._workflow_role(workflow):
            self._error("outage_paper_role_required")
            return None
        names: tuple[str, ...]
        keys: tuple[str, ...]
        if workflow == "count" and action == "submit":
            names = ("target_scope_id", "target_round_id")
            keys = ("scope_id", "round_id")
        elif workflow == "turnout" and action in ("save", "submit"):
            names, keys = ("target_period_index",), ("period_index",)
        elif workflow == "allocation" and action == "create":
            names, keys = ("target_counter_id",), ("counter_id",)
        elif workflow == "allocation" and action == "amend":
            names = ("target_counter_id", "target_allocation_id")
            keys = ("counter_id", "allocation_id")
        else:
            self._error("outage_paper_action_invalid")
            return None
        values = [positive_integer(form[name]) for name in names]
        if any(value is None for value in values):
            self._error("outage_paper_target_required")
            return None
        return {key: value for key, value in zip(keys, values, strict=True) if value is not None}

    def _paper_payload(self) -> tuple[str, str, dict[str, Any]] | None:
        if not self._state["selected"]:
            self._error("outage_not_selected")
            return None
        if not self._state["writable"]:
            self._error("election_read_only")
            return None
        if self._dirty_outage():
            self._error("unsaved_outage_changes")
            return None
        form = self._state["paper_forms"]
        reference = form["paper_reference"].strip()
        if not reference or len(reference) > 160 or len(form["notes"]) > 2000:
            self._error("outage_paper_validation")
            return None
        try:
            original = self._time_for_form("original_event_at", self._paper_original_time())
        except ValueError as error:
            self._error(str(error))
            return None
        target = self._paper_target()
        if target is None:
            return None
        payload: dict[str, Any] = {
            "original_event_at": original,
            "target": target,
            "notes": form["notes"],
        }
        paper_id = self._state["selected_paper_id"]
        if paper_id:
            paper = next(
                row for row in self._state["selected"]["paper_records"] if row["id"] == paper_id
            )
            if paper["status"] != "pending":
                self._error("paper_already_entered")
                return None
            reason = form["amendment_reason"].strip()
            if not reason or len(reason) > 2000:
                self._error("outage_paper_amendment_reason_required")
                return None
            payload.update(
                expected_outage_revision=self._state["selected"]["revision"],
                expected_revision=paper["revision"],
                amendment_reason=reason,
            )
            path = f"{self._path()}/{self._state['selected']['id']}/paper-records/{paper_id}"
            return "PUT", path, payload
        if not self._workflow_role(form["workflow"]):
            self._error("outage_paper_role_required")
            return None
        payload.update(
            expected_outage_revision=self._state["selected"]["revision"],
            paper_reference=reference,
            workflow=form["workflow"],
            action=form["action"],
        )
        return "POST", f"{self._path()}/{self._state['selected']['id']}/paper-records", payload

    def _paper_original_time(self) -> str | None:
        paper_id = self._state["selected_paper_id"]
        if not paper_id:
            return None
        paper = next(
            (row for row in self._state["selected"]["paper_records"] if row["id"] == paper_id),
            None,
        )
        return paper.get("original_event_at") if paper else None

    def _time_for_form(self, name: str, original: str | None = None) -> str:
        try:
            return parse_event_time(self._state["paper_forms"][name], original=original)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError("outage_paper_time_invalid") from None

    def _dirty_outage(self) -> bool:
        return bool(self._state["forms"] != self._outage_form_base)

    @Slot()
    def savePaper(self) -> None:
        if self._state["busy"] or not self._state["paper_editable"]:
            if not self._state["busy"]:
                self._error("outage_paper_not_editable")
            return
        command = self._paper_payload()
        if command is None:
            return
        method, path, payload = command
        pending = self._pending_command("paper", method, path, payload)
        if pending is None:
            return
        _, body = pending
        if self._pending is not None:
            body = deepcopy(self._pending["payload"])
        self._generation += 1
        self._state.update(error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            paper_id = self._state["selected_paper_id"] or data.get("id", 0)
            if not _paper_record(data, self._state["station_id"]) or data["id"] != paper_id:
                self._state.update(uncertain_save=True, dirty=True)
                self._error("outage_response_invalid")
                return
            self._finish_command("outage_paper_saved")
            self._state.update(
                selected_paper_id=data["id"],
                paper_forms=_form_from_paper(data),
                paper_editable=data["status"] == "pending",
            )
            self._paper_form_base = deepcopy(self._state["paper_forms"])
            self._load_detail(self._state["selected"]["id"])

        self._send(path, method, body, saved, uncertain=True)

    @Slot(str, str)
    def approveReconciliation(self, password: str, reason: str) -> None:
        self.erasePassword.emit()
        selected = self._state["selected"]
        if self._state["busy"]:
            return
        if not self._context_ready() or not self._state["writable"]:
            self._error("election_read_only")
            return
        if self._state["role"] != "supervisor":
            self._error("supervisor_required")
            return
        retrying_approval = bool(
            self._state["uncertain_save"] and self._pending
            and self._pending["kind"] == "approve"
        )
        if (
            not selected or self._state["newer_revision"]
            or self._state["dirty"] and not retrying_approval
        ):
            self._error("outage_review_required")
            return
        # The pending-command signature still requires the original basis and reason.
        papers = selected["paper_records"]
        if not papers or any(row["status"] != "entered" for row in papers):
            self._error("outage_papers_pending")
            return
        reason = reason.strip()
        if not reason or len(reason) > 2000 or not password:
            self._error("outage_reconciliation_validation")
            return
        reconciliation = selected.get("reconciliation") or {}
        payload = {
            "expected_revision": selected["revision"],
            "expected_reconciliation_revision": reconciliation.get("revision", 0),
            "paper_revisions": sorted(
                ({"paper_id": row["id"], "revision": row["revision"]} for row in papers),
                key=lambda row: row["paper_id"],
            ),
            "reason": reason,
        }
        path = f"{self._path()}/{selected['id']}/approve"
        pending = self._pending_command("approve", "POST", path, payload)
        if pending is None:
            return
        _, body = pending
        if self._pending is not None:
            body = deepcopy(self._pending["payload"])
        body["password"] = password
        self._generation += 1
        self._state.update(error="", notice="")

        def approved(data: dict[str, Any]) -> None:
            row, history = data.get("record"), data.get("history")
            expected_revision = payload["expected_reconciliation_revision"] + 1
            reconciliation_row = row.get("reconciliation") if isinstance(row, dict) else None
            if not (
                _outage_record(row, self._state["station_id"])
                and row["id"] == selected["id"]
                and isinstance(history, list)
                and isinstance(reconciliation_row, dict)
                and reconciliation_row.get("revision") == expected_revision
                and reconciliation_row.get("valid") is True
                and reconciliation_row.get("is_current") is True
                and row.get("reconciled") is True
            ):
                self._state.update(uncertain_save=True, dirty=True)
                self._error("outage_response_invalid")
                return
            self._finish_command("outage_reconciled")
            self._state.update(
                selected=deepcopy(row),
                history=deepcopy(history),
                forms=_form_from_outage(row),
                paper_forms=_empty_paper_form(),
                selected_paper_id=0,
                paper_editable=False,
            )
            self._outage_form_base = deepcopy(self._state["forms"])
            self._paper_form_base = deepcopy(self._state["paper_forms"])

        self._send(
            path,
            "POST",
            body,
            approved,
            uncertain=True,
            erase_password=True,
        )

    def _load_detail(self, outage_id: int) -> None:
        def loaded(data: dict[str, Any]) -> None:
            if self._accept_detail(data, outage_id):
                self._finish_command(self._state["notice"])

        self._send(f"{self._path()}/{outage_id}", "GET", None, loaded)

