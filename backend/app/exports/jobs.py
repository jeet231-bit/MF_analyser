"""Export builders and background export jobs (the Phase 7B job + polling pattern)."""

from __future__ import annotations

import io
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard_config import DashboardConfig, load_dashboard_config
from app.exports import report as report_mod
from app.exports.csv_export import write_csv
from app.exports.descriptor import ExportView, diff_view, provenance_for, sheet_view, slug
from app.exports.xlsx import write_workbook
from app.model.formula.refs import Rect
from app.storage import diffs, logic, runs, workbooks
from app.storage import views as view_store
from app.storage.models import ExportJob, Run

log = logging.getLogger(__name__)

XLSX_SYNC_CELLS = 250_000  # above this an xlsx export runs as a background job
MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
}


@dataclass
class ExportFile:
    filename: str
    media_type: str
    content: bytes


def export_scope_sheets(model, cfg: DashboardConfig, scope: str, sheet: str | None) -> list[str]:
    if scope == "sheet":
        if not sheet:
            raise ValueError("scope=sheet needs sheet=")
        return [sheet]
    if scope == "all":
        return [s.name for s in model.sheets if s.in_scope]
    return view_store.output_sheet_order(model, cfg)


def projected_cells(model, sheets: list[str]) -> int:
    return sum(s.cell_count for s in model.sheets if s.name in set(sheets))


def _stem(prov_name: str | None, filename: str) -> str:
    return slug(prov_name or Path(filename).stem, 40)


def build_run_export(
    session: Session,
    run: Run,
    fmt: str,
    *,
    scope: str = "outputs",
    sheet: str | None = None,
    window: Rect | None = None,
    formulas: bool = False,
) -> ExportFile:
    cfg = load_dashboard_config()
    model = logic.get_model(session, run.version_id)
    version = workbooks.get_version(session, run.version_id)
    stem = _stem(cfg.workbook.display_name, version.filename)
    tag = run.id[:8]
    if fmt == "csv":
        if not sheet:
            raise ValueError("csv export needs sheet=")
        view = sheet_view(session, run, model, version, cfg, sheet, rect=window, with_deltas=False)
        return ExportFile(
            f"{stem}-{slug(sheet)}-{tag}.csv", MEDIA["csv"], write_csv(view).encode("utf-8-sig")
        )
    if fmt == "xlsx":
        sheets = export_scope_sheets(model, cfg, scope, sheet)
        views: list[ExportView] = []
        for name in sheets:
            rect = window if (scope == "sheet" and window is not None) else None
            views.append(
                sheet_view(session, run, model, version, cfg, name, rect=rect, in_place=True)
            )
        if formulas:
            for name in sheets:
                views.append(
                    sheet_view(
                        session, run, model, version, cfg, name, in_place=True, formulas=True
                    )
                )
        prov = provenance_for(session, run, version, cfg, f"{scope}: {', '.join(sheets)}")
        buf = io.BytesIO()
        write_workbook(views, prov, buf)
        return ExportFile(f"{stem}-{scope}-{tag}.xlsx", MEDIA["xlsx"], buf.getvalue())
    if fmt == "pdf":
        ctx = report_mod.build_context(session, run, model, cfg)
        html_text = report_mod.render_html(ctx, cfg)
        return ExportFile(
            f"{stem}-report-{tag}.pdf", MEDIA["pdf"], report_mod.render_pdf(html_text)
        )
    raise ValueError(f"unknown format {fmt!r}")


def build_report_html(session: Session, run: Run) -> str:
    cfg = load_dashboard_config()
    model = logic.get_model(session, run.version_id)
    return report_mod.render_html(report_mod.build_context(session, run, model, cfg), cfg)


def build_diff_export(session: Session, base_id: str, target_id: str, fmt: str) -> ExportFile:
    cfg = load_dashboard_config()
    base = workbooks.get_version(session, base_id)
    target = workbooks.get_version(session, target_id)
    report = diffs.get_diff(session, base_id, target_id)
    view = diff_view(session, report, base, target, cfg)
    stem = _stem(cfg.workbook.display_name, target.filename)
    name = f"{stem}-changelog-{base.id[:8]}-{target.id[:8]}"
    if fmt == "csv":
        return ExportFile(f"{name}.csv", MEDIA["csv"], write_csv(view).encode("utf-8-sig"))
    if fmt == "xlsx":
        buf = io.BytesIO()
        write_workbook([view], view.provenance, buf)
        return ExportFile(f"{name}.xlsx", MEDIA["xlsx"], buf.getvalue())
    raise ValueError(f"changelog export supports csv or xlsx, not {fmt!r}")


# ---- background jobs ---------------------------------------------------------------------


def exports_dir() -> Path:
    d = get_settings().data_dir / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def start_export_job(session: Session, run: Run, fmt: str, params: dict[str, Any]) -> ExportJob:
    job = ExportJob(
        id=uuid.uuid4().hex,
        run_id=run.id,
        format=fmt,
        params_json=json.dumps(params, sort_keys=True),
        status="running",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    session.commit()
    job_id, run_id = job.id, run.id
    from app.storage.db import get_session_factory

    factory = get_session_factory()

    def work() -> None:
        with factory() as s:
            row = s.get(ExportJob, job_id)
            try:
                r = runs.get_run(s, run_id)
                window = Rect.from_a1(params["window"]) if params.get("window") else None
                built = build_run_export(
                    s,
                    r,
                    fmt,
                    scope=params.get("scope", "outputs"),
                    sheet=params.get("sheet"),
                    window=window,
                    formulas=bool(params.get("formulas")),
                )
                path = exports_dir() / f"{job_id}.{fmt}"
                path.write_bytes(built.content)
                row = s.get(ExportJob, job_id)
                if row is not None:
                    row.status = "ok"
                    row.file_path = str(path)
                    row.filename = built.filename
                    row.media_type = built.media_type
                    row.finished_at = datetime.now(UTC)
                    s.commit()
            except Exception as exc:  # noqa: BLE001 - reported on the row
                log.warning("export job %s failed: %s", job_id, exc)
                s.rollback()
                row = s.get(ExportJob, job_id)
                if row is not None:
                    row.status = "failed"
                    row.error = f"{type(exc).__name__}: {exc}"
                    row.finished_at = datetime.now(UTC)
                    s.commit()

    threading.Thread(target=work, name=f"export-{job_id[:8]}", daemon=True).start()
    return job
