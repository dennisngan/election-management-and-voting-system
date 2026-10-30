"""Read-only completion assessment for the selected real election."""

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest


class ElectionCompletionController(QObject):
    stateChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = request
        self._generation = 0
        self._opened = False
        self._scope: tuple[Any, ...] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._opened = False
        self._scope = None
        self._state = {
            "election_id": None, "actor_id": None, "role": "", "election": {},
            "assessment": {}, "busy": False, "refreshing": False, "error": "",
        }
        self.stateChanged.emit()

    def set_context(
        self, account: dict[str, Any], election: dict[str, Any] | None, origin: str
    ) -> None:
        target = election or {}
        election_id = target.get("id")
        scope = (origin, account.get("id"), election_id, account.get("role", ""))
        changed = scope != self._scope
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._scope = scope
        self._state.update(
            election_id=election_id, actor_id=account.get("id"),
            role=account.get("role", ""), election=deepcopy(target),
        )
        self.stateChanged.emit()
        if changed and self._opened:
            self.refresh()

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        election_id = self._state["election_id"]
        if (
            not self._opened or self._state["busy"] or self._state["refreshing"]
            or self._state["role"] != "supervisor"
            or type(election_id) is not int or election_id <= 0
            or type(self._state["actor_id"]) is not int
        ):
            return
        generation = self._generation
        self._state.update(refreshing=True, error="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, error=code)
            self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if (
                not isinstance(data.get("election"), dict)
                or data["election"].get("id") != election_id
                or type(data.get("can_finalize")) is not bool
                or not isinstance(data.get("blockers"), list)
                or not all(isinstance(row, dict) for row in data["blockers"])
                or not isinstance(data.get("sources"), dict)
            ):
                failed("request_failed")
                return
            self._state.update(assessment=deepcopy(data), refreshing=False, error="")
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion", "GET", None, loaded, failed
        )
