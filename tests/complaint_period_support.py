"""Public API arrangements for frozen complaint reporting periods."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.complaint_support import complaint_stations
from tests.lifecycle_support import schedule_payload

READY_PASSWORD = "Complaint-Ready-Test-84!"


def complaint_period_scope(admin: TestClient, **changes: object) -> dict:
    setup = complaint_stations(admin, activate=False)
    payload = schedule_payload(revision=1, planned_closing_at="2026-11-15T10:10:00+08:00")
    payload.update(changes)
    schedule = admin.put(
        f"/api/elections/{setup['election']['id']}/schedule",
        json=payload,
    )
    assert schedule.status_code == 200
    activated = admin.post(
        f"/api/elections/{setup['election']['id']}/activate",
        json={
            "election_revision": 1,
            "schedule_revision": 2,
        },
    )
    assert activated.status_code == 200
    station = setup["N1"]
    return {
        **setup,
        "station": station,
        "path": f"/api/workspace/stations/{station['id']}/complaint-periods",
        "case_path": f"/api/workspace/stations/{station['id']}/complaints",
    }


def period_command(revision: int = 0, **changes: object) -> dict:
    return {
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "expected_schedule_revision": 2,
        **changes,
    }
