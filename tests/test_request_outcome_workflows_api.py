"""Request outcome reads preserve the original turnout and allocation receipts."""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.stock_support import (
    ready_client,
    staff_account,
    stock_payload,
    stock_stations,
)
from tests.turnout_support import (
    READY_PASSWORD,
    TurnoutClock,
    turnout_command,
    turnout_draft,
    turnout_scope,
    turnout_staff,
)


def test_turnout_outcome_returns_original_receipt_and_hides_other_actors(
    admin: TestClient, database_url: str
) -> None:
    active_response = admin.get("/api/active-election")
    assert active_response.status_code == 200, active_response.text
    active = active_response.json()["election"]
    if active is None:
        created = turnout_scope(admin)
        station_contexts = [
            {
                "election": {"id": created["election"]["id"]},
                "station": station,
            }
            for station in created["stations"]
        ]
        schedule = created["schedule"]
    else:
        options = admin.get("/api/accounts/station-options")
        assert options.status_code == 200, options.text
        station_contexts = [
            row for row in options.json()["items"] if row["election"]["id"] == active["id"]
        ]
        schedule = active["schedule"]
    station_ids = [row["station"]["id"] for row in station_contexts]
    assert station_ids
    clock = TurnoutClock()
    with ExitStack() as stack:
        officer, officer_account = stack.enter_context(
            turnout_staff(admin, database_url, clock, station_ids)
        )
        supervisor, _ = stack.enter_context(
            turnout_staff(admin, database_url, clock, station_ids, "supervisor")
        )
        selected: tuple[int, str, list[dict], dict] | None = None
        for station_id in station_ids:
            path = f"/api/workspace/stations/{station_id}/turnout"
            snapshot = officer.get(path)
            assert snapshot.status_code == 200, snapshot.text
            periods = snapshot.json()["items"]
            period = next(
                (
                    row
                    for row in periods
                    if row["status"] == "missing"
                    and (
                        row["period_index"] == 1
                        or any(
                            previous["period_index"] == row["period_index"] - 1
                            and previous["status"] == "approved"
                            and previous["approval_valid"]
                            for previous in periods
                        )
                    )
                ),
                None,
            )
            if period is not None:
                selected = station_id, path, periods, period
                break
        assert selected is not None, "No untouched turnout period has a valid predecessor"
        station_id, path, periods, period = selected
        period_end = datetime.fromisoformat(period["end_at"].replace("Z", "+00:00"))
        clock.value = period_end.astimezone(UTC) + timedelta(seconds=30)
        saved = officer.put(
            path + f"/{period['period_index']}",
            json=turnout_draft(
                expected_schedule_revision=schedule["revision"],
                supplied_hourly=0,
                supplied_cumulative=0,
                event_at=period["end_at"],
                source_context="External signed zero turnout report",
            ),
        )
        assert saved.status_code == 200, saved.text
        submit_command = turnout_command(
            saved.json()["revision"], expected_schedule_revision=schedule["revision"]
        )
        request_id = submit_command["request_id"]
        response = officer.post(path + f"/{period['period_index']}/submit", json=submit_command)
        assert response.status_code == 200, response.text
        submitted = response.json()
        outcome_path = f"/api/workspace/stations/{station_id}/request-outcomes/{request_id}"

        outcome = officer.get(outcome_path, params={"workflow": "turnout"})
        assert outcome.status_code == 200, outcome.text
        assert outcome.json() == {
            "request_id": request_id,
            "workflow": "turnout",
            "status": "committed",
            "record": submitted,
        }

        approved = supervisor.post(
            path + f"/{period['period_index']}/approve",
            json=turnout_command(
                submitted["revision"],
                expected_schedule_revision=schedule["revision"],
                password=READY_PASSWORD,
            ),
        )
        assert approved.status_code == 200, approved.text
        approved_record = approved.json()
        assert approved_record["status"] == "approved"
        after_successor = officer.get(outcome_path, params={"workflow": "turnout"})
        assert after_successor.status_code == 200, after_successor.text
        assert after_successor.json()["record"] == submitted

        hidden = supervisor.get(outcome_path, params={"workflow": "turnout"})
        assert hidden.status_code == 200, hidden.text
        assert hidden.json() == {
            "request_id": request_id,
            "workflow": "turnout",
            "status": "not_found",
        }
        unknown = officer.get(
            f"/api/workspace/stations/{station_id}/request-outcomes/{uuid4()}",
            params={"workflow": "turnout"},
        )
        assert unknown.status_code == 200, unknown.text
        assert unknown.json()["status"] == "not_found"

        wrong_station = officer.get(
            f"/api/workspace/stations/{station_id + 1000000}/request-outcomes/{request_id}",
            params={"workflow": "turnout"},
        )
        assert wrong_station.status_code == 403, wrong_station.text
        assert officer_account["id"] == submitted["actor_id"]


def test_allocation_outcome_returns_immutable_revision_after_successor_and_scopes_actor(
    admin: TestClient, database_url: str
) -> None:
    stations = stock_stations(admin)
    station = stations[0]
    counter_response = admin.post(
        f"/api/elections/{station['election_id']}/constituencies/"
        f"{station['constituency_id']}/stations/{station['id']}/counters",
        json={"code": "C1", "name": "派票櫃台", "request_id": str(uuid4())},
    )
    assert counter_response.status_code == 201, counter_response.text
    counter = counter_response.json()
    account = staff_account(admin, [station["id"]])
    base = f"/api/workspace/stations/{station['id']}"
    with ready_client(database_url, account) as officer:
        received = officer.post(base + "/stock", json=stock_payload())
        assert received.status_code == 201, received.text
        command = {
            "request_id": str(uuid4()),
            "counter_id": counter["id"],
            "series": "普通系列 A",
            "serial_from": "000001",
            "serial_to": "000003",
            "event_at": "2026-11-08T08:05:00+08:00",
        }
        created = officer.post(base + "/allocations", json=command)
        assert created.status_code == 201, created.text
        original = created.json()
        request_id = command["request_id"]
        outcome_path = f"/api/workspace/stations/{station['id']}/request-outcomes/{request_id}"

        outcome = officer.get(outcome_path, params={"workflow": "allocation"})
        assert outcome.status_code == 200, outcome.text
        assert outcome.json() == {
            "request_id": request_id,
            "workflow": "allocation",
            "status": "committed",
            "record": original,
        }

        correction = officer.put(
            base + f"/allocations/{original['id']}",
            json={
                **command,
                "request_id": str(uuid4()),
                "revision": original["revision"],
                "serial_from": "000002",
                "serial_to": "000004",
                "reason": "Preserve the original interval receipt",
            },
        )
        assert correction.status_code == 200, correction.text
        later = officer.get(outcome_path, params={"workflow": "allocation"})
        assert later.status_code == 200, later.text
        assert later.json()["record"] == original

        other_account = staff_account(admin, [station["id"]])
        with ready_client(database_url, other_account) as other:
            hidden = other.get(outcome_path, params={"workflow": "allocation"})
            assert hidden.status_code == 200, hidden.text
            assert hidden.json() == {
                "request_id": request_id,
                "workflow": "allocation",
                "status": "not_found",
            }
        unknown = officer.get(
            f"/api/workspace/stations/{station['id']}/request-outcomes/{uuid4()}",
            params={"workflow": "allocation"},
        )
        assert unknown.status_code == 200, unknown.text
        assert unknown.json()["status"] == "not_found"
        wrong_station = officer.get(
            f"/api/workspace/stations/{stations[1]['id']}/request-outcomes/{request_id}",
            params={"workflow": "allocation"},
        )
        assert wrong_station.status_code == 403, wrong_station.text
