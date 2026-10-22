"""Shared API setup helpers for election configuration behavior checks."""

from uuid import uuid4

from fastapi.testclient import TestClient


def create_election(admin: TestClient) -> dict:
    response = admin.post("/api/elections", json={"name": "分區測試", "request_id": str(uuid4())})
    assert response.status_code == 201
    return response.json()


def create_constituency(admin: TestClient, election_id: int, code: str = "N") -> dict:
    response = admin.post(
        f"/api/elections/{election_id}/constituencies",
        json={"code": code, "name": "選區 " + code, "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()
