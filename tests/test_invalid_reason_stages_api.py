"""Reason codes remain unique within each stage without changing historical identities."""

from fastapi.testclient import TestClient

from tests.configuration_support import create_election
from tests.test_invalid_ballot_reasons_api import catalog_input


def test_custom_f1_code_can_coexist_with_verified_f2_source_code(admin: TestClient) -> None:
    election = create_election(admin)
    path = f"/api/elections/{election['id']}/invalid-ballot-reasons"
    f2_before = admin.get(path, params={"stage": "f2"}).json()["items"]
    created = admin.post(path, json=catalog_input(code="gc-f2-h", stage="f1"))
    assert created.status_code == 201, created.text
    custom = created.json()
    source = next(row for row in f2_before if row["code"] == "gc-f2-h")
    assert custom["id"] != source["id"]
    assert custom["stage"] == "f1" and custom["verified_source"] is False
    assert admin.get(path, params={"stage": "f2"}).json()["items"] == f2_before
    assert custom in admin.get(path).json()["items"]
    assert admin.get(path + f"/{custom['id']}").json()["record"] == custom
    duplicate = admin.post(path, json=catalog_input(code="gc-f2-h", stage="f1"))
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"]["code"] == "invalid_reason_code_exists"
