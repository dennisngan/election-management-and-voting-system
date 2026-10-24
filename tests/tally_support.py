"""Prepare count-entry scopes through authenticated public operational APIs."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.counting_support import counting_setup


@contextmanager
def tally_setup(admin: TestClient, database_url: str) -> Iterator[dict]:
    with counting_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        box = setup["boxes"]["local_n1"]
        path = setup["paths"]["n1_counting_scopes"]
        saved = receiver.post(
            path,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "reference": "F1 scope " + uuid4().hex[:8],
                "event_at": "2026-11-15T23:10:00+08:00",
                "box_revisions": [{"box_id": box["id"], "revision": box["revision"]}],
                "accounting_revisions": [
                    {"station_id": setup["stations"]["N1"]["id"], "revision": 1}
                ],
            },
        )
        assert saved.status_code == 201, saved.text
        submitted = receiver.post(
            path + f"/{saved.json()['id']}/submit",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["count_ready"] is True
        yield {
            **setup,
            "scope": submitted.json(),
            "counter": receiver,
            "rounds_path": path + f"/{saved.json()['id']}/rounds",
        }
