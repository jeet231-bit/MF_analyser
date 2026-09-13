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
    assert body["pdf"] == "available" or body["pdf"].startswith("unavailable: ")


def test_health_explains_a_missing_gtk_runtime(client: TestClient, monkeypatch) -> None:
    from app.api import health as health_mod

    monkeypatch.setattr(
        health_mod, "pdf_status", lambda: (False, "GTK not found: install the GTK3 runtime")
    )
    body = client.get("/api/health").json()
    assert body["status"] == "ok"  # the app is fine; only PDF export is off
    assert body["pdf"].startswith("unavailable: GTK not found")


def test_openapi_is_served_under_api_prefix(client: TestClient) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
