"""The analysis report: HTML assembled from view descriptors and the outputs summary, rendered
to PDF by WeasyPrint. A report, not a data dump: headline metrics, a chart where the data is a
series, category-level summaries and top-N tables, the rules that decide classifications, and
the changelog when overrides or a new version are involved.
"""

from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.dashboard_config import DashboardConfig
from app.exports.descriptor import ExportView, Provenance, provenance_for, sheet_view
from app.model.diff import DiffReport
from app.model.formula.refs import Rect
from app.model.schema import BusinessRule, WorkbookLogicModel
from app.storage import diffs, workbooks
from app.storage import views as view_store
from app.storage.models import Run

TOP_N = 20
MAX_CATEGORIES = 40
RULES_PER_KIND = 8

# Print-safe light theme: the app's tokens, never a colour outside this block.
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm;
  @bottom-right { content: counter(page) " / " counter(pages); font: 9px "Instrument Sans", "Segoe UI", sans-serif; color: #6B7078; } }
:root { --ground:#F6F6F4; --surface:#FFFFFF; --ink:#17191D; --muted:#6B7078; --hairline:#E3E3DF;
  --accent:#2F55D4; --positive:#1E7F4F; --warning:#A16207; --negative:#B4232A; }
body { font-family: "Instrument Sans", "Segoe UI", Arial, sans-serif; color: var(--ink); font-size: 10.5px; line-height: 1.45; }
h1, h2, h3, .num { font-family: "Schibsted Grotesk", "Segoe UI", Arial, sans-serif; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 15px; margin: 22px 0 8px; padding-bottom: 4px; border-bottom: 1px solid var(--hairline); }
h3 { font-size: 12px; margin: 14px 0 6px; color: var(--ink); }
.muted { color: var(--muted); }
.cover { page-break-after: always; }
.cover .lead { font-size: 12px; color: var(--muted); margin-bottom: 18px; }
dl.prov { display: grid; grid-template-columns: 110px 1fr; gap: 3px 10px; margin: 0; }
dl.prov dt { color: var(--muted); } dl.prov dd { margin: 0; }
.tiles { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.tile { flex: 1 1 140px; border: 1px solid var(--hairline); border-radius: 10px; padding: 8px 10px; background: var(--surface); }
.tile .label { font-size: 9px; color: var(--muted); }
.tile .value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .delta { font-size: 9px; font-variant-numeric: tabular-nums; }
.up { color: var(--positive); } .down { color: var(--negative); } .flat { color: var(--muted); }
table { width: 100%; border-collapse: collapse; margin: 6px 0 10px; page-break-inside: auto; }
th { text-align: left; font-family: "Schibsted Grotesk", sans-serif; font-size: 9px; color: var(--muted); font-weight: 600;
  border-bottom: 1px solid var(--hairline); padding: 3px 5px; }
td { border-bottom: 1px solid var(--hairline); padding: 3px 5px; vertical-align: top; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr { page-break-inside: avoid; }
.rules li { margin: 2px 0; } .rules { padding-left: 16px; }
.pill { display: inline-block; border: 1px solid var(--hairline); border-radius: 999px; padding: 0 7px; font-size: 9px; color: var(--muted); }
figure { margin: 8px 0; } figcaption { font-size: 9px; color: var(--muted); }
.section { page-break-inside: avoid; }
"""


@dataclass
class ReportContext:
    provenance: Provenance
    outputs: view_store.OutputsOut
    sections: list[dict[str, Any]] = field(default_factory=list)
    changelog: DiffReport | None = None
    changelog_base: str | None = None
    insights: list[Any] | None = None


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _fmt(v: Any, fmt: str = "general", cfg: DashboardConfig | None = None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int | float):
        if not math.isfinite(float(v)):
            return "—"
        decimals = cfg.number_format.decimals if cfg else 2
        indian = (cfg.number_format.grouping if cfg else "indian") == "indian"
        if fmt == "date":
            from openpyxl.utils.datetime import from_excel

            try:
                return from_excel(float(v)).strftime("%d %b %Y")
            except (ValueError, OverflowError, TypeError):
                return str(v)
        if fmt == "percent":
            return _group(float(v) * 100, decimals, indian) + "%"
        if fmt == "integer" or float(v).is_integer():
            return _group(float(v), 0, indian)
        return _group(float(v), decimals, indian)
    return str(v)


def _group(x: float, decimals: int, indian: bool) -> str:
    sign = "-" if x < 0 else ""
    s = f"{abs(x):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if indian and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    elif not indian:
        whole = f"{int(whole):,}"
    return sign + whole + (("." + frac) if frac else "")


def _delta_html(d: float | None, cfg: DashboardConfig) -> str:
    if d is None:
        return ""
    cls = "up" if d > 0 else "down" if d < 0 else "flat"
    sign = "+" if d > 0 else "−" if d < 0 else ""
    return f'<div class="delta {cls}">{sign}{_fmt(abs(d), "general", cfg)} vs baseline</div>'


# ---- analysis over a sheet view ---------------------------------------------------------------


def _numeric(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(float(v))


def category_summary(view: ExportView) -> dict[str, Any] | None:
    """Group rows by the most granular text column that still reads as a category (2..40
    distinct values; the more distinct the better) and summarise the first numeric output
    column per group: count and mean. A Yes/No flag loses to a 30-way classification."""
    if not view.rows:
        return None
    n = len(view.rows)
    best: tuple[int, int, Counter[str]] | None = None
    for j in range(len(view.columns)):
        vals = [r[j] for r in view.rows if isinstance(r[j], str) and r[j].strip()]
        if len(vals) < 0.6 * n:
            continue
        distinct = Counter(vals)
        if 2 <= len(distinct) <= MAX_CATEGORIES and (best is None or len(distinct) > len(best[2])):
            best = (j, len(distinct), distinct)
    if best is None:
        return None
    cat_j = best[0]
    num_j = next(
        (
            j
            for j, col in enumerate(view.columns)
            if col.kind in ("output", "formula")
            and sum(1 for r in view.rows if _numeric(r[j])) >= 0.3 * n
        ),
        None,
    )
    groups: dict[str, list[float]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for r in view.rows:
        key = r[cat_j]
        if not isinstance(key, str) or not key.strip():
            continue
        counts[key] += 1
        if num_j is not None and _numeric(r[num_j]):
            groups[key].append(float(r[num_j]))
    rows = []
    for key, count in counts.most_common():
        vals = groups.get(key, [])
        rows.append((key, count, (sum(vals) / len(vals)) if vals else None, len(vals)))
    return {
        "category": view.columns[cat_j].label,
        "metric": view.columns[num_j].label if num_j is not None else None,
        "metric_format": view.columns[num_j].format if num_j is not None else "general",
        "rows": rows,
    }


def top_rows(view: ExportView, n: int = TOP_N) -> dict[str, Any] | None:
    """Top-N rows by the first numeric output column, with the row label and a few columns."""
    if not view.rows:
        return None
    total = len(view.rows)
    num_j = next(
        (
            j
            for j, col in enumerate(view.columns)
            if col.kind in ("output", "formula")
            and sum(1 for r in view.rows if _numeric(r[j])) >= 0.3 * total
        ),
        None,
    )
    if num_j is None:
        return None
    shown = [j for j, c in enumerate(view.columns) if j != num_j and c.kind != "static"][:5]
    ranked = sorted(
        (i for i in range(total) if _numeric(view.rows[i][num_j])),
        key=lambda i: -float(view.rows[i][num_j]),
    )[:n]
    return {
        "metric": view.columns[num_j].label,
        "columns": [view.columns[num_j]] + [view.columns[j] for j in shown],
        "rows": [
            (view.row_labels[i], [view.rows[i][num_j]] + [view.rows[i][j] for j in shown])
            for i in ranked
        ],
        "total": total,
    }


def largest_moves(view: ExportView, n: int = TOP_N) -> dict[str, Any] | None:
    if not view.deltas:
        return None
    moves: list[tuple[float, int, int]] = []
    for i, ds in enumerate(view.deltas):
        for j, d in enumerate(ds):
            if d is not None and d != 0:
                moves.append((abs(d), i, j))
    if not moves:
        return None
    moves.sort(reverse=True)
    rows = []
    for _, i, j in moves[:n]:
        v = view.rows[i][j]
        d = view.deltas[i][j]
        rows.append((view.row_labels[i], view.columns[j].label, v - d, v, d))
    return {"rows": rows, "changed": len(moves)}


def series_svg(series: view_store.SeriesOut, width: int = 640, height: int = 200) -> str:
    """A plain polyline chart for a dated series; accent stroke, hairline grid."""
    cols = [c for c in series.columns if any(p[1] is not None for p in c.points)]
    if not cols:
        return ""
    ys = [p[1] for c in cols for p in c.points if p[1] is not None]
    lo, hi = min(ys), max(ys)
    if hi == lo:
        hi = lo + 1
    left, right, top, bottom = 48, 12, 10, 24
    w, h = width - left - right, height - top - bottom
    strokes = ["#2F55D4", "#1E7F4F", "#A16207", "#B4232A"]
    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">']
    for k in range(5):
        y = top + h * k / 4
        val = hi - (hi - lo) * k / 4
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#E3E3DF" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{y + 3:.1f}" text-anchor="end" font-size="9" fill="#6B7078">{_fmt(val)}</text>'
        )
    for ci, c in enumerate(cols):
        n = len(c.points)
        pts = []
        for i, (_x, y) in enumerate(c.points):
            if y is None:
                continue
            px = left + (w * i / max(n - 1, 1))
            py = top + h * (hi - y) / (hi - lo)
            pts.append(f"{px:.1f},{py:.1f}")
        parts.append(
            f'<polyline fill="none" stroke="{strokes[ci % 4]}" stroke-width="1.5" points="{" ".join(pts)}"/>'
        )
    first, last = cols[0].points[0][0], cols[0].points[-1][0]
    parts.append(
        f'<text x="{left}" y="{height - 6}" font-size="9" fill="#6B7078">{_esc(first)}</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - 6}" text-anchor="end" font-size="9" fill="#6B7078">{_esc(last)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ---- assembly -----------------------------------------------------------------------------


def build_context(
    session: Session, run: Run, model: WorkbookLogicModel, cfg: DashboardConfig
) -> ReportContext:
    version = workbooks.get_version(session, run.version_id)
    outputs = view_store.outputs_summary(session, model, run, cfg)
    prov = provenance_for(session, run, version, cfg, "analysis report")
    ctx = ReportContext(provenance=prov, outputs=outputs)
    what_if = outputs.baseline_run_id is not None
    for sheet in outputs.sheets:
        section: dict[str, Any] = {"sheet": sheet, "summary": None, "top": None, "moves": None}
        if sheet.table_rect:
            rect = Rect.from_a1(sheet.table_rect)
            body = Rect(max(rect.r1, sheet.body_start), rect.c1, rect.r2, rect.c2)
            view = sheet_view(
                session, run, model, version, cfg, sheet.sheet, rect=body, with_deltas=what_if
            )
            section["summary"] = category_summary(view)
            section["top"] = top_rows(view)
            section["moves"] = largest_moves(view) if what_if else None
        rules_by_kind: dict[str, list[BusinessRule]] = defaultdict(list)
        for r in sheet.rules:
            if len(rules_by_kind[r.kind]) < RULES_PER_KIND:
                rules_by_kind[r.kind].append(r)
        section["rules"] = dict(rules_by_kind)
        ctx.sections.append(section)
    try:
        from app.research import insights as rinsights
        from app.research import table as rtable

        rt = rtable.get_table(session, version, run)
        versions = (
            [(v.filename, t) for v, _r, t in rtable.baseline_tables(session)]
            if any(i.mode == "acrossVersions" for i in rt.map.insights)
            else []
        )
        ctx.insights = [c for c in rinsights.compute_all(rt, versions) if c.sentence]
    except Exception:  # noqa: BLE001 - the research map is optional for the report
        ctx.insights = None
    if what_if or version.status in ("pending_review", "active", "validated"):
        row = diffs.latest_diff_for(session, version.id)
        if row is not None:
            ctx.changelog = diffs.get_diff(session, row.base_version_id, row.target_version_id)
            try:
                ctx.changelog_base = workbooks.get_version(session, row.base_version_id).filename
            except workbooks.WorkbookNotFoundError:
                ctx.changelog_base = row.base_version_id[:8]
    return ctx


def render_html(ctx: ReportContext, cfg: DashboardConfig) -> str:
    p = ctx.provenance
    out: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{_esc(p.workbook or p.filename)} · analysis report</title>",
        f"<style>{CSS}</style></head><body>",
    ]
    # Cover
    out.append('<section class="cover">')
    out.append(f"<h1>{_esc(p.workbook or p.filename)}</h1>")
    out.append('<div class="lead">Analysis report')
    if p.overrides:
        out.append(f" · what-if with {len(p.overrides)} override(s)")
    out.append("</div><dl class='prov'>")
    for k, v in p.lines():
        out.append(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>")
    out.append("</dl>")
    if p.overrides:
        out.append("<h3>Overrides applied</h3><table><tr><th>Cell</th><th>Value</th></tr>")
        for k, v in sorted(p.overrides.items()):
            out.append(f"<tr><td>{_esc(k)}</td><td class='num'>{_esc(v)}</td></tr>")
        out.append("</table>")
    out.append("</section>")

    for section in ctx.sections:
        sheet: view_store.OutputSheetOut = section["sheet"]
        out.append(f'<section class="section"><h2>{_esc(sheet.sheet)}</h2>')
        if sheet.metrics:
            out.append('<div class="tiles">')
            for m in sheet.metrics:
                out.append(
                    f'<div class="tile"><div class="label">{_esc(m.label or m.address)}</div>'
                    f'<div class="value">{_esc(_fmt(m.value, m.format, cfg))}</div>'
                    f"{_delta_html(m.delta, cfg) if p.baseline_run_id else ''}</div>"
                )
            out.append("</div>")
        if sheet.series:
            out.append(
                f"<figure>{series_svg(sheet.series)}<figcaption>"
                f"{_esc(', '.join(c.label for c in sheet.series.columns))} over "
                f"{_esc(sheet.series.x_label or 'time')} · {sheet.series.rows} rows</figcaption></figure>"
            )
        moves = section.get("moves")
        if moves:
            out.append(
                f"<h3>Largest moves vs baseline <span class='pill'>{moves['changed']} cells changed</span></h3>"
            )
            out.append(
                "<table><tr><th>Row</th><th>Column</th><th class='num'>Baseline</th><th class='num'>Now</th><th class='num'>Change</th></tr>"
            )
            for label, col, before, now, d in moves["rows"]:
                cls = "up" if d > 0 else "down"
                out.append(
                    f"<tr><td>{_esc(label)}</td><td>{_esc(col)}</td><td class='num'>{_esc(_fmt(before, 'general', cfg))}</td>"
                    f"<td class='num'>{_esc(_fmt(now, 'general', cfg))}</td><td class='num {cls}'>{'+' if d > 0 else '−'}{_esc(_fmt(abs(d), 'general', cfg))}</td></tr>"
                )
            out.append("</table>")
        summary = section.get("summary")
        if summary:
            metric = summary["metric"]
            out.append(
                f"<h3>By {_esc(summary['category'])}</h3><table><tr><th>{_esc(summary['category'])}</th><th class='num'>Rows</th>"
            )
            if metric:
                out.append(
                    f"<th class='num'>Mean {_esc(metric)}</th><th class='num'>With value</th>"
                )
            out.append("</tr>")
            for key, count, mean, n in summary["rows"]:
                out.append(f"<tr><td>{_esc(key)}</td><td class='num'>{count}</td>")
                if metric:
                    out.append(
                        f"<td class='num'>{_esc(_fmt(mean, summary['metric_format'], cfg)) if mean is not None else '—'}</td><td class='num'>{n}</td>"
                    )
                out.append("</tr>")
            out.append("</table>")
        top = section.get("top")
        if top:
            out.append(
                f"<h3>Top {len(top['rows'])} by {_esc(top['metric'])} <span class='pill'>of {top['total']} rows</span></h3><table><tr><th>Row</th>"
            )
            for c in top["columns"]:
                cls = (
                    " class='num'"
                    if c.format in ("number", "integer", "percent", "general")
                    else ""
                )
                out.append(f"<th{cls}>{_esc(c.label)}</th>")
            out.append("</tr>")
            for label, values in top["rows"]:
                out.append(f"<tr><td>{_esc(label)}</td>")
                for c, v in zip(top["columns"], values, strict=True):
                    cls = " class='num'" if _numeric(v) else ""
                    out.append(f"<td{cls}>{_esc(_fmt(v, c.format, cfg))}</td>")
                out.append("</tr>")
            out.append("</table>")
        rules = section.get("rules") or {}
        if rules:
            out.append("<h3>How these numbers are decided</h3>")
            for kind, items in rules.items():
                out.append(
                    f"<div class='muted'>{_esc(kind.replace('_', ' '))}</div><ul class='rules'>"
                )
                for r in items:
                    out.append(f"<li>{_esc(', '.join(r.cells[:2]))}: {_esc(r.description)}</li>")
                out.append("</ul>")
        out.append("</section>")

    if ctx.insights:
        out.append("<section class='section'><h2>Insights brief</h2>")
        section = None
        for ins in ctx.insights:
            if ins.section != section:
                section = ins.section
                out.append(f"<h3>{_esc(section.replace('_', ' ').capitalize())}</h3>")
            out.append(
                f"<div class='muted' style='font-size:9px;letter-spacing:.08em;text-transform:uppercase'>{_esc(ins.eyebrow)}</div>"
                f"<div style='font-weight:600'>{_esc(ins.title)}</div><p style='margin:2px 0 6px'>{_esc(ins.sentence)}</p>"
            )
            if ins.rows:
                out.append(
                    "<table><tr><th>#</th><th>Fund / group</th><th>Detail</th><th class='num'>Value</th></tr>"
                )
                for i, r in enumerate(ins.rows, start=1):
                    out.append(
                        f"<tr><td class='num'>{i}</td><td>{_esc(r.label)}</td><td class='muted'>{_esc(r.sub or '')}</td>"
                        f"<td class='num'>{_esc(r.value_label)}</td></tr>"
                    )
                out.append("</table>")
        out.append("</section>")

    if ctx.changelog is not None:
        c = ctx.changelog
        out.append(
            f"<section class='section'><h2>Version changelog</h2><div class='muted'>From {_esc(ctx.changelog_base)} · {_esc(c.headline)}</div>"
        )
        if c.logic:
            out.append(
                "<table><tr><th>Logic change</th><th>Sheet</th><th class='num'>Cells</th><th class='num'>Outputs</th></tr>"
            )
            for ch in c.logic[:12]:
                out.append(
                    f"<tr><td>{_esc(ch.title)}<div class='muted'>{_esc(ch.description[:160])}</div></td><td>{_esc(ch.sheet)}</td>"
                    f"<td class='num'>{ch.cells}</td><td class='num'>{ch.affected_output_count}</td></tr>"
                )
            out.append("</table>")
        if c.data:
            out.append(
                "<ul class='rules'>"
                + "".join(f"<li>{_esc(d.description)}</li>" for d in c.data[:8])
                + "</ul>"
            )
        if c.structural:
            out.append(
                "<ul class='rules'>"
                + "".join(f"<li>{_esc(s.description)}</li>" for s in c.structural[:8])
                + "</ul>"
            )
        out.append("</section>")
    out.append("</body></html>")
    return "".join(out)


class PdfUnavailableError(RuntimeError):
    pass


def render_pdf(html_text: str) -> bytes:
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001 - missing extra or missing GTK runtime
        raise PdfUnavailableError(
            "PDF export needs WeasyPrint: `uv sync --extra pdf` (and the GTK/Pango runtime on Windows)."
        ) from exc
    return HTML(string=html_text).write_pdf()
