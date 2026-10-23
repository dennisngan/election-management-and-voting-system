"""Administrator category configuration through public Qt and real HTTPS/MySQL."""

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from fastapi import Request, Response
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QEvent
from starlette.responses import JSONResponse, StreamingResponse

from election.desktop.controller import DesktopController
from election.server.app import create_app
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.configuration_support import create_election
from tests.desktop_support import TLS_DIRECTORY, ControlledClock, HttpsServer, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.turnout_support import arrange_finalized_turnout_election


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def category_editor(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> Any:
    ready_setup(desktop, https_server, account, qt_app)
    editor = desktop.property("complaintCategories")
    assert editor is not None
    editor.open()
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["error"] == ""
    return editor


def category_mutations(server: HttpsServer, path: str) -> list[tuple[str, str]]:
    with server.lock:
        return [
            (method, route)
            for method, route in server.requests
            if method in ("POST", "PUT") and (route == path or route.startswith(path + "/"))
        ]


def test_admin_selects_election_reads_verified_seed_and_saves_project_category(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    seeded = editor.property("state")["items"]
    assert {row["code"] for row in seeded} == {"9", "10", "11", "12", "30"}
    other = next(row for row in seeded if row["is_other"])
    assert other["description_required"] is True
    assert other["verified_source"] is True
    assert other["source_english"] == "Miscellaneous (please specify nature)"
    assert editor.loadCategory(0, False)
    for key, value in {
        "code": "LOCAL-0001",
        "label_tc": "本地安排投訴",
        "label_sc": "本地安排投诉",
        "label_en": "Local arrangements complaint",
    }.items():
        editor.setField(key, value)
    editor.setDescriptionRequired(True)
    editor.save()
    wait_for(qt_app, lambda: setup_idle(editor))
    saved = editor.property("state")
    assert saved["error"] == ""
    assert saved["dirty"] is False
    assert saved["selected"]["code"] == "LOCAL-0001"
    assert saved["selected"]["revision"] == 1
    assert saved["selected"]["verified_source"] is False
    assert saved["selected"]["description_required"] is True
    response = admin.get(f"/api/elections/{election['id']}/complaint-categories")
    assert response.status_code == 200
    stored = next(row for row in response.json()["items"] if row["code"] == "LOCAL-0001")
    assert stored["label_tc"] == "本地安排投訴"
    assert stored["label_sc"] == "本地安排投诉"
    assert stored["label_en"] == "Local arrangements complaint"


def test_verified_source_stays_immutable_while_labels_and_availability_are_configurable(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    original = next(row for row in editor.property("state")["items"] if row["code"] == "9")
    assert editor.loadCategory(original["id"], False)
    editor.setField("code", "must-not-replace-official-code")
    editor.setField("label_tc", "本選舉投票安排投訴")
    editor.setEnabled(False)
    editor.save()
    wait_for(qt_app, lambda: setup_idle(editor))
    row = editor.property("state")["selected"]
    assert row["revision"] == 2
    assert row["enabled"] is False
    assert row["code"] == "9"
    assert row["label_tc"] == "本選舉投票安排投訴"
    assert row["source_english"] == original["source_english"]
    assert row["reference_page"] == original["reference_page"]
    assert row["verified_source"] is True
    assert editor.reload(False)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["selected"] == row
    other = next(item for item in editor.property("state")["items"] if item["is_other"])
    assert editor.loadCategory(other["id"], False)
    requests_before = category_mutations(https_server, path)
    health_requests = https_server.request_count("GET", "/api/health")
    editor.setEnabled(False)
    editor.save()
    assert editor.property("state")["error"] == "complaint_other_required"
    editor.setEnabled(True)
    editor.setDescriptionRequired(False)
    editor.save()
    assert editor.property("state")["error"] == "complaint_other_required"
    desktop.refresh()
    wait_for(qt_app, lambda: https_server.request_count("GET", "/api/health") > health_requests)
    assert category_mutations(https_server, path) == requests_before
    stored = admin.get(path).json()["items"]
    assert next(item for item in stored if item["is_other"]) == other


def test_live_catalog_refresh_preserves_reviewed_form_and_guards_discard_and_stale_saves(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    from tests.complaint_support import category_edit

    first, second = create_election(admin), create_election(admin)
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(first["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    original = next(row for row in editor.property("state")["items"] if row["code"] == "9")
    assert editor.loadCategory(original["id"], False)
    editor.setField("label_tc", "目前尚未儲存的標籤")
    form = editor.property("state")["form"]
    changed = admin.put(
        f"/api/elections/{first['id']}/complaint-categories/{original['id']}",
        json=category_edit(original, label_tc="另一名管理員先儲存"),
    )
    assert changed.status_code == 200
    editor.refresh()
    wait_for(qt_app, lambda: setup_idle(editor))
    live = editor.property("state")
    assert live["selected"] == original
    assert live["form"] == form
    assert live["dirty"] is True
    assert live["newer_revision"] is True
    assert next(row for row in live["items"] if row["id"] == original["id"])["revision"] == 2
    assert editor.selectElection(second["id"], False) is False
    assert editor.loadCategory(0, False) is False
    assert editor.reload(False) is False
    assert editor.property("state")["error"] == "unsaved_complaint_category_changes"
    editor.save()
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["error"] == "revision_conflict"
    assert editor.property("state")["form"] == form
    assert editor.reload(True)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["selected"] == changed.json()
    assert editor.property("state")["dirty"] is False
    assert editor.selectElection(second["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["election_id"] == second["id"]
    assert {row["code"] for row in editor.property("state")["items"]} == {
        "9",
        "10",
        "11",
        "12",
        "30",
    }


def test_finalized_category_view_and_logged_out_state_block_local_changes(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    database_url: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    category = editor.property("state")["items"][0]
    assert editor.loadCategory(category["id"], False)
    arrange_finalized_turnout_election(database_url, election["id"])
    editor.refresh()
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["election"]["status"] == "finalized"
    before = category_mutations(https_server, path)
    editor.setField("label_tc", "不可變更")
    editor.setEnabled(False)
    editor.setDescriptionRequired(True)
    editor.save()
    assert editor.property("state")["selected"] == category
    assert editor.property("state")["dirty"] is False
    assert category_mutations(https_server, path) == before
    desktop.signOut()
    wait_for(qt_app, lambda: not desktop.property("state")["busy"])
    assert editor.property("state")["election_id"] == 0
    assert editor.property("state")["items"] == []
    assert editor.loadCategory(0, True) is False
    editor.open()
    editor.refresh()
    editor.save()
    assert editor.property("state")["selected"] == {}


def test_late_election_directory_refresh_cannot_replace_a_new_catalog_selection(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    first, second = create_election(admin), create_election(admin)
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(first["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    https_server.hold_configuration_list = True
    editor.refresh()
    wait_for(qt_app, https_server.configuration_list_entered.is_set)
    assert editor.selectElection(second["id"], True)
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["election_id"] == second["id"]
    https_server.release_configuration_list.set()
    qt_app.processEvents()
    assert editor.property("state")["election_id"] == second["id"]
    assert all(row["election_id"] == second["id"] for row in editor.property("state")["items"])


@dataclass
class CategoryBoundaryServer(HttpsServer):
    fault_next_write: str = ""
    fault_next_catalog: str = ""
    write_request_ids: list[str] = field(default_factory=list)


@pytest.fixture
def category_boundary_server(
    database_url: str,
    qt_app: QCoreApplication,
) -> Iterator[CategoryBoundaryServer]:
    """Fault only category response delivery after ordinary persistent API execution."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    endpoint = CategoryBoundaryServer(f"https://localhost:{port}", ControlledClock())
    application = create_app(database_url, now=endpoint.clock)

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        with endpoint.lock:
            endpoint.requests.append((request.method, path))
        write = request.method in ("POST", "PUT") and "/complaint-categories" in path
        catalog = request.method == "GET" and path.endswith("/complaint-categories")
        if write:
            # Observe only the public replay UUID of these synthetic category commands.
            endpoint.write_request_ids.append((await request.json())["request_id"])
        response = await call_next(request)
        mode = (
            endpoint.fault_next_write if write else endpoint.fault_next_catalog if catalog else ""
        )
        if mode and response.status_code in (200, 201):
            if write:
                endpoint.fault_next_write = ""
            else:
                endpoint.fault_next_catalog = ""
            if mode == "partial":
                body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
                # Keep the committed target valid, but omit the previously reviewed seed rows.
                newest = max(body["items"], key=lambda row: row["id"])
                return JSONResponse({"items": [newest]})
            return StreamingResponse(
                iter([b'{"incomplete":']),
                media_type="application/json",
                headers={"Content-Length": "4096"},
            )
        return response

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
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
        assert not thread.is_alive()


@contextmanager
def boundary_editor(
    server: CategoryBoundaryServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    election_id: int,
) -> Iterator[Any]:
    client = DesktopController(server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        editor = category_editor(client, server, account, qt_app)
        assert editor.selectElection(election_id, False)
        wait_for(qt_app, lambda: setup_idle(editor))
        yield editor
    finally:
        client.shutdown()
        client.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()


def new_boundary_category(editor: Any) -> None:
    assert editor.loadCategory(0, False)
    for key, value in {
        "code": "RETRY-0001",
        "label_tc": "網絡中斷仍保留分類",
        "label_sc": "网络中断仍保留分类",
        "label_en": "Preserved uncertain category",
    }.items():
        editor.setField(key, value)
    editor.setDescriptionRequired(True)


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_uncertain_category_write_retries_the_same_command_once_without_losing_provenance(
    admin: TestClient,
    account: dict[str, str],
    qt_app: QCoreApplication,
    category_boundary_server: CategoryBoundaryServer,
    operation: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    server = category_boundary_server
    with boundary_editor(server, account, qt_app, election["id"]) as editor:
        original_items = editor.property("state")["items"]
        if operation == "create":
            new_boundary_category(editor)
            expected_revision, target_code = 1, "RETRY-0001"
        else:
            original = next(item for item in original_items if item["code"] == "9")
            assert editor.loadCategory(original["id"], False)
            editor.setField("label_tc", "保留已核實來源的修訂")
            expected_revision, target_code = 2, "9"
        before = editor.property("state")
        server.fault_next_write = "truncate"
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
        uncertain = editor.property("state")
        assert uncertain["error"] == "disconnected"
        assert uncertain["dirty"] and uncertain["notice"] == ""
        assert uncertain["form"] == before["form"]
        assert uncertain["selected"] == before["selected"]
        assert uncertain["items"] == original_items
        stored = admin.get(path).json()["items"]
        target = next(item for item in stored if item["code"] == target_code)
        assert target["revision"] == expected_revision
        assert len(stored) == (6 if operation == "create" else 5)
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        retried = editor.property("state")
        assert retried["error"] == "" and not retried["dirty"]
        assert retried["notice"] == "complaint_category_saved"
        assert retried["selected"] == target
        assert server.write_request_ids[-2] == server.write_request_ids[-1]
        assert admin.get(path).json()["items"] == stored
        if operation == "edit":
            assert target["source_english"] == original["source_english"]
            assert target["reference_page"] == original["reference_page"]
            assert target["verified_source"]
        else:
            assert not target["verified_source"] and target["description_required"]


@pytest.mark.parametrize("read_fault", ["truncate", "partial"])
def test_postwrite_catalog_failure_preserves_previous_catalog_and_dirty_form_then_replays_once(
    admin: TestClient,
    account: dict[str, str],
    qt_app: QCoreApplication,
    category_boundary_server: CategoryBoundaryServer,
    read_fault: str,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    server = category_boundary_server
    with boundary_editor(server, account, qt_app, election["id"]) as editor:
        new_boundary_category(editor)
        before = editor.property("state")
        server.fault_next_catalog = read_fault
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor), timeout=10)
        failed = editor.property("state")
        assert failed["error"] == ("disconnected" if read_fault == "truncate" else "request_failed")
        assert failed["notice"] == "" and failed["dirty"]
        assert failed["form"] == before["form"]
        assert failed["selected"] == before["selected"]
        assert failed["items"] == before["items"]
        stored = admin.get(path).json()["items"]
        assert sum(row["code"] == "RETRY-0001" for row in stored) == 1
        target = next(row for row in stored if row["code"] == "RETRY-0001")
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        saved = editor.property("state")
        assert saved["error"] == "" and not saved["dirty"]
        assert saved["selected"] == target
        assert saved["selected"]["revision"] == 1
        assert server.write_request_ids[-2] == server.write_request_ids[-1]
        assert admin.get(path).json()["items"] == stored


def test_blank_labels_and_duplicate_codes_keep_category_input_and_do_not_replace_seeded_data(
    admin: TestClient,
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/complaint-categories"
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    original = editor.property("state")["items"]
    new_boundary_category(editor)
    editor.setField("label_tc", "   ")
    requests_before = category_mutations(https_server, path)
    invalid_form = editor.property("state")["form"]
    health_requests = https_server.request_count("GET", "/api/health")
    editor.save()
    assert editor.property("state")["error"] == "complaint_category_validation"
    assert editor.property("state")["dirty"]
    desktop.refresh()
    wait_for(qt_app, lambda: https_server.request_count("GET", "/api/health") > health_requests)
    assert category_mutations(https_server, path) == requests_before
    assert editor.property("state")["form"] == invalid_form
    editor.setField("label_tc", "重複代碼保留輸入")
    editor.setField("code", "9")
    form = editor.property("state")["form"]
    editor.save()
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["error"] == "complaint_category_code_exists"
    assert editor.property("state")["dirty"]
    assert editor.property("state")["form"] == form
    assert editor.property("state")["items"] == original
    assert category_mutations(https_server, path) == requests_before + [("POST", path)]
    assert admin.get(path).json()["items"] == original
