"""Exact F1 observations and preserved count-round revisions over authenticated HTTP."""

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler
from election.desktop.event_times import format_event_time, parse_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.report_files import DownloadRequest, report_destination, save_report

NETWORK_ERRORS = frozenset({"request_failed", "disconnected", "database_unavailable"})


def empty_forms() -> dict[str, str]:
    return {
        "event_at": "",
        "notes": "",
        "amendment_reason": "",
        "questionable_quantity": "",
        "actual_counted_quantity": "",
    }


def quantity_input(value: Any) -> str:
    return "" if value is None else str(value)


class CountingRoundsController(QObject):
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
        self._generation = self._report_generation = 0
        self._opened = False
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(quantity_display(self._state))

    def reset(self) -> None:
        self._generation += 1
        self._report_generation += 1
        self._opened = False
        self._pending = None
        self._state = {
            "station_id": 0,
            "role": "",
            "context": {},
            "scopes": [],
            "selected_scope_id": 0,
            "scope": {},
            "latest_scope": {},
            "edit_scope_revision": 0,
            "candidates": [],
            "invalid_reasons": [],
            "f2_invalid_reasons": [],
            "rounds": [],
            "selected": {},
            "history": [],
            "forms": empty_forms(),
            "f2_forms": {
                "event_at": "",
                "determination_started_at": "",
                "notes": "",
                "amendment_reason": "",
            },
            "accepted_inputs": [],
            "rejected_inputs": [],
            "dirty_stage": "",
            "candidate_inputs": [],
            "invalid_inputs": [],
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "historical": False,
            "newer_revision": False,
            "error": "",
            "error_origin": "",
            "refresh_error": "",
            "notice": "",
            "uncertain_save": False,
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

    def _scope_path(self) -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/counting-scopes"

    def _path(self) -> str:
        return self._scope_path() + f"/{self._state['selected_scope_id']}/rounds"

    def _error(self, code: str, origin: str = "local") -> None:
        self._state.update(error=code, error_origin=origin, notice="")
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
        if not background:
            self._generation += 1
            self._state["refreshing"] = False
        generation = self._generation
        uncertain_credential_retry = bool(
            self._state["uncertain_save"] and payload and "password" in payload
        )
        activity = "refreshing" if background else "busy"
        self._state[activity] = True
        self.stateChanged.emit()

        def done(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if background:
                self._state["refresh_error"] = ""
                if self._state["error_origin"] == "read":
                    self._state.update(error="", error_origin="")
            success(data)
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if background:
                self._state["refresh_error"] = code
                if not self._state["error"] or self._state["error_origin"] == "read":
                    self._state.update(error=code, error_origin="read")
            else:
                self._state.update(
                    error=code, error_origin="write" if method != "GET" else "read", notice=""
                )
                if method != "GET":
                    remains_uncertain = code in NETWORK_ERRORS or (
                        uncertain_credential_retry and code == "invalid_credentials"
                    )
                    self._state["uncertain_save"] = remains_uncertain
                    if not remains_uncertain:
                        self._pending = None
            self.stateChanged.emit()

        self._request(path, method, payload, done, failed)

    @staticmethod
    def _valid_record(row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and type(row.get("id")) is int
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and type(row.get("scope_id")) is int
            and row.get("status") in ("draft", "submitted", "approved")
            and isinstance(row.get("candidate_votes"), list)
            and isinstance(row.get("invalid_papers"), list)
            and isinstance(row.get("blockers"), list)
            and type(row.get("is_current")) is bool
            and type(row.get("source_current")) is bool
            and type(row.get("f1_complete")) is bool
        )

    def _clear_report(self) -> None:
        self._report_generation += 1
        self._state.update(report={}, report_text="", export_path="")

    def _forms_for(self, record: dict[str, Any]) -> None:
        forms = empty_forms()
        if record:
            forms.update(
                event_at=format_event_time(record["event_at"]).removesuffix(" HKT"),
                notes=record["notes"],
                questionable_quantity=quantity_input(record["questionable_quantity"]),
                actual_counted_quantity=quantity_input(record["actual_counted_quantity"]),
            )
        saved_candidates = {row["candidate_id"]: row for row in record.get("candidate_votes", [])}
        candidates = record.get("candidate_votes") or self._state["candidates"]
        candidate_inputs = []
        for row in candidates:
            identity = row.get("candidate_id", row.get("id"))
            candidate_inputs.append(
                {
                    **row,
                    "candidate_id": identity,
                    "quantity": quantity_input(saved_candidates.get(identity, {}).get("quantity")),
                }
            )
        saved_reasons = {row["reason_id"]: row for row in record.get("invalid_papers", [])}
        historical = bool(record and not record["is_current"])
        frozen_view = bool(
            record
            and (
                historical
                or record["status"] != "draft"
                or self._state["role"] != "counting_officer"
            )
        )
        reasons = record["invalid_papers"] if frozen_view else self._state["invalid_reasons"]
        invalid_inputs = []
        known: set[int] = set()
        for row in reasons:
            identity = row.get("reason_id", row.get("id"))
            known.add(identity)
            saved = saved_reasons.get(identity, {})
            invalid_inputs.append(
                {
                    **row,
                    "reason_id": identity,
                    "reason_revision": row.get("reason_revision", row["revision"]),
                    "quantity": quantity_input(saved.get("quantity")),
                    "explanation": saved.get("explanation", ""),
                    "current_catalog": True,
                }
            )
        for identity, row in saved_reasons.items():
            if identity not in known:
                invalid_inputs.append(
                    {**row, "quantity": quantity_input(row["quantity"]), "current_catalog": False}
                )
        self._state.update(
            forms=forms,
            candidate_inputs=candidate_inputs,
            invalid_inputs=invalid_inputs,
            historical=historical,
            dirty=False,
            newer_revision=False,
            error="",
            error_origin="",
            notice="",
            uncertain_save=False,
            edit_scope_revision=record.get(
                "scope_revision", self._state["scope"].get("revision", 0)
            ),
        )
        self._f2_forms_for(record)
        self._clear_report()

    def _history_loaded(self, data: dict[str, Any], *, foreground: bool) -> None:
        record, history = data.get("record"), data.get("history")
        if not (
            isinstance(record, dict)
            and self._valid_record(record)
            and isinstance(history, list)
            and all(self._valid_record(row) and row["id"] == record["id"] for row in history)
            and record["scope_id"] == self._state["selected_scope_id"]
        ):
            self._error("invalid_response", "read")
            return
        self._state["history"] = deepcopy(history)
        self._state["rounds"] = [
            record if item["id"] == record["id"] else item for item in self._state["rounds"]
        ]
        if foreground:
            self._state["selected"] = deepcopy(record)
            self._forms_for(record)
            return
        selected = self._state["selected"]
        if selected.get("id") != record["id"]:
            return
        same = next((row for row in history if row["revision"] == selected["revision"]), None)
        if same is None:
            self._state["newer_revision"] = True
            return
        catalog = {row["id"]: row["revision"] for row in self._state["invalid_reasons"]}
        editable_catalog = (
            self._state["role"] == "counting_officer" and not self._state["historical"]
        )
        current_inputs = {
            row["reason_id"]
            for row in self._state["invalid_inputs"]
            if row.get("current_catalog", True)
        }
        stale_catalog = editable_catalog and (
            current_inputs != set(catalog)
            or any(
                catalog.get(row["reason_id"]) != row["reason_revision"]
                for row in self._state["invalid_inputs"]
                if row.get("current_catalog", True)
            )
        )
        self._state.update(
            selected=deepcopy(same),
            newer_revision=(
                not self._state["historical"]
                and (
                    record["revision"] != selected["revision"]
                    or self._state["latest_scope"].get("revision")
                    != self._state["edit_scope_revision"]
                )
            )
            or stale_catalog,
        )

    def _rounds_loaded(self, data: dict[str, Any], *, foreground: bool) -> None:
        if not (
            isinstance(data.get("scope"), dict)
            and data["scope"].get("id") == self._state["selected_scope_id"]
            and isinstance(data.get("context"), dict)
            and isinstance(data.get("candidates"), list)
            and isinstance(data.get("invalid_reasons"), list)
            and isinstance(data.get("rounds"), list)
            and all(self._valid_record(row) for row in data["rounds"])
        ):
            self._error("invalid_response", "read")
            return
        scope_changed = bool(
            self._state["edit_scope_revision"]
            and data["scope"]["revision"] != self._state["edit_scope_revision"]
        )
        keep_unsaved_basis = not foreground and not self._state["selected"] and scope_changed
        self._state.update(
            scope=deepcopy(self._state["scope"] if keep_unsaved_basis else data["scope"]),
            latest_scope=deepcopy(data["scope"]),
            candidates=deepcopy(data["candidates"]),
            invalid_reasons=deepcopy(data["invalid_reasons"]),
            f2_invalid_reasons=deepcopy(data.get("f2_invalid_reasons", [])),
            rounds=deepcopy(data["rounds"]),
            context={**self._state["context"], **deepcopy(data["context"])},
        )
        if not foreground and scope_changed and not self._state["historical"]:
            self._state["newer_revision"] = True
        selected = self._state["selected"]
        if foreground:
            row = next((row for row in data["rounds"] if row["id"] == selected.get("id")), None)
            if row is None and data["rounds"]:
                row = data["rounds"][-1]
            if row is None:
                self._state.update(selected={}, history=[])
                self._forms_for({})
                return
            self._send(
                self._path() + f"/{row['id']}",
                "GET",
                None,
                lambda body: self._history_loaded(body, foreground=True),
            )
        elif selected:
            self._send(
                self._path() + f"/{selected['id']}",
                "GET",
                None,
                lambda body: self._history_loaded(body, foreground=False),
                background=True,
            )
        elif data["rounds"]:
            # A peer/new uncertain create never replaces a locally entered draft.
            protected = self._state["error_origin"] not in ("", "read")
            if self._state["dirty"] or self._state["uncertain_save"] or protected:
                self._state["newer_revision"] = True
            else:
                row = data["rounds"][-1]
                self._send(
                    self._path() + f"/{row['id']}",
                    "GET",
                    None,
                    lambda body: self._history_loaded(body, foreground=True),
                    background=True,
                )

    def _scopes_loaded(self, data: dict[str, Any], *, foreground: bool) -> None:
        if not (
            isinstance(data.get("context"), dict)
            and data["context"].get("station", {}).get("id") == self._state["station_id"]
            and isinstance(data.get("scopes"), list)
        ):
            self._error("invalid_response", "read")
            return
        self._state.update(
            scopes=deepcopy(data["scopes"]),
            context={**self._state["context"], **deepcopy(data["context"])},
        )
        if self._state["selected_scope_id"]:
            self._send(
                self._path(),
                "GET",
                None,
                lambda body: self._rounds_loaded(body, foreground=foreground),
                background=not foreground,
            )

    @Slot()
    def open(self) -> None:
        if self._opened:
            self.refresh()
        else:
            self._opened = True
            self.reload()

    @Slot(result=bool)
    def reload(self) -> bool:
        if not self._state["station_id"] or self._state["busy"]:
            return False
        if self._state["dirty"]:
            self._error("unsaved_f1_changes")
            return False
        self._pending = None
        self._send(
            self._scope_path(), "GET", None, lambda body: self._scopes_loaded(body, foreground=True)
        )
        return True

    @Slot()
    def refresh(self) -> None:
        if (
            self._opened
            and self._state["station_id"]
            and not self._state["busy"]
            and not self._state["refreshing"]
        ):
            self._send(
                self._scope_path(),
                "GET",
                None,
                lambda body: self._scopes_loaded(body, foreground=False),
                background=True,
            )

    @Slot()
    def discardAndReload(self) -> None:
        if self._state["busy"]:
            return
        self._state.update(dirty=False, uncertain_save=False)
        self.reload()

    @Slot(int, result=bool)
    def selectScope(self, scope_id: int) -> bool:
        if self._state["busy"]:
            return False
        if self._state["dirty"]:
            self._error("unsaved_f1_changes")
            return False
        if not any(row.get("id") == scope_id for row in self._state["scopes"]):
            self._error("counting_scope_not_found")
            return False
        self._pending = None
        self._state.update(
            selected_scope_id=scope_id,
            scope={},
            latest_scope={},
            edit_scope_revision=0,
            selected={},
            history=[],
            rounds=[],
            candidates=[],
            invalid_reasons=[],
            f2_invalid_reasons=[],
            accepted_inputs=[],
            rejected_inputs=[],
            f2_forms={
                "event_at": "",
                "determination_started_at": "",
                "notes": "",
                "amendment_reason": "",
            },
            dirty_stage="",
            candidate_inputs=[],
            invalid_inputs=[],
            forms=empty_forms(),
            historical=False,
            newer_revision=False,
            error="",
            error_origin="",
            notice="",
            uncertain_save=False,
        )
        self._clear_report()
        self._send(
            self._path(), "GET", None, lambda body: self._rounds_loaded(body, foreground=True)
        )
        return True

    @Slot(int, result=bool)
    def selectRound(self, round_id: int) -> bool:
        if self._state["busy"]:
            return False
        if self._state["dirty"]:
            self._error("unsaved_f1_changes")
            return False
        if not any(row.get("id") == round_id for row in self._state["rounds"]):
            self._error("count_round_not_found")
            return False
        self._pending = None
        self._clear_report()
        self._send(
            self._path() + f"/{round_id}",
            "GET",
            None,
            lambda body: self._history_loaded(body, foreground=True),
        )
        return True

    @Slot(int, result=bool)
    def loadRevision(self, revision: int) -> bool:
        selected = self._state["selected"]
        if self._state["busy"] or not selected:
            return False
        if self._state["dirty"]:
            self._error("unsaved_f1_changes")
            return False
        self._clear_report()

        def loaded(row: dict[str, Any]) -> None:
            if not (
                self._valid_record(row)
                and row["id"] == selected["id"]
                and row["revision"] == revision
            ):
                self._error("invalid_response", "read")
                return
            self._state["selected"] = deepcopy(row)
            self._forms_for(row)

        self._send(self._path() + f"/{selected['id']}/revisions/{revision}", "GET", None, loaded)
        return True

    def _editable(self) -> bool:
        return bool(
            self._state["role"] == "counting_officer"
            and self._state["selected_scope_id"]
            and not self._state["busy"]
            and not self._state["historical"]
            and self._state["selected"].get("status", "draft") == "draft"
            and self._state["dirty_stage"] in ("", "f1")
            and self._state["context"].get("election", {}).get("status") == "active"
        )

    def _changed(self, stage: str = "f1") -> None:
        self._pending = None
        self._state.update(
            dirty=True,
            dirty_stage=stage,
            error="",
            error_origin="",
            notice="",
            uncertain_save=False,
        )
        self._clear_report()
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if self._editable() and name in self._state["forms"] and isinstance(value, str):
            if self._state["forms"][name] != value:
                self._state["forms"][name] = value
                self._changed()

    @Slot(int, str)
    def setCandidateQuantity(self, candidate_id: int, value: str) -> None:
        if not self._editable() or not isinstance(value, str):
            return
        row = next(
            (row for row in self._state["candidate_inputs"] if row["candidate_id"] == candidate_id),
            None,
        )
        if row is None:
            self._error("count_candidate_invalid")
        elif row["quantity"] != value:
            row["quantity"] = value
            self._changed()

    @Slot(int, str)
    def setInvalidQuantity(self, reason_id: int, value: str) -> None:
        self._set_invalid(reason_id, "quantity", value)

    @Slot(int, str)
    def setInvalidExplanation(self, reason_id: int, value: str) -> None:
        self._set_invalid(reason_id, "explanation", value)

    def _set_invalid(self, reason_id: int, field: str, value: str) -> None:
        if not self._editable() or not isinstance(value, str):
            return
        row = next(
            (row for row in self._state["invalid_inputs"] if row["reason_id"] == reason_id), None
        )
        if row is None:
            self._error("count_invalid_reason_invalid")
        elif row[field] != value:
            row[field] = value
            self._changed()

    @staticmethod
    def _quantity(value: str) -> int | None:
        text = value.strip()
        if not text:
            return None
        if not text.isascii() or not text.isdecimal():
            raise ValueError("Use a nonnegative whole number or leave unobserved")
        return int(text)

    def _payload(self) -> dict[str, Any] | None:
        form, selected = self._state["forms"], self._state["selected"]
        try:
            event = parse_event_time(form["event_at"], selected.get("event_at"))
        except ValueError, OverflowError:
            self._error("f1_time_invalid")
            return None
        try:
            candidates = [
                {"candidate_id": row["candidate_id"], "quantity": self._quantity(row["quantity"])}
                for row in self._state["candidate_inputs"]
            ]
            reasons = []
            for row in self._state["invalid_inputs"]:
                quantity = self._quantity(row["quantity"])
                if not row["current_catalog"]:
                    if quantity:
                        self._error("invalid_reason_revision_conflict")
                        return None
                    continue
                if len(row["explanation"]) > 2000:
                    self._error("f1_validation")
                    return None
                if quantity and row["explanation_required"] and not row["explanation"].strip():
                    self._error("invalid_reason_explanation_required")
                    return None
                reasons.append(
                    {
                        "reason_id": row["reason_id"],
                        "reason_revision": row["reason_revision"],
                        "quantity": quantity,
                        "explanation": row["explanation"],
                    }
                )
            questionable = self._quantity(form["questionable_quantity"])
            actual = self._quantity(form["actual_counted_quantity"])
        except ValueError:
            self._error("f1_quantity_invalid")
            return None
        if len(form["notes"]) > 2000 or len(form["amendment_reason"]) > 2000:
            self._error("f1_validation")
            return None
        return {
            "expected_revision": selected.get("revision", 0),
            "scope_revision": self._state["edit_scope_revision"],
            "event_at": event,
            "candidate_votes": candidates,
            "invalid_papers": reasons,
            "questionable_quantity": questionable,
            "actual_counted_quantity": actual,
            "notes": form["notes"],
            "amendment_reason": form["amendment_reason"],
        }

    @Slot()
    def save(self, discard_f2: bool = False) -> None:
        if self._state["role"] != "counting_officer":
            self._error("counting_officer_required")
            return
        if not self._editable():
            return
        if self._state["latest_scope"].get("revision") != self._state["edit_scope_revision"]:
            self._error("count_scope_revision_conflict")
            return
        if not self._state["scope"].get("count_ready"):
            self._error("count_scope_not_ready")
            return
        if self._state["selected"] and not self._state["selected"]["source_current"]:
            self._error("count_round_basis_stale")
            return
        payload = self._payload()
        if payload is None:
            return
        selected = self._state["selected"]
        if discard_f2:
            payload["discard_f2"] = True
        signature = json.dumps(
            {
                "station": self._state["station_id"],
                "scope": self._state["selected_scope_id"],
                "round": selected.get("id"),
                "data": payload,
            },
            sort_keys=True,
        )
        retry = bool(
            self._state["uncertain_save"] and self._pending and self._pending[0] == signature
        )
        if self._state["newer_revision"] and not retry:
            self._error("revision_conflict")
            return
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._state.update(error="", error_origin="", notice="")

        def saved(row: dict[str, Any]) -> None:
            if not self._valid_record(row):
                self._error("invalid_response", "write")
                return
            self._state["rounds"] = [
                row if item["id"] == row["id"] else item for item in self._state["rounds"]
            ]
            if not any(item["id"] == row["id"] for item in self._state["rounds"]):
                self._state["rounds"].append(row)
            # A later read can legitimately contain another actor's newer head.
            # Acknowledge this command's returned revision and keep its form pinned.
            self._state["selected"] = deepcopy(row)
            self._state["invalid_reasons"] = deepcopy(row["invalid_papers"])
            self._forms_for(row)

            def reviewed(body: dict[str, Any]) -> None:
                self._history_loaded(body, foreground=False)
                if not self._state["error"]:
                    self._pending = None
                    self._state["notice"] = "f1_saved"

            self._send(self._path() + f"/{row['id']}", "GET", None, reviewed)

        self._send(
            self._path() + (f"/{selected['id']}" if selected else ""),
            "PUT" if selected else "POST",
            payload,
            saved,
        )

    @Slot()
    def saveDiscardingF2(self) -> None:
        self.save(True)

    def _f2_forms_for(self, record: dict[str, Any]) -> None:
        saved = record.get("f2") or {}
        forms = {
            key: saved.get(key, "") for key in ("event_at", "determination_started_at", "notes")
        }
        for key in ("event_at", "determination_started_at"):
            forms[key] = format_event_time(forms[key]).removesuffix(" HKT") if forms[key] else ""
        forms["amendment_reason"] = ""
        votes = {row["candidate_id"]: row for row in saved.get("accepted_votes", [])}
        candidates = record.get("candidate_votes") or self._state["candidates"]
        accepted = []
        for candidate in candidates:
            identity = candidate.get("candidate_id", candidate.get("id"))
            accepted.append(
                {
                    **candidate,
                    "candidate_id": identity,
                    "quantity": quantity_input(votes.get(identity, {}).get("quantity")),
                }
            )
        frozen_reasons = {row["reason_id"]: row for row in saved.get("rejected_papers", [])}
        frozen_view = bool(
            record
            and (
                not record["is_current"]
                or record["status"] != "draft"
                or self._state["role"] != "counting_officer"
            )
        )
        reasons = (
            list(frozen_reasons.values())
            if frozen_view and saved
            else self._state["f2_invalid_reasons"]
        )
        rejected = []
        known = set()
        for reason in reasons:
            identity = reason.get("reason_id", reason.get("id"))
            known.add(identity)
            old = frozen_reasons.get(identity, {})
            rejected.append(
                {
                    **reason,
                    "reason_id": identity,
                    "reason_revision": reason["reason_revision"]
                    if "reason_revision" in reason
                    else reason["revision"],
                    "quantity": quantity_input(old.get("quantity")),
                    "explanation": old.get("explanation", ""),
                    "current_catalog": True,
                }
            )
        for identity, reason in frozen_reasons.items():
            if identity not in known:
                rejected.append(
                    {
                        **reason,
                        "quantity": quantity_input(reason["quantity"]),
                        "current_catalog": False,
                    }
                )
        self._state.update(
            f2_forms=forms, accepted_inputs=accepted, rejected_inputs=rejected, dirty_stage=""
        )

    def _f2_editable(self) -> bool:
        selected = self._state["selected"]
        return bool(
            self._state["role"] == "counting_officer"
            and selected
            and selected["status"] == "draft"
            and selected["f1_complete"]
            and selected["source_current"]
            and not self._state["busy"]
            and not self._state["historical"]
            and self._state["dirty_stage"] in ("", "f2")
            and self._state["context"].get("election", {}).get("status") == "active"
        )

    @Slot(str, str)
    def setF2Field(self, name: str, value: str) -> None:
        if self._f2_editable() and name in self._state["f2_forms"] and isinstance(value, str):
            if self._state["f2_forms"][name] != value:
                self._state["f2_forms"][name] = value
                self._changed("f2")

    @Slot(int, str)
    def setAcceptedQuantity(self, candidate_id: int, value: str) -> None:
        if not self._f2_editable() or not isinstance(value, str):
            return
        row = next(
            (row for row in self._state["accepted_inputs"] if row["candidate_id"] == candidate_id),
            None,
        )
        if row is None:
            self._error("count_candidate_invalid")
        elif row["quantity"] != value:
            row["quantity"] = value
            self._changed("f2")

    def _set_rejected(self, reason_id: int, field: str, value: str) -> None:
        if not self._f2_editable() or not isinstance(value, str):
            return
        row = next(
            (row for row in self._state["rejected_inputs"] if row["reason_id"] == reason_id), None
        )
        if row is None:
            self._error("count_invalid_reason_invalid")
        elif row[field] != value:
            row[field] = value
            self._changed("f2")

    @Slot(int, str)
    def setRejectedQuantity(self, reason_id: int, value: str) -> None:
        self._set_rejected(reason_id, "quantity", value)

    @Slot(int, str)
    def setRejectedExplanation(self, reason_id: int, value: str) -> None:
        self._set_rejected(reason_id, "explanation", value)

    @Slot()
    def saveF2(self) -> None:
        if not self._f2_editable():
            return
        selected, forms = self._state["selected"], self._state["f2_forms"]
        prior = selected.get("f2") or {}
        try:
            event_at = parse_event_time(forms["event_at"], prior.get("event_at"))
            start = (
                parse_event_time(
                    forms["determination_started_at"], prior.get("determination_started_at")
                )
                if forms["determination_started_at"].strip()
                else None
            )
        except ValueError, OverflowError:
            self._error("f2_time_invalid")
            return
        try:
            accepted = [
                {"candidate_id": row["candidate_id"], "quantity": self._quantity(row["quantity"])}
                for row in self._state["accepted_inputs"]
            ]
            rejected = []
            for row in self._state["rejected_inputs"]:
                quantity = self._quantity(row["quantity"])
                if not row["current_catalog"]:
                    if quantity:
                        self._error("invalid_reason_revision_conflict")
                        return
                    continue
                if quantity and row["explanation_required"] and not row["explanation"].strip():
                    self._error("invalid_reason_explanation_required")
                    return
                rejected.append(
                    {
                        "reason_id": row["reason_id"],
                        "reason_revision": row["reason_revision"],
                        "quantity": quantity,
                        "explanation": row["explanation"],
                    }
                )
        except ValueError:
            self._error("f2_quantity_invalid")
            return
        if any(len(forms[key]) > 2000 for key in ("notes", "amendment_reason")) or any(
            len(row["explanation"]) > 2000 for row in rejected
        ):
            self._error("f2_validation")
            return
        payload = {
            "expected_revision": selected["revision"],
            "scope_revision": self._state["edit_scope_revision"],
            "event_at": event_at,
            "determination_started_at": start,
            "accepted_votes": accepted,
            "rejected_papers": rejected,
            "notes": forms["notes"],
            "amendment_reason": forms["amendment_reason"],
        }
        path = self._path() + f"/{selected['id']}/f2"
        signature = json.dumps([path, payload], sort_keys=True, ensure_ascii=False)
        retry = bool(
            self._state["uncertain_save"] and self._pending and self._pending[0] == signature
        )
        if self._state["newer_revision"] and not retry:
            self._error("revision_conflict")
            return
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._state.update(error="", error_origin="", notice="")

        def saved(row: dict[str, Any]) -> None:
            if not self._valid_record(row) or row["id"] != selected["id"]:
                self._error("invalid_response", "write")
                return
            self._state["selected"] = deepcopy(row)
            self._forms_for(row)

            def reviewed(body: dict[str, Any]) -> None:
                self._history_loaded(body, foreground=False)
                if not self._state["error"]:
                    self._pending = None
                    self._state["notice"] = "f2_saved"

            self._send(self._path() + f"/{row['id']}", "GET", None, reviewed)

        self._send(path, "PUT", payload, saved)

    def _workflow(self, action: str, password: str | None = None) -> None:
        role = "counting_officer" if action == "submit" else "supervisor"
        if self._state["role"] != role:
            self._error(role + "_required")
            return
        if self._state["busy"]:
            return
        if self._state["dirty"]:
            self._error("unsaved_count_changes")
            return
        selected = self._state["selected"]
        if not selected:
            self._error("count_round_not_found")
            return
        if self._state["historical"]:
            self._error("count_round_read_only")
            return
        if self._state["context"].get("election", {}).get("status") != "active":
            self._error("active_election_required")
            return
        payload = {
            "expected_revision": selected["revision"],
            "scope_revision": self._state["edit_scope_revision"],
        }
        if action == "select":
            pointer = selected.get("selection")
            payload["expected_selection_revision"] = pointer["revision"] if pointer else 0
        path = self._path() + f"/{selected['id']}/{action}"
        # A background read can reveal a committed selection whose reply was
        # lost. Retry its original credential-free command, not a new pointer CAS.
        if self._state["uncertain_save"] and self._pending:
            try:
                pending = json.loads(self._pending[0])
                if isinstance(pending, list) and len(pending) == 2 and pending[0] == path:
                    payload = pending[1]
            except ValueError, TypeError:
                pass
        signature = json.dumps([path, payload], sort_keys=True, ensure_ascii=False)
        retry = bool(
            self._state["uncertain_save"] and self._pending and self._pending[0] == signature
        )
        if self._state["newer_revision"] and not retry:
            self._error("revision_conflict")
            return
        if not selected["source_current"] and not retry:
            self._error("count_round_basis_stale")
            return
        if action != "submit" and (
            not isinstance(password, str) or not password or len(password) > 128
        ):
            self._error("invalid_credentials")
            return
        if not self._pending or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        command: dict[str, Any] = {**payload, "request_id": self._pending[1]}
        if action != "submit":
            command["password"] = password
        self._state.update(error="", error_origin="", notice="")

        def saved(row: dict[str, Any]) -> None:
            if not self._valid_record(row) or row["id"] != selected["id"]:
                self._error("invalid_response", "write")
                return
            self._state["selected"] = deepcopy(row)
            self._forms_for(row)

            def reviewed(body: dict[str, Any]) -> None:
                self._history_loaded(body, foreground=False)
                if not self._state["error"]:
                    self._pending = None
                    self._state["notice"] = {
                        "submit": "count_submitted",
                        "approve": "count_approved",
                        "select": "count_selected",
                    }[action]

            self._send(self._path() + f"/{row['id']}", "GET", None, reviewed)

        self._send(path, "POST", command, saved)

    @Slot()
    def submitCount(self) -> None:
        self._workflow("submit")

    @Slot(str)
    def approveCount(self, password: str) -> None:
        self._workflow("approve", password)

    @Slot(str)
    def selectApproved(self, password: str) -> None:
        self._workflow("select", password)

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        row = self._state["selected"]
        if self._state["busy"] or not row or locale not in ("tc", "sc", "en"):
            self._error("count_round_not_found")
            return None
        if self._state["dirty"]:
            self._error("unsaved_f1_changes")
            return None
        return (
            f"{self._path()}/{row['id']}/revisions/{row['revision']}/statement"
            f"{extension}?locale={locale}"
        )

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None:
            return
        selected = self._state["selected"]
        identity = (
            self._state["station_id"],
            self._state["selected_scope_id"],
            selected["id"],
            selected["revision"],
        )
        self._clear_report()
        report_generation = self._report_generation

        def loaded(body: dict[str, Any]) -> None:
            if report_generation != self._report_generation:
                return
            observed = tuple(
                body.get(key) for key in ("station_id", "scope_id", "round_id", "revision")
            )
            lines = body.get("preview_lines")
            if not (
                observed == identity
                and body.get("locale") == locale
                and isinstance(lines, list)
                and lines
                and all(isinstance(line, str) for line in lines)
            ):
                self._error("invalid_response", "read")
                return
            self._state.update(report=body, report_text="\n".join(lines), notice="f1_report_ready")

        self._send(path, "GET", None, loaded)

    @Slot(str, str, str)
    def exportStatement(self, format: str, locale: str, filepath: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("f1_export_failed")
            return
        path, destination = self._report_path(locale, "." + format), report_destination(filepath)
        if path is None:
            return
        if destination is None:
            self._error("f1_export_failed")
            return
        self._generation += 1
        generation, report_generation = self._generation, self._report_generation
        self._state.update(
            busy=True, refreshing=False, error="", error_origin="", notice="", export_path=""
        )
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation and report_generation == self._report_generation:
                self._state["busy"] = False
                self._error(code, "write")

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation or report_generation != self._report_generation:
                return
            if not save_report(body, destination, format):
                failed("f1_export_failed")
                return
            self._state.update(busy=False, export_path=destination, notice="f1_exported")
            self.stateChanged.emit()

        self._download(path, loaded, failed)
