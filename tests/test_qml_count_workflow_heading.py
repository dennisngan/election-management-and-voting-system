"""Workflow password dialog headings through the actual Material workspace."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.mark.parametrize(
    ("locale", "approval_title", "selection_title", "cancel_caption", "confirm_caption"),
    [
        ("tc", "輸入主管密碼以核准點票", "輸入主管密碼以選定結果", "取消", "確認"),
        ("sc", "输入主管密码以批准点票", "输入主管密码以选定结果", "取消", "确认"),
        (
            "en",
            "Enter Supervisor password to approve this count",
            "Enter Supervisor password to select this result",
            "Cancel",
            "Confirm",
        ),
    ],
)
def test_workflow_dialog_headers_are_complete_in_all_locales_and_confirm_exact_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    approval_title: str,
    selection_title: str,
    cancel_caption: str,
    confirm_caption: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1 = complete_f1_command(options, actual_counted_quantity=5)
        f1["candidate_votes"][0]["quantity"] = 5
        created = client.post(path, json=f1)
        assert created.status_code == 201, created.text
        target = path + f"/{created.json()['id']}"
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
            "notes": "Ready for approval dialog review.",
            "amendment_reason": "",
        }
        saved = client.put(target + "/f2", json=f2)
        assert saved.status_code == 200, saved.text
        submitted = client.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD,
                "station_id": setup["stations"]["N1"]["id"],
                "locale": locale,
                "approval_title": approval_title,
                "selection_title": selection_title,
                "cancel_caption": cancel_caption,
                "confirm_caption": confirm_caption,
                "ready_password": READY_PASSWORD,
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
            assert editor.property('state')['selected']['status'] == 'submitted'
            click('countApprove')
            dialog = window.findChild(QObject, 'countWorkflowPasswordDialog')
            assert dialog is not None and dialog.property('visible') is True
            header = dialog.property('header')
            assert header is not None
            assert header.property('text') == setup['approval_title']
            assert header.property('truncated') is False
            assert control('countWorkflowCancel').property('text') == setup['cancel_caption']
            assert control('countWorkflowConfirm').property('text') == setup['confirm_caption']
            assert control('countWorkflowConfirm').property('enabled') is False
            enter('countWorkflowPassword', setup['ready_password'])
            assert control('countWorkflowConfirm').property('enabled') is True
            click('countWorkflowConfirm')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            approved = editor.property('state')['selected']
            assert approved['status'] == 'approved'
            assert approved['approval_valid'] is True
            assert control('countWorkflowPassword').property('text') == ''

            click('countSelect')
            assert dialog.property('visible') is True
            header = dialog.property('header')
            assert header.property('text') == setup['selection_title']
            assert header.property('truncated') is False
            assert control('countWorkflowCancel').property('text') == setup['cancel_caption']
            assert control('countWorkflowConfirm').property('text') == setup['confirm_caption']
            assert control('countWorkflowConfirm').property('enabled') is False
            enter('countWorkflowPassword', setup['ready_password'])
            click('countWorkflowCancel')
            wait(lambda: not dialog.property('visible'))
            assert control('countWorkflowPassword').property('text') == ''
            assert editor.property('state')['selected']['selected'] is False

            click('countSelect')
            assert control('countWorkflowConfirm').property('enabled') is False
            enter('countWorkflowPassword', setup['ready_password'])
            click('countWorkflowConfirm')
            wait(lambda: not dialog.property('visible'))
            wait(lambda: not any(editor.property('state')[key]
                for key in ('busy', 'refreshing')), timeout=5)
            selected = editor.property('state')['selected']
            assert selected['selected'] is True
            assert selected['selection']['valid'] is True
            assert selected['selection']['round_revision_id'] == approved['revision_id']
            """,
        )
