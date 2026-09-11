"""Export endpoints: a run's results as xlsx / csv / pdf, the version changelog, export jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.exports import jobs as export_store
from app.exports.report import PdfUnavailableError
from app.model.formula.refs import Rect
from app.storage import logic, workbooks
from app.storage import runs as run_store
from app.storage.db import get_session
from app.storage.models import ExportJob, Run

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


class ExportJobOut(BaseModel):
    id: str
    run_id: str
    format: str
    status: str  # running | ok | failed
    error: str | None = None
    filename: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    @classmethod
    def from_row(cls, row: ExportJob) -> ExportJobOut:
        def aware(d: datetime | None) -> datetime | None:
            return None if d is None else (d if d.tzinfo else d.replace(tzinfo=UTC))

        return cls(
            id=row.id,
            run_id=row.run_id,
            format=row.format,
            status=row.status,
            error=row.error,
            filename=row.filename,
            created_at=aware(row.created_at) or datetime.now(UTC),
            finished_at=aware(row.finished_at),
        )


def _run_or_404(session: Session, run_id: str) -> Run:
    try:
        run = run_store.get_run(session, run_id)
    except run_store.RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.") from exc
    if run.status != "ok":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Run is {run.status}; nothing to export yet."
        )
    return run


def _attachment(built: export_store.ExportFile) -> Response:
    return Response(
        content=built.content,
        media_type=built.media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(built.filename)}"},
    )


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: str,
    session: SessionDep,
    response: Response,
    format: Annotated[Literal["xlsx", "csv", "pdf"], Query()],  # noqa: A002
    scope: Annotated[
        Literal["outputs", "all", "sheet"],
        Query(description="xlsx: which sheets; csv always exports one sheet window"),
    ] = "outputs",
    sheet: Annotated[str | None, Query()] = None,
    window: Annotated[
        str | None, Query(description="A1 range, e.g. A10:AC109 (csv, sheet)")
    ] = None,
    formulas: Annotated[bool, Query(description="xlsx: add a formulas tab-set for audit")] = False,
    background: Annotated[
        Literal["auto", "true", "false"],
        Query(description="auto: xlsx exports over ~250k cells become jobs"),
    ] = "auto",
):
    """Download a run's results. Large xlsx exports return 202 with a job to poll
    (`GET /api/exports/{id}`) and then `GET /api/exports/{id}/file`."""
    run = _run_or_404(session, run_id)
    try:
        model = logic.get_model(session, run.version_id)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logic model for this run.") from exc
    rect = None
    if window:
        try:
            rect = Rect.from_a1(window)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad window {window!r}"
            ) from exc
    if sheet and model.sheet(sheet) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model.")
    if format == "csv" and not sheet:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "csv export needs sheet=")
    if scope == "sheet" and not sheet:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "scope=sheet needs sheet=")

    if format == "xlsx":
        cfg = load_dashboard_config()
        sheets = export_store.export_scope_sheets(model, cfg, scope, sheet)
        cells = export_store.projected_cells(model, sheets) * (2 if formulas else 1)
        if background == "true" or (background == "auto" and cells > export_store.XLSX_SYNC_CELLS):
            job = export_store.start_export_job(
                session,
                run,
                "xlsx",
                {"scope": scope, "sheet": sheet, "window": window, "formulas": formulas},
            )
            response.status_code = status.HTTP_202_ACCEPTED
            return ExportJobOut.from_row(job)
    try:
        built = export_store.build_run_export(
            session, run, format, scope=scope, sheet=sheet, window=rect, formulas=formulas
        )
    except PdfUnavailableError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except workbooks.SheetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet not found: {exc}") from exc
    return _attachment(built)


@router.get("/runs/{run_id}/report.html", response_class=Response)
def report_html(run_id: str, session: SessionDep) -> Response:
    """The analysis report as HTML (what the PDF renders); useful without WeasyPrint."""
    run = _run_or_404(session, run_id)
    try:
        html_text = export_store.build_report_html(session, run)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logic model for this run.") from exc
    return Response(content=html_text, media_type="text/html; charset=utf-8")


@router.get("/exports/{job_id}", response_model=ExportJobOut)
def get_export_job(job_id: str, session: SessionDep) -> ExportJobOut:
    row = session.get(ExportJob, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export job not found.")
    return ExportJobOut.from_row(row)


@router.get("/exports/{job_id}/file")
def get_export_file(job_id: str, session: SessionDep):
    row = session.get(ExportJob, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export job not found.")
    if row.status != "ok" or not row.file_path:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Export is {row.status}.")
    return FileResponse(
        row.file_path,
        media_type=row.media_type or "application/octet-stream",
        filename=row.filename or f"{job_id}.{row.format}",
    )


@router.get("/workbooks/{base_id}/diff/{target_id}/export")
def export_diff(
    base_id: str,
    target_id: str,
    session: SessionDep,
    format: Annotated[Literal["xlsx", "csv"], Query()],  # noqa: A002
):
    """The version changelog as a table (same view descriptor path as sheet exports)."""
    for vid in (base_id, target_id):
        try:
            workbooks.get_version(session, vid)
        except workbooks.WorkbookNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Version {vid} not found.") from exc
    try:
        built = export_store.build_diff_export(session, base_id, target_id, format)
    except logic.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Both versions must be interpreted before they can be compared.",
        ) from exc
    return _attachment(built)
