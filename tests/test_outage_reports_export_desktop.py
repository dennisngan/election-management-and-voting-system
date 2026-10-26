"""Outage statement PDF/CSV exports use the authenticated desktop download path."""

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, BoxClock, box_staff, box_stations
from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url


def test_assigned_officer_exports_outage_statement_pdf_and_csv_from_desktop(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
) -> None:
    stations = box_stations(admin)
    station_id = stations["N1"]["id"]
    clock = BoxClock()
    https_server.clock.value = clock.value
    base = f"/api/workspace/stations/{station_id}/outages"
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (
        officer,
        account,
    ):
        created = officer.post(
            base,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 desktop outage export " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T08:00:00+08:00",
                "ended_at": "2026-11-15T08:30:00+08:00",
                "notes": "Signed paper records were retained.",
            },
        )
        assert created.status_code == 201, created.text
        outage_id = created.json()["id"]
        pdf_path = tmp_path / "outage-statement.pdf"
        csv_path = tmp_path / "outage-statement.csv"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "pdf_path": str(pdf_path),
                "csv_path": str(csv_path),
            },
            f"""
            from pathlib import Path

            click('outagesNavigation')
            editor = controller.outages
            wait(lambda: not editor.property('state')['busy'])
            assert editor.loadOutage({outage_id}, False) is True
            wait(lambda: not editor.property('state')['busy'])

            editor.downloadReport('pdf', setup['pdf_path'], 'en')
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['export_path'] == setup['pdf_path']
            assert Path(setup['pdf_path']).read_bytes().startswith(b'%PDF-')

            editor.downloadReport('csv', setup['csv_path'], 'en')
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['export_path'] == setup['csv_path']
            assert Path(setup['csv_path']).read_bytes().startswith(bytes.fromhex('efbbbf'))
            """,
        )
