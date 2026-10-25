"""Round-owned timeline occurrences through public Qt and real HTTPS/MySQL."""

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import JSONResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.box_support import READY_PASSWORD
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_boxes_desktop import boxes_editor


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@dataclass
class RoundEventServer(HttpsServer):
    malform_next: str = ""


@pytest.fixture
def timeline_server(database_url: str, qt_app: QCoreApplication) -> Iterator[RoundEventServer]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 8476))
    endpoint = RoundEventServer("https://localhost:8476", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def envelope_boundary(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        assert isinstance(response, Response)
        if (
            endpoint.malform_next
            and request.method == "GET"
            and request.url.path.endswith("/boxes")
            and response.status_code == 200
        ):
            payload = json.loads(
                b"".join([part async for part in getattr(response, "body_iterator")])
            )
            kind, endpoint.malform_next = endpoint.malform_next, ""
            event = payload["count_events"][0]
            if kind == "missing_selection":
                del event["selection_revision"]
            elif kind == "foreign_station":
                event["station_id"] += 1
            elif kind == "boolean_id":
                event["actor_id"] = True
            elif kind == "duplicate":
                payload["count_events"].append(dict(event))
            else:
                event[kind] = "2026-11-15 23:18"  # Invalid: no offset, although ISO parses it.
            return JSONResponse(payload)
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=8476,
            ssl_certfile=str(TLS_DIRECTORY / "server.pem"),
            ssl_keyfile=str(TLS_DIRECTORY / "server-key.pem"),
            loop="asyncio",
            ws="none",
            lifespan="on",
            log_level="warning",
            access_log=False,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        wait_for(qt_app, lambda: server.started)
        yield endpoint
    finally:
        server.should_exit = True
        wait_for(qt_app, lambda: not thread.is_alive())
        thread.join(timeout=0)
        listener.close()


def save_determination(setup: dict[str, Any]) -> tuple[dict[str, Any], str]:
    api, path = setup["counter"], setup["rounds_path"]
    options = api.get(path).json()
    f1 = complete_f1_command(options, questionable_quantity=3, actual_counted_quantity=5)
    f1["candidate_votes"][0]["quantity"] = 2
    created = api.post(path, json=f1)
    assert created.status_code == 201, created.text
    target = path + f"/{created.json()['id']}"
    command = complete_f2_command(
        options, determination_started_at="2026-11-15T23:18:12.123456+08:00"
    )
    command["accepted_votes"][0]["quantity"] = 2
    reason = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
    next(row for row in command["rejected_papers"] if row["reason_id"] == reason["id"])[
        "quantity"
    ] = 1
    saved = api.put(target + "/f2", json=command)
    assert saved.status_code == 200, saved.text
    return saved.json(), target


def complete_selected_round(setup: dict[str, Any]) -> dict[str, Any]:
    first, target = save_determination(setup)
    api, supervisor = setup["counter"], setup["clients"]["supervisor"]
    options = api.get(setup["rounds_path"]).json()
    command = complete_f2_command(
        options,
        expected_revision=2,
        determination_started_at="2026-11-15T23:19:00.654321+08:00",
        amendment_reason="核對紙本 <original> & corrected\nprecise source time",
    )
    command["accepted_votes"][0]["quantity"] = 2
    reason = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
    next(row for row in command["rejected_papers"] if row["reason_id"] == reason["id"])[
        "quantity"
    ] = 1
    corrected = api.put(target + "/f2", json=command)
    assert corrected.status_code == 200, corrected.text
    submitted = api.post(
        target + "/submit",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 3,
            "scope_revision": options["scope"]["revision"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    approved = supervisor.post(
        target + "/approve",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 4,
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
        },
    )
    assert approved.status_code == 200, approved.text
    selected = supervisor.post(
        target + "/select",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 5,
            "scope_revision": options["scope"]["revision"],
            "password": READY_PASSWORD,
            "expected_selection_revision": 0,
        },
    )
    assert selected.status_code == 200, selected.text
    return {
        "first": first,
        "corrected": corrected.json(),
        "submitted": submitted.json(),
        "approved": approved.json(),
        "selected": selected.json(),
    }


def test_public_boxes_state_exposes_precise_round_owned_determination(
    admin: TestClient,
    database_url: str,
    timeline_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        saved, _ = save_determination(setup)
        timeline_server.clock.value = setup["clock"].value
        client = DesktopController(timeline_server.url, str(TLS_DIRECTORY / "ca.pem"))
        try:
            client.signIn(
                timeline_server.url, setup["accounts"]["receiveronly"]["username"], READY_PASSWORD
            )
            wait_for(qt_app, lambda: state_of(client)["phase"] == "workspace")
            editor = client.property("boxes")
            assert editor.open(setup["stations"]["N1"]["id"], "counting_officer")
            wait_for(qt_app, lambda: setup_idle(editor))
            events = editor.state["count_events"]
            assert len(events) == 1
            assert events[0]["kind"] == "determination_start"
            assert events[0]["event_at"] == "2026-11-15T15:18:12.123456Z"
            assert events[0]["round_revision"] == 2
            assert events[0]["round_revision_id"] == saved["revision_id"]
            assert events[0]["scope_id"] == setup["scope"]["id"]
            assert events[0]["source_current"] is True
            assert editor.state["count_completion"] is None
        finally:
            client.shutdown()
            client.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_app.processEvents()


def test_round_refresh_retains_dirty_manual_forms_and_reviewed_box_history(
    admin: TestClient,
    database_url: str,
    timeline_server: RoundEventServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        timeline_server.clock.value = setup["clock"].value
        with boxes_editor(
            timeline_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
        ) as (_, editor):
            assert editor.loadBox(setup["boxes"]["local_n1"]["id"])
            wait_for(qt_app, lambda: setup_idle(editor))
            assert len(editor.state["history"]) == 2
            editor.setField("event_time", "2026-11-15 23:09")
            editor.setField("reason", "接收更正草稿\nretain original input")
            editor.setMilestoneField("event_time", "2026-11-15 23:10")
            editor.setMilestoneField("reason", "獨立手動工作事項")
            before = editor.state
            assert before["dirty"] is True and before["count_events"] == []
            complete_selected_round(setup)
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            after = editor.state
            for key in (
                "selected",
                "history",
                "forms",
                "selected_milestone",
                "milestone_kind",
                "milestone_forms",
            ):
                assert after[key] == before[key], key
            assert after["dirty"] is True and after["error"] == ""
            assert len(after["count_events"]) == 3
            completion = next(
                row for row in after["count_events"] if row["kind"] == "count_completion"
            )
            assert completion["selected"] is True and completion["approval_valid"] is True
            starts = sorted(
                (row for row in after["count_events"] if row["kind"] == "determination_start"),
                key=lambda row: row["round_revision"],
            )
            assert [row["is_current"] for row in starts] == [False, True]
            after["count_events"][0]["scope_reference"] = "caller mutation"
            assert editor.state["count_events"][0]["scope_reference"] != "caller mutation"
            assert not editor.reload()
            assert editor.state["forms"] == before["forms"]


@pytest.mark.parametrize(
    "malformation",
    [
        "event_at",
        "entered_at",
        "missing_selection",
        "foreign_station",
        "boolean_id",
        "duplicate",
    ],
)
def test_invalid_round_event_envelope_preserves_last_valid_state_and_manual_inputs(
    admin: TestClient,
    database_url: str,
    timeline_server: RoundEventServer,
    qt_app: QCoreApplication,
    malformation: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        save_determination(setup)
        timeline_server.clock.value = setup["clock"].value
        with boxes_editor(
            timeline_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
        ) as (_, editor):
            editor.setMilestoneField("reason", "Do not lose this manual draft")
            before = editor.state
            timeline_server.malform_next = malformation
            editor.refresh()
            wait_for(qt_app, lambda: setup_idle(editor))
            assert timeline_server.malform_next == ""
            assert editor.state["error"] == "request_failed"
            assert editor.state["count_events"] == before["count_events"]
            assert editor.state["milestone_forms"] == before["milestone_forms"]
            assert editor.state["dirty"] is True


@pytest.mark.parametrize(
    ("locale", "title", "historical", "workflow", "selection"),
    [
        (
            "tc",
            "點票輪次工作事件",
            "歷史事件",
            "來源依據仍有效 · 已核准 · 核准目前有效",
            "已明確選定 · 選定版本 1",
        ),
        (
            "sc",
            "点票轮次工作事件",
            "历史事件",
            "来源依据仍有效 · 已核准 · 核准当前有效",
            "已明确选定 · 选定版本 1",
        ),
        (
            "en",
            "Count round workflow events",
            "Historical occurrence",
            "Source basis remains current · Approved · Approval currently valid",
            "Explicitly selected · Selection revision 1",
        ),
    ],
    ids=["tc", "sc", "en"],
)
def test_material_box_timeline_displays_round_identity_and_precise_occurrence_time(
    admin: TestClient,
    database_url: str,
    timeline_server: HttpsServer,
    locale: str,
    title: str,
    historical: str,
    workflow: str,
    selection: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        saved = complete_selected_round(setup)
        timeline_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {
                "server": timeline_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": locale,
                "title": title,
                "origin_id": saved["first"]["revision_id"],
                "historical": historical,
                "workflow": workflow,
                "selection": selection,
            },
            """
            click('boxesNavigation')
            boxes = controller.property('boxes')
            wait(lambda: not boxes.property('state')['busy'])
            frame()
            assert control('boxCountRoundEventsTitle').property('text') == setup['title']
            assert control('boxCountCompletion').property('visible') is False
            events = boxes.property('state')['count_events']
            assert len(events) == 3
            event_id = next(row['event_id'] for row in events if row['round_revision'] == 2)
            assert control('boxRoundEventTime_' + event_id).property('text').endswith(
                '2026-11-15 23:18:12.123456 HKT')
            origin = control('boxRoundEventOrigin_' + event_id).property('text')
            assert str(setup['origin_id']) in origin
            assert control('boxRoundEventCard_' + event_id).property('visible') is True
            assert control('boxRoundEventNotice').property('visible') is True
            assert control('boxRoundEventOccurrence_' + event_id).property('text').endswith(
                setup['historical'])
            completed_id = next(row['event_id'] for row in events
                                if row['kind'] == 'count_completion')
            workflow = control('boxRoundEventWorkflow_' + completed_id).property('text')
            assert workflow == setup['workflow']
            selection = control('boxRoundEventSelection_' + completed_id).property('text')
            assert selection == setup['selection']
            """,
        )
