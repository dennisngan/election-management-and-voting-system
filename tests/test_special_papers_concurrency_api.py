"""Concurrent public clients must not freeze incompatible receipt/P(12) revisions."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

from fastapi import Request
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.special_paper_support import special_paper_setup
from tests.stock_support import stock_payload
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


def test_receipt_amendment_race_never_saves_a_mixed_special_paper_snapshot_basis(
    admin: TestClient, database_url: str,
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, base, path = setup["officer"], setup["base"], setup["path"]
        original = setup["receipt"]
        source_id = original["id"]
        many = officer.post(
            base + "/stock",
            json=stock_payload(
                ordinary_quantity=1000,
                replacement_quantity=0,
                tendered_quantity=0,
                ranges=[{
                    "pool": "ordinary",
                    "serial_from": f"{10000 + 2 * index:06d}",
                    "serial_to": f"{10000 + 2 * index:06d}",
                } for index in range(1000)],
            ),
        )
        assert many.status_code == 201
        assert len(many.json()["ranges"]) == 1000
        receipt_path = base + f"/stock/{source_id}"
        correction = stock_payload(
            revision=original["revision"],
            reason="核對原接收文件，保留原系列、範圍及數量。",
            event_at=original["event_at"],
            ordinary_quantity=10,
            replacement_quantity=3,
            tendered_quantity=2,
            ranges=[
                {key: row[key] for key in ("pool", "serial_from", "serial_to")}
                for row in original["ranges"]
            ],
        )
        put_arrived = Event()
        clients_ready = Barrier(9)
        writer_app = create_app(database_url, now=setup["clock"])

        @writer_app.middleware("http")
        async def observe_public_put_arrival(request: Request, call_next):
            # Only public method/path arrival is observed; there is no SQL,
            # transaction-phase hook, forced product delay or altered response.
            if request.method == "PUT" and request.url.path == receipt_path:
                put_arrived.set()
            return await call_next(request)

        def amend_receipt() -> tuple[int, dict]:
            with TestClient(writer_app) as writer:
                writer.headers.update(officer.headers)
                response = writer.put(receipt_path, json=correction)
                return response.status_code, response.json()

        def submit_observation(index: int) -> tuple[int, dict]:
            with TestClient(create_app(database_url, now=setup["clock"])) as peer:
                peer.headers.update(officer.headers)
                clients_ready.wait(timeout=5)
                assert put_arrived.wait(timeout=5), "The public receipt PUT did not arrive"
                response = peer.post(
                    path, json={**setup["command"], "request_id": str(uuid4())},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=9) as pool:
            # Prepare independent clients before starting the source command.
            # Their actual POSTs begin only after its public request arrival.
            targets = [pool.submit(submit_observation, index) for index in range(8)]
            clients_ready.wait(timeout=5)
            writer = pool.submit(amend_receipt)
            writer_status, writer_dto = writer.result()
            outcomes = [target.result() for target in targets]

        metadata = {
            "source_receipt_id": source_id,
            "other_receipt_id": many.json()["id"],
            "other_receipt_range_count": 1000,
            "writer_status": writer_status,
            "writer_revision": writer_dto.get("revision"),
            "outcomes": [],
            "observation_limit": (
                "The event records only PUT method/path arrival. It does not prove a private "
                "transaction phase or force an overlapping repeatable-read snapshot."
            ),
        }
        for status, body in outcomes:
            receipt_basis = {
                row["receipt_id"]: row["revision"] for row in body.get("receipt_basis", [])
            }
            frozen_basis = {
                row["receipt_id"]: row["revision"]
                for row in body.get("stock_snapshot_data", {}).get("receipt_basis", [])
            }
            metadata["outcomes"].append({
                "status": status,
                "record_id": body.get("id"),
                "error_code": body.get("detail", {}).get("code"),
                "source_receipt_revision": receipt_basis.get(source_id),
                "frozen_p12_receipt_revision": frozen_basis.get(source_id),
            })
        # -s preserves this public-only outcome record on both passing and failing runs.
        print("PUBLIC CONCURRENCY OUTCOMES " + json.dumps(metadata, ensure_ascii=False))
        assert writer_status == 200
        assert writer_dto["id"] == source_id and writer_dto["revision"] == 2
        for outcome in metadata["outcomes"]:
            assert outcome["status"] in (201, 409), outcome
            if outcome["status"] == 201:
                assert outcome["source_receipt_revision"] is not None
                assert (
                    outcome["source_receipt_revision"] == outcome["frozen_p12_receipt_revision"]
                ), outcome
            else:
                assert outcome["error_code"] == "stock_snapshot_basis_stale", outcome
        for status, body in outcomes:
            if status == 201:
                read = officer.get(path + f"/{body['id']}")
                assert read.status_code == 200 and read.json() == body
        receipt_after = officer.get(receipt_path)
        assert receipt_after.status_code == 200 and receipt_after.json() == writer_dto
        snapshot_after = officer.get(base + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot_after.status_code == 200 and snapshot_after.json() == setup["snapshot"]
        turnout_after = officer.get(base + "/turnout")
        assert turnout_after.status_code == 200 and turnout_after.json() == setup["turnout"]
