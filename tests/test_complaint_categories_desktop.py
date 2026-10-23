"""Administrator category configuration through public Qt and real HTTPS/MySQL."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, setup_idle
from tests.configuration_support import create_election
from tests.desktop_support import HttpsServer, wait_for
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
    requests_before = len(https_server.requests)
    editor.setEnabled(False)
    editor.save()
    assert editor.property("state")["error"] == "complaint_other_required"
    editor.setEnabled(True)
    editor.setDescriptionRequired(False)
    editor.save()
    assert editor.property("state")["error"] == "complaint_other_required"
    assert len(https_server.requests) == requests_before
    stored = admin.get(f"/api/elections/{election['id']}/complaint-categories").json()["items"]
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
    editor = category_editor(desktop, https_server, account, qt_app)
    assert editor.selectElection(election["id"], False)
    wait_for(qt_app, lambda: setup_idle(editor))
    category = editor.property("state")["items"][0]
    assert editor.loadCategory(category["id"], False)
    arrange_finalized_turnout_election(database_url, election["id"])
    editor.refresh()
    wait_for(qt_app, lambda: setup_idle(editor))
    assert editor.property("state")["election"]["status"] == "finalized"
    before = len(https_server.requests)
    editor.setField("label_tc", "不可變更")
    editor.setEnabled(False)
    editor.setDescriptionRequired(True)
    editor.save()
    assert editor.property("state")["selected"] == category
    assert editor.property("state")["dirty"] is False
    assert len(https_server.requests) == before
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
