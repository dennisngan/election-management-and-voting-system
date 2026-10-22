"""Shared setup actions through public Qt controller slots and real HTTPS."""

from typing import Any

from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.desktop_support import PERSONAL_PASSWORD, HttpsServer, sign_in, state_of, wait_for


def setup_idle(setup: Any) -> bool:
    state = setup.property("state")
    return not state["busy"] and not state.get("refreshing", False)


def ready_setup(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> Any:
    sign_in(desktop, https_server, account, qt_app)
    desktop.changePassword(account["password"], PERSONAL_PASSWORD, PERSONAL_PASSWORD)
    wait_for(qt_app, lambda: state_of(desktop)["phase"] == "workspace")
    setup = desktop.property("configuration")
    assert setup is not None
    return setup


def save_form(setup: Any, qt_app: QCoreApplication, kind: str, values: dict[str, str]) -> dict:
    assert setup.load(kind, 0, False)
    for field, value in values.items():
        setup.setField(kind, field, value)
    setup.save(kind)
    wait_for(qt_app, lambda: setup_idle(setup))
    assert setup.property("state")["error"] == ""
    return setup.property("state")["selected"][kind]
