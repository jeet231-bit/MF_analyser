"""The built UI is served by the API process with SPA fallback; without a build the root explains."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(
        "<!doctype html><title>MF</title><div id=root></div>", encoding="utf-8"
    )
    (d / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (d / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setenv("MFA_STATIC_DIR", str(d))
    get_settings.cache_clear()
    yield d
    get_settings.cache_clear()


def test_spa_fallback_and_assets(dist: Path) -> None:
    with TestClient(create_app()) as client:
        root = client.get("/")
        assert root.status_code == 200 and "id=root" in root.text
        assert root.headers["cache-control"] == "no-store"
        deep = client.get("/funds/abc?x=1")
        assert deep.status_code == 200 and deep.text == root.text
        asset = client.get("/assets/index-abc123.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert client.get("/favicon.svg").status_code == 200
        missing_api = client.get("/api/nope")
        assert missing_api.status_code == 404 and missing_api.headers["content-type"].startswith(
            "application/json"
        )
        assert client.get("/api/health").status_code == 200
        # Nothing outside dist is reachable through the catch-all.
        assert client.get("/../pyproject.toml").text == root.text


def test_without_a_build_the_root_explains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MFA_STATIC_DIR", str(tmp_path / "nowhere"))
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            root = client.get("/")
            assert root.status_code == 200 and "not been built" in root.text
            assert client.get("/api/health").status_code == 200
    finally:
        get_settings.cache_clear()
