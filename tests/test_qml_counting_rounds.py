"""F1 entry uses the actual Material workspace over HTTPS and real MySQL."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import tally_setup
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.mark.parametrize(
    ("locale", "title"),
    [("tc", "F1 初步點票"), ("sc", "F1 初步点票"), ("en", "F1 initial tally")],
)
def test_material_f1_saves_partial_observations_and_resumes_exact_time_without_zero_autofill(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    title: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        options = setup["counter"].get(setup["rounds_path"])
        assert options.status_code == 200
        candidate = options.json()["candidates"][0]
        login = {
            "server": https_server.url,
            "username": setup["accounts"]["receiveronly"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["stations"]["N1"]["id"],
            "locale": locale,
            "title": title,
            "candidate_id": candidate["id"],
            "discard_label": {"tc": "捨棄變更", "sc": "舍弃更改", "en": "Discard changes"}[locale],
            "keep_label": {"tc": "繼續編輯", "sc": "继续编辑", "en": "Keep editing"}[locale],
        }
        run_workspace_qml(
            login,
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[k]
                for k in ('busy','refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[k]
                for k in ('busy','refreshing')), timeout=5)
            assert control('countingRoundsTitle').property('text') == setup['title']
            assert editor.property('state')['selected'] == {}
            assert control('f1QuestionableQuantity').property('text') == ''
            assert control('f1ActualCountedQuantity').property('text') == ''
            assert all(row['quantity'] == '' for row in editor.property('state')['invalid_inputs'])
            enter('f1EventAt', '2026-11-15 23:15:12.123456')
            enter('f1CandidateQuantity_' + str(setup['candidate_id']), '0')
            enter('f1QuestionableQuantity', '0')
            enter('f1ActualCountedQuantity', '0')
            enter('f1Notes', '尚未觀察無效票分類；零票為明確觀察。')
            click('f1Save')
            wait(lambda: not any(editor.property('state')[k]
                for k in ('busy','refreshing')), timeout=5)
            state = editor.property('state')
            assert state['error'] == ''
            assert state['notice'] == 'f1_saved'
            assert state['selected']['revision'] == 1
            assert state['selected']['f1_complete'] is False
            assert state['selected']['questionable_quantity'] == 0
            assert state['selected']['actual_counted_quantity'] == 0
            assert all(row['quantity'] is None for row in state['selected']['invalid_papers'])
            assert state['forms']['event_at'] == '2026-11-15 23:15:12.123456'
            enter('f1Notes', '未儲存的取消／捨棄測試')
            enter('f1QuestionableQuantity', 'invalid')
            click('f1Save')
            assert editor.property('state')['error'] == 'f1_quantity_invalid'
            click('f1Reload')
            from PySide6.QtCore import QObject
            dialog = window.findChild(QObject, 'f1DiscardDialog')
            assert dialog is not None
            click_confirmation(dialog, setup['keep_label'])
            assert editor.property('state')['dirty'] is True
            assert control('f1Notes').property('text') == '未儲存的取消／捨棄測試'
            assert control('f1QuestionableQuantity').property('text') == 'invalid'
            click('f1Reload')
            click_confirmation(dialog, setup['discard_label'])
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['dirty'] is False
            assert control('f1Notes').property('text') == '尚未觀察無效票分類；零票為明確觀察。'
            assert control('f1QuestionableQuantity').property('text') == '0'
        """,
        )

        saved = setup["counter"].get(setup["rounds_path"])
        assert saved.status_code == 200
        assert len(saved.json()["rounds"]) == 1
        assert saved.json()["rounds"][0]["candidate_votes"][0]["quantity"] == 0
        run_workspace_qml(
            login,
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[k]
                for k in ('busy','refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[k]
                for k in ('busy','refreshing')), timeout=5)
            assert editor.property('state')['selected']['revision'] == 1
            field = control('f1CandidateQuantity_' + str(setup['candidate_id']))
            assert field.property('text') == '0'
            assert control('f1QuestionableQuantity').property('text') == '0'
            assert control('f1ActualCountedQuantity').property('text') == '0'
            assert all(row['quantity'] == '' for row in editor.property('state')['invalid_inputs'])
            assert control('f1EventAt').property('text') == '2026-11-15 23:15:12.123456'
            assert control('f1Notes').property('text') == '尚未觀察無效票分類；零票為明確觀察。'
        """,
        )


@pytest.mark.parametrize(
    ("locale", "message"),
    [
        ("tc", "實際張數必須等於候選人票、明顯無效票及問題選票合計。"),
        ("sc", "实际张数必须等于候选人票、明显无效票及问题选票合计。"),
        (
            "en",
            "Actual papers must equal candidate votes plus clearly invalid and "
            "questionable papers.",
        ),
    ],
)
def test_material_backend_arithmetic_error_and_other_explanation_are_actionable(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    message: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        options = setup["counter"].get(setup["rounds_path"]).json()
        other = next(row for row in options["invalid_reasons"] if row["is_other"])
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": locale,
                "arithmetic_message": message,
                "candidate_ids": [row["id"] for row in options["candidates"]],
                "reason_ids": [row["id"] for row in options["invalid_reasons"]],
                "other_id": other["id"],
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            enter('f1EventAt', '2026-11-15 23:15:12.123456')
            for identity in setup['candidate_ids']:
                enter('f1CandidateQuantity_' + str(identity), '0')
            for identity in setup['reason_ids']:
                enter('f1InvalidQuantity_' + str(identity), '0')
            enter('f1QuestionableQuantity', '0')
            enter('f1ActualCountedQuantity', '1')
            click('f1Save')
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['error'] == 'f1_arithmetic_invalid'
            assert editor.property('state')['error_origin'] == 'write'
            frame()
            notice = control('f1Notice')
            items, texts = [notice], []
            while items:
                item = items.pop()
                if item.property('text') is not None: texts.append(item.property('text'))
                items.extend(item.childItems())
            assert setup['arithmetic_message'] in texts
            editor.refresh()
            wait(lambda: not editor.property('state')['refreshing'], timeout=5)
            assert editor.property('state')['error'] == 'f1_arithmetic_invalid'
            assert control('f1ActualCountedQuantity').property('text') == '1'
            enter('f1InvalidQuantity_' + str(setup['other_id']), '1')
            enter('f1QuestionableQuantity', '2')
            enter('f1ActualCountedQuantity', '3')
            click('f1Save')
            assert editor.property('state')['error'] == 'invalid_reason_explanation_required'
            assert editor.property('state')['error_origin'] == 'local'
            enter('f1InvalidExplanation_' + str(setup['other_id']), '另類實際記號；保留原文。')
            click('f1Save')
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['error'] == ''
            assert editor.property('state')['selected']['f1_complete'] is True
            assert editor.property('state')['selected']['questionable_quantity'] == 2
            assert editor.property('state')['selected']['status'] == 'draft'
        """,
        )
        assert https_server.request_count("POST", setup["rounds_path"]) == 2
        saved = setup["counter"].get(setup["rounds_path"]).json()["rounds"][0]
        assert saved["actual_counted_quantity"] == 3
        saved_other = next(
            row for row in saved["invalid_papers"] if row["reason_id"] == other["id"]
        )
        assert saved_other["quantity"] == 1
        assert saved_other["explanation"] == "另類實際記號；保留原文。"


def test_material_f1_keeps_exact_large_inputs_and_exports_the_saved_draft(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
) -> None:
    with tally_setup(admin, database_url, candidates_per_constituency=2) as setup:
        https_server.clock.value = setup["clock"].value
        options = setup["counter"].get(setup["rounds_path"]).json()
        candidates = options["candidates"]
        pdf_path, csv_path = tmp_path / "f1-exact.pdf", tmp_path / "f1-exact.csv"
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "candidate_ids": [row["id"] for row in candidates],
                "reason_ids": [row["id"] for row in options["invalid_reasons"]],
                "pdf_path": str(pdf_path),
                "csv_path": str(csv_path),
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            field_name = 'f1CandidateQuantity_' + str(setup['candidate_ids'][0])
            field = focus(field_name)
            QMetaObject.invokeMethod(field, 'selectAll')
            QTest.keyClick(window, Qt.Key.Key_1)
            frame()
            assert control(field_name).property('activeFocus') is True
            QTest.keyClick(window, Qt.Key.Key_2)
            assert control(field_name).property('text') == '12'
            enter('f1EventAt', '2026-11-15 23:15:12.123456')
            enter(field_name, '19999999999999999989')
            enter('f1CandidateQuantity_' + str(setup['candidate_ids'][1]), '9007199254740993')
            for identity in setup['reason_ids']:
                enter('f1InvalidQuantity_' + str(identity), '0')
            enter('f1QuestionableQuantity', '0')
            enter('f1ActualCountedQuantity', '20009007199254740982')
            click('f1Save')
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            frame()
            assert editor.property('state')['error'] == ''
            assert control(field_name).property('text') == '19999999999999999989'
            assert control('f1ActualCountedQuantity').property('text') == '20009007199254740982'
            actual = control('f1Saved_actual_counted_quantityValue')
            assert actual.property('text') == '20009007199254740982'
            click('f1Preview')
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['error'] == ''
            assert '19999999999999999989' in control('f1ReportPreview').property('text')
            preview = editor.property('state')['report_text']
            editor.refresh()
            wait(lambda: not editor.property('state')['refreshing'], timeout=5)
            assert editor.property('state')['report_text'] == preview
            editor.exportStatement('pdf', 'en', setup['pdf_path'])
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['notice'] == 'f1_exported'
            editor.exportStatement('csv', 'en', setup['csv_path'])
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['notice'] == 'f1_exported'
        """,
        )
        saved = setup["counter"].get(setup["rounds_path"]).json()["rounds"][0]
        assert saved["actual_counted_quantity"] == 20009007199254740982
        assert [row["quantity"] for row in saved["candidate_votes"]] == [
            19999999999999999989,
            9007199254740993,
        ]
        assert saved["f1_complete"] is True
        assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert b"19999999999999999989" in csv_path.read_bytes()
        text = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(pdf_path.read_bytes())).pages
        )
        assert "20009007199254740982" in text and "19999999999999999989" in text


@pytest.mark.parametrize("role", ["polling", "supervisor"])
def test_material_f1_read_only_roles_cannot_change_saved_observations(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    role: str,
) -> None:
    from tests.tally_support import complete_f1_command

    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        options = setup["counter"].get(setup["rounds_path"]).json()
        created = setup["counter"].post(setup["rounds_path"], json=complete_f1_command(options))
        assert created.status_code == 201
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"][role]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "candidate_id": options["candidates"][0]["id"],
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            frame()
            assert control('f1Save').property('visible') is False
            field_name = 'f1CandidateQuantity_' + str(setup['candidate_id'])
            field = focus(field_name)
            assert field.property('readOnly') is True
            QTest.keyClick(window, Qt.Key.Key_9)
            assert control(field_name).property('text') == '0'
            assert editor.property('state')['dirty'] is False
            assert control('f1EventAt').property('readOnly') is True
            assert control('f1Preview').property('enabled') is True
        """,
        )
        assert setup["counter"].get(setup["rounds_path"]).json()["rounds"][0] == created.json()


def test_material_history_retains_frozen_reason_wording_after_catalog_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    from uuid import uuid4

    from tests.tally_support import complete_f1_command

    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        reason = next(row for row in options["invalid_reasons"] if row["verified_source"])
        original = counter.post(path, json=complete_f1_command(options))
        assert original.status_code == 201
        changed = admin.put(
            f"/api/elections/{setup['election']['id']}/invalid-ballot-reasons/{reason['id']}",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "label_tc": "更新顯示用語",
                "label_sc": "更新显示用语",
                "label_en": "Revised display wording",
                "enabled": True,
                "explanation_required": reason["explanation_required"],
            },
        )
        assert changed.status_code == 200, changed.text
        current_options = counter.get(path).json()
        revised = counter.put(
            path + f"/{original.json()['id']}",
            json=complete_f1_command(
                current_options,
                expected_revision=1,
            ),
        )
        assert revised.status_code == 200
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "reason_id": reason["id"],
                "original_label": reason["label_en"],
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            assert editor.property('state')['selected']['revision'] == 2
            label_name = 'f1InvalidLabel_' + str(setup['reason_id'])
            assert control(label_name).property('text') == 'Revised display wording'
            choose('countingRoundHistory', 1)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            frame()
            assert editor.property('state')['selected']['revision'] == 1
            assert editor.property('state')['historical'] is True
            assert control(label_name).property('text') == setup['original_label']
            quantity = control('f1InvalidQuantity_' + str(setup['reason_id']))
            assert quantity.property('readOnly') is True
            click('f1Preview')
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            previous_report = editor.property('state')['report_text']
            editor.refresh()
            wait(lambda: not editor.property('state')['refreshing'], timeout=5)
            assert control(label_name).property('text') == setup['original_label']
            assert editor.property('state')['selected']['revision'] == 1
            assert editor.property('state')['report_text'] == previous_report
            assert editor.property('state')['newer_revision'] is False
            assert control('f1NewerWarning').property('visible') is False
            assert control('f1Save').property('enabled') is False
        """,
        )


def test_material_unready_box_scope_is_view_only_with_unobserved_inputs(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    from uuid import uuid4

    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        box = setup["boxes"]["unreceived_n2"]
        saved = setup["counter"].post(
            setup["paths"]["n1_counting_scopes"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Unreceived F1 source",
                "event_at": "2026-11-15T23:15:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [],
            },
        )
        assert saved.status_code == 201
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            choose('countingRoundsScope', 2)
            wait(lambda: not editor.property('state')['busy'], timeout=5)
            frame()
            assert editor.property('state')['scope']['count_ready'] is False
            assert editor.property('state')['selected'] == {}
            assert control('f1Save').property('enabled') is False
            assert control('f1ActualCountedQuantity').property('readOnly') is True
            assert control('f1ActualCountedQuantity').property('text') == ''
        """,
        )
