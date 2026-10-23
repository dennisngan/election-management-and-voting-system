"""Complaint case forms retain reviewed records separately from live updates."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler, positive_integer
from election.desktop.lifecycle import HKT, TIME_FORMAT


def empty_forms() -> dict[str, str]:
    return {
        "case_reference": "",
        "received_time": "",
        "category_id": "",
        "description": "",
        "work_status": "in_progress",
        "completed_time": "",
        "reason": "",
    }


class ComplaintCasesController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
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
            "context": {},
            "role": "",
            "schedule": {},
            "schedule_state": "unavailable",
            "generated_at": "",
            "categories": [],
            "items": [],
            "current": {},
            "selected": {},
            "history": [],
            "forms": empty_forms(),
            "form_category": {},
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "historical": False,
            "requires_amendment": False,
            "error": "",
            "notice": "",
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
            context=deepcopy(context),
            station_id=station_id,
            role=context.get("account", {}).get("role", ""),
        )
        self.stateChanged.emit()
        if changed and station_id and self._opened:
            self.reload(True)

    def _error(self, code: str) -> None:
        self._state.update(
            error="complaint_validation" if code == "validation_error" else code, notice=""
        )
        self.stateChanged.emit()

    def _path(self, suffix: str = "") -> str:
        return f"/api/workspace/stations/{self._state['station_id']}/complaints{suffix}"

    def _send(
        self,
        path: str,
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
            if generation != self._generation:
                return
            self._state[activity] = False
            self._error(code)

        self._request(path, method, payload, done, failed)

    def _case(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("station_id") == self._state["station_id"]
            and all(
                type(row.get(name)) is int and row[name] > 0
                for name in (
                    "id",
                    "revision_id",
                    "revision",
                    "category_id",
                    "category_revision",
                    "actor_id",
                )
            )
            and all(
                isinstance(row.get(name), str)
                for name in (
                    "case_reference",
                    "received_at",
                    "description",
                    "category_code",
                    "category_label_en",
                    "category_label_tc",
                    "category_label_sc",
                    "entered_at",
                    "amendment_reason",
                    "coverage_status",
                )
            )
            and type(row.get("ever_submitted")) is bool
            and type(row.get("requires_amendment")) is bool
            and type(row.get("is_other")) is bool
            and row.get("work_status") in ("in_progress", "completed")
            and self.formatTime(row["received_at"]) != "—"
            and self.formatTime(row["entered_at"]) != "—"
            and (
                row.get("completed_at") is None
                if row["work_status"] == "in_progress"
                else isinstance(row.get("completed_at"), str)
                and self.formatTime(row["completed_at"]) != "—"
            )
        )

    def _category(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and all(type(row.get(name)) is int and row[name] > 0 for name in ("id", "revision"))
            and all(
                isinstance(row.get(name), str)
                for name in ("code", "label_en", "label_tc", "label_sc")
            )
            and all(
                type(row.get(name)) is bool
                for name in ("enabled", "description_required", "is_other")
            )
            and row.get("election_id") == self._state["context"].get("election", {}).get("id")
        )

    def _newer(self) -> None:
        selected = self._state["selected"]
        current: dict[str, Any] = next(
            (row for row in self._state["items"] if row["id"] == selected.get("id")), {}
        )
        self._state["current"] = deepcopy(current)
        self._state["requires_amendment"] = any(
            row.get("requires_amendment", False) or row.get("ever_submitted", False)
            for row in (selected, current)
        )
        self._state["newer_revision"] = bool(
            selected
            and current
            and (
                selected["revision"] != current["revision"]
                or selected["requires_amendment"] != current["requires_amendment"]
                or selected["ever_submitted"] != current["ever_submitted"]
            )
        )

    def _frozen_category(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["category_id"],
            "revision": row["category_revision"],
            "code": row["category_code"],
            "label_en": row["category_label_en"],
            "label_tc": row["category_label_tc"],
            "label_sc": row["category_label_sc"],
            "is_other": row["is_other"],
            "description_required": row["is_other"],
            "verified_source": row.get("category_verified_source", False),
            "source_english": row.get("category_source_english", ""),
            "reference_page": row.get("category_reference_page"),
            "source": row.get("category_source", "project_configured"),
            "translation_provenance": row.get("translation_provenance", "project_translation"),
            "frozen": True,
        }

    def _accept(
        self, row: dict[str, Any], history: list[dict[str, Any]], *, historical: bool = False
    ) -> None:
        forms = empty_forms()
        if row:
            forms.update(
                case_reference=row["case_reference"],
                received_time=self.formatTime(row["received_at"]).removesuffix(" HKT"),
                category_id=str(row["category_id"]),
                description=row["description"],
                work_status=row["work_status"],
                completed_time=self.formatTime(row["completed_at"]).removesuffix(" HKT")
                if row["completed_at"]
                else "",
            )
        self._reviewed = True
        self._pending = None
        self._state.update(
            selected=deepcopy(row),
            history=deepcopy(history),
            forms=forms,
            form_category=self._frozen_category(row) if row else {},
            dirty=False,
            historical=historical,
            error="",
            notice="",
        )
        self._newer()

    def _snapshot(self, data: dict[str, Any]) -> bool:
        items, context, schedule = (data.get(name) for name in ("items", "context", "schedule"))
        if not (
            isinstance(context, dict)
            and isinstance(context.get("station"), dict)
            and context["station"].get("id") == self._state["station_id"]
            and isinstance(context.get("election"), dict)
            and context["election"].get("id")
            == self._state["context"].get("election", {}).get("id")
            and isinstance(items, list)
            and all(self._case(row) for row in items)
            and len({row["id"] for row in items}) == len(items)
            and data.get("schedule_state") in ("configured", "unavailable")
            and (
                isinstance(schedule, dict)
                if data["schedule_state"] == "configured"
                else schedule is None
            )
            and isinstance(data.get("generated_at"), str)
        ):
            self._error("request_failed")
            return False
        self._state.update(
            items=deepcopy(items),
            context={**self._state["context"], **deepcopy(context)},
            schedule=deepcopy(schedule) if schedule else {},
            schedule_state=data["schedule_state"],
            generated_at=data["generated_at"],
        )
        self._newer()
        if self._state["error"] in ("disconnected", "database_unavailable", "request_failed"):
            self._state["error"] = ""
        return True

    def _load(self, *, accept: bool, background: bool = False) -> None:
        category_path = f"/api/workspace/stations/{self._state['station_id']}/complaint-categories"

        def categories_loaded(data: dict[str, Any]) -> None:
            categories = data.get("items")
            if not isinstance(categories, list) or not all(
                self._category(row) for row in categories
            ):
                self._error("request_failed")
                return
            self._state["categories"] = deepcopy(categories)

            def loaded(snapshot: dict[str, Any]) -> None:
                if not self._snapshot(snapshot):
                    return
                if accept:
                    selected_id = self._state["selected"].get("id")
                    if selected_id:
                        self._history(selected_id)
                    else:
                        self._accept({}, [])

            self._send(self._path(), "GET", None, loaded, background=background)

        self._send(category_path, "GET", None, categories_loaded, background=background)

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
                self._error("unsaved_complaint_changes")
                return False
            self.reset()
            self._state.update(station_id=station_id, role=role)
        self._opened = True
        self._state["role"] = role
        if not station_id:
            self.stateChanged.emit()
            return True
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
            self._load(accept=False, background=True)

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def reload(self, discard: bool = False) -> bool:
        if self._state["busy"] or not self._state["station_id"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_complaint_changes")
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        self._load(accept=True)
        return True

    def _history(
        self,
        case_id: int,
        revision: int | None = None,
        *,
        saved: dict[str, Any] | None = None,
        notice: str = "",
    ) -> None:
        def loaded(data: dict[str, Any]) -> None:
            items = data.get("items")
            if not (
                isinstance(items, list)
                and items
                and all(self._case(row) and row["id"] == case_id for row in items)
                and [row["revision"] for row in items] == list(range(1, len(items) + 1))
            ):
                self._error("request_failed")
                return
            chosen = (
                items[-1]
                if revision is None
                else next((row for row in items if row["revision"] == revision), None)
            )
            if chosen is None:
                self._error("complaint_revision_not_found")
                return
            if saved is not None and any(
                chosen[name] != saved[name]
                for name in (
                    "id",
                    "revision_id",
                    "revision",
                    "case_reference",
                    "received_at",
                    "category_id",
                    "category_revision",
                    "description",
                    "work_status",
                    "completed_at",
                    "amendment_reason",
                )
            ):
                self._error("request_failed")
                return
            heads = {row["id"]: row for row in self._state["items"]}
            heads[case_id] = deepcopy(items[-1])
            self._state["items"] = [heads[key] for key in sorted(heads)]
            self._accept(chosen, items, historical=chosen["revision"] != items[-1]["revision"])
            if saved is not None:
                self._state["notice"] = notice

        self._send(self._path(f"/{case_id}/history"), "GET", None, loaded)

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadCase(self, case_id: int, discard: bool = False) -> bool:
        if self._state["busy"] or not self._state["station_id"] or case_id < 0:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_complaint_changes")
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        if case_id:
            self._history(case_id)
        else:
            self._accept({}, [])
            self.stateChanged.emit()
        return True

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def loadRevision(self, revision: int, discard: bool = False) -> bool:
        selected = self._state["selected"]
        if self._state["busy"] or not selected or revision < 1:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_complaint_changes")
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        self._history(selected["id"], revision)
        return True

    def _writable(self) -> bool:
        if self._state["busy"] or not self._state["station_id"] or not self._reviewed:
            return False
        if self._state["role"] != "polling_officer":
            self._error("polling_officer_required")
            return False
        if self._state["context"].get("election", {}).get("status") != "active":
            self._error("active_election_required")
            return False
        if self._state["historical"]:
            self._error("complaint_historical_readonly")
            return False
        return True

    @Slot(str, str)
    def setField(self, name: str, value: str) -> None:
        if name not in self._state["forms"] or not self._writable():
            return
        if name == "category_id":
            selected = self._state["selected"]
            if selected and value == str(selected["category_id"]):
                category = self._frozen_category(selected)
            else:
                category = next(
                    (
                        deepcopy(row)
                        for row in self._state["categories"]
                        if str(row["id"]) == value and row["enabled"]
                    ),
                    {},
                )
            if value and not category:
                self._error("complaint_category_disabled")
                return
            self._state["form_category"] = category
        if self._state["forms"][name] != value or name == "category_id":
            self._state["forms"][name] = value
            self._state.update(dirty=True, error="", notice="")
            self.stateChanged.emit()

    def _time(self, field: str, source: str) -> str:
        value = self._state["forms"][field]
        selected = self._state["selected"]
        if (
            selected
            and selected[source]
            and value == self.formatTime(selected[source]).removesuffix(" HKT")
        ):
            return str(selected[source])
        return datetime.strptime(value.strip(), TIME_FORMAT).replace(tzinfo=HKT).isoformat()

    def _payload(self) -> dict[str, Any] | None:
        form, category = self._state["forms"], self._state["form_category"]
        try:
            category_id = positive_integer(form["category_id"])
            if not category or category_id != category["id"]:
                raise ValueError("Select a category")
            if not form["case_reference"].strip() or len(form["case_reference"]) > 64:
                raise ValueError("Reference required")
            if len(form["description"]) > 4000 or len(form["reason"]) > 1000:
                raise ValueError("Text exceeds supported length")
            if (category["is_other"] or category["description_required"]) and not form[
                "description"
            ].strip():
                self._error("complaint_description_required")
                return None
            if form["work_status"] not in ("in_progress", "completed"):
                raise ValueError("Status required")
            return {
                "case_reference": form["case_reference"],
                "received_at": self._time("received_time", "received_at"),
                "category_id": category_id,
                "expected_category_revision": category["revision"],
                "description": form["description"],
                "work_status": form["work_status"],
                "completed_at": self._time("completed_time", "completed_at")
                if form["work_status"] == "completed"
                else None,
                "reason": form["reason"],
            }
        except ValueError, OverflowError:
            self._error("complaint_validation")
            return None

    def _write(self, action: str) -> None:
        if not self._writable():
            return
        selected = self._state["selected"]
        if bool(selected) != (action != "create"):
            self._error("complaint_validation")
            return
        if action == "amend" and not self._state["forms"]["reason"].strip():
            self._error("complaint_amendment_reason_required")
            return
        payload = self._payload()
        if payload is None:
            return
        if selected:
            payload["expected_revision"] = selected["revision"]
        suffix = (
            ""
            if action == "create"
            else f"/{selected['id']}" + ("/amend" if action == "amend" else "")
        )
        signature = json.dumps(
            {
                "station": self._state["station_id"],
                "action": action,
                "path": suffix,
                "body": payload,
            },
            sort_keys=True,
        )
        retry = self._pending is not None and self._pending[0] == signature
        if action == "edit" and self._state["requires_amendment"] and not retry:
            self._error("complaint_amendment_required")
            return
        if self._pending is None or self._pending[0] != signature:
            self._pending = signature, str(uuid4())
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._case(data) or (selected and data["id"] != selected["id"]):
                self._error("request_failed")
                return
            self._history(
                data["id"],
                data["revision"],
                saved=data,
                notice="complaint_amended" if action == "amend" else "complaint_saved",
            )

        self._send(self._path(suffix), "PUT" if action == "edit" else "POST", payload, saved)

    @Slot()
    def create(self) -> None:
        self._write("create")

    @Slot()
    def edit(self) -> None:
        self._write("edit")

    @Slot()
    def amend(self) -> None:
        self._write("amend")

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(HKT).strftime(TIME_FORMAT) + " HKT" if parsed.tzinfo else "—"
        except ValueError, OverflowError:
            return "—"
