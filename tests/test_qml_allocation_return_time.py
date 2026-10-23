"""Returned papers require a later allocation time and readable correction guidance."""

from uuid import uuid4

import pytest

from tests.qml_workspace_support import run_workspace_qml
from tests.test_qml_stock_snapshots import snapshot_qml_setup as snapshot_qml_setup
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_allocation_before_its_releasing_return_has_translated_guidance_and_retains_draft(
    snapshot_qml_setup: dict,
    locale: str,
) -> None:
    setup = snapshot_qml_setup
    returned = setup["api"].post(
        setup["base"] + "/stock-returns",
        json={
            "request_id": str(uuid4()),
            "counter_id": setup["qml"]["counter_id"],
            "series": "普通系列 A",
            "serial_from": "000006",
            "serial_to": "000006",
            "event_at": "2026-11-15T10:00:00+08:00",
        },
    )
    assert returned.status_code == 201
    original_return = returned.json()
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('allocationNavigation')
        editor = controller.property('allocations')
        def idle():
            return not any(editor.property('state')[key] for key in ('busy', 'refreshing'))
        wait(idle)
        frame()
        choose('allocationCounter', 0)
        enter('allocationSeries', '普通系列 A')
        enter('allocationSerialFrom', '000006')
        enter('allocationSerialTo', '000006')
        enter('allocationEventAt', '2026-11-15 09:30')
        click('allocationSave')
        wait(idle)
        error = editor.property('state')['error']
        assert error == 'allocation_before_return', error
        feedback = control('allocationFeedback')
        assert feedback.property('visible') is True
        labels = [item for item in feedback.childItems()
                  if isinstance(item.property('text'), str)]
        assert len(labels) == 1
        assert labels[0].property('text') != 'allocation_before_return'
        assert editor.property('state')['dirty'] is True
        assert control('allocationSerialFrom').property('text') == '000006'
        assert control('allocationEventAt').property('text') == '2026-11-15 09:30'
        frame()
        enter('allocationEventAt', '2026-11-15 10:05')
        click('allocationSave')
        wait(idle)
        assert editor.property('state')['error'] == ''
        assert editor.property('state')['selected']['revision'] == 1
        assert editor.property('state')['selected']['quantity'] == 1
        """,
    )
    allocations = setup["api"].get(setup["base"] + "/allocations")
    assert allocations.status_code == 200 and len(allocations.json()["items"]) == 2
    assert allocations.json()["availability"][0]["allocated_quantity"] == 6
    saved_return = setup["api"].get(setup["base"] + f"/stock-returns/{original_return['id']}")
    assert saved_return.status_code == 200 and saved_return.json() == original_return
