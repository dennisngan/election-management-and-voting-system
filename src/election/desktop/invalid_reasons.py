"""Administrator editor for the revisioned F1 and F2 invalid-reason catalogues."""

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
        "explanation_required": False,
    }


class InvalidReasonsController(QObject):
    """Edit stage-specific reason labels while preserving verified provenance."""

    stateChanged = Signal()
    electionsChanged = Signal()

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

    @Property(dict, notify=stateChanged)
    def viewState(self) -> dict[str, Any]:
        return deepcopy({key: value for key, value in self._state.items() if key != "elections"})

    @Property(list, notify=electionsChanged)
    def elections(self) -> list[dict[str, Any]]:
        return deepcopy(self._state["elections"])

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._opened = False
        self._pending = None
        self._state = {
            "elections": [],
            "election_id": 0,
            "election": {},
            "stage": "f1",
            "items": [],
            "selected": {},
            "history": [],
            "historical": False,
            "form": empty_form(),
            "editing": False,
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "newer_revision": False,
            "error": "",
            "notice": "",
        }
        self.electionsChanged.emit()
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
        return f"/api/elections/{self._state['election_id']}/invalid-ballot-reasons"

    def _catalog_path(self) -> str:
        return f"{self._path()}?stage={self._state['stage']}"

    def _valid_row(self, row: Any) -> bool:
        return bool(
            isinstance(row, dict)
            and row.get("election_id") == self._state["election_id"]
            and type(row.get("id")) is int
            and row["id"] > 0
            and type(row.get("revision")) is int
            and row["revision"] > 0
            and row.get("stage") == self._state["stage"]
            and all(
                isinstance(row.get(key), str)
                for key in ("code", "label_tc", "label_sc", "label_en", "source_english")
            )
            and all(
                type(row.get(key)) is bool
                for key in ("enabled", "explanation_required", "is_other", "verified_source")
            )
            and (row.get("source_letter") is None or isinstance(row.get("source_letter"), str))
            and (row.get("reference_page") is None or type(row.get("reference_page")) is int)
            and (
                row.get("reference_printed_page") is None
                or type(row.get("reference_printed_page")) is int
            )
            and row.get("translation_provenance") == "project_translation"
        )

    def _accept_catalog(
        self, data: dict[str, Any], *, saved: dict[str, Any] | None = None
    ) -> bool:
        rows = data.get("items")
        if not isinstance(rows, list) or not all(self._valid_row(row) for row in rows):
            self._error("request_failed")
            return False
        if saved is not None:
            latest = next((row for row in rows if row["id"] == saved["id"]), None)
            known_ids = {row["id"] for row in self._state["items"]}
            if (
                not known_ids.issubset({row["id"] for row in rows})
                or latest is None
                or latest["revision"] < saved["revision"]
            ):
                self._error("request_failed")
                return False
        self._state["items"] = deepcopy(rows)
        selected = self._state["selected"]
        latest = next((row for row in rows if row["id"] == selected.get("id")), None)
        self._state["newer_revision"] = bool(
            selected and not self._state["historical"] and latest != selected
        )
        if selected and self._state["historical"]:
            self._refresh_historical_history(selected["id"], selected["revision"])
        return True

    def _refresh_historical_history(self, reason_id: int, revision: int) -> None:
        generation = self._generation

        def still_selected() -> bool:
            selected = self._state["selected"]
            return bool(
                generation == self._generation
                and self._state["historical"]
                and selected.get("id") == reason_id
                and selected.get("revision") == revision
            )

        def loaded(data: dict[str, Any]) -> None:
            if not still_selected():
                return
            row, history = data.get("record"), data.get("history")
            if (
                not isinstance(row, dict)
                or not self._valid_row(row)
                or row.get("id") != reason_id
                or not isinstance(history, list)
                or not all(
                    isinstance(entry, dict)
                    and self._valid_row(entry)
                    and entry.get("id") == reason_id
                    for entry in history
                )
                or not any(entry["revision"] == revision for entry in history)
            ):
                self._error("request_failed")
                return
            catalog_head = next(
                (item for item in self._state["items"] if item["id"] == reason_id), None
            )
            if catalog_head is not None and row["revision"] < catalog_head["revision"]:
                self._send(
                    f"{self._path()}/{reason_id}", "GET", None, loaded, background=True
                )
                return
            self._state["history"] = deepcopy(history)
            self._state["historical"] = revision != row["revision"]
            self._state["newer_revision"] = False
            if catalog_head is None or row["revision"] > catalog_head["revision"]:
                self._state["items"] = [
                    row if item["id"] == reason_id else item for item in self._state["items"]
                ]

        self._send(
            f"{self._path()}/{reason_id}", "GET", None, loaded, background=True
        )

    def _accept(self, row: dict[str, Any], *, historical: bool = False) -> None:
        self._state.update(
            selected=deepcopy(row),
            form={key: row.get(key, default) for key, default in empty_form().items()},
            editing=True,
            historical=historical,
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
            if rows != self._state["elections"]:
                self._state["elections"] = deepcopy(rows)
                self.electionsChanged.emit()
            if self._state["election_id"]:
                current = next(
                    (row for row in rows if row["id"] == self._state["election_id"]), None
                )
                if current is None:
                    self._error("configuration_not_found")
                    return
                self._state["election"] = deepcopy(current)
                self._send(self._catalog_path(), "GET", None, self._accept_catalog, background=True)

        self._send("/api/elections", "GET", None, elections, background=True)

    def _can_load(self, discard: bool) -> bool:
        if not self._available or self._state["busy"]:
            return False
        if self._state["dirty"] and not discard:
            self._error("unsaved_invalid_reason_changes")
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
            history=[],
            historical=False,
            form=empty_form(),
            editing=False,
            dirty=False,
            newer_revision=False,
        )
        self._send(self._catalog_path(), "GET", None, self._accept_catalog)
        return True

    @Slot(str, bool, result=bool)
    def selectStage(self, stage: str, discard: bool) -> bool:
        if (
            stage not in ("f1", "f2")
            or stage == self._state["stage"]
            or not self._state["election_id"]
            or not self._can_load(discard)
        ):
            return False
        self._state.update(
            stage=stage,
            items=[],
            selected={},
            history=[],
            historical=False,
            form=empty_form(),
            editing=False,
            dirty=False,
            newer_revision=False,
        )
        self._send(self._catalog_path(), "GET", None, self._accept_catalog)
        return True

    @Slot(int, bool, result=bool)
    def loadReason(self, reason_id: int, discard: bool) -> bool:
        item = next((row for row in self._state["items"] if row["id"] == reason_id), None)
        if not self._state["election_id"] or (reason_id and item is None):
            return False
        if not self._can_load(discard):
            return False
        if not reason_id:
            self._state.update(
                selected={}, history=[], historical=False, form=empty_form(), editing=True,
                dirty=False, newer_revision=False,
            )
            self.stateChanged.emit()
            return True
        self._state.update(selected=deepcopy(item), history=[deepcopy(item)], historical=False)

        def loaded(data: dict[str, Any]) -> None:
            row, history = data.get("record"), data.get("history")
            if (
                not isinstance(row, dict)
                or not self._valid_row(row)
                or row.get("id") != reason_id
                or not isinstance(history, list)
                or not all(self._valid_row(entry) for entry in history)
                or any(entry.get("id") != reason_id for entry in history)
            ):
                self._error("request_failed")
                return
            self._state["history"] = deepcopy(history)
            self._accept(row)

        self._send(f"{self._path()}/{reason_id}", "GET", None, loaded)
        return True

    @Slot(int)
    def loadRevision(self, revision: int) -> None:
        if self._state["busy"] or self._state["dirty"] or self._state["newer_revision"]:
            if self._state["dirty"] or self._state["newer_revision"]:
                self._error(
                    "revision_conflict" if self._state["newer_revision"]
                    else "unsaved_invalid_reason_changes"
                )
            return
        row = next((item for item in self._state["history"] if item["revision"] == revision), None)
        if row is None:
            return
        latest_revision = max((item["revision"] for item in self._state["history"]), default=0)
        self._accept(row, historical=revision != latest_revision)
        self.stateChanged.emit()

    @Slot(bool, result=bool)
    def reload(self, discard: bool) -> bool:
        if not self._state["election_id"] or not self._can_load(discard):
            return False
        reason_id = self._state["selected"].get("id")

        def loaded(data: dict[str, Any]) -> None:
            if not self._accept_catalog(data):
                return
            if reason_id:
                self.loadReason(reason_id, True)
            else:
                self._state.update(
                    selected={}, history=[], historical=False, form=empty_form(), editing=True,
                    dirty=False, newer_revision=False,
                )

        self._send(self._catalog_path(), "GET", None, loaded)
        return True

    def _editable(self) -> bool:
        return bool(
            self._available
            and self._state["editing"]
            and not self._state["busy"]
            and not self._state["historical"]
            and not self._state["newer_revision"]
            and self._state["election"].get("status") != "finalized"
        )

    def _edited(self) -> None:
        original = {
            key: self._state["selected"].get(key, default)
            for key, default in empty_form().items()
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
        if self._editable() and not self._state["selected"].get("is_other"):
            self._state["form"]["enabled"] = value
            self._edited()

    @Slot(bool)
    def setExplanationRequired(self, value: bool) -> None:
        if self._editable() and not self._state["selected"].get("is_other"):
            self._state["form"]["explanation_required"] = value
            self._edited()

    @Slot()
    def newReason(self) -> None:
        if not self._state["election_id"] or self._state["election"].get("status") == "finalized":
            return
        if not self._can_load(False):
            return
        self._state.update(
            selected={}, history=[], historical=False, form=empty_form(), editing=True,
            dirty=False, newer_revision=False,
        )
        self.stateChanged.emit()

    @Slot()
    def save(self) -> None:
        if not self._editable() or not self._state["dirty"]:
            return
        form, selected = self._state["form"], self._state["selected"]
        if any(
            not form[key].strip() or len(form[key]) > maximum
            for key, maximum in (
                ("code", 64),
                ("label_tc", 512),
                ("label_sc", 512),
                ("label_en", 512),
            )
        ):
            self._error("invalid_reason_validation")
            return
        if selected.get("is_other") and (not form["enabled"] or not form["explanation_required"]):
            self._error("invalid_reason_other_required")
            return
        payload = deepcopy(form)
        path, method = self._path(), "POST"
        if selected:
            payload.pop("code")
            payload["expected_revision"] = selected["revision"]
            path += f"/{selected['id']}"
            method = "PUT"
        else:
            payload["stage"] = self._state["stage"]
        signature = json.dumps([path, method, payload], sort_keys=True, ensure_ascii=False)
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
                if not self._accept_catalog(snapshot, saved=data):
                    return
                latest = next(row for row in self._state["items"] if row["id"] == data["id"])
                self._accept(data)
                self._state.update(
                    history=[deepcopy(data)],
                    newer_revision=latest != data,
                    notice="invalid_reason_saved",
                    error="",
                )
                self._pending = None
                self._send(
                    f"{self._path()}/{data['id']}",
                    "GET",
                    None,
                    self._accept_history_after_save,
                    background=True,
                )

            self._send(self._catalog_path(), "GET", None, reviewed)

        self._send(path, method, payload, saved)

    def _accept_history_after_save(self, data: dict[str, Any]) -> None:
        row, history = data.get("record"), data.get("history")
        if (
            not isinstance(row, dict)
            or not self._valid_row(row)
            or row.get("id") != self._state["selected"].get("id")
            or not isinstance(history, list)
            or not all(self._valid_row(entry) for entry in history)
        ):
            self._error("request_failed")
            return
        self._state["history"] = deepcopy(history)
        latest = next((item for item in history if item["revision"] == row["revision"]), row)
        self._state["newer_revision"] = bool(
            not self._state["historical"] and latest != self._state["selected"]
        )
        self.stateChanged.emit()
