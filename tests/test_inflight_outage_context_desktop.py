"""Retain station and request identity until a real reconciliation reply arrives."""

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication, QObject

from tests.box_support import READY_PASSWORD
from tests.desktop_support import wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.tally_support import tally_setup
from tests.test_outage_reconciliation_edges_api import _count_draft, _create_outage_and_paper
from tests.test_paper_journal_failure_desktop import CompletedWriteServer, signed_in_client
from tests.test_paper_journal_failure_desktop import (
    completed_write_server as completed_write_server,
)
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_confirmed_station_discard_cannot_rehome_reconciliation_with_reply_in_flight(
    admin: TestClient,
    database_url: str,
    qt_app: QCoreApplication,
    completed_write_server: CompletedWriteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "outage-inflight-journal"))
    endpoint = completed_write_server
    with tally_setup(admin, database_url) as setup:
        endpoint.clock.value = setup["clock"].value
        counter = setup["counter"]
        supervisor = setup["clients"]["supervisor"]
        actor = setup["accounts"]["supervisor"]
        station_id, target_id = setup["stations"]["N1"]["id"], setup["stations"]["S1"]["id"]
        assert station_id != target_id
        assert setup["stations"]["N1"]["constituency_id"] != (
            setup["stations"]["S1"]["constituency_id"]
        )
        options, round_path, draft = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, draft["id"])
        submitted_response = counter.post(round_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 2,
            "scope_revision": options["scope"]["revision"], "paper_record_id": paper["id"],
        })
        assert submitted_response.status_code == 200, submitted_response.text
        assert submitted_response.json()["status"] == "submitted"
        assert submitted_response.json()["revision"] == 3
        before_response = supervisor.get(outage_path)
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        outage_id = before["record"]["id"]
        assert before["record"]["reconciled"] is False
        assert before["record"]["reconciliation"] is None
        assert before["record"]["reconciliation_history"] == []
        assert len(before["record"]["paper_records"]) == 1
        entered_paper = before["record"]["paper_records"][0]
        assert entered_paper["id"] == paper["id"] and entered_paper["status"] == "entered"
        assert entered_paper["reentry"]["record"] == submitted_response.json()
        count_before_response = counter.get(round_path)
        assert count_before_response.status_code == 200, count_before_response.text
        count_before = count_before_response.json()
        approval_path = outage_path + "/approve"
        target_path = f"/api/workspace/stations/{target_id}"
        reason = "Keep the approved paper basis and request identity until its reply is received."
        with signed_in_client(endpoint, actor["username"], station_id, qt_app) as client:
            workspace = client.property("workspace")
            outages = client.property("outages")
            assert isinstance(outages, QObject)
            outages.open()
            wait_for_editor_idle(qt_app, outages)
            assert outages.loadOutage(outage_id, False) is True
            wait_for_editor_idle(qt_app, outages)
            assert_public_business_fields(outages.property("state")["selected"], before["record"])
            assert outages.property("state")["role"] == "supervisor"
            assert outages.property("state")["dirty"] is False
            assert endpoint.request_count("POST", approval_path) == 0
            assert endpoint.request_count("GET", target_path) == 0
            assert not endpoint.entered.is_set() and not endpoint.release.is_set()
            endpoint.hold_path = approval_path
            try:
                outages.approveReconciliation(READY_PASSWORD, reason)
                wait_for(qt_app, endpoint.entered.is_set)
                # The real authenticated handler has committed; its unchanged 200 ACK is held.
                committed_response = supervisor.get(outage_path)
                assert committed_response.status_code == 200, committed_response.text
                committed = committed_response.json()
                record = committed["record"]
                assert record["reconciled"] is True
                assert len(record["reconciliation_history"]) == 1
                reconciliation = record["reconciliation"]
                assert reconciliation == record["reconciliation_history"][0]
                assert reconciliation["revision"] == 1
                assert reconciliation["actor_id"] == actor["id"]
                assert reconciliation["reason"] == reason
                assert reconciliation["valid"] is True and reconciliation["is_current"] is True
                assert reconciliation["basis"]["paper_revisions"] == [
                    {"paper_id": paper["id"], "revision": paper["revision"]}
                ]
                assert record["paper_records"] == before["record"]["paper_records"]
                pending = deepcopy(outages.property("state"))
                request_id = pending["pending_request_id"]
                assert str(UUID(request_id)) == request_id
                assert pending["pending_kind"] == "approve"
                assert pending["station_id"] == station_id and pending["role"] == "supervisor"
                assert pending["busy"] is True and pending["uncertain_save"] is False
                assert pending["error"] == ""
                assert_public_business_fields(pending["selected"], before["record"])
                assert endpoint.request_count("POST", approval_path) == 1
                assert not endpoint.release.is_set()
                strict_before_switch = workspace.property("unresolvedRequest")

                # Exercise the actual confirmed-discard overload before asserting the guard.
                workspace.selectStation(target_id, True)
                wait_for_editor_idle(qt_app, workspace)
                guarded = workspace.property("state")
                retained = outages.property("state")
                # Expected RED at 99c055ed: discard bypasses busy and resets station/UUID.
                assert guarded["selected"]["station"]["id"] == station_id, {
                    "source_station": station_id,
                    "selected_station": guarded["selected"].get("station", {}).get("id"),
                    "strict_before_switch": strict_before_switch,
                    "pending_before": request_id,
                    "pending_after": retained["pending_request_id"],
                    "target_gets": endpoint.request_count("GET", target_path),
                }
                assert strict_before_switch is True
                assert workspace.property("unresolvedRequest") is True
                assert guarded["error"] == "workspace_uncertain_request"
                assert endpoint.request_count("GET", target_path) == 0
                assert retained["station_id"] == station_id
                assert retained["pending_request_id"] == request_id
                assert retained["pending_kind"] == "approve"
                assert retained["busy"] is True and retained["uncertain_save"] is False
                assert retained["selected"] == pending["selected"]
                assert retained["forms"] == pending["forms"]
                assert retained["history"] == pending["history"]
                assert endpoint.request_count("POST", approval_path) == 1
                assert not endpoint.release.is_set()
            finally:
                # Always release this owned real response, including the intended RED path.
                endpoint.release.set()

            wait_for_editor_idle(qt_app, outages)
            settled = outages.property("state")
            assert settled["station_id"] == station_id
            assert settled["busy"] is False and settled["uncertain_save"] is False
            assert settled["dirty"] is False and settled["error"] == ""
            assert settled["pending_request_id"] == "" and settled["pending_kind"] == ""
            assert settled["notice"] == "outage_reconciled"
            assert_public_business_fields(settled["selected"], committed["record"])
            assert_public_business_fields(settled["history"], committed["history"])
            assert workspace.property("state")["selected"]["station"]["id"] == station_id
            assert workspace.property("unresolvedRequest") is False
            assert endpoint.request_count("POST", approval_path) == 1
            assert endpoint.request_count("GET", target_path) == 0
            assert READY_PASSWORD not in json.dumps(settled)
            final_response = supervisor.get(outage_path)
            assert final_response.status_code == 200, final_response.text
            assert final_response.json() == committed
            count_after_response = counter.get(round_path)
            assert count_after_response.status_code == 200, count_after_response.text
            assert count_after_response.json() == count_before

            # The original operation has settled; a new explicit context change now works.
            workspace.selectStation(target_id)
            wait_for_editor_idle(qt_app, workspace)
            assert workspace.property("state")["selected"]["station"]["id"] == target_id
            assert endpoint.request_count("GET", target_path) == 1
            assert endpoint.request_count("POST", approval_path) == 1
