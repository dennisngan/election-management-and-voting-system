"""Independent schedule editor and shared active-election context."""

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, TypeGuard

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler

HKT = timezone(timedelta(hours=8), "HKT")
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%Y-%m-%d %H:%M"


def empty_forms() -> dict[str, str]:
    return {
        "election_date": "",
        "planned_opening": "",
        "planned_closing": "",
        "reporting_interval_minutes": "60",
    }


def election_row(data: Any) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(data, dict)
        and type(data.get("id")) is int
        and data["id"] > 0
        and type(data.get("revision")) is int
        and data["revision"] > 0
        and isinstance(data.get("name"), str)
        and isinstance(data.get("status"), str)
    )


def schedule_forms(data: dict[str, Any]) -> dict[str, str] | None:
    try:
        opening = datetime.fromisoformat(data["planned_opening_at"])
        closing = datetime.fromisoformat(data["planned_closing_at"])
        election_date = datetime.strptime(data["election_date"], DATE_FORMAT).date()
        if (
            opening.tzinfo is None
            or closing.tzinfo is None
            or type(data["revision"]) is not int
            or data["revision"] < 1
            or type(data["reporting_interval_minutes"]) is not int
            or not 1 <= data["reporting_interval_minutes"] <= 1440
        ):
            return None
    except KeyError, TypeError, ValueError:
        return None
    return {
        "election_date": election_date.strftime(DATE_FORMAT),
        "planned_opening": opening.astimezone(HKT).strftime(TIME_FORMAT),
        "planned_closing": closing.astimezone(HKT).strftime(TIME_FORMAT),
        "reporting_interval_minutes": str(data["reporting_interval_minutes"]),
    }


class LifecycleController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._available = False
        self._state: dict[str, Any] = {}
        self.reset()

    def _read_only(self) -> bool:
        selected = self._state["selected"]
        active = self._state["active_election"] or {}
        return bool(
            selected and (selected["status"] != "draft" or active.get("id") == selected["id"])
        )

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return {**deepcopy(self._state), "read_only": self._read_only()}

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._state = {
            "elections": [],
            "selected": {},
            "schedule": {},
            "forms": empty_forms(),
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            "active_election": None,
        }
        self.stateChanged.emit()

    def set_available(self, available: bool) -> None:
        if not available and self._available:
            self.reset()
        self._available = available

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    def _send(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        *,
        background: bool = False,
        failure: Callable[[str], None] | None = None,
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
            if failure is not None:
                failure(code)
            else:
                self._error("schedule_validation" if code == "validation_error" else code)
            self.stateChanged.emit()

        self._request(path, method, payload, done, failed)

    def _begin_action(self) -> None:
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

    @Slot()
    def open(self) -> None:
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self._available or self._state["busy"] or self._state["refreshing"]:
            return

        def active(data: dict[str, Any]) -> None:
            if "election" not in data or (
                data["election"] is not None and not election_row(data["election"])
            ):
                self._error("request_failed")
                return
            self._state["active_election"] = data["election"]

        def listed(data: dict[str, Any]) -> None:
            items = data.get("items")
            if not isinstance(items, list) or not all(election_row(row) for row in items):
                self._error("request_failed")
                return
            self._state["elections"] = items
            self._send("/api/active-election", "GET", None, active, background=True)

        self._send("/api/elections", "GET", None, listed, background=True)

    def _accept(self, election: dict[str, Any], schedule: dict[str, Any]) -> bool:
        forms = schedule_forms(schedule) if schedule else empty_forms()
        if forms is None or (schedule and schedule.get("election_id") != election["id"]):
            self._error("request_failed")
            return False
        self._state.update(selected=election, schedule=schedule, forms=forms, dirty=False)
        return True

    @Slot(int, bool, result=bool)
    def loadElection(self, election_id: int, discard: bool) -> bool:
        if (
            not self._available
            or self._state["busy"]
            or election_id < 1
            or (self._state["dirty"] and not discard)
        ):
            return False
        self._begin_action()
        path = f"/api/elections/{election_id}"

        def selected(election: dict[str, Any]) -> None:
            if not election_row(election) or election["id"] != election_id:
                self._error("request_failed")
                return

            def loaded(data: dict[str, Any]) -> None:
                if self._accept(election, data):
                    self.refresh()

            def missing(code: str) -> None:
                if code == "schedule_not_configured":
                    self._accept(election, {})
                    self.refresh()
                else:
                    self._error(code)

            self._send(path + "/schedule", "GET", None, loaded, failure=missing)

        self._send(path, "GET", None, selected)
        return True

    @Slot(str, str)
    def setField(self, field: str, value: str) -> None:
        if (
            not self._available
            or self._state["busy"]
            or field not in empty_forms()
            or not self._state["selected"]
            or self._read_only()
        ):
            return
        self._state["forms"][field] = value
        original = (
            schedule_forms(self._state["schedule"]) if self._state["schedule"] else empty_forms()
        )
        self._state["dirty"] = self._state["forms"] != original
        self._state.update(error="", notice="")
        self.stateChanged.emit()

    def _schedule_payload(self) -> dict[str, Any] | None:
        forms = self._state["forms"]
        try:
            election_date = datetime.strptime(forms["election_date"], DATE_FORMAT).date()
            opening = datetime.strptime(forms["planned_opening"], TIME_FORMAT).replace(tzinfo=HKT)
            closing = datetime.strptime(forms["planned_closing"], TIME_FORMAT).replace(tzinfo=HKT)
            interval = forms["reporting_interval_minutes"]
            valid = (
                election_date.strftime(DATE_FORMAT) == forms["election_date"]
                and opening.strftime(TIME_FORMAT) == forms["planned_opening"]
                and closing.strftime(TIME_FORMAT) == forms["planned_closing"]
                and opening.date() == election_date
                and closing > opening
                and len(interval) <= 4
                and interval.isascii()
                and interval.isdecimal()
                and 1 <= int(interval) <= 1440
            )
        except TypeError, ValueError:
            return None
        if not valid:
            return None
        return {
            "election_date": forms["election_date"],
            "planned_opening_at": opening.isoformat(),
            "planned_closing_at": closing.isoformat(),
            "reporting_interval_minutes": int(interval),
            "revision": self._state["schedule"].get("revision", 0),
        }

    @Slot()
    def save(self) -> None:
        if not self._available or self._state["busy"] or not self._state["selected"]:
            return
        if self._read_only():
            self._error("draft_required")
            return
        payload = self._schedule_payload()
        if payload is None:
            self._error("schedule_validation")
            return
        self._begin_action()

        def saved(data: dict[str, Any]) -> None:
            if self._accept(self._state["selected"], data):
                self._state.update(error="", notice="schedule_saved")
                self.refresh()

        self._send(
            f"/api/elections/{self._state['selected']['id']}/schedule", "PUT", payload, saved
        )

    @Slot()
    def activate(self) -> None:
        if not self._available or self._state["busy"] or not self._state["selected"]:
            return
        if self._read_only():
            self._error("draft_required")
            return
        if self._state["dirty"]:
            self._error("unsaved_schedule")
            return
        if not self._state["schedule"]:
            self._error("schedule_required")
            return
        self._begin_action()

        def activated(data: dict[str, Any]) -> None:
            active = data.get("election")
            if not election_row(active) or not isinstance(active.get("schedule"), dict):
                self._error("request_failed")
                return
            if self._accept(
                {key: value for key, value in active.items() if key != "schedule"},
                active["schedule"],
            ):
                self._state.update(active_election=active, error="", notice="election_activated")
                self.refresh()

        self._send(
            f"/api/elections/{self._state['selected']['id']}/activate",
            "POST",
            {
                "election_revision": self._state["selected"]["revision"],
                "schedule_revision": self._state["schedule"]["revision"],
            },
            activated,
        )
