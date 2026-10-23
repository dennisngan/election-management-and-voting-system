"""Actual Material controls record never-issued counter stock returns."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.qml_workspace_support import run_workspace_qml
from tests.test_stock_snapshot_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_stock_snapshot_api import database_url as database_url
from tests.test_stock_snapshots_desktop import arrange_counter_stock
from tests.turnout_support import READY_PASSWORD, TurnoutClock, turnout_scope, turnout_staff


@pytest.fixture
def return_qml_setup(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> Iterator[dict]:
    scope, clock = turnout_scope(admin), TurnoutClock()
    https_server.clock.value = clock.value
    station_id = scope["stations"][0]["id"]
    base = f"/api/workspace/stations/{station_id}"
    with turnout_staff(admin, database_url, clock, [station_id]) as (api, account):
        counter, _ = arrange_counter_stock(api, base)
        yield {
            "api": api,
            "base": base,
            "turnout_path": scope["path"],
            "actor_id": account["id"],
            "qml": {
                "server": https_server.url,
                "username": account["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
            },
        }


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_saves_never_issued_counter_return_using_actual_material_controls(
    return_qml_setup: dict, locale: str,
) -> None:
    setup = return_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('counterReturnsNavigation')
        editor = controller.property('counterReturns')
        def idle():
            return not any(editor.state[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('counterReturnCounter', 0)
        enter('counterReturnSeries', '普通系列 A')
        enter('counterReturnSerialFrom', '000006')
        enter('counterReturnSerialTo', '000006')
        enter('counterReturnEventTime', '2026-11-15 10:00')
        assert control('counterReturnQuantity').property('text') == '1'
        assert control('counterReturnQuantity').property('readOnly') is True
        click('counterReturnSave')
        wait(idle)
        assert editor.state['error'] == ''
        assert editor.state['selected']['revision'] == 1
        assert editor.state['selected']['kind'] == 'unissued_counter_to_pro'
        assert control('counterReturnSerialFrom').property('text') == '000006'
        assert control('counterReturnSerialFrom').property('readOnly') is True
        assert control('counterReturnSave').property('visible') is False
        assert '2026-11-15 10:00 HKT' in control('counterReturnEventContext').property('text')
        assert control('counterReturnHistoryRevision1').property('visible') is True
        """,
    )
    response = setup["api"].get(setup["base"] + "/stock-returns")
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    saved = response.json()["items"][0]
    assert saved["revision"] == 1 and saved["kind"] == "unissued_counter_to_pro"
    assert saved["quantity"] == 1 and saved["actor_id"] == setup["actor_id"]
    assert saved["serial_from"] == saved["serial_to"] == "000006"
    assert saved["event_at"] == "2026-11-15T02:00:00Z"
    assert saved["entered_at"] == "2026-11-15T04:00:00Z"
    reopened = setup["api"].get(setup["base"] + f"/stock-returns/{saved['id']}")
    assert reopened.status_code == 200 and reopened.json() == saved
    p14 = setup["api"].get(setup["base"] + "/allocations/statement?locale=en")
    assert p14.status_code == 200
    assert p14.json()["availability"][0]["allocated_quantity"] == 5
    assert p14.json()["availability"][0]["available_quantity"] == 3
    assert all(
        row["record"] is None
        for row in setup["api"].get(setup["turnout_path"]).json()["items"]
    )


@pytest.fixture
def saved_return_qml_setup(return_qml_setup: dict) -> dict:
    from uuid import uuid4

    setup = return_qml_setup
    counters = setup["api"].get(setup["base"] + "/allocations").json()["counters"]
    counter = next(row for row in counters if row["code"] == "C1")
    created = setup["api"].post(setup["base"] + "/stock-returns", json={
        "request_id": str(uuid4()),
        "counter_id": counter["id"],
        "series": "普通系列 A",
        "serial_from": "000006",
        "serial_to": "000006",
        "event_at": "2026-11-15T10:00:17.123456+08:00",
    })
    assert created.status_code == 201
    return {**setup, "original": created.json()}


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_officer_amends_a_precise_return_and_reviews_immutable_history_in_material(
    saved_return_qml_setup: dict, locale: str,
) -> None:
    setup = saved_return_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": locale},
        """
        click('counterReturnsNavigation')
        editor = controller.property('counterReturns')
        def idle():
            return not any(editor.state[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('counterReturnPicker', 0)
        wait(idle)
        assert control('counterReturnSerialFrom').property('readOnly') is True
        assert '10:00:17.123456 HKT' in control('counterReturnEventContext').property('text')
        click('counterReturnEdit')
        enter('counterReturnSerialFrom', '000005')
        click('counterReturnSave')
        assert editor.state['error'] == 'counter_return_validation'
        enter('counterReturnReason', '紙本核對：五至六號退回。\\n第二行保留原始時間。')
        assert_multiline_inside_border('counterReturnReason')
        QTest.keyClick(window, Qt.Key.Key_Tab)
        wait(lambda: control('counterReturnSave').property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Backtab)
        wait(lambda: control('counterReturnReason').property('activeFocus'))
        assert_multiline_inside_border('counterReturnReason')
        click('counterReturnSave')
        wait(idle)
        assert editor.state['error'] == '' and editor.state['selected']['revision'] == 2
        assert control('counterReturnQuantity').property('text') == '2'
        assert control('counterReturnSerialFrom').property('readOnly') is True
        assert '第二行保留原始時間。' in control('counterReturnReasonContext').property('text')
        click('counterReturnHistoryRevision1')
        wait(idle)
        assert editor.state['historical'] is True
        assert control('counterReturnSerialFrom').property('text') == '000006'
        assert control('counterReturnSerialFrom').property('readOnly') is True
        assert control('counterReturnQuantity').property('text') == '1'
        assert control('counterReturnSave').property('visible') is False
        assert control('counterReturnEdit').property('visible') is False
        click('counterReturnReload')
        wait(idle)
        assert editor.state['selected']['revision'] == 2
        assert control('counterReturnQuantity').property('text') == '2'
        """,
    )
    original = setup["original"]
    response = setup["api"].get(setup["base"] + f"/stock-returns/{original['id']}/history")
    assert response.status_code == 200
    rows = response.json()["items"]
    assert rows[0] == original and len(rows) == 2
    assert rows[1]["quantity"] == 2 and rows[1]["event_at"] == original["event_at"]
    assert rows[1]["reason"] == "紙本核對：五至六號退回。\n第二行保留原始時間。"
    p14 = setup["api"].get(setup["base"] + "/allocations/statement?locale=en")
    assert p14.json()["availability"][0]["allocated_quantity"] == 4
    assert p14.json()["availability"][0]["available_quantity"] == 4


def test_dirty_return_switch_requires_cancel_or_explicit_discard_in_material(
    saved_return_qml_setup: dict,
) -> None:
    setup = saved_return_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": "en"},
        """
        from PySide6.QtCore import QObject
        click('counterReturnsNavigation')
        editor = controller.property('counterReturns')
        def idle():
            return not any(editor.state[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('counterReturnPicker', 0)
        wait(idle)
        click('counterReturnEdit')
        frame()
        enter('counterReturnReason', 'Unsaved correction survives cancellation')
        click('counterReturnNew')
        dialog = window.findChild(QObject, 'counterReturnDiscardDialog')
        assert dialog is not None and dialog.property('visible') is True
        wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Escape)
        wait(lambda: not dialog.property('visible'))
        assert editor.state['dirty'] is True
        assert control('counterReturnReason').property('text').startswith('Unsaved correction')
        click('counterReturnNew')
        wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
        click_confirmation(dialog, controller.texts['keep_editing'])
        wait(idle)
        assert editor.state['dirty'] is True
        assert control('counterReturnReason').property('text').startswith('Unsaved correction')
        click('counterReturnNew')
        wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
        click_confirmation(dialog, controller.texts['discard_changes'])
        wait(idle)
        assert editor.state['selected'] == {} and editor.state['dirty'] is False
        assert control('counterReturnSeries').property('text') == ''
        enter('counterReturnSeries', 'Unsaved new return')
        choose('counterReturnPicker', 0)
        wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
        QTest.keyClick(window, Qt.Key.Key_Escape)
        wait(lambda: not dialog.property('visible'))
        assert control('counterReturnSeries').property('text') == 'Unsaved new return'
        assert editor.state['selected'] == {} and editor.state['dirty'] is True
        choose('counterReturnPicker', 0)
        wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
        click_confirmation(dialog, controller.texts['discard_changes'])
        wait(idle)
        assert editor.state['selected']['revision'] == 1 and editor.state['dirty'] is False
        assert control('counterReturnSeries').property('text') == '普通系列 A'
        assert control('counterReturnSerialFrom').property('readOnly') is True
        """,
    )
    original = setup["original"]
    history = setup["api"].get(setup["base"] + f"/stock-returns/{original['id']}/history")
    assert history.status_code == 200 and history.json()["items"] == [original]


def test_eighteen_digit_return_ranges_and_large_quantities_stay_exact_in_material(
    return_qml_setup: dict,
) -> None:
    from uuid import uuid4

    from tests.stock_support import stock_payload

    setup = return_qml_setup
    receipt = setup["api"].post(setup["base"] + "/stock", json=stock_payload(
        series="精確大數量系列",
        ordinary_quantity=9007199254740993,
        replacement_quantity=0,
        tendered_quantity=0,
        ranges=[{
            "pool": "ordinary",
            "serial_from": "000000000000000001",
            "serial_to": "009007199254740993",
        }],
    ))
    assert receipt.status_code == 201
    counters = setup["api"].get(setup["base"] + "/allocations").json()["counters"]
    counter = next(row for row in counters if row["code"] == "C1")
    allocated = setup["api"].post(setup["base"] + "/allocations", json={
        "request_id": str(uuid4()),
        "counter_id": counter["id"],
        "series": "精確大數量系列",
        "serial_from": "000000000000000001",
        "serial_to": "009007199254740993",
        "event_at": "2026-11-15T09:00:00+08:00",
    })
    assert allocated.status_code == 201
    run_workspace_qml(
        {**setup["qml"], "locale": "en"},
        """
        click('counterReturnsNavigation')
        editor = controller.property('counterReturns')
        def idle():
            return not any(editor.state[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('counterReturnCounter', 0)
        enter('counterReturnSeries', '精確大數量系列')
        enter('counterReturnSerialFrom', '000000000000000001')
        enter('counterReturnSerialTo', '009007199254740993')
        enter('counterReturnEventTime', '2026-11-15 10:00')
        assert control('counterReturnQuantity').property('text') == '9007199254740993'
        for name in ('counterReturnSerialFrom', 'counterReturnSerialTo', 'counterReturnQuantity'):
            field = focus(name)
            frame()
            assert field.property('contentWidth') <= (
                field.width() - field.property('leftPadding') - field.property('rightPadding')
            ), name + ' clips its exact number'
        click('counterReturnSave')
        wait(idle)
        assert editor.state['error'] == ''
        assert control('counterReturnSerialFrom').property('text') == '000000000000000001'
        assert control('counterReturnSerialTo').property('text') == '009007199254740993'
        assert control('counterReturnQuantity').property('text') == '9007199254740993'
        """,
    )
    response = setup["api"].get(setup["base"] + "/stock-returns")
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    saved = response.json()["items"][0]
    assert saved["quantity"] == 9007199254740993
    assert saved["serial_from"] == "000000000000000001"
    assert saved["serial_to"] == "009007199254740993"


@pytest.mark.parametrize("role", ["counting_officer", "supervisor"])
def test_other_operational_roles_can_review_but_cannot_edit_returns_in_material(
    admin: TestClient,
    database_url: str,
    saved_return_qml_setup: dict,
    role: str,
) -> None:
    setup = saved_return_qml_setup
    with turnout_staff(
        admin, database_url, TurnoutClock(), [setup["qml"]["station_id"]], role=role,
    ) as (_, account):
        run_workspace_qml(
            {
                **setup["qml"],
                "username": account["username"],
                "password": READY_PASSWORD,
                "locale": "en",
            },
            """
            click('counterReturnsNavigation')
            editor = controller.property('counterReturns')
            def idle():
                return not any(editor.state[key] for key in ('busy', 'refreshing'))
            wait(idle)
            choose('counterReturnPicker', 0)
            wait(idle)
            assert control('counterReturnNew').property('visible') is False
            assert control('counterReturnEdit').property('visible') is False
            assert control('counterReturnSave').property('visible') is False
            assert control('counterReturnCounter').property('enabled') is False
            assert control('counterReturnSerialFrom').property('readOnly') is True
            focus('counterReturnSerialFrom')
            QTest.keyClick(window, Qt.Key.Key_9)
            assert control('counterReturnSerialFrom').property('text') == '000006'
            assert control('counterReturnHistoryRevision1').property('visible') is True
            assert '10:00:17.123456 HKT' in control('counterReturnEventContext').property('text')
            """,
        )
    original = setup["original"]
    response = setup["api"].get(setup["base"] + f"/stock-returns/{original['id']}/history")
    assert response.status_code == 200 and response.json()["items"] == [original]


def test_peer_refresh_keeps_local_return_reason_and_range_visible_until_explicit_reload(
    saved_return_qml_setup: dict,
) -> None:
    setup = saved_return_qml_setup
    run_workspace_qml(
        {**setup["qml"], "locale": "en"},
        """
        import ssl
        from uuid import uuid4
        import httpx
        from PySide6.QtCore import QObject
        click('counterReturnsNavigation')
        editor = controller.property('counterReturns')
        def idle():
            return not any(editor.state[key] for key in ('busy', 'refreshing'))
        wait(idle)
        choose('counterReturnPicker', 0)
        wait(idle)
        original = editor.state['selected']
        click('counterReturnEdit')
        enter('counterReturnSerialFrom', '000004')
        enter('counterReturnReason', 'LOCAL unsaved first line\\nLOCAL retained second line')
        tls = ssl.create_default_context(cafile='.runtime/tls/ca.pem')
        with httpx.Client(base_url=setup['server'], verify=tls) as peer:
            login = peer.post('/api/auth/login', json={
                'username': setup['username'], 'password': setup['password'],
            })
            assert login.status_code == 200
            peer.headers['Authorization'] = 'Bearer ' + login.json()['token']
            target = (
                '/api/workspace/stations/' + str(setup['station_id'])
                + '/stock-returns/' + str(original['id'])
            )
            revised = peer.put(target, json={
                'request_id': str(uuid4()), 'revision': 1,
                'counter_id': original['counter']['id'], 'series': original['series'],
                'serial_from': '000005', 'serial_to': '000006',
                'event_at': original['event_at'], 'reason': 'Peer verified two returned papers',
            })
            assert revised.status_code == 200 and revised.json()['revision'] == 2
            editor.refresh()
            wait(idle)
            assert control('counterReturnReason').property('visible') is True, (
                'Retained local reason must stay visible'
            )
            assert control('counterReturnReason').property('readOnly') is True
            assert control('counterReturnReason').property('text') == (
                'LOCAL unsaved first line\\nLOCAL retained second line'
            )
            assert control('counterReturnSerialFrom').property('visible') is True
            assert control('counterReturnSerialFrom').property('readOnly') is True
            assert control('counterReturnSerialFrom').property('text') == '000004'
            assert editor.state['selected'] == original and editor.state['dirty'] is True
            assert editor.state['newer_revision'] is True and editor.state['historical'] is True
            assert control('counterReturnSave').property('visible') is False
            assert control('counterReturnEdit').property('visible') is False
            editor.save()
            assert peer.get(target + '/history').json()['items'] == [original, revised.json()]
            click('counterReturnReload')
            dialog = window.findChild(QObject, 'counterReturnDiscardDialog')
            wait(lambda: dialog.property('opened') and dialog.property('activeFocus'))
            click_confirmation(dialog, controller.texts['discard_changes'])
            wait(idle)
            assert editor.state['selected'] == revised.json() and editor.state['dirty'] is False
            assert control('counterReturnSerialFrom').property('text') == '000005'
            assert control('counterReturnReason').property('visible') is False
            assert control('counterReturnEdit').property('visible') is True
        """,
    )
    original = setup["original"]
    response = setup["api"].get(setup["base"] + f"/stock-returns/{original['id']}/history")
    assert response.status_code == 200
    rows = response.json()["items"]
    assert len(rows) == 2 and rows[0] == original
    assert rows[1]["quantity"] == 2 and rows[1]["reason"] == "Peer verified two returned papers"
