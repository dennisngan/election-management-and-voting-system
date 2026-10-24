"""Material controls preserve explicit special-paper counts in all desktop languages."""

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_material_special_paper_fields_save_each_category_with_the_selected_source(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": setup["snapshot"]["station_id"],
             "locale": locale},
            """
            click('specialPapersNavigation')
            editor = controller.property('specialPapers')
            def idle():
                return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            frame()
            assert control('specialNeverIssuedTotal').property('text') == '—'
            enter('specialEventTime', '2026-11-15 09:45:17.123456')
            choose('specialBasisPicker', 1)
            assert editor.property('state')['basis']['revision'] == 1
            assert control('specialCount_replacement_issued_quantity').property('text') == ''
            click('specialZeroAll')
            for key in ('replacement_issued_quantity', 'spoilt_original_quantity',
                        'tendered_issued_quantity', 'retrieved_refused_quantity',
                        'retrieved_found_quantity', 'retrieved_held_quantity'):
                assert control('specialCount_' + key).property('text') == '0'
            enter('specialCount_replacement_issued_quantity', '2')
            enter('specialCount_spoilt_original_quantity', '2')
            enter('specialCount_tendered_issued_quantity', '1')
            enter('specialCount_retrieved_refused_quantity', '1')
            enter('specialCount_retrieved_found_quantity', '1')
            enter('specialCount_retrieved_held_quantity', '1')
            click('specialSave')
            wait(idle)
            saved = editor.property('state')
            assert saved['error'] == '' and saved['dirty'] is False
            assert saved['selected']['revision'] == 1
            assert saved['selected']['event_at'] == '2026-11-15T01:45:17.123456Z'
            assert control('specialNeverIssuedTotal').property('text') == '7'
            assert control('specialRetrievedTotal').property('text') == '3'
            assert control('specialEstimatedBoxTotal').property('text') == '2'
            assert control('specialCount_replacement_issued_quantity').property('readOnly') is True
            assert control('specialSave').property('visible') is False
            assert control('specialEdit').property('visible') is True
            """,
        )
        observed = setup["officer"].get(setup["path"])
        assert observed.status_code == 200
        selected = observed.json()["latest"]
        assert selected["replacement_issued_quantity"] == selected["spoilt_original_quantity"] == 2
        assert selected["tendered_issued_quantity"] == 1
        assert selected["never_issued_quantity"] == 7
        assert selected["estimated_box_papers_quantity"] == 2
        turnout = setup["officer"].get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
