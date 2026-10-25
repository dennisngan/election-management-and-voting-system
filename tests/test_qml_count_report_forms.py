"""Count form selection in the actual three-language Material workspace."""

from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer


def test_material_selects_each_count_form_and_preserves_translated_picker_caption(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        first = client.post(path, json=complete_f1_command(options))
        assert first.status_code == 201, first.text
        saved = client.put(path + f"/{first.json()['id']}/f2", json=complete_f2_command(options))
        assert saved.status_code == 200, saved.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "captions": {
                    "tc": ["F2 問題選票判定", "F3 無效選票總覽", "F4 最終點票總覽", "完整點票記錄"],
                    "sc": ["F2 问题选票判定", "F3 无效选票总览", "F4 最终点票总览", "完整点票记录"],
                    "en": [
                        "F2 questionable-paper determination",
                        "F3 invalid paper breakdown",
                        "F4 final count",
                        "Complete count record",
                    ],
                },
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.state[key] for key in ('busy', 'refreshing')))
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.state[key] for key in ('busy', 'refreshing')))
            assert control('countReportForm') is not None
            for language, captions in setup['captions'].items():
                controller.setLocale(language)
                frame()
                for index, form in enumerate(('f2', 'f3', 'f4', 'count'), 1):
                    choose('countReportForm', index)
                    frame()
                    assert editor.state['report_form'] == form
                    assert control('countReportForm').property('displayText') == captions[index-1]
                    click('f1Preview')
                    wait(lambda: not any(editor.state[key] for key in ('busy', 'refreshing')))
                    report = editor.state['report']
                    assert report['locale'] == language and report['form'] == form
                    assert report['revision'] == 2
                    assert report['record']['count_complete'] is False
                    assert control('f1ReportPreview').property('visible') is True
                    assert report['title'] in control('f1ReportPreview').property('text')
                    assert control('f1ExportPdf').property('enabled') is True
                    assert control('f1ExportCsv').property('enabled') is True
            controller.setLocale('en')
            frame()
            assert control('countReportForm').property('displayText') == 'Complete count record'
            """,
        )
