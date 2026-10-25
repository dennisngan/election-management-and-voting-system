"""Peer catalog changes keep F2 desktop drafts pinned until explicit review."""

from fastapi.testclient import TestClient
from PySide6.QtCore import QCoreApplication

from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_rounds_desktop import database_url as database_url
from tests.test_counting_rounds_desktop import f1_editor
from tests.test_counting_rounds_desktop import private_active_pointer as private_active_pointer
from tests.test_invalid_ballot_reasons_api import catalog_input


def test_f2_catalog_refresh_flags_conflict_without_replacing_dirty_inputs(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, path = setup["counter"], setup["rounds_path"]
        options = counter.get(path).json()
        first = counter.post(path, json=complete_f1_command(options))
        assert first.status_code == 201, first.text
        saved = counter.put(
            path + f"/{first.json()['id']}/f2",
            json=complete_f2_command(options, accepted_votes=[], rejected_papers=[]),
        )
        assert saved.status_code == 200, saved.text
        reason = next(row for row in options["f2_invalid_reasons"] if row["code"] == "gc-f2-k")
        with f1_editor(
            https_server,
            qt_app,
            setup["accounts"]["receiveronly"],
            setup["stations"]["N1"]["id"],
            setup["scope"]["id"],
        ) as (_, editor):
            editor.setF2Field("notes", "Local determination remains unsaved")
            editor.setRejectedQuantity(reason["id"], "0")
            old_inputs = editor.property("state")["rejected_inputs"]
            catalog_path = (
                f"/api/elections/{setup['election']['id']}/invalid-ballot-reasons/{reason['id']}"
            )
            edited = admin.put(
                catalog_path,
                json=catalog_input(
                    expected_revision=reason["revision"],
                    label_en="Reviewed uncertainty display label",
                    label_tc=reason["label_tc"],
                    label_sc=reason["label_sc"],
                ),
            )
            assert edited.status_code == 200, edited.text
            editor.refresh()
            wait_for_editor_idle(qt_app, editor)
            current = editor.property("state")
            assert current["newer_revision"] is True
            assert current["dirty"] is True and current["dirty_stage"] == "f2"
            assert current["f2_forms"]["notes"] == "Local determination remains unsaved"
            assert current["rejected_inputs"] == old_inputs
            target = path + f"/{first.json()['id']}/f2"
            writes_before = https_server.request_count("PUT", target)
            editor.saveF2()
            assert editor.property("state")["error"] == "revision_conflict"
            assert https_server.request_count("PUT", target) == writes_before
            editor.discardAndReload()
            wait_for_editor_idle(qt_app, editor)
            refreshed = editor.property("state")
            new_reason = next(
                row for row in refreshed["rejected_inputs"] if row["reason_id"] == reason["id"]
            )
            assert new_reason["reason_revision"] == 2
            assert new_reason["label_en"] == "Reviewed uncertainty display label"
            assert new_reason["source_english"] == "Void for uncertainty"
            assert refreshed["dirty"] is False
