"""Material counting-scope values and permissions through the real API workspace."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD
from tests.counting_support import counting_setup
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml
from tests.stock_support import stock_payload
from tests.test_accounting_desktop import private_active_pointer as private_active_pointer
from tests.test_stock_snapshot_quantity_api import allocate_large_series


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


def test_scope_page_captions_cover_each_locale_and_supervisor_is_read_only(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["stations"]["N1"]["id"]
        for locale, label in (
            ("tc", "點票範圍"),
            ("sc", "点票范围"),
            ("en", "Counting scopes"),
        ):
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": setup["accounts"]["receiveronly"]["username"],
                    "password": READY_PASSWORD,
                    "station_id": station_id,
                    "locale": locale,
                },
                f"""
                click('countingScopesNavigation')
                wait(lambda: not controller.countingScopes.property('state')['busy'])
                assert control('countingScopesNavigation').property('text') == {label!r}
                assert control('countingScopesTitle').property('text') == {label!r}
                """,
            )

        for role in ("polling", "supervisor"):
            run_workspace_qml(
                {
                    "server": https_server.url,
                    "username": setup["accounts"][role]["username"],
                    "password": READY_PASSWORD,
                    "station_id": station_id,
                    "locale": "en",
                },
                """
                click('countingScopesNavigation')
                wait(lambda: not controller.countingScopes.property('state')['busy'])
                assert controller.countingScopes.property('state')['error'] == ''
                assert control('countingScopeSave').property('visible') is False
                assert control('countingScopeNew').property('enabled') is False
                """,
            )


def test_material_scope_displays_exact_p18_and_scope_quantities(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
) -> None:
    with counting_setup(admin, database_url) as setup:
        https_server.clock.value = setup["clock"].value
        station_id = setup["stations"]["N1"]["id"]
        base = f"/api/workspace/stations/{station_id}"
        polling = setup["clients"]["polling"]
        counter = setup["clients"]["bothcounting"]
        supervisor = setup["clients"]["supervisor"]
        source = setup["accounting"]["N1"]
        allocations = polling.get(base + "/allocations")
        assert allocations.status_code == 200, allocations.text
        counter_id = allocations.json()["counters"][0]["id"]
        allocate_large_series(polling, base, [(counter_id, 20)])

        snapshot = polling.post(
            base + "/stock-snapshots",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:30:17+08:00",
                "counters": [
                    {
                        "counter_id": counter_id,
                        "ranges": [
                            {
                                "series": "普通系列 A",
                                "serial_from": "000006",
                                "serial_to": "000010",
                            }
                        ],
                    }
                ],
            },
        )
        assert snapshot.status_code == 201, snapshot.text
        assert snapshot.json()["ordinary_issued_quantity"] == 19999999999999999985

        series = ["普通系列 A"] + [
            f"Aggregate stock series {number:02d}" for number in range(1, 21)
        ]
        zeros = {
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 0,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }
        special = polling.post(
            base + "/special-papers",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T09:45:17+08:00",
                "stock_snapshot_id": snapshot.json()["id"],
                "stock_snapshot_revision": 1,
                "series": [{"series": name, **zeros} for name in series],
            },
        )
        assert special.status_code == 201, special.text
        updated = counter.put(
            source["path"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": special.json()["id"],
                "special_paper_revision": 1,
                "amendment_reason": "Record the complete exact P(18) source basis.",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["summary"]["received_quantity"] == 19999999999999999990
        assert updated.json()["summary"]["estimated_box_from_stock_quantity"] == (
            19999999999999999985
        )
        submitted = counter.post(
            source["path"] + "/submit",
            json={"request_id": str(uuid4()), "expected_revision": 2},
        )
        assert submitted.status_code == 200, submitted.text
        approved = supervisor.post(
            source["path"] + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "password": READY_PASSWORD,
            },
        )
        assert approved.status_code == 200, approved.text

        n2_id = setup["stations"]["N2"]["id"]
        n2_base = f"/api/workspace/stations/{n2_id}"
        n2_source = setup["accounting"]["N2"]
        large_reserve = 9007199254740993
        received_reserve = polling.post(
            n2_base + "/stock",
            json=stock_payload(
                series="Large replacement reserve N2",
                event_at="2026-11-15T10:30:00+08:00",
                ordinary_quantity=0,
                replacement_quantity=large_reserve,
                tendered_quantity=0,
                ranges=[
                    {
                        "pool": "replacement",
                        "serial_from": "000000000000000001",
                        "serial_to": "009007199254740993",
                    }
                ],
            ),
        )
        assert received_reserve.status_code == 201, received_reserve.text
        reserve_quantities = {
            "replacement_issued_quantity": 0,
            "spoilt_original_quantity": 0,
            "tendered_issued_quantity": 0,
            "retrieved_refused_quantity": 0,
            "retrieved_found_quantity": 0,
            "retrieved_held_quantity": 0,
        }
        n2_special = polling.post(
            n2_base + "/special-papers",
            json={
                "request_id": str(uuid4()),
                "event_at": "2026-11-15T10:45:00+08:00",
                "stock_snapshot_id": n2_source["stock_snapshot"]["id"],
                "stock_snapshot_revision": 1,
                "series": [
                    {"series": series_name, **reserve_quantities}
                    for series_name in (
                        "普通系列 A",
                        "Large replacement reserve N2",
                    )
                ],
            },
        )
        assert n2_special.status_code == 201, n2_special.text
        n2_updated = counter.put(
            n2_source["path"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "special_paper_id": n2_special.json()["id"],
                "special_paper_revision": 1,
                "amendment_reason": "Preserve the large unused replacement reserve.",
            },
        )
        assert n2_updated.status_code == 200, n2_updated.text
        assert n2_updated.json()["summary"]["replacement_unissued_quantity"] == large_reserve
        n2_submitted = counter.post(
            n2_source["path"] + "/submit",
            json={"request_id": str(uuid4()), "expected_revision": 2},
        )
        assert n2_submitted.status_code == 200, n2_submitted.text
        n2_approved = supervisor.post(
            n2_source["path"] + "/approve",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 2,
                "password": READY_PASSWORD,
            },
        )
        assert n2_approved.status_code == 200, n2_approved.text

        box = setup["boxes"]["local_n1"]
        scope_path = setup["paths"]["n1_counting_scopes"]
        saved = setup["clients"]["receiveronly"].post(
            scope_path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Exact source stock scope",
                "event_at": "2026-11-15T23:15:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [{"station_id": station_id, "revision": 2}],
                "notes": "All received N1 boxes included.",
            },
        )
        assert saved.status_code == 201, saved.text
        n2_saved = setup["clients"]["receiveronly"].post(
            setup["paths"]["n1_counting_scopes"],
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "Exact reserve scope N2",
                "event_at": "2026-11-15T23:15:00+08:00",
                "box_revisions": [
                    {
                        "box_id": setup["boxes"]["transferred_n2"]["id"],
                        "revision": setup["boxes"]["transferred_n2"]["revision"],
                    }
                ],
                "accounting_revisions": [{"station_id": n2_id, "revision": 2}],
                "notes": "The N2 received box keeps its origin P(18) reserve basis.",
            },
        )
        assert n2_saved.status_code == 201, n2_saved.text
        run_workspace_qml(
            {
                "server": https_server.url,
                "username": setup["accounts"]["receiveronly"]["username"],
                "password": READY_PASSWORD,
                "station_id": station_id,
                "locale": "en",
                "scope_id": saved.json()["id"],
                "n2_id": n2_id,
                "reserve_scope_id": n2_saved.json()["id"],
            },
            """
            click('countingScopesNavigation')
            wait(lambda: not controller.countingScopes.property('state')['busy'])
            click('countingScopeOption_' + str(setup['scope_id']))
            wait(lambda: not controller.countingScopes.property('state')['busy'])
            editor = controller.countingScopes
            state = editor.property('state')
            assert state['selected']['estimated_box_from_stock_quantity'] == (
                '19999999999999999985'
            )
            assert state['selected']['estimated_box_from_turnout_quantity'] is None
            assert control('countingScopeStockEstimate').property('text') == (
                '19999999999999999985'
            )
            assert control('countingScopeTurnoutEstimate').property('text') == '—'
            p18 = state['selected']['accounting_basis'][0]
            assert p18['summary']['received_quantity'] == '19999999999999999990'
            assert p18['summary']['received_quantity_display'] == '19999999999999999990'
            source_quantity = control('countingScopeP18Received_' + str(state['station_id']))
            assert source_quantity.property('text') == (
                'Source P(18) papers received: 19999999999999999990'
            )
            click('countingScopePreview')
            wait(lambda: not editor.property('state')['busy'])
            assert '19999999999999999985' in editor.property('state')['report_text']
            click('countingScopeOption_' + str(setup['reserve_scope_id']))
            wait(lambda: not controller.countingScopes.property('state')['busy'])
            assert editor.property('state')['report'] == {}
            assert editor.property('state')['report_text'] == ''
            click('countingScopePreview')
            wait(lambda: not editor.property('state')['busy'])
            assert editor.property('state')['report']['scope_id'] == setup['reserve_scope_id']
            reserve = control('countingScopeP18Replacement_' + str(setup['n2_id']))
            assert reserve.property('text') == (
                'Source P(18) unused replacement reserve: 9007199254740993'
            )
            assert control('countingScopeStockEstimate').property('text') == '—'
            """,
        )
