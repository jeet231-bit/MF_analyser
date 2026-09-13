"""The access gate: one shared password, a signed session cookie, every ``/api`` route behind it.

The password is stored as a PBKDF2-HMAC-SHA256 hash (``pbkdf2_sha256$iterations$salt$hash``);
the cookie carries a random session id signed with ``itsdangerous`` and expires after
``session_hours`` of inactivity (it is refreshed on use once half its life has passed). Real
accounts will replace this gate and also supply the viewer's name and the watchlist owner.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

log = logging.getLogger(__name__)

COOKIE = "mfa_session"
ITERATIONS = 600_000
PUBLIC_PREFIXES = ("/api/health", "/api/auth/")


# ---- passwords ---------------------------------------------------------------------------------


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, hash_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)


# ---- sessions ----------------------------------------------------------------------------------


class SessionManager:
    def __init__(self, secret: str, hours: int) -> None:
        self.signer = TimestampSigner(secret, salt="mfa-session")
        self.max_age = max(1, hours) * 3600

    def issue(self) -> str:
        return self.signer.sign(secrets.token_urlsafe(24)).decode("ascii")

    def age(self, token: str) -> int | None:
        """Seconds since the token was issued, or None when it is invalid or expired."""
        try:
            _value, timestamp = self.signer.unsign(
                token, max_age=self.max_age, return_timestamp=True
            )
        except (BadSignature, SignatureExpired):
            return None
        return int(time.time() - timestamp.timestamp())

    def cookie_header(self, token: str) -> str:
        return f"{COOKIE}={token}; Path=/; Max-Age={self.max_age}; HttpOnly; SameSite=Lax"

    def clear_header(self) -> str:
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


class LoginThrottle:
    """After three failures from one address, each further attempt waits a growing delay."""

    def __init__(self, free_attempts: int = 3, max_delay: float = 8.0) -> None:
        self.free_attempts = free_attempts
        self.max_delay = max_delay
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    def delay_for(self, key: str) -> float:
        with self._lock:
            n = self._failures.get(key, 0)
        over = n - self.free_attempts + 1
        return min(self.max_delay, float(2 ** (over - 1))) if over > 0 else 0.0

    def failed(self, key: str) -> None:
        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def cookie_value(headers: list[tuple[bytes, bytes]], name: str = COOKIE) -> str | None:
    for key, value in headers:
        if key.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
    return None


def is_public(path: str) -> bool:
    if not path.startswith("/api/") and path != "/api":
        return True  # the UI itself, its assets, and the login screen
    return any(path == p.rstrip("/") or path.startswith(p) for p in PUBLIC_PREFIXES)


class AuthMiddleware:
    """Pure ASGI: every ``/api`` request needs a valid session cookie, except the health
    endpoint and the auth endpoints. A session past half its life is refreshed on use."""

    def __init__(self, app: Any, sessions: SessionManager) -> None:
        self.app = app
        self.sessions = sessions

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http" or is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        token = cookie_value(scope.get("headers", []))
        age = self.sessions.age(token) if token else None
        if age is None:
            body = b'{"detail":"Sign in to continue."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if age < self.sessions.max_age / 2:
            await self.app(scope, receive, send)
            return
        fresh = self.sessions.issue()

        async def send_with_cookie(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"set-cookie", self.sessions.cookie_header(fresh).encode("latin-1"))
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
