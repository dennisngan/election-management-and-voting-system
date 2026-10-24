"""Invalid category commands preserve public records and reusable request identities."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.special_paper_support import special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_invalid_create_and_correction_inputs_do_not_consume_requests_or_change_records(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path, base = setup["officer"], setup["path"], setup["base"]
        created = officer.post(path, json=setup["command"])
        assert created.status_code == 201
        first = created.json()
        target = path + f"/{first['id']}"
        snapshot_path = base + f"/stock-snapshots/{setup['snapshot']['id']}"
        observed_paths = (
            path, target, target + "/history", snapshot_path, snapshot_path + "/history",
            base + "/turnout",
        )

        def readback() -> dict:
            records = {}
            for read_path in observed_paths:
                response = officer.get(read_path)
                assert response.status_code == 200, read_path
                records[read_path] = response.json()
            return records

        before = readback()
        failed_request_id = str(uuid4())
        count_changes = [
            (label, {"series": [{**setup["entered_series"], "replacement_issued_quantity": value}]})
            for label, value in (
                ("boolean-count", True), ("float-count", 1.0), ("string-count", "1"),
                ("negative-count", -1), ("above-supported-count", 9223372036854775808),
            )
        ]
        changes = [
            *count_changes,
            ("unknown-field", {"unexpected_field": "This field is outside the command contract."}),
            ("duplicate-series", {"series": [setup["entered_series"], setup["entered_series"]]}),
            ("blank-series", {"series": [{**setup["entered_series"], "series": "   "}]}),
            ("naive-time", {"event_at": "2026-11-15T09:45:17.123456"}),
            ("future-time", {"event_at": "2026-11-15T13:00:00+08:00"}),
            ("string-source-id", {"stock_snapshot_id": str(setup["snapshot"]["id"])}),
        ]
        correction = {
            **setup["command"], "revision": 1,
            "reason": "An invalid command must leave the saved observation unchanged.",
        }
        for method, endpoint, command in (
            ("POST", path, setup["command"]), ("PUT", target, correction),
        ):
            for label, changed in changes:
                request_id = (
                    failed_request_id if method == "POST" and label == "future-time"
                    else str(uuid4())
                )
                invalid = officer.request(method, endpoint, json={
                    **command, **changed, "request_id": request_id,
                })
                assert invalid.status_code == 422, (method, label, invalid.status_code)
                assert readback() == before
        invalid_reason = officer.put(target, json={
            **correction, "request_id": str(uuid4()), "reason": " \n ",
        })
        assert invalid_reason.status_code == 422
        assert readback() == before

        valid = officer.put(target, json={
            **correction, "request_id": failed_request_id,
            "reason": "The earlier rejected command did not consume this request identity.",
            "series": [{**setup["entered_series"], "retrieved_found_quantity": 0}],
        })
        assert valid.status_code == 200
        second = valid.json()
        assert second["revision"] == 2
        assert second["event_at"] == first["event_at"]
        assert second["retrieved_unused_quantity"] == 2
        assert second["estimated_box_papers_quantity"] == 3
        assert second["never_issued_quantity"] == 7
        current = officer.get(target)
        assert current.status_code == 200 and current.json() == second
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [first, second]
        collection = officer.get(path)
        assert collection.status_code == 200
        assert collection.json()["items"] == [second] and collection.json()["latest"] == second
        assert collection.json()["latest_basis_current"] is True
        assert officer.get(target, params={"revision": 1}).json() == first
        for read_path in (snapshot_path, snapshot_path + "/history", base + "/turnout"):
            response = officer.get(read_path)
            assert response.status_code == 200 and response.json() == before[read_path]
