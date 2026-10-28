"""Turnout paper references are selected through public Material desktop controls."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer, wait_for, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.test_turnout_desktop import turnout_boundary_server as turnout_boundary_server
from tests.test_turnout_desktop import turnout_editor as turnout_editor
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def _outage(
    officer: TestClient,
    station_id: int,
    *,
    reference: str,
    ended_at: str = "2026-11-15T09:00:00+08:00",
) -> dict:
    response = officer.post(
        f"/api/workspace/stations/{station_id}/outages",
        json={
            "request_id": str(uuid4()),
            "reference": reference,
            "kind": "network",
            "started_at": "2026-11-15T08:00:00+08:00",
            "ended_at": ended_at,
            "notes": "Turnout reporting was recorded on the signed paper form.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _paper(
    officer: TestClient,
    station_id: int,
    outage_id: int,
    *,
    reference: str,
    action: str,
    period_index: int,
    event_at: str,
) -> dict:
    response = officer.post(
        f"/api/workspace/stations/{station_id}/outages/{outage_id}/paper-records",
        json={
            "request_id": str(uuid4()),
            "expected_outage_revision": 1,
            "paper_reference": reference,
            "workflow": "turnout",
            "action": action,
            "original_event_at": event_at,
            "target": {"period_index": period_index},
            "notes": "Signed turnout worksheet retained during the outage.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_material_turnout_save_submit_paper_receipts_and_unbound_legacy_save(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(officer, station_id, reference="N1 turnout paper " + uuid4().hex[:8])
        outage_id = outage["id"]
        save_paper = _paper(
            officer,
            station_id,
            outage_id,
            reference="N1-TURNOUT-SAVE-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:30:00+08:00",
        )
        submit_paper = _paper(
            officer,
            station_id,
            outage_id,
            reference="N1-TURNOUT-SUBMIT-" + uuid4().hex[:8],
            action="submit",
            period_index=1,
            event_at="2026-11-15T09:30:00+08:00",
        )
        legacy_paper = _paper(
            officer,
            station_id,
            outage_id,
            reference="N1-TURNOUT-LEGACY-" + uuid4().hex[:8],
            action="save",
            period_index=2,
            event_at="2026-11-15T10:30:00+08:00",
        )
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            f"""
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy'])
            frame()
            assert control('turnoutPaperRefresh').property('visible')
            click('turnoutPaperRefresh')
            wait(lambda: len(turnout.property('state')['paper_records']) == 2)
            assert turnout.property('state')['paper_record'] == {{}}

            # The selector starts at ordinary entry; explicitly clear a paper choice.
            assert control('turnoutPaperPicker').property('currentIndex') == 0
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id')
                == {save_paper['id']})
            assert turnout.property('state')['paper_record']['paper_reference'] == (
                '{save_paper['paper_reference']}'
            )
            assert turnout.property('state')['forms']['event_time'] == '2026-11-15 09:30'
            click('turnoutPaperClear')
            wait(lambda: turnout.property('state')['paper_record'] == {{}})

            # An ordinary legacy draft works while a matching paper reference remains pending.
            enter('turnoutHourly', '0')
            enter('turnoutCumulative', '0')
            enter('turnoutEventTime', '2026-11-15 09:30')
            enter('turnoutSource', 'Normal entry before paper re-entry.')
            click('turnoutSave')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['status'] == 'draft'
            assert turnout.property('state')['paper_record'] == {{}}

            click('turnoutPaperRefresh')
            wait(lambda: len(turnout.property('state')['paper_records']) == 2)
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id') == {save_paper['id']})
            assert turnout.property('state')['paper_record']['action'] == 'save'
            # A Save paper must not be silently omitted from an attempted Submit.
            turnout.submit()
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['status'] == 'draft'
            assert turnout.property('state')['paper_record']['id'] == {save_paper['id']}
            assert turnout.property('state')['error']
            assert control('turnoutSave').property('enabled') is True
            assert turnout.selectPaperRecord({save_paper['id']}) is True
            assert turnout.property('state')['error'] == ''
            click('turnoutSave')
            wait(lambda: turnout.property('state')['busy']
                or turnout.property('state')['selected'].get('revision') == 2)
            wait(lambda: not turnout.property('state')['busy'])
            save_state = turnout.property('state')
            assert save_state['selected'].get('revision') == 2, {{
                'error': save_state['error'],
                'notice': save_state['notice'],
                'selected': save_state['selected'],
                'paper_record': save_state['paper_record'],
                'selected_period': save_state['selected_period'],
                'role': save_state['role'],
                'busy': save_state['busy'],
            }}
            assert turnout.property('state')['selected']['status'] == 'draft'
            assert turnout.property('state')['paper_record'] == {{}}

            # The matching Submit paper re-enters the already saved, exact period-one draft.
            click('turnoutPaperRefresh')
            wait(lambda: len(turnout.property('state')['paper_records']) == 1)
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id')
                == {submit_paper['id']})
            assert turnout.property('state')['paper_record']['action'] == 'submit'
            assert turnout.property('state')['forms']['event_time'] == '2026-11-15 09:30'
            click('turnoutSubmit')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['status'] == 'submitted'
            assert turnout.property('state')['paper_record'] == {{}}

            # A target change clears binding; ordinary period-two Save leaves its paper pending.
            assert turnout.selectPeriod(2, False) is True
            wait(lambda: turnout.property('state')['selected_period'] == 2
                and not turnout.property('state')['busy'])
            assert turnout.property('state')['paper_record'] == {{}}
            enter('turnoutHourly', '0')
            enter('turnoutCumulative', '0')
            enter('turnoutEventTime', '2026-11-15 10:30')
            enter('turnoutSource', 'Ordinary period-two entry.')
            click('turnoutSave')
            wait(lambda: not turnout.property('state')['busy'])
            assert turnout.property('state')['selected']['period_index'] == 2
            assert turnout.property('state')['selected']['status'] == 'draft'
            """,
        )

        assert https_server.request_count("POST", path + "/1/submit") == 1
        assert https_server.request_count("PUT", path + "/1") == 2
        assert https_server.request_count("PUT", path + "/2") == 1

        period_one = officer.get(path + "/1")
        period_two = officer.get(path + "/2")
        assert period_one.status_code == period_two.status_code == 200
        assert period_one.json()["status"] == "submitted"
        assert period_one.json()["supplied_hourly"] == 0
        assert period_one.json()["supplied_cumulative"] == 0
        assert period_two.json()["status"] == "draft"
        assert period_two.json()["supplied_hourly"] == 0

        outage_record = officer.get(f"/api/workspace/stations/{station_id}/outages/{outage_id}")
        assert outage_record.status_code == 200, outage_record.text
        papers = {row["id"]: row for row in outage_record.json()["record"]["paper_records"]}
        saved_reentry = papers[save_paper["id"]]
        submitted_reentry = papers[submit_paper["id"]]
        unchanged_legacy = papers[legacy_paper["id"]]
        assert saved_reentry["status"] == "entered"
        assert saved_reentry["reentry"]["record"]["revision"] == 2
        assert saved_reentry["reentry"]["record"]["status"] == "draft"
        assert saved_reentry["reentry"]["record"]["event_at"] == "2026-11-15T01:30:00Z"
        assert saved_reentry["reentry"]["actor_id"] == account["id"]
        assert submitted_reentry["status"] == "entered"
        assert submitted_reentry["reentry"]["record"] == period_one.json()
        assert submitted_reentry["reentry"]["actor_id"] == account["id"]
        assert unchanged_legacy["status"] == "pending"
        assert unchanged_legacy["reentry"] is None


def test_assigned_counting_officer_cannot_write_turnout_paper_reentry(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with (
        turnout_staff(admin, database_url, clock, [station_id]) as (polling, _),
        turnout_staff(admin, database_url, clock, [station_id], "counting_officer") as (
            _counting_api,
            counting_account,
        ),
    ):
        outage = _outage(polling, station_id, reference="N1 role paper " + uuid4().hex[:8])
        paper = _paper(
            polling,
            station_id,
            outage["id"],
            reference="N1-COUNTING-OFFICER-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:30:00+08:00",
        )
        with turnout_editor(https_server, qt_app, counting_account, station_id) as (
            client,
            editor,
        ):
            assert client.property("state")["account"]["role"] == "counting_officer"
            editor.refreshPaperRecords()
            wait_for_editor_idle(qt_app, editor)
            rows = editor.property("state")["paper_records"]
            assert any(row["id"] == paper["id"] for row in rows)
            editor.selectPaperRecord(paper["id"])
            editor.setField("supplied_hourly", "0")
            editor.save()
            wait_for_editor_idle(qt_app, editor)
            state = editor.property("state")
            assert state["role"] == "counting_officer"
            assert state["dirty"] is False
            assert state["error"] == "polling_officer_required"
            assert https_server.request_count("PUT", scope["path"] + "/1") == 0
            record = polling.get(
                f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
            ).json()["record"]["paper_records"]
            assert next(row for row in record if row["id"] == paper["id"])["status"] == "pending"


def test_submit_paper_keeps_saved_observation_time_when_paper_time_differs(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(
            officer,
            station_id,
            reference="N1 submit paper time " + uuid4().hex[:8],
            ended_at="2026-11-15T10:00:00+08:00",
        )
        paper = _paper(
            officer,
            station_id,
            outage["id"],
            reference="N1-TURNOUT-SUBMIT-TIME-" + uuid4().hex[:8],
            action="submit",
            period_index=1,
            event_at="2026-11-15T09:45:00+08:00",
        )
        draft = officer.put(
            f"{path}/1",
            json=turnout_draft(
                supplied_hourly=0,
                supplied_cumulative=0,
                event_at="2026-11-15T09:30:00+08:00",
                source_context="Saved observation time differs from paper completion.",
            ),
        )
        assert draft.status_code == 200, draft.text
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            f"""
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy'])
            click('turnoutPaperRefresh')
            wait(lambda: len(turnout.property('state')['paper_records']) == 1)
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id') == {paper['id']})
            assert turnout.property('state')['forms']['event_time'] == '2026-11-15 09:30'
            assert control('turnoutSubmit').property('enabled') is True
            click('turnoutSubmit')
            wait(lambda: not turnout.property('state')['busy'])
            state = turnout.property('state')
            assert state['error'] == '', state['error']
            assert state['selected'].get('status') == 'submitted', state['selected']
            assert turnout.property('state')['selected']['event_at'] == '2026-11-15T01:30:00Z'
            assert turnout.property('state')['paper_record'] == {{}}
            """,
        )

        submitted = officer.get(f"{path}/1")
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["event_at"] == "2026-11-15T01:30:00Z"
        record = officer.get(f"/api/workspace/stations/{station_id}/outages/{outage['id']}")
        assert record.status_code == 200, record.text
        linked = record.json()["record"]["paper_records"][0]
        assert linked["id"] == paper["id"]
        assert linked["status"] == "entered"
        assert linked["original_event_at"] == "2026-11-15T01:45:00Z"
        assert linked["reentry"]["record"]["event_at"] == "2026-11-15T01:30:00Z"


def test_period_change_invalidates_inflight_turnout_paper_list_read(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(officer, station_id, reference="N1 period switch " + uuid4().hex[:8])
        period_one = _paper(
            officer,
            station_id,
            outage["id"],
            reference="N1-TURNOUT-PERIOD-1-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:00:00+08:00",
        )
        period_two = _paper(
            officer,
            station_id,
            outage["id"],
            reference="N1-TURNOUT-PERIOD-2-" + uuid4().hex[:8],
            action="save",
            period_index=2,
            event_at="2026-11-15T10:00:00+08:00",
        )
        with turnout_editor(https_server, qt_app, account, station_id) as (_, editor):
            wait_for_editor_idle(qt_app, editor)
            if not editor.state["paper_refreshing"]:
                assert [row["id"] for row in editor.state["paper_records"]] == [
                    period_one["id"]
                ]
                assert editor.refreshPaperRecords() is True
            assert editor.state["paper_refreshing"] is True
            assert editor.selectPeriod(2, False) is True
            wait_for(
                qt_app,
                lambda: editor.state["selected_period"] == 2 and not editor.state["busy"],
            )
            wait_for(qt_app, lambda: not editor.state["paper_refreshing"])
            assert [row["id"] for row in editor.state["paper_records"]] == [period_two["id"]]


def test_uncertain_turnout_paper_write_stays_bound_until_public_outcome_is_committed(
    admin: TestClient,
    database_url: str,
    turnout_boundary_server,
    qt_app,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    server = turnout_boundary_server
    server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(officer, station_id, reference="N1 uncertain paper " + uuid4().hex[:8])
        paper = _paper(
            officer,
            station_id,
            outage["id"],
            reference="N1-UNCERTAIN-TURNOUT-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:30:00+08:00",
        )
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
        with turnout_editor(server, qt_app, account, station_id) as (client, editor):
            editor.refreshPaperRecords()
            wait_for_editor_idle(qt_app, editor)
            wait_for(qt_app, lambda: not editor.property("state")["paper_refreshing"])
            assert any(
                row["id"] == paper["id"]
                for row in editor.property("state")["paper_records"]
            )
            assert editor.selectPaperRecord(paper["id"]) is True
            assert (
                editor.property("state")["paper_record"]["paper_reference"]
                == paper["paper_reference"]
            )
            editor.setField("supplied_hourly", "0")
            editor.setField("supplied_cumulative", "0")
            editor.setField("event_time", "2026-11-15 09:30")
            editor.setField("source_context", "Paper turnout retained through a lost reply.")
            server.truncate_next_mutation = True
            editor.save()
            wait_for_editor_idle(qt_app, editor, timeout=10)

            uncertain = editor.property("state")
            assert uncertain["paper_record"]["id"] == paper["id"]
            assert uncertain["error"] in ("disconnected", "request_failed", "invalid_response")
            recovery = client.property("recovery")
            recovery.open()
            wait_for_editor_idle(qt_app, recovery)
            commands = recovery.property("state")["commands"]
            command = next(
                row for row in commands
                if row["workflow"] == "turnout" and row["path"] == path + "/1"
            )
            assert command["status"] == "uncertain"
            assert command["payload"]["paper_record_id"] == paper["id"]
            request_id = command["request_id"]
            assert READY_PASSWORD not in repr(command)
            assert "password" not in repr(command).lower()

            assert editor.selectPaperRecord(0) is False
            assert editor.property("state")["paper_record"]["id"] == paper["id"]
            recovery.checkOutcome(request_id)
            wait_for(
                qt_app,
                lambda: any(
                    row["request_id"] == request_id and row["status"] == "committed"
                    for row in recovery.property("state")["commands"]
                ),
            )
            wait_for(qt_app, lambda: editor.property("state")["paper_record"] == {})
            wait_for(
                qt_app,
                lambda: not editor.property("state")["busy"]
                and editor.property("state")["selected"].get("status") == "draft",
            )
            assert editor.property("state")["selected"]["status"] == "draft"
            assert editor.property("state")["selected"]["supplied_hourly"] == 0

        assert server.request_count("PUT", path + "/1") == 1
        outage_record = officer.get(
            f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
        ).json()["record"]
        linked = next(row for row in outage_record["paper_records"] if row["id"] == paper["id"])
        assert linked["status"] == "entered"
        assert linked["reentry"]["request_id"] == request_id
        assert linked["reentry"]["record"]["supplied_hourly"] == 0
        history = officer.get(path + "/1/history")
        assert history.status_code == 200, history.text
        assert len(history.json()["items"]) == 1


@pytest.mark.parametrize("locale", ["en", "tc", "sc"])
def test_material_precise_save_paper_preserves_time_and_missing_cumulative(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    locale: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    path = scope["path"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(officer, station_id, reference="Precise turnout " + uuid4().hex[:8])
        paper = _paper(
            officer,
            station_id,
            outage["id"],
            reference="TURNOUT-PRECISE-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:30:12.123456+08:00",
        )
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
            },
            f"""
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy'])
            click('turnoutPaperRefresh')
            wait(lambda: len(turnout.property('state')['paper_records']) == 1)
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id') == {paper['id']})
            assert control('turnoutEventTime').property('text') == '2026-11-15 09:30:12.123456'
            enter('turnoutHourly', '0')
            assert control('turnoutCumulative').property('text') == ''
            enter('turnoutSource', 'Paper supplies hourly zero; cumulative figure not supplied.')
            assert control('turnoutSave').property('enabled') is True
            click('turnoutSave')
            wait(lambda: not turnout.property('state')['busy'])
            saved = turnout.property('state')
            assert saved['selected'].get('revision') == 1, {{'error': saved['error']}}
            assert saved['selected']['status'] == 'draft'
            assert saved['selected']['event_at'] == '2026-11-15T01:30:12.123456Z'
            assert saved['selected']['supplied_hourly'] == 0
            assert saved['selected']['supplied_cumulative'] is None
            assert saved['paper_record'] == {{}}
            assert saved['dirty'] is False
            """,
        )
        assert https_server.request_count("PUT", path + "/1") == 1
        response = officer.get(path + "/1")
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["status"] == "draft"
        assert record["event_at"] == "2026-11-15T01:30:12.123456Z"
        assert record["supplied_hourly"] == 0
        assert record["supplied_cumulative"] is None
        result = officer.get(
            f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
        )
        assert result.status_code == 200, result.text
        linked = next(row for row in result.json()["record"]["paper_records"]
                      if row["id"] == paper["id"])
        assert linked["status"] == "entered"
        assert linked["original_event_at"] == "2026-11-15T01:30:12.123456Z"
        assert linked["reentry"]["record"] == record
        assert linked["reentry"]["actor_id"] == account["id"]


@pytest.mark.parametrize(
    ("locale", "server_entry_caption", "original_caption"),
    [
        ("tc", "伺服器記錄時間", "紙本原始事件時間（香港時間）"),
        ("sc", "服务器记录时间", "纸本原始事件时间（香港时间）"),
        ("en", "Server entry time", "Original paper event time (HKT)"),
    ],
    ids=("tc", "sc", "en"),
)
def test_material_turnout_paper_server_entry_caption_preserves_separate_times(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    locale: str,
    server_entry_caption: str,
    original_caption: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    clock = TurnoutClock()
    https_server.clock.value = clock.value
    with turnout_staff(admin, database_url, clock, [station_id]) as (officer, account):
        outage = _outage(officer, station_id, reference="Entry caption " + uuid4().hex[:8])
        paper = _paper(
            officer,
            station_id,
            outage["id"],
            reference="N1-TURNOUT-CAPTION-" + uuid4().hex[:8],
            action="save",
            period_index=1,
            event_at="2026-11-15T09:30:00+08:00",
        )
        assert paper["original_event_at"] == "2026-11-15T01:30:00Z"
        assert paper["entered_at"] == "2026-11-15T04:00:00Z"
        monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "client-state"))
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": locale,
                "paper_id": paper["id"],
                "original_event_at": paper["original_event_at"],
                "entered_at": paper["entered_at"],
                "server_entry_caption": server_entry_caption,
                "original_caption": original_caption,
            },
            """
            def visible_texts(root):
                pending = list(root.childItems())
                texts = []
                while pending:
                    item = pending.pop()
                    text = item.property('text')
                    if item.property('visible') and isinstance(text, str):
                        texts.append(text)
                    pending.extend(item.childItems())
                return texts

            click('turnoutNavigation')
            turnout = controller.property('turnout')
            wait(lambda: not turnout.property('state')['busy']
                and not turnout.property('state')['paper_refreshing'])
            click('turnoutPaperRefresh')
            wait(lambda: not turnout.property('state')['paper_refreshing']
                and [row['id'] for row in turnout.property('state')['paper_records']]
                == [setup['paper_id']])
            assert control('turnoutPaperPicker').property('currentIndex') == 0
            choose('turnoutPaperPicker', 1)
            wait(lambda: turnout.property('state')['paper_record'].get('id')
                == setup['paper_id'])
            frame()

            entry = control('turnoutPaperServerEntryTime')
            assert entry.property('visible') is True
            assert entry.property('caption') == setup['server_entry_caption'], (
                entry.property('caption'), setup['server_entry_caption'])
            assert setup['server_entry_caption'] in visible_texts(entry)
            assert entry.property('value') == '2026-11-15 12:00 HKT'
            entry_value = control('turnoutPaperServerEntryTimeValue')
            assert entry_value.property('visible') is True
            assert entry_value.property('text') == '2026-11-15 12:00 HKT'

            original = control('turnoutPaperOriginalEventAt')
            assert original.property('visible') is True
            assert original.property('caption') == setup['original_caption']
            assert setup['original_caption'] in visible_texts(original)
            assert original.property('value') == '2026-11-15 09:30 HKT'
            original_value = control('turnoutPaperOriginalEventAtValue')
            assert original_value.property('visible') is True
            assert original_value.property('text') == '2026-11-15 09:30 HKT'
            selected = turnout.property('state')['paper_record']
            assert selected['original_event_at'] == setup['original_event_at']
            assert selected['entered_at'] == setup['entered_at']
            assert selected['status'] == 'pending'
            assert control('turnoutEventTime').property('text') == '2026-11-15 09:30'
            """,
        )
        response = officer.get(
            f"/api/workspace/stations/{station_id}/outages/{outage['id']}"
        )
        assert response.status_code == 200, response.text
        stored = next(
            row for row in response.json()["record"]["paper_records"]
            if row["id"] == paper["id"]
        )
        assert stored["original_event_at"] == paper["original_event_at"]
        assert stored["entered_at"] == paper["entered_at"]
        assert stored["status"] == "pending"
        assert stored["reentry"] is None
