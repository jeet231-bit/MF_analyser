"""The access gate: one shared password, a signed cookie, every /api route behind it."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.auth import LoginThrottle, SessionManager, hash_password, verify_password
from app.config import get_settings
from app.main import create_app
from app.tools import set_password

PASSWORD = "correct horse battery"


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MFA_AUTH_PASSWORD_HASH", hash_password(PASSWORD, iterations=1000))
    monkeypatch.setenv("MFA_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("MFA_SESSION_HOURS", "1")
    get_settings.cache_clear()
    auth_api.throttle.__init__()
    try:
        with TestClient(create_app()) as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_password_hashing_round_trip() -> None:
    stored = hash_password("s3cret", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert verify_password("s3cret", stored)
    assert not verify_password("S3cret", stored)
    assert not verify_password("s3cret", "garbage")
    assert hash_password("s3cret", iterations=1000) != stored  # fresh salt every time


def test_every_api_route_is_locked_until_sign_in(gated: TestClient) -> None:
    assert gated.get("/api/health").status_code == 200
    locked = gated.get("/api/workbooks")
    assert locked.status_code == 401 and locked.json() == {"detail": "Sign in to continue."}
    assert gated.get("/api/docs").status_code == 401
    assert gated.get("/api/research/summary").status_code == 401
    state = gated.get("/api/auth/session").json()
    assert state == {"required": True, "authenticated": False, "sessionHours": 1}
    # The UI itself is public so the login screen can load.
    assert gated.get("/").status_code == 200

    wrong = gated.post("/api/auth/login", json={"password": "nope"})
    assert wrong.status_code == 401 and "mfa_session" not in gated.cookies

    ok = gated.post("/api/auth/login", json={"password": PASSWORD})
    assert ok.status_code == 204
    cookie = ok.headers["set-cookie"]
    assert "mfa_session=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert gated.get("/api/workbooks").status_code == 200
    assert gated.get("/api/auth/session").json()["authenticated"] is True

    assert gated.post("/api/auth/logout").status_code == 204
    assert gated.get("/api/workbooks").status_code == 401


def test_a_tampered_or_foreign_cookie_is_rejected(gated: TestClient) -> None:
    gated.post("/api/auth/login", json={"password": PASSWORD})
    token = gated.cookies["mfa_session"]
    gated.cookies.clear()
    gated.cookies.set("mfa_session", token[:-3] + "abc")
    assert gated.get("/api/workbooks").status_code == 401
    foreign = SessionManager("another-secret", 1).issue()
    gated.cookies.clear()
    gated.cookies.set("mfa_session", foreign)
    assert gated.get("/api/workbooks").status_code == 401


def test_expired_sessions_lock_and_live_ones_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = SessionManager("s", hours=1)
    token = sessions.issue()
    assert sessions.age(token) == 0
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 2 * 3600)
    assert sessions.age(token) is None


def test_throttle_delays_after_three_failures() -> None:
    throttle = LoginThrottle(max_delay=8)
    for _ in range(3):
        assert throttle.delay_for("1.2.3.4") == 0
        throttle.failed("1.2.3.4")
    assert throttle.delay_for("1.2.3.4") == 1
    throttle.failed("1.2.3.4")
    assert throttle.delay_for("1.2.3.4") == 2
    throttle.failed("1.2.3.4")
    throttle.failed("1.2.3.4")
    throttle.failed("1.2.3.4")
    throttle.failed("1.2.3.4")
    assert throttle.delay_for("1.2.3.4") == 8
    assert throttle.delay_for("5.6.7.8") == 0
    throttle.succeeded("1.2.3.4")
    assert throttle.delay_for("1.2.3.4") == 0


def test_login_waits_after_repeated_failures(gated: TestClient) -> None:
    for _ in range(3):
        gated.post("/api/auth/login", json={"password": "wrong"})
    started = time.perf_counter()
    assert gated.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert time.perf_counter() - started >= 0.9


def test_no_hash_means_no_gate(client: TestClient) -> None:
    assert client.get("/api/workbooks").status_code == 200
    state = client.get("/api/auth/session").json()
    assert state["required"] is False and state["authenticated"] is True


def test_set_password_tool_writes_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.env"
    cfg.write_text("MFA_PORT=8000\n# keep me\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("a strong password\n"))
    assert set_password.main(["--config-file", str(cfg), "--stdin"]) == 0
    text = cfg.read_text(encoding="utf-8")
    assert "MFA_PORT=8000" in text and "# keep me" in text
    assert verify_password(
        "a strong password", set_password.current(cfg, "MFA_AUTH_PASSWORD_HASH") or ""
    )
    secret = set_password.current(cfg, "MFA_AUTH_SECRET")
    assert secret
    # A second run replaces the hash and keeps the secret.
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("another password\n"))
    assert set_password.main(["--config-file", str(cfg), "--stdin"]) == 0
    assert set_password.current(cfg, "MFA_AUTH_SECRET") == secret
    assert verify_password(
        "another password", set_password.current(cfg, "MFA_AUTH_PASSWORD_HASH") or ""
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("short\n"))
    assert set_password.main(["--config-file", str(cfg), "--stdin"]) == 2
