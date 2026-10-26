"""Workspace station changes are guarded through public uncertain paper-reentry flows."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD as BOX_READY_PASSWORD
from tests.box_support import box_stations
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_client_recovery_contract_desktop import RecoveryFaultServer
from tests.test_client_recovery_contract_desktop import (
    recovery_fault_server as recovery_fault_server,
)
from tests.turnout_support import READY_PASSWORD as TURNOUT_READY_PASSWORD
from tests.turnout_support import TurnoutClock, turnout_draft, turnout_staff


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def reset_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture(autouse=True)
def isolate_client_journal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "workspace-guard-journal"))


def _paper_outage(
    officer: TestClient,
    station_id: int,
    *,
    workflow: str,
    action: str,
    target: dict[str, int],
    original_event_at: str,
) -> dict:
    outage_path = f"/api/workspace/stations/{station_id}/outages"
    outage = officer.post(
        outage_path,
        json={
            "request_id": str(uuid4()),
            "reference": "T25 workspace-guard outage " + uuid4().hex[:8],
            "kind": "network",
            "started_at": "2026-11-15T07:30:00+08:00",
            "ended_at": "2026-11-15T08:30:00+08:00",
            "notes": "A signed operational paper record remained available.",
        },
    )
    assert outage.status_code == 201, outage.text
    paper = officer.post(
        outage_path + f"/{outage.json()['id']}/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": "T25-WORKSPACE-PAPER-" + uuid4().hex[:10],
            "workflow": workflow,
            "action": action,
            "original_event_at": original_event_at,
            "target": target,
            "notes": "Paper record retained for assigned-station reentry.",
        },
    )
    assert paper.status_code == 201, paper.text
    assert paper.json()["status"] == "pending"
    return {"outage_path": outage_path + f"/{outage.json()['id']}", "paper": paper.json()}


def test_count_workspace_stays_on_source_station_until_committed_outcome_check(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        station_id = setup["stations"]["N1"]["id"]
        other_station_id = setup["stations"]["N2"]["id"]
        recovery_fault_server.clock.value = setup["clock"].value
        counting_api = setup["clients"]["bothcounting"]
        options_response = counting_api.get(setup["rounds_path"])
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()
        f1 = counting_api.post(setup["rounds_path"], json=complete_f1_command(options))
        assert f1.status_code == 201, f1.text
        round_id = f1.json()["id"]
        round_path = f"{setup['rounds_path']}/{round_id}"
        f2 = counting_api.put(
            round_path + "/f2",
            json=complete_f2_command(options),
        )
        assert f2.status_code == 200, f2.text

        paper_setup = _paper_outage(
            counting_api,
            station_id,
            workflow="count",
            action="submit",
            target={"scope_id": setup["scope"]["id"], "round_id": round_id},
            original_event_at="2026-11-15T23:05:00+08:00",
        )
        submit_path = round_path + "/submit"
        recovery_fault_server.fail_after_path = submit_path

        scenario = """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            def count_idle():
                return not editor.property('state')['busy']
            wait(count_idle)
            assert editor.selectScope(SCOPE_ID) is True
            wait(count_idle)
            assert editor.selectRound(ROUND_ID) is True
            wait(lambda: count_idle()
                and not editor.property('state')['paper_loading']
                and any(row['id'] == PAPER_ID
                    for row in editor.property('state')['paper_records']))
            picker = control('countRoundPaperRecord')
            for index in range(int(picker.property('count'))):
                choose('countRoundPaperRecord', index)
                wait(count_idle)
                if editor.property('state')['paper_record'].get('id') == PAPER_ID:
                    break
            assert editor.property('state')['paper_record']['id'] == PAPER_ID
            click('countSubmit')
            wait(lambda: editor.property('state')['uncertain_save'])

            workspace = controller.workspace
            workspace.selectStation(OTHER_STATION_ID)
            wait(lambda: not workspace.property('state')['busy'])
            state = workspace.property('state')
            assert state['selected']['station']['id'] == SOURCE_STATION_ID
            assert editor.property('state')['uncertain_save'] is True
            assert editor.property('state')['paper_record']['id'] == PAPER_ID

            recovery = controller.recovery
            recovery.open()
            wait(lambda: not recovery.property('state')['busy'])
            command = next(row for row in recovery.property('state')['commands']
                if row['request_id'] and row['workflow'] == 'count'
                and row['path'] == SUBMIT_PATH)
            assert command['status'] == 'uncertain'
            request_id = command['request_id']
            recovery.checkOutcome(request_id)
            wait(lambda: not recovery.property('state')['busy']
                and next(row for row in recovery.property('state')['commands']
                    if row['request_id'] == request_id)['status'] == 'committed')
            wait(lambda: count_idle()
                and editor.property('state')['selected']['status'] == 'submitted')
            assert editor.property('state')['uncertain_save'] is False
            assert editor.property('state')['paper_record'] == {}

            workspace.selectStation(OTHER_STATION_ID)
            wait(lambda: not workspace.property('state')['busy'])
            assert workspace.property('state')['selected']['station']['id'] == OTHER_STATION_ID
        """.replace("SCOPE_ID", str(setup["scope"]["id"]))
        scenario = scenario.replace("ROUND_ID", str(round_id))
        scenario = scenario.replace("PAPER_ID", str(paper_setup["paper"]["id"]))
        scenario = scenario.replace("SOURCE_STATION_ID", str(station_id))
        scenario = scenario.replace("OTHER_STATION_ID", str(other_station_id))
        scenario = scenario.replace("SUBMIT_PATH", repr(submit_path))
        run_workspace_qml(
            {
                "server": recovery_fault_server.url,
                "username": setup["accounts"]["bothcounting"]["username"],
                "password": BOX_READY_PASSWORD,
                "station_id": station_id,
            },
            scenario,
        )

        outage = counting_api.get(paper_setup["outage_path"])
        assert outage.status_code == 200, outage.text
        entered = outage.json()["record"]["paper_records"]
        assert len(entered) == 1
        assert entered[0]["status"] == "entered"
        assert entered[0]["reentry"]["record"]["status"] == "submitted"


def test_turnout_workspace_stays_locked_after_not_found_until_original_retry_commits(
    admin: TestClient,
    database_url: str,
    recovery_fault_server: RecoveryFaultServer,
    tmp_path: Path,
) -> None:
    stations = box_stations(admin)
    station_id = stations["N1"]["id"]
    other_station_id = stations["N2"]["id"]
    clock = TurnoutClock()
    recovery_fault_server.clock.value = clock.value
    path = f"/api/workspace/stations/{station_id}/turnout"
    with turnout_staff(
        admin,
        database_url,
        clock,
        [station_id, other_station_id],
    ) as (officer, account):
        saved = officer.put(
            path + "/1",
            json=turnout_draft(
                supplied_hourly=10,
                supplied_cumulative=10,
                event_at="2026-11-15T08:00:00+08:00",
                source_context="Ordinary turnout draft saved before paper submission.",
            ),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "draft"
        paper_setup = _paper_outage(
            officer,
            station_id,
            workflow="turnout",
            action="submit",
            target={"period_index": 1},
            original_event_at="2026-11-15T08:00:00+08:00",
        )
        submit_path = path + "/1/submit"
        recovery_fault_server.fail_before_path = submit_path
        not_found_marker = tmp_path / "turnout-not-found-checked"
        retry_release = tmp_path / "turnout-retry-release"
        scenario = """
            click('turnoutNavigation')
            turnout = controller.turnout
            def turnout_idle():
                return not any(turnout.property('state')[key] for key in ('busy', 'refreshing'))
            wait(turnout_idle)
            click('turnoutPaperRefresh')
            wait(lambda: not turnout.property('state')['paper_refreshing']
                and any(row['id'] == PAPER_ID
                    for row in turnout.property('state')['paper_records']))
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id') == PAPER_ID)
            assert turnout.property('state')['selected']['status'] == 'draft'
            assert turnout.property('state')['dirty'] is False
            click('turnoutSubmit')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['uncertain_save'] is True
            assert turnout.property('state')['paper_record']['id'] == PAPER_ID

            workspace = controller.workspace
            workspace.selectStation(OTHER_STATION_ID)
            wait(lambda: not workspace.property('state')['busy'])
            assert workspace.property('state')['selected']['station']['id'] == SOURCE_STATION_ID
            assert turnout.property('state')['paper_record']['id'] == PAPER_ID
            assert turnout.property('state')['uncertain_save'] is True

            recovery = controller.recovery
            recovery.open()
            wait(lambda: not recovery.property('state')['busy'])
            command = next(row for row in recovery.property('state')['commands']
                if row['workflow'] == 'turnout' and row['path'] == SUBMIT_PATH)
            assert command['status'] == 'uncertain'
            request_id = command['request_id']
            recovery.checkOutcome(request_id)
            wait(lambda: not recovery.property('state')['busy']
                and next(row for row in recovery.property('state')['commands']
                    if row['request_id'] == request_id)['error'] == 'request_not_found')
            workspace.selectStation(OTHER_STATION_ID)
            wait(lambda: not workspace.property('state')['busy'])
            assert workspace.property('state')['selected']['station']['id'] == SOURCE_STATION_ID
            assert turnout.property('state')['paper_record']['id'] == PAPER_ID
            assert turnout.property('state')['uncertain_save'] is True

            Path('NOT_FOUND_MARKER').write_text('checked')
            wait(lambda: Path('RETRY_RELEASE').exists())
            recovery.retry(request_id, '')
            wait(lambda: not recovery.property('state')['busy'])
            retried = next(row for row in recovery.property('state')['commands']
                if row['request_id'] == request_id)
            assert retried['status'] == 'committed', {
                'status': retried['status'],
                'error': retried.get('error'),
                'notice': recovery.property('state')['notice'],
            }
            wait(lambda: turnout_idle()
                and turnout.property('state')['selected'].get('status') == 'submitted')
            assert turnout.property('state')['paper_record'] == {}
            assert turnout.property('state')['uncertain_save'] is False
            workspace.selectStation(OTHER_STATION_ID)
            wait(lambda: not workspace.property('state')['busy'])
            assert workspace.property('state')['selected']['station']['id'] == OTHER_STATION_ID
        """.replace("PAPER_ID", str(paper_setup["paper"]["id"]))
        scenario = scenario.replace("SUBMIT_PATH", repr(submit_path))
        scenario = scenario.replace("SOURCE_STATION_ID", str(station_id))
        scenario = scenario.replace("OTHER_STATION_ID", str(other_station_id))
        scenario = scenario.replace("NOT_FOUND_MARKER", str(not_found_marker))
        scenario = scenario.replace("RETRY_RELEASE", str(retry_release))
        qml_errors: list[BaseException] = []

        def run_qml() -> None:
            try:
                run_workspace_qml(
                    {
                        "server": recovery_fault_server.url,
                        "username": account["username"],
                        "password": TURNOUT_READY_PASSWORD,
                        "station_id": station_id,
                    },
                    scenario,
                )
            except BaseException as error:
                qml_errors.append(error)

        worker = threading.Thread(target=run_qml)
        worker.start()
        try:
            deadline = time.monotonic() + 15
            while (
                not not_found_marker.exists()
                and worker.is_alive()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
        finally:
            recovery_fault_server.fail_before_path = ""
            retry_release.write_text("retry original")
            worker.join(timeout=45)
        assert not worker.is_alive(), "The Material retry flow did not finish after release."
        if qml_errors:
            raise qml_errors[0]
        assert not_found_marker.exists(), (
            "The Material flow did not complete the public not-found outcome check."
        )

        current = officer.get(path + "/1")
        assert current.status_code == 200, current.text
        assert current.json()["status"] == "submitted"
        outage = officer.get(paper_setup["outage_path"])
        assert outage.status_code == 200, outage.text
        entered = outage.json()["record"]["paper_records"]
        assert len(entered) == 1
        assert entered[0]["status"] == "entered"
        assert entered[0]["reentry"]["record"] == current.json()
