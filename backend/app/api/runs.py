"""Engine endpoints: runs, values per sheet, lineage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.engine.functions import UnsupportedFunctionError
from app.engine.lineage import LineageNode, explain
from app.engine.runner import ModelHasCyclesError, OverrideError, RunSummary
from app.model.formula.refs import Rect, parse_a1_cell
from app.storage import logic, workbooks
from app.storage import runs as store
from app.storage.db import get_session
from app.storage.models import Run

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


class RunRequest(BaseModel):
    overrides: dict[str, Any] = Field(
        default_factory=dict, description="'Sheet!A1' or defined name -> value"
    )
    mode: Literal["auto", "full"] = "auto"


class RunOut(BaseModel):
    id: str
    version_id: str
    kind: str
    parent_run_id: str | None
    overrides: dict[str, Any]
    status: str
    created_at: datetime
    summary: RunSummary

    @classmethod
    def from_row(cls, row: Run) -> RunOut:
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        return cls(
            id=row.id,
            version_id=row.version_id,
            kind=row.kind,
            parent_run_id=row.parent_run_id,
            overrides=store.overrides_of(row),
            status=row.status,
            created_at=created,
            summary=store.summary_of(row),
        )


class SheetValuesOut(BaseModel):
    run_id: str
    sheet: str
    range: str | None
    count: int
    cells: list[dict[str, Any]]


def _version_or_404(session: Session, version_id: str) -> None:
    try:
        workbooks.get_version(session, version_id)
    except workbooks.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc


@router.post(
    "/workbooks/{version_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED
)
def create_run(version_id: str, session: SessionDep, body: RunRequest | None = None) -> RunOut:
    body = body or RunRequest()
    _version_or_404(session, version_id)
    try:
        run = store.create_run(session, version_id, body.overrides, body.mode)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No logic model for this version yet. POST /interpret first."
        ) from exc
    except ModelHasCyclesError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "cycles": exc.descriptions},
        ) from exc
    except UnsupportedFunctionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": str(exc), "function": exc.function, "sheet": exc.sheet, "cell": exc.cell},
        ) from exc
    except OverrideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return RunOut.from_row(run)


@router.get("/workbooks/{version_id}/runs", response_model=list[RunOut])
def list_runs(version_id: str, session: SessionDep) -> list[RunOut]:
    _version_or_404(session, version_id)
    return [RunOut.from_row(r) for r in store.list_runs(session, version_id)]


def _run_or_404(session: Session, run_id: str) -> Run:
    try:
        return store.get_run(session, run_id)
    except store.RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.") from exc


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: SessionDep) -> RunOut:
    return RunOut.from_row(_run_or_404(session, run_id))


@router.get("/runs/{run_id}/values", response_model=SheetValuesOut)
def get_values(
    run_id: str,
    session: SessionDep,
    sheet: Annotated[str, Query()],
    range: Annotated[str | None, Query(description="A1 range to restrict to, e.g. A1:D50")] = None,  # noqa: A002
) -> SheetValuesOut:
    run = _run_or_404(session, run_id)
    rect = None
    if range:
        try:
            rect = Rect.from_a1(range)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad range {range!r}"
            ) from exc
    try:
        cells = store.sheet_values(session, run, sheet, rect)
    except workbooks.SheetNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not found in this version."
        ) from exc
    return SheetValuesOut(run_id=run.id, sheet=sheet, range=range, count=len(cells), cells=cells)


@router.get(
    "/workbooks/{version_id}/lineage/{cellref}",
    response_model=LineageNode,
    response_model_exclude_none=True,
)
def get_lineage(
    version_id: str,
    cellref: str,
    session: SessionDep,
    run_id: Annotated[
        str | None, Query(description="Run whose values to show; default: the baseline run")
    ] = None,
    depth: Annotated[int, Query(ge=1, le=6)] = 1,
) -> LineageNode:
    _version_or_404(session, version_id)
    try:
        model = logic.get_model(session, version_id)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No logic model for this version yet."
        ) from exc
    if "!" not in cellref:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cellref must be 'Sheet!A1'")
    sheet, addr = cellref.rsplit("!", 1)
    sheet = sheet.strip("'")
    if model.sheet(sheet) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model.")
    try:
        row, col = parse_a1_cell(addr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    run = _run_or_404(session, run_id) if run_id else store.baseline_run(session, version_id)
    if run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No run for this version yet. POST /runs first."
        )
    return explain(model, sheet, row, col, value_at=store.value_lookup(session, run), depth=depth)
