"""Dashboard view endpoints: windowed sheet grid, inputs catalogue, outputs summary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.storage import logic, workbooks
from app.storage import runs as run_store
from app.storage import views as store
from app.storage.db import get_session
from app.storage.models import Run

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def _model_or_404(session: Session, version_id: str):
    try:
        workbooks.get_version(session, version_id)
        return logic.get_model(session, version_id)
    except workbooks.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No logic model for this version yet. POST /interpret first."
        ) from exc


def _run_or_404(session: Session, run_id: str) -> Run:
    try:
        return run_store.get_run(session, run_id)
    except run_store.RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.") from exc


def _run_for(session: Session, version_id: str, run_id: str | None) -> Run | None:
    if run_id:
        run = _run_or_404(session, run_id)
        if run.version_id != version_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Run belongs to another version."
            )
        return run
    return run_store.baseline_run(session, version_id)


@router.get("/runs/{run_id}/grid", response_model=store.GridOut)
def get_grid(
    run_id: str,
    session: SessionDep,
    sheet: Annotated[str, Query()],
    r1: Annotated[int | None, Query(ge=1)] = None,
    r2: Annotated[int | None, Query(ge=1)] = None,
    c1: Annotated[int | None, Query(ge=1)] = None,
    c2: Annotated[int | None, Query(ge=1)] = None,
) -> store.GridOut:
    """A window of one sheet as the run computed it: labelled columns, labelled rows, cells with
    formula / override / baseline markers. At most 200 rows by 120 columns per call."""
    run = _run_or_404(session, run_id)
    model = _model_or_404(session, run.version_id)
    if model.sheet(sheet) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model.")
    try:
        return store.grid_window(session, run, model, sheet, r1=r1, r2=r2, c1=c1, c2=c2)
    except workbooks.SheetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not found.") from exc


@router.get("/workbooks/{version_id}/inputs", response_model=store.InputsOut)
def get_inputs(
    version_id: str,
    session: SessionDep,
    run_id: Annotated[str | None, Query(description="Run whose overrides to show")] = None,
) -> store.InputsOut:
    """Every input block in scope, grouped by sheet; small blocks carry their labelled cells."""
    model = _model_or_404(session, version_id)
    run = _run_for(session, version_id, run_id)
    return store.inputs_catalogue(session, model, version_id, run, load_dashboard_config())


@router.get("/workbooks/{version_id}/outputs", response_model=store.OutputsOut)
def get_outputs(
    version_id: str,
    session: SessionDep,
    run_id: Annotated[str | None, Query(description="Run to summarise; default baseline")] = None,
) -> store.OutputsOut:
    """Output sheets in display order with headline metrics (and deltas vs the baseline when the
    run is a what-if), their business rules and a series descriptor when the data is a time series."""
    model = _model_or_404(session, version_id)
    run = _run_for(session, version_id, run_id)
    if run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No run for this version yet. Validate or POST /runs first."
        )
    return store.outputs_summary(session, model, run, load_dashboard_config())
