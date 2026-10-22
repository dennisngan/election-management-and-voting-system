"""Draft editor state; server refreshes never replace local form text."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

ResultHandler = Callable[[dict[str, Any]], None]
AuthorizedRequest = Callable[
    [str, str, dict[str, Any] | None, ResultHandler, Callable[[str], None]], None
]
KINDS = ("election", "constituency", "candidate")
LISTS = {"election": "elections", "constituency": "constituencies", "candidate": "candidates"}
FIELDS = {
    "election": ("name",),
    "constituency": ("name", "code"),
    "candidate": ("name", "ballot_number"),
}


class ConfigurationController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._available = False
        self._state: dict[str, Any] = {}
        self._keys: dict[str, str] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._keys = {kind: str(uuid4()) for kind in KINDS}
        self._state = {
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            **{name: [] for name in LISTS.values()},
            "selected": {kind: {} for kind in KINDS},
            "forms": {kind: dict.fromkeys(FIELDS[kind], "") for kind in KINDS},
            "dirty": dict.fromkeys(KINDS, False),
            "editing": dict.fromkeys(KINDS, False),
        }
        self.stateChanged.emit()

    def set_available(self, available: bool) -> None:
        if not available and self._available:
            self.reset()
        self._available = available

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
            if generation == self._generation:
                self._state[activity] = False
                success(data)
                self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._state.update(error=code, notice="")
                self.stateChanged.emit()

        self._request(path, method, payload, done, failed)

    def _path(self, kind: str) -> str:
        path = "/api/elections"
        if kind != "election":
            path += f"/{self._state['selected']['election']['id']}/constituencies"
        if kind == "candidate":
            path += f"/{self._state['selected']['constituency']['id']}/candidates"
        return path

    @Slot()
    def open(self) -> None:
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self._available or self._state["busy"] or self._state["refreshing"]:
            return

        def fetch(index: int) -> None:
            if index >= len(KINDS):
                return
            kind = KINDS[index]
            if index and not self._state["selected"][KINDS[index - 1]]:
                return

            def listed(data: dict[str, Any]) -> None:
                items = data.get("items")
                if not isinstance(items, list) or not all(isinstance(row, dict) for row in items):
                    self._state["error"] = "request_failed"
                    return
                self._state[LISTS[kind]] = items
                fetch(index + 1)

            self._send(self._path(kind), "GET", None, listed, background=True)

        fetch(0)

    def _accept(self, kind: str, row: dict[str, Any], *, clear_children: bool = False) -> None:
        self._state["selected"][kind] = row
        self._state["forms"][kind] = {field: str(row.get(field, "")) for field in FIELDS[kind]}
        self._state["dirty"][kind] = False
        self._state["editing"][kind] = True
        if clear_children:
            for child in KINDS[KINDS.index(kind) + 1 :]:
                self._state["selected"][child] = {}
                self._state["forms"][child] = dict.fromkeys(FIELDS[child], "")
                self._state["dirty"][child] = False
                self._state["editing"][child] = False
                self._state[LISTS[child]] = []
                self._keys[child] = str(uuid4())

    @Slot(str, int, bool, result=bool)
    def load(self, kind: str, row_id: int, discard: bool) -> bool:
        if not self._available or self._state["busy"] or kind not in KINDS:
            return False
        index = KINDS.index(kind)
        if index and not self._state["selected"][KINDS[index - 1]]:
            return False
        if any(self._state["dirty"][child] for child in KINDS[index:]) and not discard:
            return False
        self._generation += 1
        self._state.update(error="", notice="", refreshing=False)
        if row_id == 0:
            self._keys[kind] = str(uuid4())
            self._accept(kind, {}, clear_children=True)
            self.stateChanged.emit()
        else:

            def loaded(data: dict[str, Any]) -> None:
                if not isinstance(data.get("id"), int) or not isinstance(data.get("revision"), int):
                    self._state["error"] = "request_failed"
                    return
                self._accept(kind, data, clear_children=True)
                self.refresh()

            self._send(f"{self._path(kind)}/{row_id}", "GET", None, loaded)
        return True

    @Slot(str, str, str)
    def setField(self, kind: str, field: str, value: str) -> None:
        if (
            not self._available
            or self._state["busy"]
            or kind not in KINDS
            or field not in FIELDS[kind]
            or not self._state["editing"][kind]
        ):
            return
        self._state["forms"][kind][field] = value
        row = self._state["selected"][kind]
        self._state["dirty"][kind] = any(
            self._state["forms"][kind][key] != str(row.get(key, "")) for key in FIELDS[kind]
        )
        self._state.update(error="", notice="")
        self.stateChanged.emit()

    @Slot(str)
    def save(self, kind: str) -> None:
        if (
            not self._available
            or self._state["busy"]
            or kind not in KINDS
            or not self._state["editing"][kind]
        ):
            return
        payload = self._state["forms"][kind].copy()
        valid = bool(payload["name"].strip()) and len(payload["name"]) <= 160
        if kind == "constituency":
            valid = valid and bool(payload["code"].strip()) and len(payload["code"]) <= 32
        if kind == "candidate":
            number = payload["ballot_number"]
            valid = (
                valid
                and len(number) <= 10
                and number.isascii()
                and number.isdecimal()
                and 1 <= int(number) <= 2147483647
            )
            if valid:
                payload["ballot_number"] = int(number)
        if not valid:
            self._state["error"] = "configuration_validation"
            self.stateChanged.emit()
            return
        # A save supersedes any older list snapshots already in flight. Inputs stay
        # editable during list refresh; only the explicit save/load owns `busy`.
        self._generation += 1
        self._state["refreshing"] = False
        row = self._state["selected"][kind]
        path, method = self._path(kind), "POST"
        if row:
            path, method = f"{path}/{row['id']}", "PUT"
            payload["revision"] = row["revision"]
        else:
            payload["request_id"] = self._keys[kind]

        def saved(data: dict[str, Any]) -> None:
            self._accept(kind, data)
            self._state.update(error="", notice="configuration_saved")
            self.refresh()

        self._state.update(error="", notice="")
        self._send(path, method, payload, saved)
