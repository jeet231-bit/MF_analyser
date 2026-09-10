from fastapi.testclient import TestClient

from app import __version__


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert body["python"].startswith("3.12")


def test_openapi_is_served_under_api_prefix(client: TestClient) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
