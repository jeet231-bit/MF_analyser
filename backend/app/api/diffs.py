"""Logic diff endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.model.diff import DiffReport
from app.storage import diffs as store
from app.storage import logic, workbooks
from app.storage.db import get_session

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/workbooks/{base_id}/diff/{target_id}", response_model=DiffReport)
def get_diff(
    base_id: str,
    target_id: str,
    session: SessionDep,
    refresh: Annotated[bool, Query(description="Recompute even if a stored report exists")] = False,
) -> DiffReport:
    """Changes from ``base_id`` to ``target_id`` in logic terms: LOGIC, DATA, STRUCTURAL, with impact."""
    for vid in (base_id, target_id):
        try:
            workbooks.get_version(session, vid)
        except workbooks.WorkbookNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Workbook version {vid} not found."
            ) from exc
    try:
        return store.get_diff(session, base_id, target_id, refresh=refresh)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Both versions must be interpreted before they can be compared.",
        ) from exc
