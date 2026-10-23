"""Qt displays exact stock-derived totals beyond JavaScript's integer precision."""

from uuid import uuid4

from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload
from tests.test_qml_stock_snapshots import snapshot_qml_setup as snapshot_qml_setup
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url


def test_snapshot_material_controls_keep_eighteen_digit_serials_and_exact_large_totals(
    snapshot_qml_setup: dict,
) -> None:
    setup = snapshot_qml_setup
    maximum = 999999999999999999
    receipts = setup["api"].get(setup["base"] + "/stock")
    assert receipts.status_code == 200
    receipt = receipts.json()["items"][0]
    corrected = setup["api"].put(
        setup["base"] + f"/stock/{receipt['id']}",
        json=stock_payload(
            revision=receipt["revision"],
            reason="Synthetic exact large stock range",
            ordinary_quantity=maximum,
            replacement_quantity=0,
            tendered_quantity=0,
            ranges=[{"pool": "ordinary", "serial_from": "000001", "serial_to": str(maximum)}],
        ),
    )
    assert corrected.status_code == 200
    allocated = setup["api"].post(
        setup["base"] + "/allocations",
        json={
            "request_id": str(uuid4()),
            "counter_id": setup["qml"]["counter_id"],
            "series": "普通系列 A",
            "serial_from": "000007",
            "serial_to": str(maximum),
            "event_at": "2026-11-15T09:00:00+08:00",
        },
    )
    assert allocated.status_code == 201
    run_workspace_qml(
        {**setup["qml"], "locale": "en", "maximum": str(maximum), "issued": str(maximum - 1)},
        """
        click('stockSnapshotsNavigation')
        editor = controller.property('stockSnapshots')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        enter('snapshotEventTime', '2026-11-15 09:30')
        suffix = str(setup['counter_id'])
        click('snapshotReported' + suffix)
        click('snapshotAddRange' + suffix)
        enter('snapshotSeries' + suffix + '_0', '普通系列 A')
        enter('snapshotSerialFrom' + suffix + '_0', setup['maximum'])
        enter('snapshotSerialTo' + suffix + '_0', setup['maximum'])
        assert control('snapshotQuantity' + suffix + '_0').property('text') == '1'
        click('snapshotSave')
        wait(idle)
        assert editor.property('state')['error'] == ''
        assert control('snapshotSerialFrom' + suffix + '_0').property('text') == setup['maximum']
        total = control('snapshotCurrentIssued')
        assert total.property('text') == setup['issued']
        frame()
        assert total.property('contentWidth') <= total.width() + 1
        assert total.property('contentHeight') <= total.height() + 1
        assert control('snapshotRemainingTotal').property('text') == '1'
        assert editor.property('state')['totals']['ordinary_net_allocated_display'] == (
            setup['maximum'])
        """,
    )
    records = setup["api"].get(setup["base"] + "/stock-snapshots")
    assert records.status_code == 200
    saved = records.json()["latest"]
    assert saved["ordinary_net_allocated_quantity"] == maximum
    assert saved["ordinary_issued_quantity"] == maximum - 1
    assert saved["ordinary_remaining_quantity"] == 1
    assert saved["counters"][0]["ranges"][0]["serial_from"] == str(maximum)
