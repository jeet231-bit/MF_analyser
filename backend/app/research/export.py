"""Research responses as ExportViews: the same writers as every other export."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.dashboard_config import DashboardConfig
from app.exports.descriptor import ExportColumn, ExportView, provenance_for, slug
from app.research.insights import ComputedInsight
from app.research.table import Entity, ResearchTable
from app.storage.models import Run, WorkbookVersion


def _measure_columns(table: ResearchTable) -> list[ExportColumn]:
    cols = []
    for m in table.resolved.measure_specs():
        fmt = "integer" if m.role in ("rank", "quartile") or m.format == "integer" else m.format
        cols.append(
            ExportColumn(
                key=m.key,
                label=m.label + (f" ({m.unit})" if m.unit else ""),
                format=fmt,
                kind="field",
            )
        )
    return cols


def entities_view(
    session: Session,
    version: WorkbookVersion,
    run: Run,
    cfg: DashboardConfig,
    table: ResearchTable,
    rows: list[Entity],
    scope: str,
) -> ExportView:
    dim_keys = list(table.resolved.dimensions)
    columns = (
        [ExportColumn(key="key", label="Identity", kind="field")]
        + [ExportColumn(key=d, label=table.map.dimensions[d].label, kind="field") for d in dim_keys]
        + _measure_columns(table)
    )
    data: list[list[Any]] = []
    for e in rows:
        data.append(
            [e.key]
            + [e.dims.get(d) for d in dim_keys]
            + [
                e.measures.get(m.key) if e.measures.get(m.key) is not None else e.raw.get(m.key)
                for m in table.resolved.measure_specs()
            ]
        )
    return ExportView(
        id="funds",
        title="Funds",
        subtitle=scope,
        columns=columns,
        row_label_header="Fund",
        row_labels=[e.label for e in rows],
        rows=data,
        provenance=provenance_for(session, run, version, cfg, f"research funds · {scope}"),
    )


def categories_view(
    session: Session,
    version: WorkbookVersion,
    run: Run,
    cfg: DashboardConfig,
    table: ResearchTable,
    categories: list[dict[str, Any]],
) -> ExportView:
    return_keys = [m for m in table.resolved.measure_specs() if m.role == "return"]
    stat_cols = list(table.resolved.category_stat_labels.items())
    columns = (
        [
            ExportColumn(key="count", label="Funds", format="integer", kind="field"),
            ExportColumn(key="rated", label="Rated", format="integer", kind="field"),
            ExportColumn(key="q1", label="Q1", format="integer", kind="field"),
            ExportColumn(key="q2", label="Q2", format="integer", kind="field"),
            ExportColumn(key="q3", label="Q3", format="integer", kind="field"),
            ExportColumn(key="q4", label="Q4", format="integer", kind="field"),
        ]
        + [
            ExportColumn(
                key=f"mean_{m.key}", label=f"Mean {m.label}", format="number", kind="field"
            )
            for m in return_keys
        ]
        + [
            ExportColumn(key=f"stat_{c}", label=label, format="number", kind="field")
            for c, label in stat_cols
        ]
    )
    rows = []
    for c in categories:
        rows.append(
            [c["count"], c["rated"], c["quartiles"].get("1", c["quartiles"].get(1, 0)), c["quartiles"].get("2", c["quartiles"].get(2, 0)),
             c["quartiles"].get("3", c["quartiles"].get(3, 0)), c["quartiles"].get("4", c["quartiles"].get(4, 0))]
            + [c["means"].get(m.key) for m in return_keys]
            + [c["stats"].get(col) for col, _l in stat_cols]
        )  # fmt: skip
    return ExportView(
        id="categories",
        title="Categories",
        columns=columns,
        row_label_header="Category",
        row_labels=[c["key"] for c in categories],
        rows=rows,
        provenance=provenance_for(session, run, version, cfg, "research categories"),
    )


def movement_view(
    session: Session,
    version: WorkbookVersion,
    run: Run,
    cfg: DashboardConfig,
    movers: list[dict[str, Any]],
    scope: str,
) -> ExportView:
    columns = [
        ExportColumn(key="category", label="Category", kind="field"),
        ExportColumn(key="rank_from", label="Rank before", format="integer", kind="field"),
        ExportColumn(key="rank_to", label="Rank now", format="integer", kind="field"),
        ExportColumn(key="delta", label="Change", format="integer", kind="field"),
        ExportColumn(key="q_from", label="Quartile before", format="integer", kind="field"),
        ExportColumn(key="q_to", label="Quartile now", format="integer", kind="field"),
        ExportColumn(key="cause", label="Cause", kind="field"),
    ]
    rows = [
        [
            m.get("category"),
            m.get("rankFrom"),
            m.get("rankTo"),
            m.get("delta"),
            m.get("quartileFrom"),
            m.get("quartileTo"),
            m.get("cause"),
        ]
        for m in movers
    ]
    return ExportView(
        id="movement",
        title="Movement",
        subtitle=scope,
        columns=columns,
        row_label_header="Fund",
        row_labels=[m.get("label") for m in movers],
        rows=rows,
        provenance=provenance_for(session, run, version, cfg, f"research movement · {scope}"),
    )


def insights_view(
    session: Session,
    version: WorkbookVersion,
    run: Run,
    cfg: DashboardConfig,
    insights: list[ComputedInsight],
) -> ExportView:
    columns = [
        ExportColumn(key="section", label="Section", kind="field"),
        ExportColumn(key="insight", label="Insight", kind="field"),
        ExportColumn(key="sentence", label="Finding", kind="field"),
        ExportColumn(key="rank", label="#", format="integer", kind="field"),
        ExportColumn(key="sub", label="Detail", kind="field"),
        ExportColumn(key="value", label="Value", kind="field"),
    ]
    rows: list[list[Any]] = []
    labels: list[str | None] = []
    for ins in insights:
        if not ins.rows:
            rows.append([ins.section, ins.title, ins.sentence, None, None, None])
            labels.append("")
        for i, r in enumerate(ins.rows, start=1):
            rows.append(
                [ins.section, ins.title, ins.sentence if i == 1 else "", i, r.sub, r.value_label]
            )
            labels.append(r.label)
    return ExportView(
        id="insights",
        title="Insights brief",
        columns=columns,
        row_label_header="Fund / group",
        row_labels=labels,
        rows=rows,
        provenance=provenance_for(session, run, version, cfg, "research insights"),
    )


def slug_of(text: str) -> str:
    return slug(text)


def pivot_view(
    session: Session,
    version: WorkbookVersion,
    run: Run,
    cfg: DashboardConfig,
    spec: Any,
    query: Any,
    table: dict[str, Any],
) -> ExportView:
    """A computed pivot as a flat table: the row fields, then one column per column key and
    value; subtotals and the grand total are rows like any other, labelled by kind."""
    row_fields: list[str] = table["rowFields"]
    columns = [
        ExportColumn(key=f"row{i}", label=name, format="text", kind="field")
        for i, name in enumerate(row_fields)
    ]
    columns.append(ExportColumn(key="kind", label="Row type", format="text", kind="field"))
    columns.append(ExportColumn(key="n", label="Records", format="integer", kind="field"))
    for ci, ck in enumerate(table["colKeys"] or [[]]):
        prefix = " · ".join(ck) + " · " if ck else ""
        for vi, v in enumerate(table["values"]):
            fmt = "integer" if v["agg"] in ("count", "countNums") else "number"
            columns.append(
                ExportColumn(
                    key=f"c{ci}v{vi}", label=f"{prefix}{v['label']}", format=fmt, kind="output"
                )
            )
    rows: list[list[Any]] = []
    labels: list[str | None] = []
    for r in [*table["rows"], table["total"]]:
        keys = list(r["keys"]) + [None] * (len(row_fields) - len(r["keys"]))
        cells = (
            [c for group in r["cells"] for c in group]
            if r["cells"]
            else [None] * (len(columns) - len(row_fields) - 2)
        )
        rows.append(keys + [r["kind"], r["n"]] + cells)
        labels.append(" › ".join(r["keys"]))
    filters = (
        ", ".join(f"{k} = {' | '.join(v)}" for k, v in query.filters.items() if v) or "no filter"
    )
    return ExportView(
        id=slug(spec.sheet),
        title=f"{spec.sheet} · {spec.name}",
        subtitle=f"{filters} · {table['matched']} of {table['records']} records · {'engine values' if table['live'] else 'cached values'}",
        columns=columns,
        row_label_header="Row",
        row_labels=labels,
        rows=rows,
        provenance=provenance_for(session, run, version, cfg, f"pivot {spec.sheet} · {filters}"),
    )
