"""Staff administration editor; credentials never enter persistent form state."""

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest, ResultHandler

ROLES = ("administrator", "polling_officer", "counting_officer", "supervisor")


def empty_form() -> dict[str, Any]:
    return {
        "username": "",
        "display_name": "",
        "role": "polling_officer",
        "enabled": True,
        "station_ids": [],
    }


class StaffController(QObject):
    stateChanged = Signal()
    erasePassword = Signal()
    accessChanged = Signal()

    def __init__(self, request: AuthorizedRequest, parent: QObject) -> None:
        super().__init__(parent)
        self._request = request
        self._available = False
        self._opened = False
        self._account_id = 0
        self._generation = 0
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def reset(self) -> None:
        self._generation += 1
        self._available = False
        self._opened = False
        self._account_id = 0
        self._state = {
            "accounts": [],
            "station_options": [],
            "selected": {},
            "form": empty_form(),
            "audit": [],
            "dirty": False,
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            "editing": False,
        }
        self.erasePassword.emit()
        self.stateChanged.emit()

    def set_available(self, available: bool, account_id: int) -> None:
        if not available and self._available:
            self.reset()
        self._available, self._account_id = available, account_id

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
                # refresh() already publishes the accepted state before returning.
                if not self._state["refreshing"]:
                    self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation:
                self._state[activity] = False
                self._state.update(error=code, notice="")
                self.stateChanged.emit()

        self._request(path, method, payload, done, failed)

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if (
            not self._opened
            or not self._available
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return
        requests = [
            ("/api/accounts", "accounts"),
            ("/api/accounts/station-options", "station_options"),
        ]
        if self._state["selected"]:
            requests.append((f"/api/accounts/{self._state['selected']['id']}/audit", "audit"))

        generation = self._generation
        pending = len(requests)
        staged: dict[str, list[Any]] = {}
        error: str | None = None
        self._state["refreshing"] = True
        self.stateChanged.emit()

        def settled() -> None:
            nonlocal pending
            pending -= 1
            if pending:
                return
            # Publish once: intermediate completions must not signal full idle
            # or repeatedly copy the large directories into the Qt view.
            self._state.update(staged, refreshing=False)
            if error is not None:
                self._state.update(error=error, notice="")
            self.stateChanged.emit()

        def listed(key: str) -> ResultHandler:
            def received(data: dict[str, Any]) -> None:
                nonlocal error
                if generation != self._generation:
                    return
                items = data.get("items")
                if isinstance(items, list):
                    staged[key] = items
                else:
                    error = error or "request_failed"
                settled()

            return received

        def failed(code: str) -> None:
            nonlocal error
            if generation != self._generation:
                return
            error = error or code
            settled()

        for path, key in requests:
            if generation != self._generation:
                return
            self._request(path, "GET", None, listed(key), failed)

    def _accept(self, data: dict[str, Any]) -> None:
        self._state["selected"] = data
        self._state["form"] = {
            key: deepcopy(data.get(key, default)) for key, default in empty_form().items()
        }
        self._state.update(dirty=False, editing=True)

    @Slot(int, bool, result=bool)
    def loadAccount(self, account_id: int, discard: bool) -> bool:
        if not self._available or self._state["busy"] or (self._state["dirty"] and not discard):
            return False
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="", audit=[])
        self.erasePassword.emit()
        if account_id == 0:
            self._accept({})
            self.stateChanged.emit()
        else:

            def loaded(data: dict[str, Any]) -> None:
                self._accept(data)
                self.refresh()

            self._send(f"/api/accounts/{account_id}", "GET", None, loaded)
        return True

    def _edited(self) -> None:
        original = {
            key: self._state["selected"].get(key, default) for key, default in empty_form().items()
        }
        self._state["dirty"] = self._state["form"] != original
        self._state.update(error="", notice="")
        self.stateChanged.emit()

    @Slot(str, str)
    def setField(self, field: str, value: str) -> None:
        if not self._available or self._state["busy"] or not self._state["editing"]:
            return
        if field not in ("username", "display_name", "role"):
            return
        if field == "username" and self._state["selected"]:
            return
        if field == "role" and value not in ROLES:
            return
        self._state["form"][field] = value
        if field == "role" and value == "administrator":
            self._state["form"]["station_ids"] = []
        self._edited()

    @Slot(bool)
    def setEnabled(self, enabled: bool) -> None:
        if self._available and not self._state["busy"] and self._state["editing"]:
            self._state["form"]["enabled"] = enabled
            self._edited()

    @Slot(int, bool)
    def setStationAssigned(self, station_id: int, assigned: bool) -> None:
        if (
            not self._available
            or self._state["busy"]
            or not self._state["editing"]
            or self._state["form"]["role"] == "administrator"
            or station_id < 1
        ):
            return
        ids = set(self._state["form"]["station_ids"])
        if assigned:
            ids.add(station_id)
        else:
            ids.discard(station_id)
        self._state["form"]["station_ids"] = sorted(ids)
        self._edited()

    def _password_valid(self, password: str, confirmation: str) -> bool:
        if password != confirmation:
            self._state["error"] = "password_mismatch"
        elif not 12 <= len(password) <= 128:
            self._state["error"] = "min_password"
        else:
            return True
        self.stateChanged.emit()
        return False

    def _saved(self, data: dict[str, Any], notice: str) -> None:
        if data.get("id") == self._account_id:
            self.accessChanged.emit()
            return
        self._accept(data)
        self._state.update(error="", notice=notice)
        self.refresh()

    @Slot(str, str)
    def save(self, password: str, confirmation: str) -> None:
        if not self._available or self._state["busy"] or not self._state["editing"]:
            return
        payload = deepcopy(self._state["form"])
        valid = (
            bool(payload["username"].strip())
            and len(payload["username"].strip()) <= 64
            and bool(payload["display_name"].strip())
            and len(payload["display_name"]) <= 120
        )
        self.erasePassword.emit()
        if not valid:
            self._state["error"] = "staff_validation"
            self.stateChanged.emit()
            return
        selected = self._state["selected"]
        if selected:
            path, method = f"/api/accounts/{selected['id']}", "PUT"
            payload.pop("username")
            payload["revision"] = selected["revision"]
        else:
            if not self._password_valid(password, confirmation):
                return
            path, method = "/api/accounts", "POST"
            payload["temporary_password"] = password
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        self._send(path, method, payload, lambda data: self._saved(data, "staff_saved"))

    @Slot(str, str)
    def resetPassword(self, password: str, confirmation: str) -> None:
        selected = self._state["selected"]
        if not self._available or self._state["busy"] or not selected:
            return
        self.erasePassword.emit()
        if not self._password_valid(password, confirmation):
            return
        if self._state["dirty"]:
            self._state["error"] = "unsaved_staff_changes"
            self.stateChanged.emit()
            return
        self._generation += 1
        self._state.update(refreshing=False, error="", notice="")
        self._send(
            f"/api/accounts/{selected['id']}/password-reset",
            "POST",
            {"temporary_password": password, "revision": selected["revision"]},
            lambda data: self._saved(data, "password_reset_success"),
        )
