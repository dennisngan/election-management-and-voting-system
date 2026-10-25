"""Physical comparisons derive from frozen scope estimates and actual F1 counts."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.counting_support import counting_setup
from tests.outcomes_support import complete_f2_command
from tests.tally_support import complete_f1_command, tally_setup
from tests.test_counting_scopes_api import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_counting_scopes_api import database_url as database_url


def test_f2_projection_includes_frozen_physical_comparisons(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1_command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=0,
        )
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text

        f2_command = complete_f2_command(options)
        f2 = client.put(path + f"/{f1.json()['id']}/f2", json=f2_command)
        assert f2.status_code == 200, f2.text
        record = f2.json()
        assert record["scope_basis"]["estimated_box_from_stock_quantity"] == 5
        assert record["actual_counted_quantity"] == 0
        comparisons = {row["source"]: row for row in record["physical_comparisons"]}
        assert comparisons == {
            "stock": {
                "source": "stock",
                "expected_quantity": 5,
                "actual_quantity": 0,
                "difference_quantity": -5,
                "available": True,
                "status": "pending",
            },
            "turnout": {
                "source": "turnout",
                "expected_quantity": None,
                "actual_quantity": 0,
                "difference_quantity": None,
                "available": False,
                "status": "unavailable",
            },
        }
        assert any(
            row["code"] == "count_physical_difference_unaccepted"
            and row["source"] == "stock"
            and row["difference_quantity"] == -5
            for row in record["approval_blockers"]
        )
        assert not any(
            row.get("source") == "turnout" for row in record["approval_blockers"]
        )
        replay = client.put(path + f"/{f1.json()['id']}/f2", json=f2_command)
        assert replay.status_code == 200 and replay.json() == record
        resumed = client.get(path + f"/{f1.json()['id']}")
        assert resumed.status_code == 200
        assert resumed.json()["record"]["physical_comparisons"] == record["physical_comparisons"]


def test_matching_physical_comparison_is_visible_without_review_blocker(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        f1_command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=5,
        )
        f1_command["candidate_votes"][0]["quantity"] = 5
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text
        f2 = client.put(
            path + f"/{f1.json()['id']}/f2",
            json=complete_f2_command(options),
        )
        assert f2.status_code == 200, f2.text
        comparisons = {row["source"]: row for row in f2.json()["physical_comparisons"]}
        assert comparisons["stock"] == {
            "source": "stock",
            "expected_quantity": 5,
            "actual_quantity": 5,
            "difference_quantity": 0,
            "available": True,
            "status": "matching",
        }
        assert not any(
            row.get("source") == "stock"
            and row["code"] == "count_physical_difference_unaccepted"
            for row in f2.json()["approval_blockers"]
        )


def test_large_positive_physical_difference_stays_exact_through_round_readback(
    admin: TestClient,
    database_url: str,
) -> None:
    with tally_setup(admin, database_url) as setup:
        client, path = setup["counter"], setup["rounds_path"]
        options = client.get(path).json()
        actual = 900719925474099312345
        f1_command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=actual,
        )
        f1_command["candidate_votes"][0]["quantity"] = actual
        f1 = client.post(path, json=f1_command)
        assert f1.status_code == 201, f1.text
        f2_command = complete_f2_command(options)
        f2 = client.put(path + f"/{f1.json()['id']}/f2", json=f2_command)
        assert f2.status_code == 200, f2.text
        expected_difference = 900719925474099312340
        stock = next(
            row for row in f2.json()["physical_comparisons"] if row["source"] == "stock"
        )
        assert type(stock["difference_quantity"]) is int
        assert stock["difference_quantity"] == expected_difference
        saved = client.get(path + f"/{f1.json()['id']}").json()["record"]
        stock_after_read = next(
            row for row in saved["physical_comparisons"] if row["source"] == "stock"
        )
        assert type(stock_after_read["difference_quantity"]) is int
        assert stock_after_read["difference_quantity"] == expected_difference


def test_partial_source_scope_marks_both_physical_comparisons_unavailable(
    admin: TestClient,
    database_url: str,
) -> None:
    with counting_setup(admin, database_url) as setup:
        receiver = setup["clients"]["receiveronly"]
        scopes_path = setup["paths"]["n1_counting_scopes"]
        selected_boxes = [setup["boxes"]["local_n1"], setup["boxes"]["transferred_n2"]]
        origin_codes = ("N1", "N2")
        scope_command = {
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "reference": "Partial source comparison scope",
            "event_at": "2026-11-15T23:10:00+08:00",
            "box_revisions": [
                {"box_id": box["id"], "revision": box["revision"]} for box in selected_boxes
            ],
            "accounting_revisions": [
                {"station_id": setup["stations"][code]["id"], "revision": 1}
                for code in origin_codes
            ],
        }
        created = receiver.post(scopes_path, json=scope_command)
        assert created.status_code == 201, created.text
        scope = receiver.post(
            scopes_path + f"/{created.json()['id']}/submit",
            json={"request_id": str(uuid4()), "expected_revision": 1},
        )
        assert scope.status_code == 200, scope.text
        assert scope.json()["estimated_box_from_stock_quantity"] is None
        assert scope.json()["estimated_box_from_turnout_quantity"] is None

        rounds_path = scopes_path + f"/{created.json()['id']}/rounds"
        options = receiver.get(rounds_path).json()
        f1_command = complete_f1_command(
            options,
            questionable_quantity=0,
            actual_counted_quantity=0,
        )
        f1 = receiver.post(rounds_path, json=f1_command)
        assert f1.status_code == 201, f1.text
        f2 = receiver.put(
            rounds_path + f"/{f1.json()['id']}/f2",
            json=complete_f2_command(options),
        )
        assert f2.status_code == 200, f2.text
        comparisons = {row["source"]: row for row in f2.json()["physical_comparisons"]}
        assert set(comparisons) == {"stock", "turnout"}
        for comparison in comparisons.values():
            assert comparison["expected_quantity"] is None
            assert comparison["actual_quantity"] == 0
            assert comparison["difference_quantity"] is None
            assert comparison["available"] is False
            assert comparison["status"] == "unavailable"
        assert not any(
            row["code"] == "count_physical_difference_unaccepted"
            for row in f2.json()["approval_blockers"]
        )
