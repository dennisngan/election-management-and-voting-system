"""Counter allocation retries and guards use public Qt slots and real HTTPS/MySQL."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest

from tests.allocation_desktop_support import allocation_editor
from tests.configuration_desktop_support import setup_idle
from tests.desktop_support import HttpsServer, state_of, wait_for
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.stock_support import ready_client, staff_account, stock_payload
from tests.test_allocation_api import allocation_payload
from tests.test_allocation_api import allocation_setup as allocation_setup
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_lifecycle_state(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def fill_allocation(editor: Any, setup: dict, **changes: str) -> dict:
    fields = {
        "counter_id": str(setup["counter"]["id"]),
        "series": "普通系列 A",
        "serial_from": "000001",
        "serial_to": "000003",
        "event_at": "2026-11-08 08:05",
        **changes,
    }
    for name, value in fields.items():
        editor.setField(name, value)
    return editor.property("state")["forms"]


@pytest.mark.parametrize("amended_elsewhere", [False, True])
def test_uncertain_create_checks_original_outcome_before_loading_its_saved_revision(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication,
    amended_elsewhere: bool,
) -> None:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    with allocation_editor(
        https_server, qt_app, setup["account"], setup["station"]["id"]
    ) as (client, editor):
        fields = fill_allocation(editor, setup)
        https_server.truncate_next_allocation_write = True
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        uncertain = editor.property("state")
        assert uncertain["error"] in ("disconnected", "request_failed")
        assert uncertain["selected"] == {} and uncertain["forms"] == fields
        assert uncertain["dirty"] is True
        saved = setup["officer"].get(path).json()["items"]
        assert len(saved) == 1
        original = saved[0]
        recovery = client.property("recovery")
        recovery.open()
        wait_for(qt_app, lambda: setup_idle(recovery))
        commands = recovery.property("state")["commands"]
        assert len(commands) == 1
        command = commands[0]
        request_id, original_payload = command["request_id"], dict(command["payload"])
        assert command["workflow"] == "allocation" and command["path"] == path
        assert command["status"] == "uncertain"
        QTest.qWait(100)
        assert https_server.request_count("POST", path) == 1
        if amended_elsewhere:
            changed = setup["officer"].put(
                path + f"/{original['id']}",
                json=allocation_payload(
                    setup["counter"]["id"], revision=1, serial_to="000004",
                    reason="另一部電腦核對交接單後更正",
                ),
            )
            assert changed.status_code == 200
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        blocked = editor.property("state")
        assert blocked["error"] == "recovery_outcome_check_required"
        assert blocked["selected"] == {} and blocked["forms"] == fields
        assert blocked["dirty"] is True
        assert https_server.request_count("POST", path) == 1
        recovery.reload()
        wait_for(qt_app, lambda: setup_idle(recovery))
        retained = recovery.property("state")["commands"][0]
        assert retained["request_id"] == request_id and retained["payload"] == original_payload
        assert retained["status"] == "uncertain"

        recovery.checkOutcome(request_id)
        wait_for(qt_app, lambda: setup_idle(recovery))
        committed = recovery.property("state")["commands"][0]
        assert committed["request_id"] == request_id and committed["payload"] == original_payload
        assert committed["status"] == "committed" and committed["error"] == ""
        record = committed["receipt"]["record"]
        assert_public_business_fields(record, original)
        assert record["revision"] == 1 and record["serial_to"] == "000003"
        assert record["quantity"] == 3 and record["quantity_display"] == "3"
        assert https_server.request_count("POST", path) == 1
        checked = editor.property("state")
        assert checked["selected"] == {} and checked["forms"] == fields
        assert checked["dirty"] is True

        assert editor.loadAllocation(original["id"], True)
        wait_for(qt_app, lambda: setup_idle(editor))
        assert editor.property("state")["selected"]["revision"] == (
            2 if amended_elsewhere else 1
        )
        if amended_elsewhere:
            assert editor.loadRevision(1, False)
            wait_for(qt_app, lambda: setup_idle(editor))
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        recovered = editor.property("state")
        assert recovered["error"] == "" and recovered["dirty"] is False
        assert recovered["selected"]["id"] == original["id"]
        assert recovered["selected"]["revision"] == 1
        assert recovered["selected"]["serial_to"] == "000003"
        assert https_server.request_count("POST", path) == 1
        current = setup["officer"].get(path).json()
        assert len(current["items"]) == 1
        if amended_elsewhere:
            assert recovered["historical"] is True and recovered["newer_revision"] is True
            assert recovered["items"][0]["revision"] == 2
            assert recovered["availability"][0]["available_display"] == "4"
            assert current["items"][0]["revision"] == 2
            assert [row["revision"] for row in recovered["history"]] == [1, 2]
        else:
            assert recovered["historical"] is False and recovered["newer_revision"] is False
            assert current["items"] == [original]
            assert recovered["availability"][0]["available_display"] == "5"
            assert len(recovered["history"]) == 1


def test_stale_amendment_keeps_reviewed_fields_while_refresh_updates_live_availability(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    created = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert created.status_code == 201
    original = created.json()
    with allocation_editor(
        https_server, qt_app, setup["account"], setup["station"]["id"]
    ) as (_, editor):
        assert editor.loadAllocation(original["id"], False)
        wait_for(qt_app, lambda: setup_idle(editor))
        fields = fill_allocation(editor, setup, serial_to="000005", reason="保留此機的修正原因")
        pinned = editor.property("state")["selected"]
        changed = setup["officer"].put(
            path + f"/{original['id']}",
            json=allocation_payload(
                setup["counter"]["id"], revision=1, serial_to="000004",
                reason="另一部電腦已核對並儲存",
            ),
        )
        assert changed.status_code == 200
        editor.refresh()
        wait_for(qt_app, lambda: setup_idle(editor))
        refreshed = editor.property("state")
        assert refreshed["selected"] == pinned and refreshed["forms"] == fields
        assert refreshed["newer_revision"] is True
        assert refreshed["availability"][0]["available_display"] == "4"
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        conflict = editor.property("state")
        assert conflict["error"] == "revision_conflict"
        assert conflict["selected"] == pinned and conflict["forms"] == fields
        assert conflict["dirty"] is True and conflict["newer_revision"] is True
        history = setup["officer"].get(path + f"/{original['id']}/history").json()
        assert [row["revision"] for row in history["items"]] == [1, 2]


@pytest.mark.parametrize(
    ("first", "last", "code"),
    [("000003", "000005", "allocation_overlap"), ("000008", "000009", "allocation_outside_stock")],
)
def test_ownership_errors_are_visible_without_erasing_unsubmitted_fields(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication,
    first: str, last: str, code: str,
) -> None:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    original = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert original.status_code == 201
    with allocation_editor(
        https_server, qt_app, setup["account"], setup["station"]["id"]
    ) as (_, editor):
        fields = fill_allocation(editor, setup, serial_from=first, serial_to=last)
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        state = editor.property("state")
        assert state["error"] == code and state["forms"] == fields
        assert state["selected"] == {} and state["dirty"] is True
        assert setup["officer"].get(path).json()["items"] == [original.json()]


def test_large_serial_quantities_remain_exact_strings_in_forms_selected_and_availability(
    allocation_setup: dict, https_server: HttpsServer, qt_app: QCoreApplication
) -> None:
    setup = allocation_setup
    receipt = setup["officer"].put(
        setup["base"] + f"/stock/{setup['receipt']['id']}",
        json=stock_payload(
            revision=1, reason="核對完整十八位數系列", series="大數系列",
            ranges=[{
                "pool": "ordinary", "serial_from": "100000000000000000",
                "serial_to": "999999999999999999",
            }],
            ordinary_quantity=900000000000000000, replacement_quantity=0, tendered_quantity=0,
        ),
    )
    assert receipt.status_code == 200
    with allocation_editor(
        https_server, qt_app, setup["account"], setup["station"]["id"]
    ) as (_, editor):
        fill_allocation(
            editor, setup, series="大數系列", serial_from="100000000000000000",
            serial_to="999999999999999998",
        )
        assert editor.property("state")["quantity_display"] == "899999999999999999"
        editor.save()
        wait_for(qt_app, lambda: setup_idle(editor))
        state = editor.property("state")
        assert state["error"] == ""
        assert state["forms"]["serial_to"] == "999999999999999998"
        assert state["selected"]["quantity_display"] == "899999999999999999"
        assert state["availability"][0]["ordinary_received_display"] == "900000000000000000"
        assert state["availability"][0]["allocated_display"] == "899999999999999999"
        assert state["availability"][0]["available_display"] == "1"
        assert state["availability"][0]["ranges"][0]["quantity_display"] == "1"


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_read_only_roles_can_preview_and_export_but_cannot_change_or_save_fields(
    allocation_setup: dict, admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication, tmp_path: Path, role: str,
) -> None:
    setup = allocation_setup
    path = setup["base"] + "/allocations"
    saved = setup["officer"].post(path, json=allocation_payload(setup["counter"]["id"]))
    assert saved.status_code == 201
    account = staff_account(admin, [setup["station"]["id"]], role)
    with ready_client(database_url, account):
        pass
    with allocation_editor(
        https_server, qt_app, account, setup["station"]["id"]
    ) as (_, editor):
        assert editor.loadAllocation(saved.json()["id"], False)
        wait_for(qt_app, lambda: setup_idle(editor))
        before = editor.property("state")
        for field, value in (("serial_to", "000004"), ("reason", "唯讀職員不可修改")):
            editor.setField(field, value)
        editor.save()
        blocked = editor.property("state")
        assert blocked["error"] == "election_read_only"
        assert blocked["forms"] == before["forms"] and blocked["selected"] == before["selected"]
        assert https_server.request_count("POST", path) == 0
        assert https_server.request_count("PUT", path + f"/{saved.json()['id']}") == 0
        editor.setReportScope("allocation_revision")
        editor.preview("en")
        wait_for(qt_app, lambda: setup_idle(editor))
        report = editor.property("state")
        assert report["error"] == "" and report["report"]["revision"] == 1
        assert report["report_text"].startswith("P(14) Counter ballot allocations")
        for format in ("csv", "pdf"):
            destination = tmp_path / f"{role}-allocation.{format}"
            editor.download(format, destination.as_uri(), "en")
            wait_for(qt_app, lambda: setup_idle(editor))
            assert editor.property("state")["error"] == ""
            assert destination.is_file()
            signature = b"%PDF-" if format == "pdf" else b"\xef\xbb\xbf"
            assert destination.read_bytes().startswith(signature)
    assert setup["officer"].get(path).json()["items"] == [saved.json()]


def test_delayed_old_station_lists_cannot_repopulate_a_switched_or_signed_out_workspace(
    allocation_setup: dict, admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    setup = allocation_setup
    first, second = setup["station"], setup["stations"][1]
    account = staff_account(admin, [first["id"], second["id"]])
    with ready_client(database_url, account):
        pass
    saved = setup["officer"].post(
        setup["base"] + "/allocations", json=allocation_payload(setup["counter"]["id"])
    )
    assert saved.status_code == 201
    with allocation_editor(https_server, qt_app, account, first["id"]) as (client, editor):
        workspace = client.property("workspace")
        https_server.hold_allocation_list = True
        editor.refresh()
        wait_for(qt_app, https_server.allocation_list_entered.is_set)
        try:
            workspace.selectStation(second["id"])
            wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
            assert editor.property("state")["station_id"] == second["id"]
            assert editor.property("state")["items"] == []
        finally:
            https_server.release_allocation_list.set()
        QTest.qWait(150)
        switched = editor.property("state")
        assert switched["station_id"] == second["id"]
        assert switched["items"] == [] and switched["availability"] == []
        workspace.selectStation(first["id"])
        wait_for(qt_app, lambda: setup_idle(workspace) and setup_idle(editor))
        assert len(editor.property("state")["items"]) == 1
        https_server.allocation_list_entered.clear()
        https_server.release_allocation_list.clear()
        https_server.hold_allocation_list = True
        editor.refresh()
        wait_for(qt_app, https_server.allocation_list_entered.is_set)
        try:
            client.signOut()
        finally:
            https_server.release_allocation_list.set()
        QTest.qWait(150)
        assert state_of(client)["phase"] == "signed_out"
        signed_out = editor.property("state")
        assert signed_out["station_id"] == 0
        assert signed_out["items"] == [] and signed_out["selected"] == {}
        assert signed_out["availability"] == [] and signed_out["report"] == {}
