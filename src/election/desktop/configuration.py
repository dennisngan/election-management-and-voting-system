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
PARENTS = {
    "election": None,
    "constituency": "election",
    "candidate": "constituency",
    "station": "constituency",
    "counter": "station",
}
KINDS = tuple(PARENTS)
LISTS = {
    "election": "elections",
    "constituency": "constituencies",
    "candidate": "candidates",
    "station": "stations",
    "counter": "counters",
}
FIELDS = {
    "election": ("name",),
    "constituency": ("name", "code"),
    "candidate": ("name", "ballot_number"),
    "station": ("name", "code", "counting_mode", "destination_station_id"),
    "counter": ("name", "code"),
}


def empty_form(kind: str) -> dict[str, str]:
    result = dict.fromkeys(FIELDS[kind], "")
    if kind == "station":
        result["counting_mode"] = "local"
    return result


def positive_integer(value: str) -> int | None:
    if not (1 <= len(value) <= 10 and value.isascii() and value.isdecimal()):
        return None
    number = int(value)
    return number if 1 <= number <= 2147483647 else None


def affected_forms(kind: str) -> tuple[str, ...]:
    affected = []
    for child in KINDS:
        ancestor: str | None = child
        while ancestor is not None:
            if ancestor == kind:
                affected.append(child)
                break
            ancestor = PARENTS[ancestor]
    return tuple(affected)


class ConfigurationController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._available = False
        self._state: dict[str, Any] = {}
        self._keys: dict[str, str] = {}
        self._live_election: dict[str, Any] | None = None
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        state = deepcopy(self._state)
        current = self._current_election()
        selected = state["selected"]["election"]
        state["election_status"] = current.get("status", "draft")
        state["read_only"] = self._read_only()
        state["newer_revision"] = bool(
            selected and current.get("revision") != selected.get("revision")
        )
        return state

    def _current_election(self) -> dict[str, Any]:
        selected: dict[str, Any] = self._state["selected"]["election"]
        if not selected:
            return {}
        if self._live_election and self._live_election.get("id") == selected["id"]:
            return self._live_election
        return next(
            (row for row in self._state["elections"] if row.get("id") == selected["id"]), selected
        )

    def _read_only(self) -> bool:
        return bool(
            self._state["selected"]["election"]
            and self._current_election().get("status") != "draft"
        )

    def sync_active_election(self, election: dict[str, Any] | None) -> None:
        if self._live_election != election:
            self._live_election = deepcopy(election)
            self.stateChanged.emit()

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._live_election = None
        self._keys = {kind: str(uuid4()) for kind in KINDS}
        self._state = {
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            **{name: [] for name in LISTS.values()},
            "selected": {kind: {} for kind in KINDS},
            "forms": {kind: empty_form(kind) for kind in KINDS},
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
        segments = []
        current: str | None = kind
        while current is not None:
            segments.append(LISTS[current])
            parent = PARENTS[current]
            if parent is not None:
                segments.append(str(self._state["selected"][parent]["id"]))
            current = parent
        return "/api/" + "/".join(reversed(segments))

    @Slot()
    def open(self) -> None:
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self._available or self._state["busy"] or self._state["refreshing"]:
            return
        kinds = [
            kind
            for kind in KINDS
            if PARENTS[kind] is None or self._state["selected"][PARENTS[kind]]
        ]

        def fetch(index: int) -> None:
            if index >= len(kinds):
                return
            kind = kinds[index]

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
        self._state["forms"][kind] = {
            field: str(row[field]) if row.get(field) is not None else default
            for field, default in empty_form(kind).items()
        }
        self._state["dirty"][kind] = False
        self._state["editing"][kind] = True
        if clear_children:
            for child in affected_forms(kind)[1:]:
                self._state["selected"][child] = {}
                self._state["forms"][child] = empty_form(child)
                self._state["dirty"][child] = False
                self._state["editing"][child] = False
                self._state[LISTS[child]] = []
                self._keys[child] = str(uuid4())

    @Slot(str, int, bool, result=bool)
    def load(self, kind: str, row_id: int, discard: bool) -> bool:
        if not self._available or self._state["busy"] or kind not in KINDS:
            return False
        if kind != "election" and row_id == 0 and self._read_only():
            self._state["error"] = "read_only_election"
            self.stateChanged.emit()
            return False
        parent = PARENTS[kind]
        if parent is not None and not self._state["selected"][parent]:
            return False
        if any(self._state["dirty"][child] for child in affected_forms(kind)) and not discard:
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
            or self._read_only()
        ):
            return
        self._state["forms"][kind][field] = value
        if kind == "station" and field == "counting_mode" and value == "local":
            self._state["forms"][kind]["destination_station_id"] = ""
        row = self._state["selected"][kind]
        self._state["dirty"][kind] = any(
            self._state["forms"][kind][key]
            != (str(row[key]) if row.get(key) is not None else default)
            for key, default in empty_form(kind).items()
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
        if self._read_only():
            self._state["error"] = "read_only_election"
            self.stateChanged.emit()
            return
        payload = self._state["forms"][kind].copy()
        valid = bool(payload["name"].strip()) and len(payload["name"]) <= 160
        if kind in ("constituency", "station", "counter"):
            valid = valid and bool(payload["code"].strip()) and len(payload["code"]) <= 32
        if kind == "candidate":
            number = positive_integer(payload["ballot_number"])
            valid = valid and number is not None
            if number is not None:
                payload["ballot_number"] = number
        if kind == "station":
            mode, destination = payload["counting_mode"], payload["destination_station_id"]
            if mode == "local":
                payload["destination_station_id"] = None
            elif mode == "send":
                destination_id = positive_integer(destination)
                valid = valid and destination_id is not None
                if destination_id is not None:
                    payload["destination_station_id"] = destination_id
            else:
                valid = False
        if not valid:
            self._state["error"] = (
                "station_configuration_validation"
                if kind in ("station", "counter")
                else "configuration_validation"
            )
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
