"""Selected special-paper statements preserve frozen accounting in three languages."""

import csv
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from tests.special_paper_support import save_special_paper_revisions, special_paper_setup
from tests.test_special_papers_api import database_url as database_url
from tests.test_special_papers_api import private_active_election as private_active_election


@pytest.mark.parametrize(
    ("locale", "labels"),
    [
        pytest.param("en", {
            "title": "Special ballot stock accounting",
            "replacement": "Replacement papers issued",
            "retrieved": "Retrieved-unused papers total",
            "never_issued": "Never-issued stock total",
            "box": "Estimated box papers from stock",
        }, id="en"),
        pytest.param("tc", {
            "title": "補發、重複及未用選票核算",
            "replacement": "補發選票數量",
            "retrieved": "已收回未用選票合計",
            "never_issued": "從未發出選票合計",
            "box": "庫存推算票箱選票數量",
        }, id="tc"),
        pytest.param("sc", {
            "title": "补发、重复及未用选票核算",
            "replacement": "补发选票数量",
            "retrieved": "已收回未用选票合计",
            "never_issued": "从未发出选票合计",
            "box": "库存推算票箱选票数量",
        }, id="sc"),
    ],
)
def test_selected_statement_and_csv_keep_historical_figures_and_precise_source_context(
    admin: TestClient, database_url: str, locale: str, labels: dict[str, str],
) -> None:
    with special_paper_setup(admin, database_url) as setup:
        officer, path = setup["officer"], setup["path"]
        first, second, reason = save_special_paper_revisions(setup)
        target = path + f"/{first['id']}"
        assert second["revision"] == 2
        assert (first["retrieved_unused_quantity"], first["never_issued_quantity"],
                first["estimated_box_papers_quantity"]) == (3, 7, 2)
        assert (second["retrieved_unused_quantity"], second["never_issued_quantity"],
                second["estimated_box_papers_quantity"]) == (2, 6, 3)
        params = {"snapshot_id": first["id"], "revision": 1, "locale": locale}
        response = officer.get(path + "/statement", params=params)
        # First new-report assertion; the baseline treats "statement" as an invalid numeric ID.
        # Later JSON/CSV and immutable-readback assertions remain unreached in that RED.
        assert response.status_code == 200
        report = response.json()
        assert report["items"] == [first]
        assert report["revision_state"] == "historical"
        assert report.get("availability") is None
        assert report["locale"] == locale and report["title"] == labels["title"]
        assert isinstance(report["preview_lines"], list) and report["preview_lines"]
        assert all(isinstance(line, str) for line in report["preview_lines"])
        assert report["preview_lines"][0] == labels["title"]
        preview = "\n".join(report["preview_lines"])
        for key, value in (("replacement", "2"), ("retrieved", "3"),
                           ("never_issued", "7"), ("box", "2")):
            assert labels[key] + " · " + value in report["preview_lines"]
        for expected in (
            first["scope"]["election"]["name"],
            first["scope"]["constituency"]["code"],
            first["scope"]["constituency"]["name"],
            first["scope"]["station"]["code"],
            first["scope"]["station"]["name"],
            "2026-11-15 09:45:17.123456 HKT",
            "2026-11-15 09:30:17.123456 HKT",
        ):
            assert expected in preview
        exported = officer.get(path + "/statement.csv", params=params)
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/csv")
        assert exported.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
        assert rows[0] == [labels["title"]]
        for key, value in (("replacement", "2"), ("retrieved", "3"),
                           ("never_issued", "7"), ("box", "2")):
            assert [labels[key], value] in rows
        assert any("000011" in row and "000013" in row for row in rows)
        assert any("000014" in row and "000015" in row for row in rows)
        cells = [cell for row in rows for cell in row]
        assert "2026-11-15 09:45:17.123456 HKT" in cells
        assert "2026-11-15 09:30:17.123456 HKT" in cells
        assert reason not in cells

        current_params = {**params, "revision": 2}
        current_report = officer.get(path + "/statement", params=current_params)
        assert current_report.status_code == 200
        current = current_report.json()
        assert current["items"] == [second] and current["revision_state"] == "current"
        assert current["locale"] == locale and current.get("availability") is None
        current_preview = "\n".join(current["preview_lines"])
        assert all(line in current_preview for line in reason.splitlines())
        current_csv = officer.get(path + "/statement.csv", params=current_params)
        assert current_csv.status_code == 200 and current_csv.content.startswith(b"\xef\xbb\xbf")
        current_rows = list(csv.reader(StringIO(current_csv.content.decode("utf-8-sig"))))
        for key, value in (("replacement", "3"), ("retrieved", "2"),
                           ("never_issued", "6"), ("box", "3")):
            assert [labels[key], value] in current_rows
        assert any(cell == reason for row in current_rows for cell in row)
        repeated = officer.get(path + "/statement", params=params)
        assert repeated.status_code == 200 and repeated.json()["items"] == [first]
        assert repeated.json()["preview_lines"] == report["preview_lines"]
        retained = officer.get(target)
        assert retained.status_code == 200 and retained.json() == second
        history = officer.get(target + "/history")
        assert history.status_code == 200 and history.json()["items"] == [first, second]
        snapshot = officer.get(setup["base"] + f"/stock-snapshots/{setup['snapshot']['id']}")
        assert snapshot.status_code == 200 and snapshot.json() == setup["snapshot"]
        turnout = officer.get(setup["base"] + "/turnout")
        assert turnout.status_code == 200 and turnout.json() == setup["turnout"]
