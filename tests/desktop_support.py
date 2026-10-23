"""Shared public-state helpers for real HTTPS/MySQL desktop tests."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController

INITIAL_PASSWORD = "Initial-Desktop-Password-42!"
PERSONAL_PASSWORD = "Personal-Desktop-Password-84!"
TLS_DIRECTORY = Path(".runtime/tls").resolve()


@dataclass
class ControlledClock:
    value: datetime = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


@dataclass
class HttpsServer:
    url: str
    clock: ControlledClock
    requests: list[tuple[str, str]] = field(default_factory=list)
    # ASGI middleware timings stop at response-header readiness, before transport completion.
    request_timings: list[dict[str, str | int | float]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    hold_profile: bool = False
    hold_password_response: bool = False
    hold_configuration_list: bool = False
    truncate_next_report: bool = False
    truncate_next_allocation_write: bool = False
    hold_allocation_list: bool = False
    allocation_list_entered: threading.Event = field(default_factory=threading.Event)
    release_allocation_list: threading.Event = field(default_factory=threading.Event)
    configuration_list_entered: threading.Event = field(default_factory=threading.Event)
    release_configuration_list: threading.Event = field(default_factory=threading.Event)
    profile_entered: threading.Event = field(default_factory=threading.Event)
    release_profile: threading.Event = field(default_factory=threading.Event)
    profile_finished: threading.Event = field(default_factory=threading.Event)
    password_committed: threading.Event = field(default_factory=threading.Event)
    release_password_response: threading.Event = field(default_factory=threading.Event)
    delayed_profile_status: int | None = None

    def request_count(self, method: str, path: str) -> int:
        with self.lock:
            return self.requests.count((method, path))


def wait_for(app: QCoreApplication, predicate: Callable[[], bool], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if predicate():
            return
        if time.monotonic() >= deadline:
            pytest.fail(
                f"Desktop public state did not reach the expected outcome in {timeout} seconds"
            )
        time.sleep(0.01)


def wait_for_editor_idle(app: QCoreApplication, editor: Any, timeout: float = 5) -> None:
    """Observe full-idle completion even if a later refresh starts in the same event batch."""
    completed = False

    def observe() -> None:
        nonlocal completed
        # The public Python Qt property avoids a second QVariant conversion of large directories.
        state = editor.state
        if not state["busy"] and not state.get("refreshing", False):
            completed = True

    editor.stateChanged.connect(observe)
    try:
        observe()
        wait_for(app, lambda: completed, timeout)
    finally:
        editor.stateChanged.disconnect(observe)


def state_of(controller: DesktopController) -> dict[str, Any]:
    """Qt Property descriptors lack a precise instance-return type in the PySide stubs."""
    return cast("dict[str, Any]", controller.property("state"))


def texts_of(controller: DesktopController) -> dict[str, str]:
    return cast("dict[str, str]", controller.property("texts"))


def sign_in(
    controller: DesktopController,
    server: HttpsServer,
    account: dict[str, str],
    app: QCoreApplication,
) -> None:
    controller.signIn(server.url, account["username"], account["password"])
    wait_for(app, lambda: state_of(controller)["phase"] == "password_change")
    assert state_of(controller)["account"]["username"] == account["username"]
    assert state_of(controller)["busy"] is False
