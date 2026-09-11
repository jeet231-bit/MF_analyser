"""Validation and activation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.workbooks import WorkbookVersionOut
from app.engine.runner import ModelHasCyclesError
from app.storage import logic, workbooks
from app.storage import validation as store
from app.storage.db import get_session
from app.validation.schema import ValidationReport

router = APIRouter(prefix="/workbooks/{version_id}")
SessionDep = Annotated[Session, Depends(get_session)]


class ActivateRequest(BaseModel):
    override_reason: str | None = None


def _version_or_404(session: Session, version_id: str) -> None:
    try:
        workbooks.get_version(session, version_id)
    except workbooks.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc


@router.post("/validate", response_model=ValidationReport)
def validate(version_id: str, session: SessionDep) -> ValidationReport:
    """Run the engine with no overrides and reconcile every formula cell against Excel's cached values."""
    _version_or_404(session, version_id)
    try:
        return store.validate_version(session, version_id)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No logic model for this version yet. POST /interpret first."
        ) from exc
    except ModelHasCyclesError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"message": str(exc), "cycles": exc.descriptions}
        ) from exc


@router.get("/validation", response_model=ValidationReport)
def get_validation(version_id: str, session: SessionDep) -> ValidationReport:
    _version_or_404(session, version_id)
    try:
        return store.latest_validation(session, version_id)
    except store.ValidationNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This version has not been validated yet."
        ) from exc


@router.post("/activate", response_model=WorkbookVersionOut)
def activate(
    version_id: str, session: SessionDep, body: ActivateRequest | None = None
) -> WorkbookVersionOut:
    _version_or_404(session, version_id)
    body = body or ActivateRequest()
    try:
        version = store.activate_version(session, version_id, body.override_reason)
    except store.ActivationRefusedError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "validation_status": exc.validation_status},
        ) from exc
    return WorkbookVersionOut.from_row(version)
