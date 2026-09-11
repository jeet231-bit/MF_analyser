"""The export view descriptor: every export (xlsx, csv, pdf) is built from an ``ExportView``.

A view is rows × columns with labels, a title and provenance. Sheet grids produce one; so do
non-sheet views such as a version changelog. Writers never look at sheets directly, so a future
view (a pivot, a category summary, a comparison) exports through the same code path.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dashboard_config import DashboardConfig
from app.model.diff import DiffReport
from app.model.formula.refs import Rect
from app.model.schema import WorkbookLogicModel
from app.storage import runs, validation, workbooks
from app.storage import views as view_store
from app.storage.models import Run, WorkbookVersion


class ExportColumn(BaseModel):
    key: str
    label: str
    format: str = "general"  # general | number | integer | percent | date | text
    kind: str = "static"  # output | formula | input | static | field


class Provenance(BaseModel):
    workbook: str | None = None
    filename: str
    version_id: str
    version_status: str
    validation_status: str | None = None
    run_id: str | None = None
    run_kind: str | None = None
    run_created_at: datetime | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    baseline_run_id: str | None = None
    exported_at: datetime
    scope: str

    def lines(self) -> list[tuple[str, str]]:
        """Key / value pairs for cover sheets and report headers."""
        out = [
            ("Workbook", self.workbook or self.filename),
            ("File", self.filename),
            ("Version", f"{self.version_id[:8]} ({self.version_status.replace('_', ' ')})"),
            ("Validation", (self.validation_status or "not validated").replace("_", " ")),
        ]
        if self.run_id:
            when = self.run_created_at.strftime("%d %b %Y %H:%M UTC") if self.run_created_at else ""
            out.append(("Run", f"{self.run_id[:8]} · {self.run_kind} · {when}".strip(" ·")))
        if self.overrides:
            out.append(
                ("Overrides", "; ".join(f"{k} = {v!r}" for k, v in sorted(self.overrides.items())))
            )
        elif self.run_id:
            out.append(("Overrides", "none (baseline)"))
        out.append(("Scope", self.scope))
        out.append(("Exported", self.exported_at.strftime("%d %b %Y %H:%M UTC")))
        return out


class ExportView(BaseModel):
    id: str = Field(description="Slug for sheet and file names")
    title: str
    subtitle: str | None = None
    columns: list[ExportColumn]
    row_label_header: str = "Row"
    row_labels: list[str | None] = Field(default_factory=list)
    rows: list[list[Any]]
    types: list[list[str]] | None = Field(
        default=None, description="Per cell: number | text | bool | date | error | empty"
    )
    formats: list[list[str | None]] | None = Field(
        default=None, description="Excel number formats per cell, when known"
    )
    deltas: list[list[float | None]] | None = Field(
        default=None, description="value minus baseline per numeric cell under a what-if"
    )
    first_row: int | None = Field(
        default=None, description="Sheet row of rows[0]; set for in-place sheet exports"
    )
    first_col: int | None = None
    provenance: Provenance


def slug(text: str, limit: int = 31) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or "view"
    return s[:limit]


def provenance_for(
    session: Session, run: Run | None, version: WorkbookVersion, cfg: DashboardConfig, scope: str
) -> Provenance:
    root = view_store._root_run(session, run) if run is not None else None
    created = None
    if run is not None:
        created = run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=UTC)
    overrides: dict[str, Any] = {}
    if run is not None:
        chain: list[Run] = []
        current: Run | None = run
        while current is not None:
            chain.append(current)
            current = session.get(Run, current.parent_run_id) if current.parent_run_id else None
        for r in reversed(chain):
            overrides.update(runs.overrides_of(r))
    return Provenance(
        workbook=cfg.workbook.display_name,
        filename=version.filename,
        version_id=version.id,
        version_status=version.status,
        validation_status=validation.latest_status(session, version.id),
        run_id=run.id if run else None,
        run_kind=run.kind if run else None,
        run_created_at=created,
        overrides=overrides,
        baseline_run_id=root.id
        if root is not None and run is not None and root.id != run.id
        else None,
        exported_at=datetime.now(UTC),
        scope=scope,
    )


def sheet_view(
    session: Session,
    run: Run,
    model: WorkbookLogicModel,
    version: WorkbookVersion,
    cfg: DashboardConfig,
    sheet: str,
    *,
    rect: Rect | None = None,
    in_place: bool = False,
    formulas: bool = False,
    with_deltas: bool = False,
) -> ExportView:
    """A sheet (or a window of it) as the run computed it.

    ``in_place`` starts at A1 so exported addresses equal the original ones; ``formulas`` puts
    the formula text where a formula lives (the audit tab-set); ``with_deltas`` adds value
    minus baseline for numeric formula cells when the run is a what-if.
    """
    idx = view_store.sheet_cache.get(session, run.version_id, sheet)
    fblocks, iblocks = view_store._blocks_on(model, sheet)
    used = idx.used
    if used is None:
        return ExportView(
            id=slug(sheet),
            title=sheet,
            columns=[],
            rows=[],
            provenance=provenance_for(session, run, version, cfg, f"{sheet} (empty)"),
        )
    body = view_store._body_start(idx, fblocks, iblocks)
    if rect is None:
        rect = Rect(1, 1, used.r2, used.c2) if in_place else used
    elif in_place:
        rect = Rect(1, 1, rect.r2, rect.c2)
    computed = runs.formula_values(session, run, sheet)
    root = view_store._root_run(session, run)
    baseline = (
        runs.formula_values(session, root, sheet) if with_deltas and root.id != run.id else {}
    )
    overrides = view_store._overrides_for(session, run, sheet)
    output_cols = {
        c for b in fblocks if b.classification == "output" for c in range(b.rect.c1, b.rect.c2 + 1)
    }
    formula_cols = {c for b in fblocks for c in range(b.rect.c1, b.rect.c2 + 1)}
    input_cols = {c for b in iblocks for c in range(b.rect.c1, b.rect.c2 + 1)}

    columns: list[ExportColumn] = []
    for col in range(rect.c1, rect.c2 + 1):
        kind = (
            "output"
            if col in output_cols
            else "formula"
            if col in formula_cols
            else "input"
            if col in input_cols
            else "static"
        )
        fmt = "general"
        for row in range(max(body, rect.r1), min(rect.r2, max(body, rect.r1) + 5) + 1):
            if (row, col) in idx.at:
                fmt = view_store._format_kind(idx.number_format(row, col), idx.value_type(row, col))
                break
        letter = get_column_letter(col)
        label = view_store._column_label(col, fblocks, iblocks, idx, body)
        columns.append(ExportColumn(key=letter, label=label or letter, format=fmt, kind=kind))

    label_col = None
    if not in_place:
        from collections import Counter

        counts = Counter(b.row_label_col for b in fblocks if b.row_label_col is not None)
        label_col = counts.most_common(1)[0][0] if counts else None

    rows: list[list[Any]] = []
    types: list[list[str]] = []
    formats: list[list[str | None]] = []
    deltas: list[list[float | None]] = []
    row_labels: list[str | None] = []
    for row in range(rect.r1, rect.r2 + 1):
        values: list[Any] = []
        kinds: list[str] = []
        fmts: list[str | None] = []
        ds: list[float | None] = []
        for col in range(rect.c1, rect.c2 + 1):
            i = idx.at.get((row, col))
            if i is None:
                values.append(None)
                kinds.append("empty")
                fmts.append(None)
                ds.append(None)
                continue
            addr = idx.raw.cells.address[i]
            raw_formula = idx.raw.cells.formula[i]
            fmts.append(idx.raw.cells.number_format[i])
            if raw_formula is not None:
                if formulas:
                    values.append("=" + raw_formula.lstrip("="))
                    kinds.append("text")
                    ds.append(None)
                    continue
                v, t = computed.get(addr, (idx.raw.cells.value[i], idx.raw.cells.value_type[i]))
                values.append(v)
                kinds.append(t)
                b = baseline.get(addr)
                ds.append(
                    float(v) - float(b[0])
                    if b is not None and view_store._numeric(v) and view_store._numeric(b[0])
                    else None
                )
            elif addr in overrides:
                values.append(overrides[addr])
                kinds.append(view_store._python_type(overrides[addr]))
                ds.append(None)
            else:
                values.append(idx.raw.cells.value[i])
                kinds.append(idx.raw.cells.value_type[i])
                ds.append(None)
        rows.append(values)
        types.append(kinds)
        formats.append(fmts)
        deltas.append(ds)
        row_labels.append(
            idx.any_text(row, label_col) if label_col is not None and not in_place else str(row)
        )

    scope = f"{sheet} {rect.to_a1()}" + (" (formulas)" if formulas else "")
    return ExportView(
        id=slug(sheet + ("-formulas" if formulas else "")),
        title=sheet + (" (formulas)" if formulas else ""),
        subtitle=rect.to_a1(),
        columns=columns,
        row_label_header="Row",
        row_labels=row_labels,
        rows=rows,
        types=types,
        formats=formats,
        deltas=deltas if with_deltas and baseline else None,
        first_row=rect.r1 if in_place else None,
        first_col=rect.c1 if in_place else None,
        provenance=provenance_for(session, run, version, cfg, scope),
    )


def diff_view(
    session: Session,
    report: DiffReport,
    base: WorkbookVersion,
    target: WorkbookVersion,
    cfg: DashboardConfig,
) -> ExportView:
    """The version changelog as rows: one per change, grouped LOGIC / DATA / STRUCTURAL."""
    columns = [
        ExportColumn(key="group", label="Group", kind="field"),
        ExportColumn(key="kind", label="Change", kind="field"),
        ExportColumn(key="sheet", label="Sheet", kind="field"),
        ExportColumn(key="location", label="Location", kind="field"),
        ExportColumn(key="cells", label="Cells", format="integer", kind="field"),
        ExportColumn(key="description", label="Description", kind="field"),
        ExportColumn(key="outputs", label="Outputs affected", format="integer", kind="field"),
        ExportColumn(key="affected", label="Affected outputs", kind="field"),
    ]
    rows: list[list[Any]] = []
    for c in report.logic:
        rows.append(
            [
                "LOGIC",
                c.kind.replace("_", " "),
                c.sheet,
                c.location,
                c.cells,
                c.description,
                c.affected_output_count,
                "; ".join(f"{o.sheet}!{o.range}" for o in c.affected_outputs[:12]),
            ]
        )
    for d in report.data:
        rows.append(
            ["DATA", d.kind.replace("_", " "), d.sheet, "", d.count, d.description, None, ""]
        )
    for s in report.structural:
        rows.append(
            ["STRUCTURAL", s.kind.replace("_", " "), s.sheet, "", None, s.description, None, ""]
        )
    prov = provenance_for(
        session,
        None,
        target,
        cfg,
        f"changes from {base.filename} ({base.id[:8]}) to {target.filename} ({target.id[:8]})",
    )
    return ExportView(
        id="changelog",
        title="Version changelog",
        subtitle=report.headline,
        columns=columns,
        row_label_header="#",
        row_labels=[str(i + 1) for i in range(len(rows))],
        rows=rows,
        provenance=prov,
    )


def version_of(session: Session, run: Run) -> WorkbookVersion:
    return workbooks.get_version(session, run.version_id)
