"""An authenticated staff member's assigned station context."""

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest


class WorkspaceController(QObject):
    stateChanged = Signal()
    contextChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._available = False
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._state = {
            "contexts": [],
            "selected": {},
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
        }
        self.contextChanged.emit()
        self.stateChanged.emit()

    def set_available(self, available: bool) -> None:
        if not available and self._available:
            self.reset()
        self._available = available

    @staticmethod
    def _valid_context(data: dict[str, Any]) -> bool:
        return (
            all(
                isinstance(data.get(key), dict)
                for key in ("election", "constituency", "station", "account", "capabilities")
            )
            and type(data["station"].get("id")) is int
        )

    @Slot()
    def open(self) -> None:
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self._available or self._state["busy"] or self._state["refreshing"]:
            return
        generation = self._generation
        self._state["refreshing"] = True
        self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state["refreshing"] = False
            contexts = data.get("items")
            if not isinstance(contexts, list) or not all(
                isinstance(row, dict) and self._valid_context(row) for row in contexts
            ):
                self._state["error"] = "request_failed"
            else:
                self._state["contexts"] = contexts
                selected_id = self._state["selected"].get("station", {}).get("id")
                selected: dict[str, Any] = next(
                    (row for row in contexts if row["station"]["id"] == selected_id), {}
                )
                if not selected and len(contexts) == 1:
                    selected = contexts[0]
                self._state["selected"] = selected
                self.contextChanged.emit()
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state.update(refreshing=False, error=code)
                self.stateChanged.emit()

        self._request("/api/workspace/stations", "GET", None, loaded, failed)

    @Slot(int)
    def selectStation(self, station_id: int) -> None:
        if not self._available or self._state["busy"]:
            return
        self._generation += 1
        generation = self._generation
        self._state.update(busy=True, refreshing=False, error="", notice="")
        self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state["busy"] = False
            if not self._valid_context(data) or data["station"]["id"] != station_id:
                self._state["error"] = "request_failed"
            else:
                self._state["selected"] = data
                self.contextChanged.emit()
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state.update(busy=False, error=code)
                self.stateChanged.emit()

        self._request(f"/api/workspace/stations/{station_id}", "GET", None, loaded, failed)
