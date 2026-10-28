"""Large canonical allocation quantities remain exact in actual receipt views."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QCoreApplication

from tests.box_support import READY_PASSWORD
from tests.desktop_support import HttpsServer, wait_for_editor_idle
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload
from tests.test_allocation_paper_reentry_desktop import _register_paper
from tests.test_allocation_paper_reentry_desktop import (
    allocation_base_setup as allocation_base_setup,
)
from tests.test_paper_journal_failure_desktop import signed_in_client


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def isolated_receipt_state(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(tmp_path / "large-receipt-journal"))
    with lifecycle_test_state(database_url):
        yield


def test_large_allocation_quantity_is_exact_in_recovery_and_paper_matching_material(
    allocation_base_setup: dict,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
) -> None:
    setup = allocation_base_setup
    quantity = 9007199254740993
    series = setup["series"] + "-EXACT"
    first, last = "000000000000000001", "009007199254740993"
    polling, base = setup["polling"], setup["base"]
    station_id = setup["station"]["id"]
    stock = polling.post(base + "/stock", json=stock_payload(
        series=series, ordinary_quantity=quantity, replacement_quantity=0, tendered_quantity=0,
        ranges=[{"pool": "ordinary", "serial_from": first, "serial_to": last}],
        event_at="2026-11-15T08:00:00+08:00",
    ))
    assert stock.status_code == 201, stock.text
    with signed_in_client(
        https_server, setup["account"]["username"], station_id, qt_app,
    ) as client:
        allocations = client.property("allocations")
        allocations.open()
        wait_for_editor_idle(qt_app, allocations)
        for key, value in {
            "counter_id": str(setup["counter"]["id"]), "series": series,
            "serial_from": first, "serial_to": last, "event_at": "2026-11-15 08:15:00",
        }.items():
            allocations.setField(key, value)
        allocations.save()
        wait_for_editor_idle(qt_app, allocations)
        saved = allocations.property("state")["selected"]
        assert allocations.property("state")["error"] == ""
        assert saved["quantity"] == quantity and saved["quantity_display"] == str(quantity)
        allocation_id = saved["id"]
        recovery = client.property("recovery")
        recovery.open()
        wait_for_editor_idle(qt_app, recovery)
        commands = [row for row in recovery.property("state")["commands"]
                    if row["workflow"] == "allocation" and row["path"] == base + "/allocations"]
        assert len(commands) == 1 and commands[0]["status"] == "committed"
        request_id = commands[0]["request_id"]
        assert commands[0]["receipt"]["record"]["quantity"] == quantity
    assert https_server.request_count("POST", base + "/allocations") == 1
    outcome_path = base + f"/request-outcomes/{request_id}"
    original = polling.get(outcome_path, params={"workflow": "allocation"})
    assert original.status_code == 200, original.text
    assert original.json()["record"]["id"] == allocation_id
    assert type(original.json()["record"]["quantity"]) is int
    assert original.json()["record"]["quantity"] == quantity

    # The ordinary receipt predates the separately registered paper reference.
    setup["clock"].value += timedelta(minutes=1)
    https_server.clock.value = setup["clock"].value
    outage_path, paper = _register_paper(
        setup, action="create", target={"counter_id": setup["counter"]["id"]},
    )
    paper_path = outage_path + f"/paper-records/{paper['id']}"
    preview = polling.get(paper_path + "/receipt", params={"request_id": request_id})
    assert preview.status_code == 200, preview.text
    assert preview.json()["record"] == original.json()["record"]
    outage_id = int(outage_path.rsplit("/", 1)[1])
    run_workspace_qml(
        {
            "server": https_server.url, "username": setup["account"]["username"],
            "password": READY_PASSWORD, "station_id": station_id, "locale": "en",
            "request_id": request_id, "quantity_text": str(quantity),
            "outage_id": outage_id, "paper_id": paper["id"],
        },
        """
        recovery = controller.property('recovery')
        click('recoveryNavigation')
        wait(lambda: not recovery.property('state')['busy'])
        click('recoveryCommand_' + setup['request_id'])
        summary = control('recoveryReceiptSummary')
        assert summary.property('visible') is True
        recovery_text = summary.property('text')

        click('outagesNavigation')
        outages = controller.property('outages')
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['outage_id'] for row in outages.property('state')['items']))
        click('outageOption_' + str(setup['outage_id']))
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['paper_id']
                for row in outages.property('state')['selected'].get('paper_records', [])))
        click('outagePaperOption_' + str(setup['paper_id']))
        enter('outageExistingRequestId', setup['request_id'])
        click('outageExistingReceiptCheck')
        wait(lambda: not outages.property('state')['busy']
            and outages.property('state')['existing_receipt']['checked'].get('status')
                == 'committed')
        matching = control('outageExistingReceiptSummary')
        assert matching.property('visible') is True
        def visual_descendants(root):
            pending = [root]
            found = []
            while pending:
                item = pending.pop()
                found.append(item)
                pending.extend(item.childItems())
            return found
        quantity_details = [item for item in visual_descendants(matching)
            if item.property('visible')
            and item.property('caption') == controller.texts['allocation_quantity']]
        assert len(quantity_details) == 1, [
            (item.property('caption'), item.property('value'))
            for item in visual_descendants(matching) if item.property('caption')]
        displayed_quantity = quantity_details[0].property('value')
        visible_values = [item.property('text')
            for item in visual_descendants(quantity_details[0]) if item.property('visible')]
        assert displayed_quantity in visible_values
        # Check the numeric field itself; the exact serial text contains the same digits.
        assert recovery_text.endswith(' ' + setup['quantity_text']) and (
            displayed_quantity == setup['quantity_text']
        ), {'expected': setup['quantity_text'], 'recovery': recovery_text,
            'matching_quantity': displayed_quantity}
        """,
    )
    assert https_server.request_count("POST", base + "/allocations") == 1
    unchanged = polling.get(outcome_path, params={"workflow": "allocation"})
    assert unchanged.status_code == 200 and unchanged.json() == original.json()
    still_pending = polling.get(outage_path)
    assert still_pending.status_code == 200
    assert still_pending.json()["record"]["paper_records"][0]["status"] == "pending"


@pytest.mark.parametrize(
    ("locale", "code_caption", "counter_id_caption", "record_id_caption", "revision_caption"),
    [
        ("tc", "發票櫃台代號", "發票櫃台編號", "原始記錄編號", "原始記錄修訂"),
        ("sc", "发票柜台代号", "发票柜台编号", "原始记录编号", "原始记录修订"),
        ("en", "Issuance counter code", "Issuance counter ID", "Original record ID",
         "Original record revision"),
    ],
)
def test_existing_allocation_counter_code_caption_in_checked_and_linked_material(
    allocation_base_setup: dict,
    https_server: HttpsServer,
    locale: str,
    code_caption: str,
    counter_id_caption: str,
    record_id_caption: str,
    revision_caption: str,
) -> None:
    setup = allocation_base_setup
    polling, base = setup["polling"], setup["base"]
    counter_id = setup["counter"]["id"]
    assert setup["counter"]["code"] == "C1" != str(counter_id)
    request_id = str(uuid4())
    saved = polling.post(
        base + "/allocations",
        json={
            "request_id": request_id, "counter_id": counter_id,
            "series": setup["series"], "serial_from": "000001", "serial_to": "000002",
            "event_at": "2026-11-15T08:15:00+08:00",
        },
    )
    assert saved.status_code == 201, saved.text
    original_record = saved.json()
    assert original_record["counter"]["code"] == "C1"
    assert original_record["counter"]["id"] == counter_id
    outcome_path = base + f"/request-outcomes/{request_id}"
    original = polling.get(outcome_path, params={"workflow": "allocation"})
    assert original.status_code == 200, original.text
    assert original.json()["record"] == original_record
    setup["clock"].value += timedelta(minutes=1)
    https_server.clock.value = setup["clock"].value
    outage_path, paper = _register_paper(
        setup, action="create", target={"counter_id": counter_id},
    )
    paper_path = outage_path + f"/paper-records/{paper['id']}"
    reason = "Link the original allocation receipt while preserving counter code and target ID."
    run_workspace_qml(
        {
            "server": https_server.url, "username": setup["account"]["username"],
            "password": READY_PASSWORD, "station_id": setup["station"]["id"],
            "locale": locale, "request_id": request_id, "counter_id": counter_id,
            "code_caption": code_caption, "counter_id_caption": counter_id_caption,
            "record_id_caption": record_id_caption, "revision_caption": revision_caption,
            "record_id": original_record["id"], "revision": original_record["revision"],
            "outage_id": int(outage_path.rsplit("/", 1)[1]), "paper_id": paper["id"],
            "reason": reason,
        },
        """
        import re
        click('outagesNavigation')
        outages = controller.property('outages')
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['outage_id'] for row in outages.property('state')['items']))
        click('outageOption_' + str(setup['outage_id']))
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['paper_id']
                for row in outages.property('state')['selected'].get('paper_records', [])))
        click('outagePaperOption_' + str(setup['paper_id']))
        enter('outageExistingRequestId', setup['request_id'])
        click('outageExistingReceiptCheck')
        wait(lambda: not outages.property('state')['busy']
            and outages.property('state')['existing_receipt']['checked'].get('status')
                == 'committed')

        def visible_label_text(root):
            pending = [root]
            texts = []
            while pending:
                item = pending.pop()
                if item.property('visible') and item.inherits('QQuickText'):
                    text = item.property('text')
                    if isinstance(text, str) and text:
                        texts.append(text)
                pending.extend(item.childItems())
            return ' '.join(texts)

        def has_label(text, caption, value):
            return re.search(re.escape(caption + ' ' + str(value))
                + '(?![0-9A-Za-z_])', text) is not None

        def assert_original_counter_caption(text):
            assert has_label(text, setup['code_caption'], 'C1'), text
            assert not has_label(text, setup['counter_id_caption'], 'C1'), text
            assert has_label(text, setup['record_id_caption'], setup['record_id']), text
            assert has_label(text, setup['revision_caption'], setup['revision']), text

        summary = control('outageExistingReceiptSummary')
        assert summary.property('visible') is True
        assert_original_counter_caption(visible_label_text(summary))
        page_text = visible_label_text(control('outageReportPanel').parentItem())
        assert has_label(page_text, setup['counter_id_caption'], setup['counter_id']), page_text
        enter('outageExistingReceiptReason', setup['reason'])
        assert control('outageExistingReceiptLink').property('enabled') is True
        click('outageExistingReceiptLink')
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['paper_id'] and row['status'] == 'entered'
                for row in outages.property('state')['selected'].get('paper_records', [])))
        wait(lambda: not control('outageExistingReceiptSummary').property('visible'))
        click('outagePaperOption_' + str(setup['paper_id']))
        entered_text = visible_label_text(control('outageReportPanel').parentItem())
        assert_original_counter_caption(entered_text)
        assert has_label(entered_text, setup['counter_id_caption'],
            setup['counter_id']), entered_text
        """,
    )
    assert https_server.request_count("GET", paper_path + "/receipt") == 1
    assert https_server.request_count("POST", paper_path + "/link-receipt") == 1
    assert https_server.request_count("POST", base + "/allocations") == 0
    current = polling.get(outage_path)
    assert current.status_code == 200, current.text
    linked = next(row for row in current.json()["record"]["paper_records"]
                  if row["id"] == paper["id"])
    assert linked["status"] == "entered" and linked["revision"] == paper["revision"]
    assert linked["reentry"]["request_id"] == request_id
    assert linked["reentry"]["record"] == original_record
    assert linked["reentry"]["link"]["request_id"] != request_id
    assert linked["reentry"]["link"]["reason"] == reason
    unchanged = polling.get(outcome_path, params={"workflow": "allocation"})
    assert unchanged.status_code == 200 and unchanged.json() == original.json()


@pytest.mark.parametrize(
    ("locale", "station_empty_text", "papers_empty_text"),
    [
        ("tc", "此投票站尚無連線中斷紀錄。", "此中斷紀錄尚未登記紙本參考。"),
        ("sc", "此投票站尚无连接中断记录。", "此中断记录尚未登记纸本参考。"),
        ("en", "No connectivity outages are recorded for this station.",
         "No paper references are recorded for this outage."),
    ],
)
def test_existing_outage_without_papers_has_its_own_empty_message_in_material(
    allocation_base_setup: dict,
    https_server: HttpsServer,
    locale: str,
    station_empty_text: str,
    papers_empty_text: str,
) -> None:
    setup = allocation_base_setup
    polling, base = setup["polling"], setup["base"]
    outage_path = base + "/outages"
    empty = polling.get(outage_path)
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []
    workspace_setup = {
        "server": https_server.url, "username": setup["account"]["username"],
        "password": READY_PASSWORD, "station_id": setup["station"]["id"], "locale": locale,
        "station_empty_text": station_empty_text, "papers_empty_text": papers_empty_text,
    }
    visible_labels_script = """
        def visible_page_labels():
            pending = [control('outageReportPanel').parentItem()]
            labels = []
            while pending:
                item = pending.pop()
                if item.property('visible') and item.inherits('QQuickText'):
                    text = item.property('text')
                    if isinstance(text, str) and text:
                        labels.append(text)
                pending.extend(item.childItems())
            return labels
    """
    run_workspace_qml(
        workspace_setup,
        visible_labels_script + """
        click('outagesNavigation')
        outages = controller.property('outages')
        wait(lambda: not outages.property('state')['busy']
            and outages.property('state')['station_id'] == setup['station_id'])
        assert outages.property('state')['items'] == []
        assert not outages.property('state')['selected'].get('id')
        frame()
        labels = visible_page_labels()
        assert setup['station_empty_text'] in labels, labels
        assert setup['papers_empty_text'] not in labels, labels
        """,
    )

    created = polling.post(
        outage_path,
        json={
            "request_id": str(uuid4()), "reference": "Empty paper list " + uuid4().hex[:8],
            "kind": "network", "started_at": "2026-11-15T08:00:00+08:00",
            "ended_at": "2026-11-15T08:30:00+08:00",
            "notes": "This outage exists; no paper references have been registered.",
        },
    )
    assert created.status_code == 201, created.text
    outage_id = created.json()["id"]
    detail_path = outage_path + f"/{outage_id}"
    before = polling.get(detail_path)
    assert before.status_code == 200, before.text
    assert before.json()["record"]["id"] == outage_id
    assert before.json()["record"]["paper_records"] == []
    run_workspace_qml(
        {**workspace_setup, "outage_id": outage_id, "reference": created.json()["reference"]},
        visible_labels_script + """
        click('outagesNavigation')
        outages = controller.property('outages')
        wait(lambda: not outages.property('state')['busy']
            and any(row['id'] == setup['outage_id'] for row in outages.property('state')['items']))
        click('outageOption_' + str(setup['outage_id']))
        wait(lambda: not outages.property('state')['busy']
            and outages.property('state')['selected'].get('id') == setup['outage_id'])
        assert outages.property('state')['selected']['paper_records'] == []
        option = control('outageOption_' + str(setup['outage_id']))
        assert option.property('visible') is True
        assert setup['reference'] in option.property('text')
        assert control('outageReportPanel').property('visible') is True
        frame()
        labels = visible_page_labels()
        assert setup['papers_empty_text'] in labels, labels
        assert setup['station_empty_text'] not in labels, labels
        """,
    )
    after = polling.get(detail_path)
    assert after.status_code == 200 and after.json() == before.json()
    assert https_server.request_count("POST", outage_path) == 0
    assert https_server.request_count("POST", detail_path + "/paper-records") == 0
