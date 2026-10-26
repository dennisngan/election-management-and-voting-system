"""Link a committed count receipt to its later paper record in Material."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer
from tests.outcomes_support import complete_f2_command
from tests.qml_workspace_support import run_workspace_qml
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_outage_reports_desktop import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_outage_reports_desktop import database_url as database_url


@pytest.fixture(autouse=True)
def isolated_client_command_journal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "desktop-commands"))


def test_counting_officer_links_an_existing_count_receipt_from_material(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with tally_setup(admin, database_url) as setup:
        counter = setup["counter"]
        station_id = setup["stations"]["N1"]["id"]
        rounds_path = setup["rounds_path"]
        options_response = counter.get(rounds_path)
        assert options_response.status_code == 200, options_response.text
        options = options_response.json()

        f1_command = complete_f1_command(options, actual_counted_quantity=5)
        f1_command["candidate_votes"][0]["quantity"] = 5
        f1_saved = counter.post(rounds_path, json=f1_command)
        assert f1_saved.status_code == 201, f1_saved.text
        round_id = f1_saved.json()["id"]
        round_path = f"{rounds_path}/{round_id}"
        f2_saved = counter.put(
            round_path + "/f2",
            json=complete_f2_command(options, determination_started_at=None),
        )
        assert f2_saved.status_code == 200, f2_saved.text

        original_request_id = str(uuid4())
        submit_command = {
            "request_id": original_request_id,
            "expected_revision": f2_saved.json()["revision"],
            "scope_revision": setup["scope"]["revision"],
        }
        assert "paper_record_id" not in submit_command
        submitted = counter.post(round_path + "/submit", json=submit_command)
        assert submitted.status_code == 200, submitted.text
        submitted_record = submitted.json()
        assert submitted_record["status"] == "submitted"

        outcome_path = (
            f"/api/workspace/stations/{station_id}/request-outcomes/{original_request_id}"
        )
        original_outcome = counter.get(outcome_path, params={"workflow": "count"})
        assert original_outcome.status_code == 200, original_outcome.text
        assert original_outcome.json() == {
            "request_id": original_request_id,
            "workflow": "count",
            "status": "committed",
            "record": submitted_record,
        }
        count_before_link = counter.get(round_path)
        assert count_before_link.status_code == 200, count_before_link.text

        setup["clock"].value += timedelta(minutes=15)
        outage_path = f"/api/workspace/stations/{station_id}/outages"
        outage = counter.post(
            outage_path,
            json={
                "request_id": str(uuid4()),
                "reference": "T21 existing count receipt " + uuid4().hex[:8],
                "kind": "network",
                "started_at": "2026-11-15T23:10:00+08:00",
                "ended_at": "2026-11-15T23:50:00+08:00",
                "notes": (
                    "The count receipt was committed before the paper reference was registered."
                ),
            },
        )
        assert outage.status_code == 201, outage.text
        outage_id = outage.json()["id"]
        outage_record_path = outage_path + f"/{outage_id}"
        original_event_at = "2026-11-15T23:35:12.345678+08:00"
        paper = counter.post(
            outage_record_path + "/paper-records",
            json={
                "request_id": str(uuid4()),
                "expected_outage_revision": 1,
                "paper_reference": "T21-COUNT-LINK-" + uuid4().hex[:8],
                "workflow": "count",
                "action": "submit",
                "original_event_at": original_event_at,
                "target": {"scope_id": setup["scope"]["id"], "round_id": round_id},
                "notes": "Link the previously committed count receipt.",
            },
        )
        assert paper.status_code == 201, paper.text
        paper_before = paper.json()
        assert paper_before["status"] == "pending"

        paper_path = outage_record_path + f"/paper-records/{paper_before['id']}"
        expected_preview = counter.get(
            paper_path + "/receipt",
            params={"request_id": original_request_id},
        )
        assert expected_preview.status_code == 200, expected_preview.text
        expected_preview_body = expected_preview.json()
        assert expected_preview_body["request_id"] == original_request_id
        assert expected_preview_body["record"] == submitted_record

        reason = "Link the existing committed count receipt with no second count effect."
        setup["outage_id"] = outage_id
        setup["paper_id"] = paper_before["id"]
        setup["paper_entered_at"] = paper_before["entered_at"]
        setup["original_request_id"] = original_request_id
        setup["submitted_record"] = submitted_record
        setup["expected_preview"] = expected_preview_body
        setup["reason"] = reason

        setup["clock"].value += timedelta(minutes=15)
        https_server.clock.value = setup["clock"].value
        submit_path = round_path + "/submit"
        submit_posts_before = https_server.request_count("POST", submit_path)
        link_path = paper_path + "/link-receipt"
        receipt_path = paper_path + "/receipt"

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "outage_id": outage_id,
                "paper_id": paper_before["id"],
                "original_request_id": original_request_id,
                "submitted_record_id": submitted_record["id"],
                "submitted_record_revision": submitted_record["revision"],
                "expected_preview": expected_preview_body,
                "reason": reason,
            },
            """
            click('outagesNavigation')
            outages = controller.outages
            wait(lambda: not outages.property('state')['busy']
                and any(row['id'] == setup['outage_id']
                    for row in outages.property('state')['items']))

            click('outageOption_' + str(setup['outage_id']))
            wait(lambda: not outages.property('state')['busy']
                and outages.property('state')['selected'].get('id') == setup['outage_id']
                and any(row['id'] == setup['paper_id']
                    for row in outages.property('state')['selected'].get('paper_records', [])))
            click('outagePaperOption_' + str(setup['paper_id']))
            wait(lambda: outages.property('state')['selected_paper_id'] == setup['paper_id'])

            def click_settled_receipt_control(name):
                item = focus(name)
                frame()
                center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                clipped_ancestors = []
                ancestor = item.parentItem()
                while ancestor is not None:
                    if ancestor.property('clip'):
                        local = item.mapToItem(
                            ancestor, QPointF(item.width() / 2, item.height() / 2))
                        inside = (0 < local.x() < ancestor.width()
                            and 0 < local.y() < ancestor.height())
                        clipped_ancestors.append({
                            'name': ancestor.objectName(), 'inside': inside,
                            'x': local.x(), 'y': local.y(),
                            'width': ancestor.width(), 'height': ancestor.height(),
                        })
                    ancestor = ancestor.parentItem()
                assert all(row['inside'] for row in clipped_ancestors), (
                    name + ' is clipped after focus and render: ' + str(clipped_ancestors))
                assert item.property('activeFocus'), name + ' lost focus after render'
                assert item.property('enabled'), name + ' became disabled before click'
                meta_object = item.metaObject()
                signal_index = meta_object.indexOfSignal('clicked()')
                assert signal_index >= 0
                clicked = QSignalSpy(item, meta_object.method(signal_index))
                QTest.mouseClick(window, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier, center.toPoint())
                application.processEvents()
                assert clicked.count() == 1, (
                    name + ' did not receive exactly one pointer click at '
                    + str((center.x(), center.y())) + '; clipped ancestors '
                    + str(clipped_ancestors))

            enter('outageExistingRequestId', setup['original_request_id'])
            check_button = control('outageExistingReceiptCheck')
            assert check_button.property('visible') is True
            assert check_button.property('enabled') is True
            click_settled_receipt_control('outageExistingReceiptCheck')
            wait(lambda: not outages.property('state')['busy']
                and outages.property('state')['existing_receipt']['checked'].get('status')
                == 'committed')

            checked = outages.property('state')['existing_receipt']['checked']
            assert checked == setup['expected_preview']
            summary = control('outageExistingReceiptSummary')
            assert summary.property('visible') is True
            summary_parts = []
            pending_summary = [summary]
            while pending_summary:
                item = pending_summary.pop()
                for property_name in ('text', 'value'):
                    value = item.property(property_name)
                    if isinstance(value, str) and value:
                        summary_parts.append(value)
                pending_summary.extend(item.childItems())
            summary_text = ' '.join(summary_parts)
            assert str(setup['submitted_record_id']) in summary_text
            assert 'submitted' in summary_text.lower()

            enter('outageExistingReceiptReason', setup['reason'])
            link_button = control('outageExistingReceiptLink')
            assert link_button.property('visible') is True
            assert link_button.property('enabled') is True
            click_settled_receipt_control('outageExistingReceiptLink')
            wait(lambda: not outages.property('state')['busy']
                and any(row['id'] == setup['paper_id'] and row['status'] == 'entered'
                    for row in outages.property('state')['selected'].get('paper_records', [])))
            """,
        )

        assert submit_posts_before == 0
        assert https_server.request_count("GET", receipt_path) == 1
        assert https_server.request_count("POST", link_path) == 1
        assert https_server.request_count("POST", submit_path) == submit_posts_before

        outage_after = counter.get(outage_record_path)
        assert outage_after.status_code == 200, outage_after.text
        paper_after = outage_after.json()["record"]["paper_records"]
        assert len(paper_after) == 1
        linked_paper = paper_after[0]
        assert linked_paper["status"] == "entered"
        assert linked_paper["original_event_at"] == "2026-11-15T15:35:12.345678Z"
        assert linked_paper["entered_at"] == setup["paper_entered_at"]
        reentry = linked_paper["reentry"]
        assert reentry["request_id"] == original_request_id
        assert reentry["actor_id"] == submitted_record["actor_id"]
        assert reentry["record"] == submitted_record
        assert reentry["entered_at"] > submitted_record["entered_at"]
        link = reentry["link"]
        assert link["request_id"] != original_request_id
        assert link["reason"] == reason
        assert link["actor_id"] == submitted_record["actor_id"]
        assert link["linked_at"] == reentry["entered_at"]
        assert link["linked_at"] > linked_paper["entered_at"]

        outcome_after = counter.get(outcome_path, params={"workflow": "count"})
        assert outcome_after.status_code == 200, outcome_after.text
        assert outcome_after.json() == original_outcome.json()
        count_after_link = counter.get(round_path)
        assert count_after_link.status_code == 200, count_after_link.text
        assert count_after_link.json() == count_before_link.json()
