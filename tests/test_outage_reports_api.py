"""Application-outage report reads use the normal assigned-station API boundary."""

from fastapi.testclient import TestClient

from tests.test_turnout_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_turnout_api import database_url as database_url
from tests.turnout_support import TurnoutClock, turnout_scope, turnout_staff


def test_missing_outage_statement_returns_the_assigned_api_not_found_dto(
    admin: TestClient, database_url: str,
) -> None:
    scope = turnout_scope(admin)
    station_id = scope["stations"][0]["id"]
    with turnout_staff(admin, database_url, TurnoutClock(), [station_id]) as (officer, _):
        response = officer.get(
            f"/api/workspace/stations/{station_id}/outages/2147483647/statement"
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "outage_not_found"
