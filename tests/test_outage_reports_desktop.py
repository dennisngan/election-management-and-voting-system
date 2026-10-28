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
from tests.test_outage_reconciliation_edges_api import (
    _count_draft,
    _create_outage_and_paper,
)


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


@pytest.mark.parametrize(
    ("locale", "decision_label", "status_label", "history_label", "outage_label"),
    [
        ("tc", "核對決定修訂", "目前紙本核對已核准", "核對決定歷史", "中斷修訂"),
        ("sc", "核对决定修订", "当前纸本核对已核准", "核对决定历史", "中断修订"),
        ("en", "Reconciliation decision revision", "Current paper reconciliation is approved",
         "Reconciliation decision history", "Outage revision"),
    ],
)
def test_material_reconciliation_revision_is_distinct_from_outage_revision(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    locale: str,
    decision_label: str,
    status_label: str,
    history_label: str,
    outage_label: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        counter, supervisor = setup["counter"], setup["clients"]["supervisor"]
        station_id = setup["stations"]["N1"]["id"]
        options, round_path, count_round = _count_draft(setup)
        outage_path, paper = _create_outage_and_paper(setup, count_round["id"])
        submitted = counter.post(round_path + "/submit", json={
            "request_id": str(uuid4()), "expected_revision": 2,
            "scope_revision": options["scope"]["revision"], "paper_record_id": paper["id"],
        })
        assert submitted.status_code == 200, submitted.text
        before_response = counter.get(outage_path)
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()["record"]
        assert before["revision"] == 1
        amended = counter.put(outage_path, json={
            **{key: before[key] for key in ("reference", "kind", "started_at", "ended_at")},
            "request_id": str(uuid4()), "expected_revision": 1,
            "notes": "The outage notes were clarified before the first paper reconciliation.",
            "amendment_reason": "Preserve the signed return and clarify the recorded outage notes.",
        })
        assert amended.status_code == 200, amended.text
        assert amended.json()["revision"] == 2
        approved = supervisor.post(outage_path + "/approve", json={
            "request_id": str(uuid4()), "expected_revision": 2,
            "expected_reconciliation_revision": 0,
            "paper_revisions": [{"paper_id": paper["id"], "revision": paper["revision"]}],
            "password": READY_PASSWORD,
            "reason": "Compare the signed count receipt after clarifying the outage notes.",
        })
        assert approved.status_code == 200, approved.text
        record = approved.json()["record"]
        assert record["revision"] == 2 and record["reconciled"] is True
        assert record["reconciliation"]["revision"] == 1
        assert record["reconciliation"]["valid"] is True
        assert record["reconciliation"]["is_current"] is True
        assert record["reconciliation"]["basis"]["outage_revision"] == 2
        assert [row["revision"] for row in record["reconciliation_history"]] == [1]

        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD, "station_id": station_id, "locale": locale,
                "outage_id": record["id"], "decision_label": decision_label,
                "status_label": status_label, "history_label": history_label,
                "outage_label": outage_label,
            },
            """
            click('outagesNavigation')
            outages = controller.outages
            wait(lambda: not any(outages.property('state')[key]
                for key in ('busy', 'refreshing')))
            click('outageOption_' + str(setup['outage_id']))
            wait(lambda: not outages.property('state')['busy']
                and outages.property('state')['selected'].get('id') == setup['outage_id'])
            assert outages.property('state')['selected']['revision'] == 2
            assert outages.property('state')['selected']['reconciliation']['revision'] == 1
            frame()
            page = control('outageReportPanel').parentItem()

            def visual_descendants(root):
                pending = list(root.childItems())
                while pending:
                    item = pending.pop()
                    yield item
                    pending.extend(item.childItems())

            details = list(visual_descendants(page))
            def shown_detail(caption):
                found = [item for item in details if item.property('caption') == caption]
                assert len(found) == 1, (caption, len(found))
                detail = found[0]
                assert detail.property('visible') is True
                labels = [item.property('text') for item in visual_descendants(detail)
                          if item.property('visible')]
                assert caption in labels
                return detail.property('value'), labels

            current, current_labels = shown_detail(setup['status_label'])
            expected = setup['status_label'] + ' · ' + setup['decision_label'] + ' 1'
            assert current == expected, (current, expected)
            assert expected in current_labels
            shown_detail(setup['history_label'] + ' · ' + setup['decision_label'] + ' 1')
            outage, outage_labels = shown_detail(setup['outage_label'])
            assert outage.startswith('2 · '), outage
            assert outage in outage_labels
            """,
        )
