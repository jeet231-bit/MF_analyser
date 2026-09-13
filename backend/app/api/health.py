import platform
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.exports.report import pdf_status
from app.storage.db import check_database

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    python: str
    database: str
    # "available", or "unavailable: <why>" so an operator learns about a missing GTK runtime
    # from deploy\status.ps1 and not from a 501 weeks later.
    pdf: str
    time: datetime


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    db_ok = check_database()
    pdf_ok, pdf_reason = pdf_status()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        python=platform.python_version(),
        database="ok" if db_ok else "unavailable",
        pdf="available" if pdf_ok else f"unavailable: {pdf_reason}",
        time=datetime.now(UTC),
    )
