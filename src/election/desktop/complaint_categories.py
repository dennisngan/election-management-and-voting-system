"""Administrator category editor with reviewed revisions and live catalog refresh."""

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest


def empty_form() -> dict[str, Any]:
    return {
        "code": "",
        "label_tc": "",
        "label_sc": "",
        "label_en": "",
        "enabled": True,
        "description_required": False,
    }


class ComplaintCategoriesController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
        self._available = False
        self._opened = False
        self._generation = 0
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._opened = False
        self._pending = None
        self._state = {
            "elections": [],
            "election_id": 0,
            "election": {},
            "items": [],
            "selected": {},
            "form": empty_form(),
            "editing": False,
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "error": "",
            "notice": "",
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
        success: Callable[[dict[str, Any]], object],
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

        self._request(path, method, payload, done, failed)

    def _path(self) -> str:
        return f"/api/elections/{self._state['election_id']}/complaint-categories"

    def _valid_row(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("election_id") == self._state["election_id"]
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and all(
                isinstance(row.get(key), str)
                for key in ("code", "label_tc", "label_sc", "label_en")
            )
            and all(
                type(row.get(key)) is bool
                for key in ("enabled", "description_required", "is_other", "verified_source")
            )
        )

    def _list(self, data: dict[str, Any], *, saved: dict[str, Any] | None = None) -> bool:
        rows = data.get("items")
        if not isinstance(rows, list) or not all(self._valid_row(row) for row in rows):
            self._error("request_failed")
            return False
        if saved is not None:
            latest = next((row for row in rows if row["id"] == saved["id"]), None)
            known_ids = {row["id"] for row in self._state["items"]}
            # Categories are retained, including disabled entries. An incomplete
            # readback must not replace the catalogue or acknowledge the command.
            if (
                not known_ids.issubset({row["id"] for row in rows})
                or latest is None
                or latest["revision"] < saved["revision"]
            ):
                self._error("request_failed")
                return False
        self._state["items"] = rows
        selected = self._state["selected"]
        latest = next((row for row in rows if row["id"] == selected.get("id")), None)
        self._state["newer_revision"] = bool(selected and latest != selected)
        return True

    def _accept(self, row: dict[str, Any]) -> None:
        self._state.update(
            selected=deepcopy(row),
            form={key: row.get(key, default) for key, default in empty_form().items()},
            editing=True,
            dirty=False,
            newer_revision=False,
        )

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if (
            not self._available
            or not self._opened
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return

        def elections(data: dict[str, Any]) -> None:
            rows = data.get("items")
            if not isinstance(rows, list) or not all(
                isinstance(row, dict)
                and type(row.get("id")) is int
                and isinstance(row.get("name"), str)
                and row.get("status") in ("draft", "active", "finalized")
                for row in rows
            ):
                self._error("request_failed")
                return
            self._state["elections"] = rows
            if self._state["election_id"]:
                current = next(
                    (row for row in rows if row["id"] == self._state["election_id"]), None
                )
                if current is None:
                    self._error("configuration_not_found")
                    return
                self._state["election"] = current
                self._send(self._path(), "GET", None, self._list, background=True)

        self._send("/api/elections", "GET", None, elections, background=True)

    def _can_load(self, discard: bool) -> bool:
        if not self._available or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_complaint_category_changes")
            return False
        self._generation += 1
        self._pending = None
        self._state.update(refreshing=False, error="", notice="")
        return True

    @Slot(int, bool, result=bool)
    def selectElection(self, election_id: int, discard: bool) -> bool:
        election = next((row for row in self._state["elections"] if row["id"] == election_id), None)
        if not election or not self._can_load(discard):
            return False
        self._state.update(
            election_id=election_id,
            election=deepcopy(election),
            items=[],
            selected={},
            form=empty_form(),
            editing=False,
            dirty=False,
            newer_revision=False,
        )
        self._send(self._path(), "GET", None, self._list)
        return True

    @Slot(int, bool, result=bool)
    def loadCategory(self, category_id: int, discard: bool) -> bool:
        row = next((item for item in self._state["items"] if item["id"] == category_id), None)
        if not self._state["election_id"] or (category_id and row is None):
            return False
        if not self._can_load(discard):
            return False
        self._accept(row or {})
        self.stateChanged.emit()
        return True

    @Slot(bool, result=bool)
    def reload(self, discard: bool) -> bool:
        if not self._state["election_id"] or not self._can_load(discard):
            return False
        category_id = self._state["selected"].get("id")

        def loaded(data: dict[str, Any]) -> None:
            if self._list(data):
                row: dict[str, Any] = next(
                    (item for item in self._state["items"] if item["id"] == category_id), {}
                )
                self._accept(row)

        self._send(self._path(), "GET", None, loaded)
        return True

    def _editable(self) -> bool:
        return bool(
            self._available
            and self._state["editing"]
            and not self._state["busy"]
            and self._state["election"].get("status") != "finalized"
        )

    def _edited(self) -> None:
        original = {
            key: self._state["selected"].get(key, default) for key, default in empty_form().items()
        }
        self._state.update(dirty=self._state["form"] != original, error="", notice="")
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, key: str, value: str) -> None:
        if not self._editable() or key not in ("code", "label_tc", "label_sc", "label_en"):
            return
        if key == "code" and self._state["selected"]:
            return
        self._state["form"][key] = value
        self._edited()

    @Slot(bool)
    def setEnabled(self, value: bool) -> None:
        if self._editable():
            self._state["form"]["enabled"] = value
            self._edited()

    @Slot(bool)
    def setDescriptionRequired(self, value: bool) -> None:
        if self._editable():
            self._state["form"]["description_required"] = value
            self._edited()

    @Slot()
    def save(self) -> None:
        if not self._editable() or not self._state["dirty"]:
            return
        form, selected = self._state["form"], self._state["selected"]
        if any(
            not form[key].strip() or len(form[key]) > maximum
            for key, maximum in (
                ("code", 64),
                ("label_tc", 255),
                ("label_sc", 255),
                ("label_en", 255),
            )
        ):
            self._error("complaint_category_validation")
            return
        if selected.get("is_other") and (not form["enabled"] or not form["description_required"]):
            self._error("complaint_other_required")
            return
        payload = deepcopy(form)
        path, method = self._path(), "POST"
        if selected:
            payload.pop("code")
            payload["expected_revision"] = selected["revision"]
            path += f"/{selected['id']}"
            method = "PUT"
        signature = json.dumps([path, method, payload], sort_keys=True)
        if self._pending is None or self._pending[0] != signature:
            self._pending = (signature, str(uuid4()))
        payload["request_id"] = self._pending[1]
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")

        def saved(data: dict[str, Any]) -> None:
            if not self._valid_row(data) or data["revision"] != selected.get("revision", 0) + 1:
                self._error("request_failed")
                return
            if selected and data["id"] != selected["id"]:
                self._error("request_failed")
                return

            def reviewed(snapshot: dict[str, Any]) -> None:
                if not self._list(snapshot, saved=data):
                    return
                latest = next(row for row in self._state["items"] if row["id"] == data["id"])
                self._accept(data)
                self._state.update(
                    newer_revision=latest != data, notice="complaint_category_saved", error=""
                )
                self._pending = None

            self._send(self._path(), "GET", None, reviewed)

        self._send(path, method, payload, saved)
