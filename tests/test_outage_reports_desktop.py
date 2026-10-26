"""Application outage statements through the public Material desktop client."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


def test_assigned_officer_previews_the_selected_outage_statement_in_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options = officer.get(rounds_path)
        assert options.status_code == 200, options.text
        counted = officer.post(rounds_path, json=complete_f1_command(options.json()))
        assert counted.status_code == 201, counted.text

        outage_path = f"/api/workspace/stations/{station_id}/outages"
        created = officer.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T25 desktop report outage " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:00:01.123456+08:00",
                "ended_at": "2026-11-15T23:30:02.654321+08:00",
                "notes": "Signed paper was retained while the service was unavailable.",
            },
        )
        assert created.status_code == 201, created.text
        outage_id = created.json()["id"]
        statement_path = f"{outage_path}/{outage_id}/statement"
        report = officer.get(statement_path, params={"locale": "en"})
        assert report.status_code == 200, report.text
        expected = report.json()
        assert expected["outage_id"] == outage_id
        assert expected["revision"] == 1
        assert expected["locale"] == "en"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
            },
            f"""
            click('outagesNavigation')
            editor = controller.outages
            wait(lambda: not editor.property('state')['busy'])
            assert editor.loadOutage({outage_id}, False) is True
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['selected']['id'] == {outage_id}
            click('outageReportPreview')
            wait(lambda: not editor.property('state')['busy'])
            shown = editor.property('state')['report']
            assert shown['outage_id'] == {outage_id}
            assert shown['revision'] == 1
            assert shown['locale'] == 'en'
            assert shown['preview_lines'] == {expected['preview_lines']!r}
            preview = control('outageReportPreviewText').property('text')
            assert 'T25 desktop report outage' in preview
            assert '2026-11-15 23:00:01.123456 HKT' in preview
            """,
        )
