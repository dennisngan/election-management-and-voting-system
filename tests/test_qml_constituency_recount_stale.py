"""A genuine peer instruction freezes stale Material fields while keeping discard usable."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.box_support import READY_PASSWORD, box_staff
from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.qml_workspace_support import run_workspace_qml
from tests.results_support import save_result_round
from tests.test_constituency_tie_api import complete_tie_setup


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


MATERIAL_SCENARIO = """
import ssl
from copy import deepcopy
from uuid import uuid4
import httpx
from tests.test_physical_acceptance_recovery_desktop import assert_public_business_fields

results = controller.property('constituencyResults')
click('constituencyResultsNavigation')
wait(lambda: not any(results.property('state')[key] for key in ('busy', 'refreshing')), timeout=5)
child = results.property('recounts')
assert isinstance(child, QObject)
wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing')), timeout=5)
initial = deepcopy(child.property('state'))
assert initial['can_instruct'] is True and initial['instructions'] == []
assert [row['scope_id'] for row in initial['scope_sources']] == setup['scope_ids']
assert len(initial['scope_sources']) == 2
assert initial['pending_request_id'] == ''
assert control('constituencyRecountEventAt').property('readOnly') is False
assert control('constituencyRecountReason').property('readOnly') is False
enter('constituencyRecountEventAt', setup['draft_time'])
enter('constituencyRecountReason', setup['draft_reason'])
draft = deepcopy(child.property('state'))
assert draft['forms'] == {'event_at': setup['draft_time'], 'reason': setup['draft_reason']}
assert draft['dirty'] is True and draft['newer_basis'] is False
assert results.property('state')['dirty'] is False
assert control('constituencyRecountInstruct').property('enabled') is True
assert control('constituencyRecountDiscard').property('enabled') is True
instructed = QSignalSpy(child.instructed)
assert instructed.isValid()

# A separate authenticated HTTPS Supervisor client commits the real peer command;
# it never edits a journal or calls the first client's controller.
with httpx.Client(base_url=setup['server'],
        verify=ssl.create_default_context(cafile='.runtime/tls/ca.pem'), timeout=8) as peer:
    authenticated = False
    try:
        login = peer.post('/api/auth/login', json={
            'username': setup['peer_username'], 'password': setup['password']})
        assert login.status_code == 200, login.text
        body = login.json()
        assert body['account']['id'] == setup['peer_actor_id']
        assert body['account']['role'] == 'supervisor'
        peer.headers['Authorization'] = 'Bearer ' + body['token']
        authenticated = True
        ready = peer.get(setup['target'])
        assert ready.status_code == 200, ready.text
        ready = ready.json()
        assert ready['can_instruct'] is True
        assert ready['basis_digest'] == initial['basis_digest']
        assert ready['scope_sources'] == initial['scope_sources']
        created = peer.post(setup['target'], json={
            'request_id': str(uuid4()), 'basis_digest': ready['basis_digest'],
            'scope_sources': ready['scope_sources'],
            'event_at': '2026-11-16T00:05:42.123456+08:00',
            'reason': setup['peer_reason'], 'password': setup['password']})
        assert created.status_code == 201, created.text
        receipt = created.json()
        parent = receipt['instruction']
        assert parent['actor_id'] == setup['peer_actor_id']
        assert parent['member_count'] == 2 and len(receipt['members']) == 2
        assert [row['round']['revision'] for row in receipt['members']] == [1, 1]
        current = peer.get(setup['target'])
        assert current.status_code == 200, current.text
        current = current.json()
        assert current['basis_digest'] != initial['basis_digest']
        assert current['scope_sources'] == [] and current['can_instruct'] is False
    finally:
        if authenticated:
            logout = peer.delete('/api/auth/session')
            assert logout.status_code == 204

wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing')), timeout=5)
click('constituencyRecountRefresh')
wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing'))
    and child.property('state')['newer_basis'] is True, timeout=5)
stale = child.property('state')
assert stale['forms'] == draft['forms'] and stale['dirty'] is True
assert stale['basis_digest'] == initial['basis_digest']
assert stale['scope_sources'] == initial['scope_sources']
# An unsent draft has no allocated command UUID; refresh must not invent one.
assert stale['pending_request_id'] == draft['pending_request_id'] == ''
assert stale['uncertain_save'] is False and results.property('state')['dirty'] is False
assert [row['id'] for row in stale['instructions']] == [parent['id']]
assert_public_business_fields(stale['instructions'][0], parent)
for source in initial['scope_sources']:
    name = 'constituencyRecountProgress_' + str(parent['id']) + '_' + str(source['scope_id'])
    assert control(name).property('visible') is True
assert control('constituencyRecountInstruct').property('enabled') is False
assert control('constituencyResultPreview').property('enabled') is False
assert control('constituencyResultExportPdf').property('enabled') is False
assert control('constituencyResultExportCsv').property('enabled') is False
assert control('constituencyRecountDiscard').property('enabled') is True
assert instructed.count() == 0

for locale in ('en', 'tc', 'sc'):
    controller.setLocale(locale)
    wait(lambda: controller.property('state')['locale'] == locale, timeout=5)
    frame()
    assert child.property('state')['newer_basis'] is True
    assert child.property('state')['forms'] == draft['forms']
    assert results.property('state')['dirty'] is False
    assert control('constituencyRecountEventAt').property('text') == setup['draft_time']
    assert control('constituencyRecountReason').property('text') == setup['draft_reason']
    # Intended first RED: stale controls advertise editing although setField ignores it.
    assert control('constituencyRecountEventAt').property('readOnly') is True, locale
    assert control('constituencyRecountReason').property('readOnly') is True, locale
    assert control('constituencyRecountDiscard').property('enabled') is True

wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing')), timeout=5)
click('constituencyRecountDiscard')
dialog = window.findChild(QObject, 'constituencyRecountDiscardDialog')
assert dialog is not None
wait(lambda: dialog.property('opened'), timeout=5)
before_refresh = deepcopy(child.property('state'))
child.reload()
wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing')), timeout=5)
# A same-context genuine refresh must keep this intentional discard available.
assert dialog.property('opened') is True and dialog.property('visible') is True
assert child.property('state')['forms'] == draft['forms']
assert child.property('state')['newer_basis'] is True
for field in ('account_id', 'station_id', 'constituency_id', 'role'):
    assert child.property('state')[field] == before_refresh[field]
assert child.property('state')['uncertain_save'] is False
click_confirmation(dialog, controller.texts['discard_changes'])
wait(lambda: not any(child.property('state')[key] for key in ('busy', 'refreshing'))
    and child.property('state')['dirty'] is False, timeout=5)
adopted = child.property('state')
assert adopted['forms'] == {'event_at': '', 'reason': ''}
assert adopted['newer_basis'] is False and adopted['uncertain_save'] is False
assert adopted['pending_request_id'] == ''
assert adopted['basis_digest'] == current['basis_digest']
assert adopted['scope_sources'] == [] and adopted['can_instruct'] is False
assert [row['id'] for row in adopted['instructions']] == [parent['id']]
assert_public_business_fields(adopted['instructions'][0], parent)
assert [row['new_round_id'] for row in adopted['instructions'][0]['members']] == [
    row['round']['id'] for row in receipt['members']]
assert control('constituencyRecountEventAt').property('text') == ''
assert control('constituencyRecountReason').property('text') == ''
assert control('constituencyRecountDiscard').property('enabled') is False
assert control('constituencyRecountInstruct').property('enabled') is False
assert results.property('state')['dirty'] is False
assert results.property('state')['recount_protected'] is False
assert instructed.count() == 0
assert setup['password'] not in json.dumps(adopted)
"""


def test_stale_material_fields_are_readonly_and_discard_adopts_the_actual_peer_instruction(
    admin: TestClient,
    database_url: str,
    https_server: HttpsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_directory = tmp_path / "stale-wide-draft-journal"
    monkeypatch.setenv("ELECTION_CLIENT_STATE_DIR", str(journal_directory))
    with complete_tie_setup(admin, database_url) as setup:
        saved = save_result_round(setup, [6, 4], approve_and_select=True)
        assert [row["quantity"] for row in saved["selected"]["candidate_votes"]] == [6, 4]
        assert [row["quantity"] for row in setup["n3_round"]["selected"]["candidate_votes"]] == [
            0, 0,
        ]
        priors = [saved, setup["n3_round"]]
        supervisor = setup["clients"]["supervisor"]
        source_views = []
        for prior in priors:
            response = supervisor.get(prior["round_path"])
            assert response.status_code == 200, response.text
            source_views.append(response.json())
        setup["clock"].value += timedelta(minutes=10)
        https_server.clock.value = setup["clock"].value
        constituency_id = setup["constituency_id"]
        target = f"/api/workspace/constituencies/{constituency_id}/recounts"
        peer_reason = "A second Supervisor explicitly instructed both current North scopes."
        north_ids = [setup["stations"][code]["id"] for code in ("N1", "N2", "N3")]
        with box_staff(
            admin, database_url, setup["clock"], "supervisor", north_ids,
        ) as (_, peer):
            assert peer["id"] != setup["accounts"]["supervisor"]["id"]
            run_workspace_qml({
                "server": https_server.url,
                "username": setup["accounts"]["supervisor"]["username"],
                "password": READY_PASSWORD, "locale": "en",
                "station_id": setup["stations"]["N1"]["id"],
                "scope_ids": [setup["scope"]["id"], setup["n3_scope"]["id"]],
                "draft_time": "2026-11-16 00:04:17.654321",
                "draft_reason": (
                    "Own unsent draft retained while the peer creates the new requirement."
                ),
                "peer_username": peer["username"], "peer_actor_id": peer["id"],
                "peer_reason": peer_reason, "target": target,
            }, MATERIAL_SCENARIO)
            # Only the distinct peer HTTPS client dispatched a wide command.
            assert https_server.request_count("POST", target) == 1
            assert not list(journal_directory.glob("*.json"))
            response = supervisor.get(target)
            assert response.status_code == 200, response.text
            assert len(response.json()["instructions"]) == 1
            parent = response.json()["instructions"][0]
            assert parent["actor_id"] == peer["id"] and parent["reason"] == peer_reason
            assert str(UUID(parent["request_id"])) == parent["request_id"]
            assert parent["member_count"] == 2
            assert [row["scope_id"] for row in parent["members"]] == [
                setup["scope"]["id"], setup["n3_scope"]["id"],
            ]
            assert [row["progress"] for row in parent["members"]] == ["incomplete", "incomplete"]
            for member, prior, original in zip(
                parent["members"], priors, source_views, strict=True,
            ):
                rounds_path = prior["round_path"].rsplit("/", 1)[0]
                listed = supervisor.get(rounds_path)
                assert listed.status_code == 200, listed.text
                assert [row["id"] for row in listed.json()["rounds"]] == [
                    prior["selected"]["id"], member["new_round_id"],
                ]
                blank = supervisor.get(f"{rounds_path}/{member['new_round_id']}")
                assert blank.status_code == 200, blank.text
                assert len(blank.json()["history"]) == 1
                assert blank.json()["record"]["revision"] == 1
                assert blank.json()["record"]["status"] == "draft"
                assert [row["quantity"] for row in blank.json()["record"]["candidate_votes"]] == [
                    None, None,
                ]
                preserved = supervisor.get(prior["round_path"])
                assert preserved.status_code == 200, preserved.text
                assert [row["revision_id"] for row in preserved.json()["history"]] == [
                    row["revision_id"] for row in original["history"]
                ]
                for field in ("candidate_votes", "invalid_papers", "f2", "scope_basis", "event_at",
                              "entered_at", "actor_id", "approved_at", "approved_by"):
                    assert preserved.json()["record"][field] == original["record"][field]
