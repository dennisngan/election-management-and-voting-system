"""An authenticated staff member's assigned station context."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest


class WorkspaceController(QObject):
    stateChanged = Signal()
    contextChanged = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject,
        *,
        selection_guard: Callable[[], bool] | None = None,
        unresolved_guard: Callable[[], bool] | None = None,
        unresolved_target_guard: Callable[[int, dict[str, Any] | None], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._selection_guard = selection_guard
        self._unresolved_guard = unresolved_guard
        self._unresolved_target_guard = unresolved_target_guard
        self._generation = 0
        self._available = False
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    @Property(bool, notify=stateChanged)
    def selectionGuarded(self) -> bool:
        return bool(self.unresolvedRequest) or bool(
            self._selection_guard and self._selection_guard()
        )

    @Property(bool, notify=stateChanged)
    def unresolvedRequest(self) -> bool:
        return bool(self._unresolved_guard and self._unresolved_guard())

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
    @Slot(int, bool)
    def selectStation(self, station_id: int, discard: bool = False) -> None:
        if not self._available or self._state["busy"]:
            return
        selected_id = self._state["selected"].get("station", {}).get("id")
        unresolved = (
            self._unresolved_target_guard(station_id, None)
            if self._unresolved_target_guard else self.unresolvedRequest
        )
        if station_id != selected_id and unresolved:
            self._state["error"] = "workspace_uncertain_request"
            self.stateChanged.emit()
            return
        if (
            station_id != selected_id and not discard
            and self._selection_guard and self._selection_guard()
        ):
            self._state["error"] = "unsaved_station_changes"
            self.stateChanged.emit()
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
            elif self._unresolved_target_guard and self._unresolved_target_guard(station_id, data):
                self._state["error"] = "workspace_uncertain_request"
            else:
                self._state["selected"] = data
                self.contextChanged.emit()
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state.update(busy=False, error=code)
                self.stateChanged.emit()

        self._request(f"/api/workspace/stations/{station_id}", "GET", None, loaded, failed)
