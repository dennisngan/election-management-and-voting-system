"""Box QML controls execute real station workflows; native Computer proof is separate."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.box_support import (
    READY_PASSWORD,
    BoxClock,
    box_staff,
    box_stations,
    event_command,
    prepared_box,
)
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_uses_visible_box_fields_departure_and_report_buttons(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    station, clock = box_stations(admin)["N2"], BoxClock()
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station["id"],
                "locale": locale,
            },
            """
            click('boxesNavigation')
            boxes = controller.property('boxes')
            wait(lambda: not boxes.property('state')['busy'])
            frame()
            assert control('boxReference').property('visible') is True
            enter('boxReference', '界面票箱 0001')
            enter('boxSeal', '封條 000099')
            enter('boxPreparedTime', '2026-11-15 22:40')
            assert boxes.property('state')['forms']['box_reference'] == '界面票箱 0001'
            click('boxCreate')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['error'] == ''
            assert boxes.property('state')['selected']['revision'] == 1
            assert control('boxOrigin').property('value').startswith('N2 · ')
            assert control('boxDestination').property('value').startswith('N1 · ')
            frame()
            enter('boxEventTime', '2026-11-15 22:45')
            enter('boxEventReason', '核對封條後送箱')
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('boxDepart').property('activeFocus'))
            click('boxDepart')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['error'] == ''
            assert boxes.property('state')['selected']['revision'] == 2
            assert boxes.property('state')['selected']['status'] == 'departed'
            frame()
            click('boxPreview')
            wait(lambda: not boxes.property('state')['busy'])
            assert boxes.property('state')['report']['locale'] == setup['locale']
            assert '界面票箱 0001' in control('boxReportPreview').property('text')
            """,
        )
        saved = api.get(f"/api/workspace/stations/{station['id']}/boxes").json()["items"]
        assert len(saved) == 1
        assert saved[0]["box_reference"] == "界面票箱 0001"
        assert saved[0]["seal_reference"] == "封條 000099"
        assert saved[0]["status"] == "departed"


def test_counting_officer_receives_sixth_arrival_and_records_milestones_through_controls(
    admin: TestClient, database_url: str, https_server: HttpsServer
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, _):
        with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
            receiver,
            account,
        ):
            for index in range(6):
                created = sender.post(
                    f"/api/workspace/stations/{origin['id']}/boxes",
                    json=prepared_box(box_reference=f"界面送箱 {index + 1:04d}"),
                )
                assert created.status_code == 201
                box_id = created.json()["id"]
                departed = sender.post(
                    f"/api/workspace/stations/{origin['id']}/boxes/{box_id}/departure",
                    json=event_command(1, "2026-11-15T22:45:00+08:00"),
                )
                assert departed.status_code == 201
                if index < 5:
                    received = receiver.post(
                        f"/api/workspace/stations/{destination['id']}/boxes/{box_id}/receipt",
                        json=event_command(2, "2026-11-15T22:50:00+08:00"),
                    )
                    assert received.status_code == 201
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": destination["id"],
                    "box_id": box_id,
                    "locale": "sc",
                },
                """
                click('boxesNavigation')
                boxes = controller.property('boxes')
                wait(lambda: not boxes.property('state')['busy'])
                frame()
                assert control('boxCreate').property('visible') is False
                choose('boxPicker', 5)
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['selected']['id'] == setup['box_id']
                frame()
                enter('boxEventTime', '2026-11-15 22:59')
                click('boxReceive')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                assert boxes.property('state')['selected']['status'] == 'received'
                frame()
                enter('boxMilestoneTime', '2026-11-15 23:00')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                frame()
                choose('boxMilestoneKind', 1)
                wait(lambda: boxes.property('state')['milestone_kind'] == 'first_box_opening')
                frame()
                choose('boxMilestoneBox', 5)
                assert boxes.property('state')['milestone_forms']['box_id'] == str(setup['box_id'])
                enter('boxMilestoneTime', '2026-11-15 23:05')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                frame()
                choose('boxMilestoneKind', 2)
                wait(lambda: boxes.property('state')['milestone_kind']
                    == 'questionable_determination_start')
                frame()
                enter('boxMilestoneTime', '2026-11-15 23:10')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                assert boxes.property('state')['error'] == ''
                assert len(boxes.property('state')['milestone_history']) == 3
                assert boxes.property('state')['count_completion'] is None
                frame()
                click('boxPreview')
                wait(lambda: not boxes.property('state')['busy'])
                assert '界面送箱 0006' in control('boxReportPreview').property('text')
                """,
            )
            saved = receiver.get(f"/api/workspace/stations/{destination['id']}/boxes").json()
            assert len(saved["items"]) == 6
            assert all(row["status"] == "received" for row in saved["items"])
            assert saved["milestones"][1]["box_id"] == box_id
            assert saved["count_completion"] is None


def test_box_export_dialog_rebuilds_local_suggestions_after_scheme_less_folder(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    export_folder = tmp_path / "box export 資料"
    export_folder.mkdir()
    origin_path = f"/api/workspace/stations/{origin['id']}/boxes"
    destination_path = f"/api/workspace/stations/{destination['id']}/boxes"

    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (
        sender,
        _,
    ):
        created = sender.post(
            origin_path,
            json=prepared_box(box_reference="URL 測試票箱 0001"),
        )
        assert created.status_code == 201, created.text
        box_id = created.json()["id"]
        departed = sender.post(
            f"{origin_path}/{box_id}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert departed.status_code == 201, departed.text

        with box_staff(
            admin, database_url, clock, "counting_officer", [destination["id"]]
        ) as (receiver, account):
            received = receiver.post(
                f"{destination_path}/{box_id}/receipt",
                json=event_command(2, "2026-11-15T22:50:00+08:00"),
            )
            assert received.status_code == 201, received.text

            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": destination["id"],
                    "box_id": box_id,
                    "locale": "en",
                    "scheme_less_folder": str(export_folder),
                    "checks": [
                        {
                            "format": "pdf",
                            "button": "boxExportPdf",
                            "locale": "en",
                            "filename": f"box-handover-{destination['id']}-en.pdf",
                            "filters": ["PDF (*.pdf)"],
                        },
                        {
                            "format": "csv",
                            "button": "boxExportCsv",
                            "locale": "en",
                            "filename": f"box-handover-{destination['id']}-en.csv",
                            "filters": ["CSV (*.csv)"],
                        },
                        {
                            "format": "pdf",
                            "button": "boxExportPdf",
                            "locale": "tc",
                            "filename": f"box-handover-{destination['id']}-tc.pdf",
                            "filters": ["PDF (*.pdf)"],
                        },
                    ],
                },
                """
                from PySide6.QtCore import QObject, QMetaObject, QUrl

                click('boxesNavigation')
                boxes = controller.property('boxes')
                wait(lambda: not boxes.property('state')['busy'])
                choose('boxPicker', 0)
                wait(lambda: not boxes.property('state')['busy']
                    and boxes.property('state')['selected']['id'] == setup['box_id'])
                assert boxes.property('state')['selected']['status'] == 'received'

                def file_dialogs():
                    return [
                        item for item in window.findChildren(QObject)
                        if isinstance(item.property('currentFolder'), QUrl)
                        and isinstance(item.property('selectedFile'), QUrl)
                        and item.property('defaultSuffix') in ('pdf', 'csv')
                    ]

                def visible_file_dialogs():
                    return [item for item in file_dialogs() if item.property('visible')]

                for index, check in enumerate(setup['checks']):
                    if controller.property('state')['locale'] != check['locale']:
                        controller.setLocale(check['locale'])
                        frame()
                    export_button = control(check['button'])
                    assert export_button.property('visible') is True
                    assert export_button.property('enabled') is True
                    assert QMetaObject.invokeMethod(export_button, 'click')
                    application.processEvents()
                    wait(lambda: len(visible_file_dialogs()) == 1)

                    dialog = visible_file_dialogs()[0]
                    selected_file = dialog.property('selectedFile')
                    assert dialog.property('defaultSuffix') == check['format']
                    assert list(dialog.property('nameFilters')) == check['filters']
                    assert selected_file.toString().rsplit('/', 1)[-1] == check['filename']

                    if index == 0:
                        scheme_less_folder = QUrl(setup['scheme_less_folder'])
                        assert scheme_less_folder.scheme() == ''
                        assert dialog.setProperty('currentFolder', scheme_less_folder)
                        current_folder = dialog.property('currentFolder')
                        assert current_folder.path() == setup['scheme_less_folder']
                        assert current_folder.isLocalFile() is False
                    else:
                        assert selected_file.isLocalFile(), selected_file.toString()
                        assert selected_file.toLocalFile() == (
                            setup['scheme_less_folder'] + '/' + check['filename']
                        )
                        current_folder = dialog.property('currentFolder')
                        assert current_folder.path() == setup['scheme_less_folder']

                    assert QMetaObject.invokeMethod(dialog, 'reject')
                    application.processEvents()
                    frame()
                    wait(lambda: not visible_file_dialogs())
                """,
            )

    for suffix in ("pdf", "csv"):
        assert https_server.request_count(
            "GET", f"{destination_path}/statement.{suffix}"
        ) == 0


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_multiline_departure_note_and_readonly_preview_stay_inside_material_borders(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    station, clock = box_stations(admin)["N2"], BoxClock()
    https_server.clock.value = clock.value
    note = "送箱紀錄第一行：已核對封條及票箱編號。\n第二行：合成運送流程，準備交收。"
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (
        api,
        account,
    ):
        prepared = api.post(path, json=prepared_box(box_reference="多行說明票箱 0001"))
        assert prepared.status_code == 201
        box_id = prepared.json()["id"]
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station["id"],
                "box_id": box_id,
                "locale": locale,
                "note": note,
            },
            """
            click('boxesNavigation')
            boxes = controller.property('boxes')
            wait(lambda: not boxes.property('state')['busy'])
            frame()
            choose('boxPicker', 0)
            wait(lambda: not boxes.property('state')['busy']
                and boxes.property('state')['selected'].get('id') == setup['box_id'])
            frame()
            enter('boxEventTime', '2026-11-15 22:45')
            enter('boxEventReason', setup['note'])
            QTest.keyClick(window, Qt.Key.Key_Tab)
            wait(lambda: control('boxDepart').property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            wait(lambda: control('boxEventReason').property('activeFocus'))
            assert control('boxEventReason').property('text') == setup['note']
            assert_multiline_inside_border('boxEventReason')
            click('boxDepart')
            wait(lambda: not boxes.property('state')['busy'])
            saved = boxes.property('state')
            assert saved['error'] == ''
            assert saved['selected']['revision'] == 2
            assert saved['selected']['status'] == 'departed'
            assert saved['selected']['departure']['reason'] == setup['note']
            frame()
            click('boxPreview')
            wait(lambda: not boxes.property('state')['busy']
                and bool(boxes.property('state')['report_text']))
            assert boxes.property('state')['report']['locale'] == setup['locale']
            preview = control('boxReportPreview')
            assert preview.property('readOnly') is True
            assert_multiline_inside_border('boxReportPreview')
            saved_preview = preview.property('text')
            assert all(line in saved_preview for line in setup['note'].splitlines())
            QTest.keyClick(window, Qt.Key.Key_9)
            assert preview.property('text') == saved_preview
            """,
        )
        response = api.get(path)
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1
        saved = response.json()["items"][0]
        assert saved["id"] == box_id and saved["revision"] == 2
        assert saved["status"] == "departed"
        assert saved["departure"]["reason"] == note
        assert saved["departure"]["event_at"] == "2026-11-15T14:45:00Z"
        assert saved["departure"]["actor_id"] == account["id"]
        history = api.get(f"{path}/{box_id}/history")
        assert history.status_code == 200
        assert [row["kind"] for row in history.json()["items"]] == ["prepared", "departure"]
        assert history.json()["items"][-1]["reason"] == note


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_multiline_conversion_note_and_readonly_preview_stay_inside_material_borders(
    admin: TestClient, database_url: str, https_server: HttpsServer, locale: str
) -> None:
    stations, clock = box_stations(admin), BoxClock()
    origin, destination = stations["N2"], stations["N1"]
    https_server.clock.value = clock.value
    note = "轉換完成第一行：票箱及封條已核對。\n第二行：合成點票站準備完成。"
    source = f"/api/workspace/stations/{origin['id']}/boxes"
    target = f"/api/workspace/stations/{destination['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, _):
        prepared = sender.post(source, json=prepared_box(box_reference="多行轉換票箱 0001"))
        assert prepared.status_code == 201
        box_id = prepared.json()["id"]
        departed = sender.post(
            f"{source}/{box_id}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert departed.status_code == 201
        with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
            receiver,
            account,
        ):
            received = receiver.post(
                f"{target}/{box_id}/receipt",
                json=event_command(2, "2026-11-15T22:50:00+08:00"),
            )
            assert received.status_code == 201
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": account["username"],
                    "password": READY_PASSWORD,
                    "station_id": destination["id"],
                    "box_id": box_id,
                    "locale": locale,
                    "note": note,
                },
                """
                click('boxesNavigation')
                boxes = controller.property('boxes')
                wait(lambda: not boxes.property('state')['busy'])
                frame()
                choose('boxPicker', 0)
                wait(lambda: not boxes.property('state')['busy']
                    and boxes.property('state')['selected'].get('id') == setup['box_id'])
                assert boxes.property('state')['selected']['status'] == 'received'
                assert boxes.property('state')['milestone_kind'] == 'conversion_complete'
                frame()
                enter('boxMilestoneTime', '2026-11-15 23:00')
                enter('boxMilestoneReason', setup['note'])
                QTest.keyClick(window, Qt.Key.Key_Tab)
                wait(lambda: control('boxSaveMilestone').property('activeFocus'))
                QTest.keyClick(window, Qt.Key.Key_Backtab)
                wait(lambda: control('boxMilestoneReason').property('activeFocus'))
                assert control('boxMilestoneReason').property('text') == setup['note']
                assert_multiline_inside_border('boxMilestoneReason')
                click('boxSaveMilestone')
                wait(lambda: not boxes.property('state')['busy'])
                saved = boxes.property('state')
                assert saved['error'] == ''
                assert saved['selected_milestone']['kind'] == 'conversion_complete'
                assert saved['selected_milestone']['revision'] == 1
                assert saved['selected_milestone']['reason'] == setup['note']
                assert len(saved['milestone_history']) == 1
                assert saved['count_completion'] is None
                frame()
                click('boxPreview')
                wait(lambda: not boxes.property('state')['busy']
                    and bool(boxes.property('state')['report_text']))
                assert boxes.property('state')['report']['locale'] == setup['locale']
                preview = control('boxReportPreview')
                assert preview.property('readOnly') is True
                assert_multiline_inside_border('boxReportPreview')
                saved_preview = preview.property('text')
                assert all(line in saved_preview for line in setup['note'].splitlines())
                QTest.keyClick(window, Qt.Key.Key_9)
                assert preview.property('text') == saved_preview
                """,
            )
            response = receiver.get(target)
            assert response.status_code == 200
            saved = response.json()
            assert len(saved["items"]) == 1 and saved["items"][0]["status"] == "received"
            assert len(saved["milestones"]) == len(saved["milestone_history"]) == 1
            milestone = saved["milestones"][0]
            assert milestone["kind"] == "conversion_complete" and milestone["revision"] == 1
            assert milestone["box_id"] is None
            assert milestone["event_at"] == "2026-11-15T15:00:00Z"
            assert milestone["entered_at"] == "2026-11-15T16:00:00Z"
            assert milestone["actor_id"] == account["id"] and milestone["reason"] == note
            assert saved["milestone_history"] == [milestone]
            assert saved["count_completion"] is None
