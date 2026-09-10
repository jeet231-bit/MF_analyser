import platform
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.storage.db import check_database

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    python: str
    database: str
    time: datetime


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    db_ok = check_database()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        python=platform.python_version(),
        database="ok" if db_ok else "unavailable",
        time=datetime.now(UTC),
    )
