import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_collections_api():
    client = TestClient(app)
    resp = client.get("/api/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if len(data) > 0:
        col = data[0]
        assert "id" in col
        assert "name" in col
        assert "code" in col
        assert "members" in col

        # Test single get
        single_resp = client.get(f"/api/collections/{col['id']}")
        assert single_resp.status_code == 200
        assert single_resp.json()["id"] == col["id"]

        # Test export
        export_resp = client.get(f"/api/collections/{col['id']}/export")
        assert export_resp.status_code == 200
        assert export_resp.headers["content-type"] == "application/json"
        postman = export_resp.json()
        assert "item" in postman
        assert "info" in postman
