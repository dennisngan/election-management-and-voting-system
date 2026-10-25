"""Count-revision wording in the actual Material workspace and public workflow."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.mark.parametrize(
    ("locale", "complete", "history", "reload", "approved"),
    [
        ("tc", "F1 所需數字齊全且算術相符。", "保留的點票版本", "重新載入已儲存點票", "已確認"),
        ("sc", "F1 所需数字齐全且算术相符。", "保留的点票版本", "重新载入已保存点票", "已确认"),
        (
            "en",
            "F1 inputs are complete and balanced.",
            "Preserved count revisions",
            "Reload saved count",
            "Approved",
        ),
    ],
)
def test_material_count_revision_wording_stays_state_neutral_after_submission_and_approval(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    complete: str,
    history: str,
    reload: str,
    approved: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        officer, supervisor, rounds_path = (
            setup["counter"], setup["clients"]["supervisor"], setup["rounds_path"]
        )
        options = officer.get(rounds_path).json()
        initial = complete_f1_command(options, actual_counted_quantity=5)
        initial["candidate_votes"][0]["quantity"] = 5
        created = officer.post(rounds_path, json=initial)
        assert created.status_code == 201, created.text
        target = rounds_path + f"/{created.json()['id']}"

        f2_saved = officer.put(target + "/f2", json=complete_f2_command(options))
        assert f2_saved.status_code == 200, f2_saved.text
        submitted = officer.post(
            target + "/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": f2_saved.json()["revision"],
                "scope_revision": options["scope"]["revision"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"

        login = {
            "server": https_server.url,
            "username": setup["accounts"]["receiveronly"]["username"],
            "password": READY_PASSWORD,
            "station_id": setup["stations"]["N1"]["id"],
            "locale": locale,
            "title": {"tc": "F1 初步點票", "sc": "F1 初步点票", "en": "F1 initial tally"}[locale],
        }

        def inspect_material_revision(status: str, revision: int, status_label: str) -> None:
            run_workspace_qml(
                login,
                f"""
                click('countingRoundsNavigation')
                editor = controller.countingRounds
                wait(lambda: not any(
                    editor.property('state')[key] for key in ('busy', 'refreshing')
                ))
                choose('countingRoundsScope', 1)
                wait(lambda: not any(
                    editor.property('state')[key] for key in ('busy', 'refreshing')
                ))
                state = editor.property('state')
                assert state['selected']['status'] == {status!r}
                assert state['selected']['revision'] == {revision}
                caption = control('f1RoundRevision').property('text')
                assert {status_label!r} in caption

                from PySide6.QtQuick import QQuickItem
                visible_text = [
                    item.property('text') for item in window.findChildren(QQuickItem)
                    if isinstance(item.property('text'), str)
                ]
                relevant_text = [
                    text for text in visible_text if 'F1' in text or 'draft' in text.lower()
                ]
                assert 'this remains a count draft' not in visible_text, repr(relevant_text)
                assert {complete!r} in visible_text, repr(relevant_text)
                assert {history!r} in visible_text, repr(visible_text)
                assert control('f1Reload').property('text') == {reload!r}
                """,
            )

        if locale == "en":
            inspect_material_revision(
                "submitted", submitted.json()["revision"], "Submitted for review"
            )

        approved_record = supervisor.post(
            target + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": submitted.json()["revision"],
                "scope_revision": options["scope"]["revision"],
                "password": READY_PASSWORD,
            },
        )
        assert approved_record.status_code == 200, approved_record.text
        assert approved_record.json()["status"] == "approved"
        assert approved_record.json()["reviewed_revision"] == submitted.json()["revision"]
        inspect_material_revision("approved", approved_record.json()["revision"], approved)
