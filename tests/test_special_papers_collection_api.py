"""Shared special-paper state distinguishes missing, zero and changed source bases."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_collection_retains_saved_zeroes_and_requires_review_of_a_changed_ordinary_basis(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path, base = setup["officer"], setup["path"], setup["base"]
        missing = officer.get(path)
        assert missing.status_code == 200
        assert missing.json()["items"] == [] and missing.json()["latest"] is None
        assert missing.json()["latest_basis_current"] is None
        zero = {
            **setup["command"],
            "series": [{key: value if key == "series" else 0
                        for key, value in setup["entered_series"].items()}],
        }
        created = officer.post(path, json=zero)
        assert created.status_code == 201
        saved = created.json()
        target = path + f"/{saved['id']}"
        current = officer.get(path)
        assert current.status_code == 200
        assert current.json()["items"] == [saved] and current.json()["latest"] == saved
        assert current.json()["latest_basis_current"] is True
        assert current.json()["latest"]["retrieved_unused_quantity"] == 0
        assert current.json()["latest"]["never_issued_quantity"] == 10
        snapshot = setup["snapshot"]
        revised_snapshot = officer.put(base + f"/stock-snapshots/{snapshot['id']}", json={
            "request_id": str(uuid4()), "revision": 1,
            "reason": "A sixth ordinary paper had already been issued at this observation.",
            "event_at": "2026-11-15T09:30:17.123456+08:00",
            "counters": [{
                "counter_id": snapshot["counters"][0]["counter"]["id"],
                "ranges": [{"series": "普通系列 A", "serial_from": "000007",
                            "serial_to": "000010"}],
            }],
        })
        assert revised_snapshot.status_code == 200
        assert revised_snapshot.json()["ordinary_issued_quantity"] == 6
        stale = officer.get(path)
        assert stale.status_code == 200 and stale.json()["latest_basis_current"] is False
        assert stale.json()["latest"] == saved and stale.json()["items"] == [saved]
        rejected = officer.post(path, json={**zero, "request_id": str(uuid4())})
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "stock_snapshot_basis_stale"
        reviewed = officer.put(target, json={
            **zero, "request_id": str(uuid4()), "revision": 1,
            "reason": "Review the category observation against the corrected P(12) revision.",
            "stock_snapshot_revision": 2,
        })
        assert reviewed.status_code == 200
        second = reviewed.json()
        assert second["ordinary_issued_quantity"] == second["estimated_box_papers_quantity"] == 6
        assert second["ordinary_unissued_quantity"] == 4
        assert second["never_issued_quantity"] == 9
        assert second["stock_snapshot_revision"] == 2
        current = officer.get(path)
        assert current.status_code == 200 and current.json()["latest_basis_current"] is True
        assert current.json()["latest"] == second and current.json()["items"] == [second]
        assert officer.get(target, params={"revision": 1}).json() == saved
        turnout = officer.get(base + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
