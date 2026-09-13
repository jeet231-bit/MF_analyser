"""Sign in with the shared password; the session lives in an HttpOnly cookie."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth import COOKIE, LoginThrottle, SessionManager, cookie_value, verify_password
from app.config import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")
throttle = LoginThrottle()


class LoginIn(BaseModel):
    password: str


class SessionOut(BaseModel):
    required: bool
    authenticated: bool
    sessionHours: int  # noqa: N815 - mirrors the JSON the frontend reads


def _sessions(request: Request) -> SessionManager | None:
    return getattr(request.app.state, "sessions", None)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/session", response_model=SessionOut)
def session_state(request: Request) -> SessionOut:
    settings = get_settings()
    sessions = _sessions(request)
    if not settings.auth_enabled or sessions is None:
        return SessionOut(required=False, authenticated=True, sessionHours=settings.session_hours)
    token = cookie_value(request.scope.get("headers", []))
    return SessionOut(
        required=True,
        authenticated=bool(token) and sessions.age(token or "") is not None,
        sessionHours=settings.session_hours,
    )


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(body: LoginIn, request: Request, response: Response) -> Response:
    settings = get_settings()
    sessions = _sessions(request)
    if not settings.auth_enabled or sessions is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    key = _client(request)
    delay = throttle.delay_for(key)
    if delay:
        time.sleep(delay)
    if not verify_password(body.password, settings.auth_password_hash):
        throttle.failed(key)
        log.warning("failed sign-in from %s", key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That password is not right.")
    throttle.succeeded(key)
    log.info("sign-in from %s", key)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    out.headers.append("set-cookie", sessions.cookie_header(sessions.issue()))
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    sessions = _sessions(request)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    if sessions is not None:
        out.headers.append("set-cookie", sessions.clear_header())
    else:
        out.headers.append("set-cookie", f"{COOKIE}=; Path=/; Max-Age=0")
    return out
