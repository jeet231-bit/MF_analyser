"""FastAPI application factory: the API under /api, the access gate in front of it, the built
frontend served from the same process, logs in the data directory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.auth import AuthMiddleware, SessionManager
from app.config import get_settings
from app.logging_setup import configure_logging
from app.static import mount_frontend
from app.storage import models as _models  # noqa: F401 - registers ORM tables on Base
from app.storage.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.resolved_log_dir)
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.auth_enabled:
        sessions = SessionManager(
            settings.auth_secret or settings.auth_password_hash, settings.session_hours
        )
        app.state.sessions = sessions
        app.add_middleware(AuthMiddleware, sessions=sessions)
    app.include_router(api_router, prefix="/api")
    mount_frontend(app, settings.resolved_static_dir)
    return app


app = create_app()
