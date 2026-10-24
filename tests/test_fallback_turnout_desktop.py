"""P(15) fallback source selection uses two real TLS Qt clients and public stock data."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.fallback_support import (
    approved_mixed_period,
    confirm_fallback_activation,
    fallback_setup,
)
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.test_turnout_desktop import turnout_editor
from tests.turnout_support import READY_PASSWORD, turnout_command


@contextmanager
def turnout_editor_with_response_diagnostics(
    server: HttpsServer, app: QCoreApplication, account: dict, station_id: int,
) -> Iterator[tuple[Any, Any]]:
    try:
        with turnout_editor(server, app, account, station_id) as connected:
            yield connected
    except BaseException:
        print("Public TLS responses:", [
            (row.get("method"), row.get("path"), row.get("status"))
            for row in server.request_timings
        ])
        raise


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_election(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_qt_selects_confirmed_fallback_sources_and_approves_mixed_115_period(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        activation = confirm_fallback_activation(setup)
        officer, base = setup["officer"], setup["base"]
        observed = officer.post(base + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        endpoint = observed.json()
        assert endpoint["ordinary_issued_quantity"] == 115
        assert endpoint["ordinary_remaining_quantity"] == 85
        https_server.clock.value = setup["clock"].value
        station_id = endpoint["station_id"]
        with turnout_editor(https_server, qt_app, setup["account"], station_id) as (_, editor):
            assert editor.selectPeriod(2) is True
            wait_for_editor_idle(qt_app, editor)
            editor.setField("mode", "fallback")
            editor.setField("fallback_activation_id", str(activation["id"]))
            editor.setField("fallback_activation_revision", "1")
            editor.setField("stock_snapshot_id", str(endpoint["id"]))
            editor.setField("stock_snapshot_revision", "1")
            editor.setField("event_time", "2026-11-15 12:00")
            editor.setField("source_context", "Confirmed 110 plus five later ordinary issues.")
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            saved = editor.property("state")
            # First new-feature assertion: ignoring mode sends a normal command and gets 409.
            assert saved["error"] == "", {
                "state_error": saved["error"],
                "public_save_responses": [
                    (row["method"], row["path"], row["status"])
                    for row in https_server.request_timings
                    if row["method"] == "PUT" and row["path"] == setup["scope"]["path"] + "/2"
                ],
            }
            assert saved["notice"] == "turnout_saved"
            selected = saved["selected"]
            assert selected["provenance"] == "mixed" and selected["status"] == "draft"
            assert selected["supplied_hourly"] is None and selected["supplied_cumulative"] is None
            assert saved["forms"]["mode"] == "fallback"
            assert saved["forms"]["fallback_activation_id"] == str(activation["id"])
            basis = selected["source_basis"]
            display_basis = selected["source_basis_display"]
            assert basis["ordinary_issued_since_activation_quantity"] == 5
            assert display_basis["stock_derived_cumulative_quantity_display"] == "115"
            assert display_basis["activation_stock_snapshot"]["counters"][0][
                "ordinary_remaining_quantity_display"
            ] == "90"
            assert display_basis["stock_snapshot"]["ordinary_issued_quantity_display"] == "115"
            assert [row["hourly_quantity_display"]
                    for row in display_basis["coverage"]] == ["10", "5"]
            assert basis["coverage"][0]["cumulative_start_quantity"] == 100
            assert basis["coverage"][1]["cumulative_end_quantity"] == 115
            assert len(basis["source_events"]) == 1
            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["selected"]["status"] == "submitted"
            with turnout_editor(
                https_server, qt_app, setup["supervisor_account"], station_id,
            ) as (_, reviewer):
                assert reviewer.selectPeriod(2) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.loadRevision(1) is True
                wait_for_editor_idle(qt_app, reviewer)
                reviewer.refresh()
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.property("state")["newer_revision"] is False
                reviewer.approve(READY_PASSWORD)
                wait_for_editor_idle(qt_app, reviewer)
                reviewed = reviewer.property("state")
                assert reviewed["error"] == "" and reviewed["notice"] == "turnout_approved"
                approved = reviewed["selected"]
                assert approved["revision"] == 1 and approved["status"] == "approved"
                assert approved["derived_cumulative_start_display"] == "100"
                assert approved["derived_hourly_display"] == "15"
                assert approved["derived_cumulative_end_display"] == "115"
                assert reviewed["approved_prefix"]["cumulative_end_display"] == "115"
                for locale in ("tc", "sc", "en"):
                    reviewer.preview(locale)
                    wait_for_editor_idle(qt_app, reviewer)
                    report = reviewer.property("state")["report"]
                    assert report["locale"] == locale
                    assert report["report_scope"] == "period_revision"
                    assert report["items"][0]["derived_cumulative_end"] == 115
                    assert report["items"][0]["derived_hourly"] == 15
                    assert "115" in reviewer.property("state")["report_text"]
                current = officer.get(setup["scope"]["path"])
                assert current.status_code == 200
                assert current.json()["approved_prefix"]["cumulative_end"] == 115


def test_qt_selects_confirmed_recovery_and_renews_period_115_as_116(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        activation, endpoint, old_turnout = (
            prepared["activation"], prepared["endpoint"], prepared["approved"]
        )
        officer = setup["officer"]
        created = officer.post(setup["path"], json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 116,
            "source_context": "Recovered external register: cumulative 116 at noon.",
            "reason": "Reconcile recovered 116 with the stock-derived 115 endpoint.",
        })
        assert created.status_code == 201
        recovery = created.json()
        recovery_path = setup["path"] + f"/{recovery['id']}"
        submitted = officer.post(recovery_path + "/submit", json=turnout_command(1))
        assert submitted.status_code == 200
        confirmed = setup["supervisor"].post(
            recovery_path + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        https_server.clock.value = setup["clock"].value
        station_id = endpoint["station_id"]
        with turnout_editor_with_response_diagnostics(
            https_server, qt_app, setup["account"], station_id,
        ) as (_, editor):
            assert editor.selectPeriod(2) is True
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["current"]["review_required"] is True
            editor.setField("mode", "recovery")
            editor.setField("fallback_recovery_id", str(recovery["id"]))
            editor.setField("fallback_recovery_revision", "1")
            editor.setField("event_time", "2026-11-15 12:00")
            editor.setField(
                "source_context", "Selected recovered noon endpoint 116, replacing 115.",
            )
            editor.setField("amendment_reason", "Renew this period against confirmed recovery r1.")
            entered = editor.property("state")["forms"]
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            assert editor.property("state")["forms"] == entered
            editor.amend()
            wait_for_editor_idle(qt_app, editor)
            saved = editor.property("state")
            # First new-feature assertion: the fallback-only Qt payload rejects recovery mode.
            assert saved["error"] == ""
            assert saved["notice"] == "turnout_amended"
            draft = saved["selected"]
            assert draft["revision"] == 2 and draft["status"] == "draft"
            assert draft["provenance"] == "external_reconciled"
            assert saved["forms"]["mode"] == "recovery"
            assert saved["forms"]["fallback_recovery_id"] == str(recovery["id"])
            assert saved["forms"]["fallback_activation_id"] == ""
            basis = draft["source_basis"]
            display_basis = draft["source_basis_display"]
            assert basis["recovery_id"] == recovery["id"]
            assert display_basis["stock_derived_cumulative_quantity_display"] == "115"
            assert display_basis["recovered_cumulative_quantity_display"] == "116"
            assert display_basis["reconciliation_difference_display"] == "1"
            assert [row["hourly_quantity_display"]
                    for row in display_basis["coverage"]] == ["10", "6"]
            editor.submit()
            wait_for_editor_idle(qt_app, editor)
            submitted_period = editor.property("state")["selected"]
            assert submitted_period["revision"] == 2 and submitted_period["status"] == "submitted"
            with turnout_editor(
                https_server, qt_app, setup["supervisor_account"], station_id,
            ) as (_, reviewer):
                assert reviewer.selectPeriod(2) is True
                wait_for_editor_idle(qt_app, reviewer)
                assert reviewer.loadRevision(2) is True
                wait_for_editor_idle(qt_app, reviewer)
                reviewer.approve(READY_PASSWORD)
                wait_for_editor_idle(qt_app, reviewer)
                reviewed = reviewer.property("state")
                assert reviewed["error"] == "" and reviewed["notice"] == "turnout_approved"
                approved = reviewed["selected"]
                assert approved["derived_cumulative_start_display"] == "100"
                assert approved["derived_hourly_display"] == "16"
                assert approved["derived_cumulative_end_display"] == "116"
                assert reviewed["approved_prefix"]["cumulative_end_display"] == "116"
                for locale in ("tc", "sc", "en"):
                    reviewer.preview(locale)
                    wait_for_editor_idle(qt_app, reviewer)
                    report = reviewer.property("state")["report"]
                    assert report["locale"] == locale
                    assert report["items"][0]["derived_cumulative_end"] == 116
                    assert report["items"][0]["derived_hourly"] == 16
                editor.refresh()
                wait_for_editor_idle(qt_app, editor)
                assert editor.property("state")["current"]["record"] == approved
                assert editor.property("state")["selected"] == submitted_period
                assert editor.property("state")["newer_revision"] is True
                assert editor.reload(True) is True
                wait_for_editor_idle(qt_app, editor)
                assert editor.loadRevision(1) is True
                wait_for_editor_idle(qt_app, editor)
                historical = editor.property("state")
                assert historical["historical"] is True
                assert historical["forms"]["mode"] == "fallback"
                assert historical["selected"]["derived_cumulative_end_display"] == "115"
                old = officer.get(setup["scope"]["path"] + "/2?revision=1")
                assert old.status_code == 200 and old.json() == old_turnout
