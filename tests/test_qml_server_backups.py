"""Administrator backup workflows use visible Material controls and public HTTPS."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.desktop_support import HttpsServer
from tests.lifecycle_support import lifecycle_database_url
from tests.qml_workspace_support import run_workspace_qml

pytest_plugins = ("tests.test_counting_workflow_retry_desktop",)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def configure_private_backup_runtime(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    directory = tmp_path / "private-qml-backups"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setenv("ELECTION_BACKUP_DIRECTORY", str(directory))
    monkeypatch.setenv("ELECTION_MYSQL_CONTAINER", "election-system-mysql")
    monkeypatch.setenv("ELECTION_MYSQLDUMP_BINARY", "mysqldump")
    yield directory


def _credentials(admin: TestClient) -> dict[str, str]:
    response = admin.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return {"username": response.json()["username"], "password": "Configuration-Ready-84!"}


def test_admin_creates_backup_and_reviews_translated_server_metadata(
    admin: TestClient,
    https_server: HttpsServer,
    configure_private_backup_runtime: Path,
) -> None:
    account = _credentials(admin)
    before = {row["id"] for row in admin.get("/api/backups").json()["backups"]}
    labels = {
        "tc": {
            "navigation": "伺服器備份",
            "title": "伺服器備份",
            "create": "建立伺服器備份",
            "check": "檢查要求結果",
        },
        "sc": {
            "navigation": "服务器备份",
            "title": "服务器备份",
            "create": "创建服务器备份",
            "check": "检查要求结果",
        },
        "en": {
            "navigation": "Server backups",
            "title": "Server backups",
            "create": "Create backup",
            "check": "Check request outcome",
        },
    }
    run_workspace_qml(
        {
            "server": https_server.url,
            "username": account["username"],
            "password": account["password"],
            "station_id": 0,
            "locale": "tc",
            "labels": labels,
        },
        """
        import re
        for language in ('tc', 'sc', 'en'):
            controller.setLocale(language)
            frame()
            language_words = setup['labels'][language]
            navigation = control('serverBackupsNavigation').property('text')
            assert navigation == language_words['navigation']
            click('serverBackupsNavigation')
            page = controller.property('serverBackups')
            wait(lambda: not page.property('state')['refreshing'])
            assert control('serverBackupsTitle').property('text') == language_words['title']
            assert control('serverBackupCreate').property('text') == language_words['create']
            assert control('serverBackupRefresh').property('text')
            assert control('serverBackupPrivacyHint').property('text')
        assert window.findChild(QQuickItem, 'serverBackupDownload') is None

        controller.setLocale('en')
        frame()
        focus('serverBackupCreate')
        prior_jobs = controller.property('serverBackups').property('state')['jobs']
        prior_ids = {row['id'] for row in prior_jobs}
        click('serverBackupCreate')
        page = controller.property('serverBackups')
        wait(lambda: any(
            row['id'] not in prior_ids and row['status'] in ('succeeded', 'failed')
            for row in page.property('state')['jobs']))
        job = next(row for row in page.property('state')['jobs'] if row['id'] not in prior_ids)
        assert job['status'] == 'succeeded', job
        assert job['size_bytes'] > 0
        assert re.fullmatch(r'[0-9a-f]{64}', job['sha256'])
        assert job['cutoff_start'] and job['cutoff_end']
        expected_fields = {
            'id', 'request_id', 'status', 'requested_at', 'completed_at',
            'cutoff_start', 'cutoff_end', 'sha256', 'size_bytes', 'error_code'}
        assert set(job) == expected_fields
        assert 'path' not in job and 'artifact_path' not in job
        assert control('serverBackupStatus').property('text') == 'Completed'
        assert control('serverBackupLatestRequestId').property('text') == job['request_id']
        assert control('serverBackupLatestSha256').property('text') == job['sha256']
        assert control('serverBackupLatestSize').property('text') == str(job['size_bytes'])
        """,
    )

    with https_server.lock:
        assert ("GET", "/api/backups") in https_server.requests
        assert https_server.request_count("POST", "/api/backups") == 1
    listing = admin.get("/api/backups")
    assert listing.status_code == 200, listing.text
    new_jobs = [row for row in listing.json()["backups"] if row["id"] not in before]
    assert len(new_jobs) == 1
    job = new_jobs[0]
    assert job["status"] == "succeeded"
    assert str(configure_private_backup_runtime) not in json.dumps(listing.json())
    assert "password" not in json.dumps(listing.json()).lower()
    assert "database_url" not in json.dumps(listing.json()).lower()
    assert "path" not in job and "artifact_path" not in job


def test_material_outcome_check_resolves_committed_backup_after_lost_tls_reply(
    admin: TestClient,
    lost_selection_response,
    configure_private_backup_runtime: Path,
) -> None:
    endpoint = lost_selection_response
    account = _credentials(admin)
    before = {row["id"] for row in admin.get("/api/backups").json()["backups"]}
    endpoint.drop_path = "/api/backups"
    run_workspace_qml(
        {
            "server": endpoint.url,
            "username": account["username"],
            "password": account["password"],
            "station_id": 0,
            "locale": "en",
            "labels": {
                "en": {
                    "navigation": "Server backups",
                    "title": "Server backups",
                    "check": "Check request outcome",
                },
            },
        },
        """
        import re
        click('serverBackupsNavigation')
        page = controller.property('serverBackups')
        wait(lambda: not page.property('state')['refreshing'])
        click('serverBackupCreate')
        wait(lambda: page.property('state')['uncertain_save'])
        pending = page.property('state')['pending_request_id']
        assert pending
        assert control('serverBackupUncertain').property('visible') is True
        assert control('serverBackupCheckOutcome').property('enabled') is True
        expected_check = setup['labels']['en']['check']
        assert control('serverBackupCheckOutcome').property('text') == expected_check

        click('serverBackupCheckOutcome')
        wait(lambda: any(row['request_id'] == pending and row['status'] == 'succeeded'
            for row in page.property('state')['jobs'])
            and not page.property('state')['uncertain_save'])
        assert page.property('state')['pending_request_id'] in (None, '')
        assert control('serverBackupUncertain').property('visible') is False
        """,
    )

    assert endpoint.response_tagged.is_set()
    assert endpoint.response_dropped.is_set()
    assert endpoint.request_count("POST", "/api/backups") == 1
    assert endpoint.request_count("GET", "/api/backups") >= 2
    response = admin.get("/api/backups")
    assert response.status_code == 200, response.text
    new_jobs = [row for row in response.json()["backups"] if row["id"] not in before]
    assert len(new_jobs) == 1
    assert new_jobs[0]["status"] == "succeeded", new_jobs[0]
