"""F2 determination and workflow through the real Material client."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from election.desktop.controller import DesktopController
from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_material_f2_partial_save_derives_authoritative_totals_in_three_locales(
    admin: TestClient,
    database_url: str,
    desktop: DesktopController,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        candidate = options["candidates"][0]
        uncertainty = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        first = complete_f1_command(
            options,
            questionable_quantity=3,
            actual_counted_quantity=5,
        )
        first["candidate_votes"][0]["quantity"] = 2
        created = client.post(path, json=first)
        assert created.status_code == 201, created.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "candidate_id": candidate["id"],
                "uncertainty_id": uncertainty["id"],
                "f2_titles": {
                    "tc": "F2 判定",
                    "sc": "F2 判定",
                    "en": "F2 determination",
                },
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['revision'] == 1
            assert control('f2EventAt') is not None

            for language, title in setup['f2_titles'].items():
                controller.setLocale(language)
                frame()
                assert control('countOutcomesTitle').property('text') == title
            controller.setLocale('en')
            frame()

            enter('f2EventAt', '2026-11-15 23:20:17.654321')
            enter('f2DeterminationStartedAt', '2026-11-15 23:18:12.123456')
            enter('f2AcceptedQuantity_' + str(setup['candidate_id']), '2')
            enter('f2RejectedQuantity_' + str(setup['uncertainty_id']), '1')
            enter('f2Notes', 'Partial F2 observations retain missing rows as unobserved.')
            click('f2Save')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            saved = editor.property('state')['selected']
            assert saved['revision'] == 2 and saved['f2_complete'] is False
            assert saved['count_inputs_complete'] is False
            assert saved['f2']['accepted_votes'][0]['quantity'] == 2
            assert next(row for row in saved['f2']['rejected_papers']
                if row['reason_id'] == setup['uncertainty_id'])['quantity'] == 1
            assert all(row['quantity'] is None for row in saved['f2']['rejected_papers']
                if row['reason_id'] != setup['uncertainty_id'])
            assert control('f2SourceEnglish_' + str(setup['uncertainty_id'])).property('text')

            for row in saved['f2']['rejected_papers']:
                if row['reason_id'] != setup['uncertainty_id']:
                    enter('f2RejectedQuantity_' + str(row['reason_id']), '0')
            click('f2Save')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            complete = editor.property('state')['selected']
            assert complete['f2_complete'] is True
            assert complete['count_inputs_complete'] is True
            assert complete['count_complete'] is False
            assert complete['final_candidate_votes'][0]['quantity'] == 4
            assert complete['final_invalid_quantity'] == 1
            assert complete['final_valid_quantity'] == 4
            assert complete['final_accounted_quantity'] == 5
            final_candidate = control(
                'countFinalCandidateQuantity_' + str(setup['candidate_id'])
            )
            assert final_candidate.property('text') == '4'
            assert control('countTotal_final_invalid_quantity').property('text') == '1'
            assert control('countTotal_final_accounted_quantity').property('text') == '5'
            assert len(complete['physical_comparisons']) == 2
            assert all('status' in row for row in complete['physical_comparisons'])
            assert control('countWorkflowCompletion').property('text')
            choose('countingRoundHistory', 1)
            wait(lambda: editor.property('state')['historical'], timeout=5)
            historical = editor.property('state')['selected']
            assert historical['revision'] == 2
            assert historical['f2']['notes'] == (
                'Partial F2 observations retain missing rows as unobserved.'
            )
            assert control('f2EventAt').property('readOnly') is True
            assert control('f2Save').property('enabled') is False
            choose('countingRoundHistory', 0)
            wait(lambda: not editor.property('state')['historical'], timeout=5)
            assert editor.property('state')['selected']['revision'] == 3
            """,
        )
        saved_api = client.get(path + f"/{created.json()['id']}")
        assert saved_api.status_code == 200, saved_api.text
        assert saved_api.json()["record"]["f2"]["notes"] == (
            "Partial F2 observations retain missing rows as unobserved."
        )


def test_material_f2_requires_an_explanation_for_positive_other_quantity(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        other = next(row for row in options["f2_invalid_reasons"] if row["is_other"])
        f1 = complete_f1_command(
            options,
            questionable_quantity=1,
            actual_counted_quantity=1,
        )
        f1["candidate_votes"][0]["quantity"] = 0
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "other_id": other["id"],
                "reason_ids": [row["id"] for row in options["f2_invalid_reasons"]],
                "candidate_id": options["candidates"][0]["id"],
            },
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            enter('f2EventAt', '2026-11-15 23:20:17.654321')
            enter('f2DeterminationStartedAt', '2026-11-15 23:18:12.123456')
            enter('f2AcceptedQuantity_' + str(setup['candidate_id']), '0')
            enter('f2RejectedQuantity_' + str(setup['other_id']), '1')
            click('f2Save')
            assert editor.property('state')['error'] == 'invalid_reason_explanation_required'
            assert editor.property('state')['error_origin'] == 'local'
            assert editor.property('state')['selected']['revision'] == 1
            enter(
                'f2RejectedExplanation_' + str(setup['other_id']),
                'Recorded a distinct paper mark.',
            )
            for identity in setup['reason_ids']:
                if identity != setup['other_id']:
                    enter('f2RejectedQuantity_' + str(identity), '0')
            click('f2Save')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            selected = editor.property('state')['selected']
            assert selected['revision'] == 2
            assert selected['f2_complete'] is True
            assert selected['count_inputs_complete'] is True
            reason = next(row for row in selected['f2']['rejected_papers']
                if row['reason_id'] == setup['other_id'])
            assert reason['is_other'] is True and reason['explanation_required'] is True
            assert reason['explanation'] == 'Recorded a distinct paper mark.'
            assert reason['source_english'] == '' and reason['verified_source'] is False
            """,
        )


def test_material_f1_replace_confirms_discarding_current_f2_and_keeps_its_history(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        f2 = {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "scope_revision": options["scope"]["revision"],
            "event_at": "2026-11-15T23:20:17.654321+08:00",
            "determination_started_at": None,
            "accepted_votes": [
                {"candidate_id": row["id"], "quantity": 0} for row in options["candidates"]
            ],
            "rejected_papers": [
                {
                    "reason_id": row["id"],
                    "reason_revision": row["revision"],
                    "quantity": 0,
                    "explanation": "",
                }
                for row in options["f2_invalid_reasons"]
            ],
            "notes": "Existing F2 history survives a new F1 observation.",
            "amendment_reason": "",
        }
        saved = client.put(path + f"/{created.json()['id']}/f2", json=f2)
        assert saved.status_code == 200, saved.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
            },
            """
            from PySide6.QtCore import QObject

            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['f2'] is not None
            enter('f2Notes', 'Unsaved F2 edit remains in its own stage.')
            assert editor.property('state')['dirty_stage'] == 'f2'
            assert control('f1EventAt').property('readOnly') is True
            assert control('f1Save').property('enabled') is False
            click('f1Reload')
            dialog = window.findChild(QObject, 'f1DiscardDialog')
            assert dialog is not None and dialog.property('visible') is True
            click_confirmation(dialog, controller.texts['keep_editing'])
            assert editor.property('state')['dirty_stage'] == 'f2'
            assert control('f2Notes').property('text') == (
                'Unsaved F2 edit remains in its own stage.'
            )
            click('f1Reload')
            click_confirmation(dialog, controller.texts['discard_changes'])
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['dirty'] is False
            assert control('f2Notes').property('text') == (
                'Existing F2 history survives a new F1 observation.'
            )

            enter('f1Notes', 'Updated F1 observation note.')
            assert editor.property('state')['dirty_stage'] == 'f1'
            click('f1Save')
            dialog = window.findChild(QObject, 'f1DiscardF2Dialog')
            assert dialog is not None and dialog.property('visible') is True
            click_confirmation(dialog, controller.texts['keep_editing'])
            assert editor.property('state')['dirty'] is True
            assert editor.property('state')['selected']['f2'] is not None
            assert control('f1Notes').property('text') == 'Updated F1 observation note.'

            click('f1Save')
            click_confirmation(dialog, controller.texts['f1_discard_f2_confirm'])
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            selected = editor.property('state')['selected']
            assert selected['revision'] == 3
            assert selected.get('f2') is None
            assert selected['notes'] == 'Updated F1 observation note.'
            assert editor.property('state')['dirty'] is False
            """,
        )
        history = client.get(path + f"/{created.json()['id']}")
        assert history.status_code == 200, history.text
        rows = history.json()["history"]
        assert [row["revision"] for row in rows] == [3, 2, 1]
        assert rows[0].get("f2") is None
        assert rows[1]["f2"]["notes"] == "Existing F2 history survives a new F1 observation."


def test_material_submission_approval_and_selection_use_transient_password_dialogs(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        f2 = {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "scope_revision": options["scope"]["revision"],
            "event_at": "2026-11-15T23:20:17.654321+08:00",
            "determination_started_at": None,
            "accepted_votes": [
                {"candidate_id": row["id"], "quantity": 0} for row in options["candidates"]
            ],
            "rejected_papers": [
                {
                    "reason_id": row["id"],
                    "reason_revision": row["revision"],
                    "quantity": 0,
                    "explanation": "",
                }
                for row in options["f2_invalid_reasons"]
            ],
            "notes": "Ready for review.",
            "amendment_reason": "",
        }
        saved = client.put(path + f"/{created.json()['id']}/f2", json=f2)
        assert saved.status_code == 200, saved.text

        officer = {
            "server": https_server.url,
            "username": setup["accounts"]["receiveronly"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["stations"]["N1"]["id"],
            "locale": "en",
            "completion_label": "Count was submitted and completion recorded.",
        }
        run_workspace_qml(
            officer,
            """
            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['status'] == 'draft'
            assert control('countSubmit').property('visible') is True
            assert control('countApprove').property('visible') is False
            assert control('countSelect').property('visible') is False
            click('countSubmit')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['status'] == 'submitted'
            assert editor.property('state')['selected']['count_complete'] is True
            assert control('countWorkflowCompletion').property('text') == (
                setup['completion_label']
            )
            """,
        )

        supervisor = {
            "server": https_server.url,
            "username": setup["accounts"]["supervisor"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["stations"]["N1"]["id"],
            "locale": "en",
            "ready_password": READY_PASSWORD,
            "wrong_password": "Incorrect-Password-42!",
        }
        run_workspace_qml(
            supervisor,
            """
            from PySide6.QtCore import QObject

            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['status'] == 'submitted'
            assert control('countSubmit').property('visible') is False
            assert control('countApprove').property('visible') is True
            assert control('countSelect').property('visible') is False
            click('countApprove')
            dialog = window.findChild(QObject, 'countWorkflowPasswordDialog')
            assert dialog is not None and dialog.property('visible') is True
            enter('countWorkflowPassword', setup['wrong_password'])
            click('countWorkflowConfirm')
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['error'] == 'invalid_credentials'
            assert editor.property('state')['selected']['status'] == 'submitted'
            assert control('countWorkflowPassword').property('text') == ''

            click('countApprove')
            enter('countWorkflowPassword', setup['wrong_password'])
            click('countWorkflowCancel')
            wait(lambda: not dialog.property('visible'))
            assert control('countWorkflowPassword').property('text') == ''
            assert editor.property('state')['selected']['status'] == 'submitted'

            click('countApprove')
            enter('countWorkflowPassword', setup['ready_password'])
            click('countWorkflowConfirm')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert control('countWorkflowPassword').property('text') == ''
            assert editor.property('state')['selected']['status'] == 'approved'
            assert editor.property('state')['selected']['approval_valid'] is True
            assert control('countSelect').property('visible') is True

            click('countSelect')
            enter('countWorkflowPassword', setup['ready_password'])
            click('countWorkflowConfirm')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert control('countWorkflowPassword').property('text') == ''
            selected = editor.property('state')['selected']
            assert selected['selected'] is True
            assert selected['selection']['valid'] is True
            assert selected['selection']['round_revision_id'] == selected['revision_id']
            assert 'password' not in selected and 'password' not in editor.property('state')
            """,
        )


def test_material_report_dialog_reinitializes_name_for_form_format_and_locale(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        f2 = {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "scope_revision": options["scope"]["revision"],
            "event_at": "2026-11-15T23:20:17.654321+08:00",
            "determination_started_at": None,
            "accepted_votes": [
                {"candidate_id": row["id"], "quantity": 0} for row in options["candidates"]
            ],
            "rejected_papers": [
                {
                    "reason_id": row["id"],
                    "reason_revision": row["revision"],
                    "quantity": 0,
                    "explanation": "",
                }
                for row in options["f2_invalid_reasons"]
            ],
            "notes": "Report dialog name test.",
            "amendment_reason": "",
        }
        saved = client.put(path + f"/{created.json()['id']}/f2", json=f2)
        assert saved.status_code == 200, saved.text
        round_id = created.json()["id"]
        export_folder = tmp_path / "count export 資料"
        export_folder.mkdir()

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": "en",
                "round_id": round_id,
                "scheme_less_folder": str(export_folder),
                "cancel_caption": "Cancel",
                "checks": [
                    {
                        "form": "f2",
                        "format": "pdf",
                        "button": "f1ExportPdf",
                        "locale": "en",
                        "filename": f"f2-round-{round_id}-revision-2-en.pdf",
                        "filters": ["PDF (*.pdf)"],
                    },
                    {
                        "form": "f2",
                        "format": "csv",
                        "button": "f1ExportCsv",
                        "locale": "en",
                        "filename": f"f2-round-{round_id}-revision-2-en.csv",
                        "filters": ["CSV (*.csv)"],
                    },
                    {
                        "form": "f3",
                        "format": "pdf",
                        "button": "f1ExportPdf",
                        "locale": "en",
                        "filename": f"f3-round-{round_id}-revision-2-en.pdf",
                        "filters": ["PDF (*.pdf)"],
                    },
                    {
                        "form": "f4",
                        "format": "csv",
                        "button": "f1ExportCsv",
                        "locale": "sc",
                        "filename": f"f4-round-{round_id}-revision-2-sc.csv",
                        "filters": ["CSV (*.csv)"],
                    },
                ],
            },
            """
            from PySide6.QtCore import QObject, QMetaObject, QUrl

            click('countingRoundsNavigation')
            editor = controller.countingRounds
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            choose('countingRoundsScope', 1)
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            assert editor.property('state')['selected']['id'] == setup['round_id']

            def visible_export_dialog():
                return [item for item in window.findChildren(
                    QObject, 'countReportExportDialog') if item.property('visible')]

            for index, check in enumerate(setup['checks']):
                if controller.property('state')['locale'] != check['locale']:
                    controller.setLocale(check['locale'])
                    frame()
                if editor.property('state')['report_form'] != check['form']:
                    assert editor.selectReportForm(check['form'])
                    frame()
                    assert editor.property('state')['report_form'] == check['form']
                export_button = control(check['button'])
                assert export_button.property('visible') and export_button.property('enabled')
                assert QMetaObject.invokeMethod(export_button, 'click')
                application.processEvents()
                try:
                    wait(lambda: len(visible_export_dialog()) == 1)
                except AssertionError as error:
                    remaining = window.findChildren(QObject, 'countReportExportDialog')
                    raise AssertionError((
                        check,
                        [(item.property('visible'), item.property('selectedFile').toString())
                            for item in remaining],
                    )) from error
                dialog = visible_export_dialog()[0]
                suffix = dialog.property('defaultSuffix')
                filters = dialog.property('nameFilters')
                selected_url = dialog.property('selectedFile')
                assert suffix == check['format']
                assert list(filters) == check['filters']
                assert selected_url.toString().rsplit('/', 1)[-1] == check['filename']
                current_folder = dialog.property('currentFolder')
                if index == 0:
                    # Cocoa can return an absolute local path without a URL scheme.
                    # Preserve that public folder value, then ensure later exports
                    # reconstruct a usable local-file URL from it.
                    scheme_less_folder = QUrl(setup['scheme_less_folder'])
                    assert scheme_less_folder.scheme() == ''
                    assert dialog.setProperty('currentFolder', scheme_less_folder)
                    current_folder = dialog.property('currentFolder')
                    assert current_folder.path() == setup['scheme_less_folder']
                    assert current_folder.isLocalFile() is False
                else:
                    assert selected_url.isLocalFile(), selected_url.toString()
                    assert selected_url.toLocalFile() == (
                        setup['scheme_less_folder'] + '/' + check['filename']
                    )
                    assert current_folder.path() == setup['scheme_less_folder'], (
                        current_folder.toString(), current_folder.scheme(),
                        setup['scheme_less_folder'],
                    )
                assert QMetaObject.invokeMethod(dialog, 'reject')
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                application.processEvents()
                frame()
                wait(lambda: not visible_export_dialog())
            """,
        )
        for form, suffix in (("f2", "pdf"), ("f2", "csv"), ("f3", "pdf"), ("f4", "csv")):
            report_path = f"{path}/{round_id}/revisions/2/{form}.{suffix}"
            assert https_server.request_count("GET", report_path) == 0
