"""Research endpoints: entity-shaped views over the active version's baseline run (or a what-if
run), driven by the semantic map in dashboard.config.json. Every response says whether the map
is configured; an incomplete map yields a 200 with problems, never a 500."""

from __future__ import annotations

import math
import re
import statistics
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.exports.csv_export import write_csv
from app.exports.xlsx import write_workbook
from app.research import export as rexport
from app.research import insights as engine
from app.research import scope as scoping
from app.research import snapshots as snaps
from app.research.insights import (
    entity_sub,
    fmt_count,
    fmt_measure,
    render_sentence,
    render_sentences,
)
from app.research.semantic import MeasureSpec, parse_map
from app.research.snapshots import Snapshot
from app.research.table import (
    Entity,
    NotConfigured,
    ResearchTable,
    get_table,
    register_cache,
    resolve_for_version,
)
from app.storage import diffs, validation, workbooks
from app.storage import runs as run_store
from app.storage import views as view_store
from app.storage.db import get_session
from app.storage.models import Run, WorkbookVersion

router = APIRouter(prefix="/research")
SessionDep = Annotated[Session, Depends(get_session)]
PAGE_SIZE = 100
MAX_PAGE = 500


# ---- context ----------------------------------------------------------------------------


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat()


def _not_configured(problems: list[str], version: WorkbookVersion | None = None) -> dict[str, Any]:
    return {
        "configured": False,
        "problems": problems,
        "version_id": version.id if version else None,
        "run_id": None,
    }


def _pick_version(session: Session, version_id: str | None) -> WorkbookVersion | None:
    if version_id:
        try:
            return workbooks.get_version(session, version_id)
        except workbooks.WorkbookNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc
    versions = workbooks.list_versions(session)
    active = next((v for v in versions if v.status == "active"), None)
    if active is not None:
        return active
    for v in versions:  # newest first
        if run_store.baseline_run(session, v.id) is not None:
            return v
    return None


def _scope(raw: str | None) -> scoping.Scope:
    try:
        return scoping.parse_scope(raw)
    except scoping.ScopeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _context(
    session: Session, version_id: str | None, run_id: str | None, scope: str | None = None
) -> tuple[WorkbookVersion, Run, ResearchTable] | dict[str, Any]:
    """The version, run and research table a request works on. With a ``scope`` the table is
    the scoped view; ``get_table`` still gives the full one."""
    version = _pick_version(session, version_id)
    if version is None:
        return _not_configured(
            ["no version with a baseline run yet; upload and validate a master first"]
        )
    if run_id:
        try:
            run = run_store.get_run(session, run_id)
        except run_store.RunNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.") from exc
        if run.status != "ok":
            return _not_configured([f"run {run_id[:8]} is {run.status}"], version)
        version = workbooks.get_version(session, run.version_id)
    else:
        run = run_store.baseline_run(session, version.id)
        if run is None:
            return _not_configured(
                [f"version {version.id[:8]} has no baseline run yet; validate it first"], version
            )
    try:
        table = get_table(session, version, run)
    except NotConfigured as exc:
        return _not_configured(exc.problems, version)
    sc = _scope(scope)
    if not sc.is_empty:
        table = scoping.apply_scope(table, sc)
    return version, run, table


def _base(
    session: Session, version: WorkbookVersion, run: Run, table: ResearchTable
) -> ResearchTable:
    return table if not table.scope_key else get_table(session, version, run)


def _status(
    version: WorkbookVersion, run: Run, table: ResearchTable, base: ResearchTable | None = None
) -> dict[str, Any]:
    sc = scoping.parse_scope(table.scope_key)
    return {
        "configured": True,
        "problems": table.resolved.problems,
        "version_id": version.id,
        "run_id": run.id,
        "scope": {
            "key": table.scope_key,
            "applied": not sc.is_empty,
            "description": scoping.describe(base or table, sc),
            "value": sc.model_dump(),
        },
        "version": {
            "id": version.id,
            "filename": version.filename,
            "uploaded_at": _iso(version.uploaded_at),
            "status": version.status,
        },
        "run": {"id": run.id, "kind": run.kind, "created_at": _iso(run.created_at)},
    }


def _previous_version(session: Session, current: WorkbookVersion) -> WorkbookVersion | None:
    """The version activated before the current one (falls back to the previous baseline)."""
    candidates = [
        v
        for v in workbooks.list_versions(session)
        if v.id != current.id and run_store.baseline_run(session, v.id) is not None
    ]
    activated = [v for v in candidates if v.activated_at is not None]
    pool = activated or candidates
    pool = [v for v in pool if v.uploaded_at < current.uploaded_at] or pool
    return max(pool, key=lambda v: v.activated_at or v.uploaded_at) if pool else None


def _snapshot_of(
    session: Session, version: WorkbookVersion | None, table: ResearchTable | None = None
) -> Snapshot | None:
    """The version's snapshot (taken on demand when it is missing). For the current table the
    snapshot is derived in memory so a what-if run never writes one."""
    if version is None:
        return None
    if table is not None and table.version_id == version.id:
        rows, fingerprint = snaps.build_payload(table)
        return Snapshot(
            version_id=version.id,
            filename=version.filename,
            uploaded_at=version.uploaded_at,
            activated_at=version.activated_at,
            run_id=table.run_id,
            as_of=table.as_of,
            fingerprint=fingerprint,
            rows={k: snaps.SnapshotRow(*v) for k, v in rows.items()},
        )
    return snaps.snapshot_for(session, version)


def _history(session: Session, current: Snapshot | None) -> list[Snapshot]:
    """Genuine (distinct-month) activated snapshots, oldest first."""
    return snaps.genuine(snaps.activated_snapshots(session))


def _version_out(v: WorkbookVersion, snapshot: Snapshot | None, current: Snapshot | None):
    return {
        "id": v.id,
        "filename": v.filename,
        "uploaded_at": _iso(v.uploaded_at),
        "as_of": snapshot.date.date().isoformat() if snapshot else None,
        "date": snaps.date_label(snapshot, current),
    }


def _entity_dict(table: ResearchTable, e: Entity) -> dict[str, Any]:
    return {
        "key": e.key,
        "label": e.label,
        "sub": entity_sub(e),
        "dims": e.dims,
        "measures": e.measures,
        "raw": {k: v for k, v in e.raw.items() if e.measures.get(k) is None and v is not None},
        "rated": table.rated(e),
    }


def _measure_meta(table: ResearchTable) -> list[dict[str, Any]]:
    out = []
    for m in table.resolved.measure_specs():
        out.append(
            {
                "key": m.key,
                "label": m.label,
                "role": m.role,
                "format": m.format,
                "unit": m.unit,
                "higherIsBetter": m.higherIsBetter,
                "primary": m.primary,
                "decimals": m.decimals,
            }
        )
    return out


def _fmt_delta(delta: int | None) -> str | None:
    if delta is None:
        return None
    if delta > 0:
        return f"up {delta} place{'s' if delta != 1 else ''}"
    if delta < 0:
        return f"down {-delta} place{'s' if delta != -1 else ''}"
    return "unchanged"


# ---- movement ---------------------------------------------------------------------------


def _repair_keys(
    session: Session, base: WorkbookVersion, target: WorkbookVersion, table: ResearchTable
) -> dict[str, str]:
    """Entity keys whose rows were repaired between base and target, with the change title."""
    try:
        report = diffs.get_diff(session, base.id, target.id)
    except Exception:  # noqa: BLE001 - a missing or failing diff must not break movement
        return {}
    rmap = table.map
    key_cols: dict[str, str] = {rmap.entity.sheet: rmap.entity.keyColumn}
    for m in rmap.measures:
        if m.sheet and m.keyColumn:
            key_cols.setdefault(m.sheet, m.keyColumn)
    if rmap.phases:
        key_cols.setdefault(rmap.phases.sheet, rmap.phases.keyColumn)
    if rmap.periods:
        key_cols.setdefault(rmap.periods.sheet, rmap.periods.keyColumn)
    from openpyxl.utils import column_index_from_string as ci

    out: dict[str, str] = {}
    for change in report.logic:
        if not change.detail.get("repair"):
            continue
        col_letter = key_cols.get(change.sheet)
        if not col_letter:
            continue
        rows = {int(r) for r in re.findall(r"[A-Z]+(\d+)", change.location)}
        idx = view_store.sheet_cache.get(session, target.id, change.sheet)
        for row in rows:
            key = idx.any_text(row, ci(col_letter))
            if key and key in table.by_key:
                out[key] = change.title
    return out


def compute_movement(
    session: Session,
    base: WorkbookVersion,
    target: WorkbookVersion,
    table_to: ResearchTable,
    all_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Rank and quartile movement from the base version's snapshot to the target's table."""
    if run_store.baseline_run(session, base.id) is None:
        return {"available": False, "reason": f"version {base.id[:8]} has no baseline run"}
    snap_from = _snapshot_of(session, base)
    if snap_from is None:
        return {
            "available": False,
            "reason": f"the research map does not resolve on version {base.id[:8]}",
        }
    rank_key = table_to.primary_key("rank")
    q_key = table_to.primary_key("quartile")
    if rank_key is None:
        return {"available": False, "reason": "the primary rank measure does not resolve"}
    if table_to.summary["rated"] == 0:
        return {
            "available": False,
            "reason": "no rated fund in this scope: movement compares composite ranks",
        }
    snap_to = _snapshot_of(session, target, table_to)
    repairs = _repair_keys(session, base, target, table_to)
    movers: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    into_q1 = out_q1 = q_changes = 0
    for e in table_to.entities:
        before = snap_from.rows.get(e.key)
        if before is None:
            entries.append({"key": e.key, "label": e.label, "category": e.category})
            continue
        r_from, r_to = before.rank, e.measures.get(rank_key)
        q_from = before.quartile if q_key else None
        q_to = e.measures.get(q_key) if q_key else None
        if q_from != q_to and (q_from is not None or q_to is not None):
            q_changes += 1
            if q_to == 1 and q_from != 1:
                into_q1 += 1
            if q_from == 1 and q_to != 1:
                out_q1 += 1
        if r_from is None or r_to is None or r_from == r_to:
            continue
        delta = int(r_from - r_to)  # positive = moved up (a smaller rank)
        movers.append(
            {
                "key": e.key,
                "label": e.label,
                "sub": entity_sub(e),
                "category": e.category,
                "rankFrom": int(r_from),
                "rankTo": int(r_to),
                "delta": delta,
                "quartileFrom": int(q_from) if q_from is not None else None,
                "quartileTo": int(q_to) if q_to is not None else None,
                "cause": "repair" if e.key in repairs else "market",
                "note": repairs.get(e.key),
            }
        )
    present = all_keys if all_keys is not None else set(table_to.by_key)
    for k, before in snap_from.rows.items():
        if k not in present:
            exits.append({"key": k, "label": before.label, "category": before.category})
    up = [m for m in movers if m["delta"] > 0]
    down = [m for m in movers if m["delta"] < 0]
    up.sort(key=lambda m: -m["delta"])
    down.sort(key=lambda m: m["delta"])
    return {
        "available": True,
        "from": _version_out(base, snap_from, snap_to),
        "to": _version_out(target, snap_to, snap_to),
        "same_month": bool(snap_to and snap_from.fingerprint == snap_to.fingerprint),
        "rated": table_to.summary["rated"],
        "moved": len(movers),
        "up": len(up),
        "down": len(down),
        "avg_up": round(statistics.mean(m["delta"] for m in up), 1) if up else None,
        "avg_down": round(statistics.mean(-m["delta"] for m in down), 1) if down else None,
        "quartileChanges": {"total": q_changes, "into_q1": into_q1, "out_of_q1": out_q1},
        "risers": up,
        "fallers": down,
        "entries": entries,
        "exits": exits,
        "repairs": [
            {"key": k, "label": table_to.by_key[k].label, "note": note}
            for k, note in repairs.items()
        ],
    }


def _held_q1(table: ResearchTable, history: list[Snapshot]) -> dict[str, Any]:
    """How many current Q1 funds were Q1 in every genuine month. Unavailable (with the reason)
    until two activated versions with different as-of dates exist."""
    q_key = table.primary_key("quartile")
    if q_key is None:
        return {"available": False, "note": "the primary quartile measure does not resolve"}
    if len(history) < 2:
        return {
            "available": False,
            "versions": len(history),
            "note": "Becomes available after a second genuine monthly upload; every activated "
            "version so far carries the same as-of date."
            if history
            else "Becomes available once two activated versions with different as-of dates exist.",
        }
    tallies: dict[str, int] = {}
    for snap in history:
        for key, row in snap.rows.items():
            if row.quartile == 1:
                tallies[key] = tallies.get(key, 0) + 1
    current_q1 = [e.key for e in table.entities if e.measures.get(q_key) == 1]
    held = [k for k in current_q1 if tallies.get(k, 0) == len(history)]
    return {
        "available": True,
        "count": len(held),
        "current_q1": len(current_q1),
        "versions": len(history),
        "from": snaps.date_label(history[0], history[-1]),
    }


def _previous_label(movement: dict[str, Any]) -> str | None:
    """'31 Aug' normally; 'the earlier upload of 31 Aug' when both versions carry that date."""
    date = movement["from"]["date"]
    if date is None:
        return None
    return f"the earlier upload of {date}" if movement.get("same_month") else date


def _coverage_since(table: ResearchTable) -> str | None:
    cov = table.map.coverage
    if not cov:
        return None
    value = table.constants.get(cov.constant)
    return (
        fmt_measure(
            value, MeasureSpec(key="_", label="_", role="factor", column="A", format="date")
        )
        if value is not None
        else None
    )


def _kpis(table: ResearchTable, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """KPI tiles from the config: a tile is omitted when a required input is missing or when
    its value renders to zero (unless keepZero); a zero note is dropped, never shown."""
    from app.research.insights import _as_number  # noqa: PLC0415 - sibling helper
    from app.research.semantic import SentenceSpec

    numbers = ctx.get("_n") or {}
    tiles = []
    for k in table.map.kpis:
        if any(
            (numbers.get(r) if r in numbers else _lookup_ctx(ctx, r)) in (None, 0, 0.0)
            for r in k.requires
        ):
            continue
        value = render_sentence(k.value, ctx)
        if value is None:
            continue
        n = _as_number(value)
        if not k.keepZero and n is not None and n == 0:
            continue
        note = (
            render_sentences([SentenceSpec(default=k.note)], ctx, capitalize=False)
            if k.note
            else None
        )
        tiles.append({"label": k.label, "value": value, "note": note, "tone": k.tone})
    return tiles


def _lookup_ctx(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def _coverage_ctx(base: ResearchTable, as_of: str | None) -> dict[str, Any]:
    """The universe and coverage vocabulary, always over the full table."""
    u = base.summary
    return _numbers(
        total=u["total"],
        rated=u["rated"],
        unrated=u["total"] - u["rated"],
        categories=u["categories"],
        unranked=u["unranked_categories"],
        unranked_below=base.map.quartileRule.unrankedBelow,
        unrated_small=u["unrated_small_categories"],
        unrated_other=u["unrated_missing_data"],
        outside=u.get("outside_universe", 0),
        unrated_young=u.get("unrated_young", 0),
        unrated_gap=u.get("unrated_gap", 0),
        unrated_unknown=u.get("unrated_unknown", 0),
        coverage_since=_coverage_since(base),
        as_of=as_of,
    )


_computed_cache: dict[tuple[str, str, str], list[engine.ComputedInsight]] = {}
register_cache(_computed_cache)


def _computed(
    session: Session, table: ResearchTable, section: str | None = None
) -> list[engine.ComputedInsight]:
    """Every insight on this (possibly scoped) table, cached per version, run and scope."""
    key = (table.version_id, table.run_id, table.scope_key)
    hit = _computed_cache.get(key)
    if hit is None:
        hit = engine.compute_all(table, _versions_for_insights(session, table))
        if len(_computed_cache) >= 24:
            _computed_cache.pop(next(iter(_computed_cache)))
        _computed_cache[key] = hit
    return [c for c in hit if section is None or c.section == section]


def _numbers(**values: Any) -> dict[str, Any]:
    """Formatted placeholders plus the raw numbers (under ``_n``) for zero-variant selection."""
    ctx: dict[str, Any] = {"_n": {}}
    for k, v in values.items():
        if isinstance(v, bool) or v is None:
            ctx[k] = v
        elif isinstance(v, int | float):
            ctx[k] = fmt_count(v)
            ctx["_n"][k] = v
        else:
            ctx[k] = v
    return ctx


# ---- endpoints --------------------------------------------------------------------------


@router.get("/config")
def research_config(
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    cfg = load_dashboard_config()
    rmap, problems = parse_map(cfg.research)
    base: dict[str, Any] = {"configured": rmap is not None, "problems": problems}
    if rmap is None:
        return base
    version = _pick_version(session, version_id)
    resolved = None
    if version is not None:
        try:
            resolved = resolve_for_version(session, version.id)
            base["problems"] = resolved.problems
            base["version_id"] = version.id
        except NotConfigured as exc:
            base["configured"] = False
            base["problems"] = exc.problems
            base["version_id"] = version.id
    ent = rmap.entity
    base.update(
        {
            "entity": {
                "sheet": ent.sheet,
                "rows": list(resolved.entity_rows)
                if resolved
                else (list(ent.rows) if ent.rows else None),
                "key": f"{ent.sheet}!{ent.keyColumn}",
                "label": f"{ent.sheet}!{ent.labelColumn}" if ent.labelColumn else None,
                "universe": f"{ent.sheet}!{ent.universe.column} = {ent.universe.equals!r}"
                if ent.universe
                else None,
            },
            "dimensions": [
                {
                    "key": k,
                    "label": d.label,
                    "ref": f"{d.sheet or ent.sheet}!{d.column}",
                    "resolved": bool(resolved and k in resolved.dimensions),
                }
                for k, d in rmap.dimensions.items()
            ],
            "measures": [
                {
                    "key": m.key,
                    "label": m.label,
                    "role": m.role,
                    "ref": f"{m.sheet or ent.sheet}!{m.column}",
                    "format": m.format,
                    "unit": m.unit,
                    "higherIsBetter": m.higherIsBetter,
                    "primary": m.primary,
                    "resolved": bool(resolved and m.key in resolved.measures),
                }
                for m in rmap.measures
            ],
            "phases": [
                {
                    "key": g.key,
                    "label": g.label,
                    "columns": [
                        {
                            "col": c.upper(),
                            "label": (resolved.phase_labels.get(g.key, {}) if resolved else {}).get(
                                c.upper()
                            ),
                        }
                        for c in g.columns
                    ],
                }
                for g in (rmap.phases.groups if rmap.phases else [])
            ],
            "periods": [
                {
                    "col": c.upper(),
                    "label": (resolved.period_labels if resolved else {}).get(c.upper()),
                }
                for c in (rmap.periods.columns if rmap.periods else [])
            ],
            "categoryStats": [
                {
                    "col": c.upper(),
                    "label": (resolved.category_stat_labels if resolved else {}).get(c.upper()),
                }
                for c in (rmap.categoryStats.columns if rmap.categoryStats else [])
            ],
            "insights": [
                {
                    "key": i.key,
                    "section": i.section,
                    "eyebrow": i.eyebrow,
                    "title": i.title,
                    "mode": i.mode,
                }
                for i in rmap.insights
            ],
            "narratives": rmap.narratives,
            "footer": rmap.footer,
            "findings": [f.model_dump() for f in rmap.findings],
            "quartileRule": rmap.quartileRule.model_dump(),
            "minGroupCount": rmap.minGroupCount,
            "sectionLabels": rmap.sectionLabels,
            "constants": {k: v.model_dump() for k, v in rmap.constants.items()},
            "coverage": rmap.coverage.model_dump() if rmap.coverage else None,
        }
    )
    for d in base["dimensions"]:
        d["split"] = rmap.dimensions[d["key"]].split
        d["attribute"] = rmap.dimensions[d["key"]].attribute
    return base


@router.get("/summary")
def research_summary(
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    measure: Annotated[
        str | None, Query(description="return measure for the category averages")
    ] = None,
    scope: Annotated[str | None, Query(description="the global scope, as JSON")] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    base = _base(session, version, run, table)
    out = _status(version, run, table, base)
    out["as_of"] = table.as_of
    out["universe"] = table.summary
    out["universe_all"] = base.summary
    out["scope_options"] = scoping.options(base)
    out["quartiles"] = {str(k): v for k, v in table.summary["quartiles"].items()}
    returns = [m for m in table.resolved.measure_specs() if m.role == "return"]
    chosen = next((m for m in returns if m.key == measure), returns[0] if returns else None)
    if chosen is not None:
        rows = [
            {
                "key": c.key,
                "value": c.means.get(chosen.key),
                "label": fmt_measure(c.means.get(chosen.key), chosen),
                "count": c.rated,
            }
            for c in table.categories.values()
            if c.means.get(chosen.key) is not None
            and not c.unranked
            and c.rated >= table.map.minGroupCount
        ]
        rows.sort(key=lambda r: -r["value"])
        out["category_averages"] = {
            "measure": chosen.key,
            "label": chosen.label,
            "rows": rows[:8],
            "total": len(rows),
            "minGroupCount": table.map.minGroupCount,
        }
    else:
        out["category_averages"] = None
    out["measures"] = _measure_meta(table)
    # Validation and findings.
    try:
        report = validation.latest_validation(session, version.id)
        out["validation"] = {
            "status": report.status,
            "checked": report.totals.checked,
            "matched": report.totals.matched,
            "anomalies": sum(report.anomaly_counts.values()),
        }
    except validation.ValidationNotFoundError:
        out["validation"] = None
    findings = table.map.findings
    out["findings"] = {
        "open": sum(1 for f in findings if f.status == "open"),
        "fixed": sum(1 for f in findings if f.status == "fixed"),
    }
    # Movement headline vs the previous activated version.
    previous = _previous_version(session, version)
    movement = (
        compute_movement(session, previous, version, table, set(base.by_key)) if previous else None
    )
    available = bool(movement and movement.get("available"))
    out["movement"] = (
        {
            "previous": movement["from"],
            "same_month": movement["same_month"],
            "moved": movement["moved"],
            "up": movement["up"],
            "down": movement["down"],
            "repairs": len(movement["repairs"]),
            "entries": len(movement["entries"]),
            "exits": len(movement["exits"]),
            "top": (movement["risers"][:3] + movement["fallers"][:2]),
        }
        if available and movement
        else None
    )
    current = _snapshot_of(session, version, table)
    history = _history(session, current)
    held = _held_q1(table, history)
    out["held_q1"] = held
    out["history"] = [
        {
            "id": s.version_id,
            "date": snaps.date_label(s, current),
            "as_of": s.date.date().isoformat(),
        }
        for s in history
    ]
    u = table.summary
    universe_ctx = _coverage_ctx(base, snaps.date_label(current) if current else None)
    out["universe_narrative"] = render_sentences(table.map.narrative("universe"), universe_ctx)
    out["coverage_narrative"] = render_sentences(table.map.narrative("coverage"), universe_ctx)
    # The executive summary and the KPI tiles read the scoped numbers and the computed insights.
    computed = _computed(session, table)
    exec_ctx = _numbers(
        rated=u["rated"],
        total=u["total"],
        q1=u["quartiles"].get(1, 0),
        ranked_categories=u.get("ranked_categories", 0),
        categories=u["categories"],
        moved=movement["moved"] if available and movement else None,
        up=movement["up"] if available and movement else None,
        down=movement["down"] if available and movement else None,
        repairs=len(movement["repairs"]) if available and movement else None,
        checked=out["validation"]["checked"] if out.get("validation") else None,
        matched=out["validation"]["matched"] if out.get("validation") else None,
        mismatched=(out["validation"]["checked"] - out["validation"]["matched"])
        if out.get("validation")
        else None,
    )
    exec_ctx["q1_pct"] = (
        f"{100 * u['quartiles'].get(1, 0) / u['rated']:.1f}%" if u["rated"] else None
    )
    v = out.get("validation")
    exec_ctx["agreement"] = (
        f"{100 * v['matched'] / v['checked']:.2f}%" if v and v["checked"] else None
    )
    exec_ctx["previous"] = _previous_label(movement) if available and movement else None
    exec_ctx["current"] = snaps.date_label(current) if current else None
    exec_ctx["as_of"] = exec_ctx["current"]
    exec_ctx["scope"] = " · ".join(out["scope"]["description"])
    exec_ctx["ins"] = {c.key: c.context for c in computed}
    for c in computed:
        for path, value in c.numbers.items():
            exec_ctx["_n"][f"ins.{c.key}.{path}"] = value
        exec_ctx["_n"][f"ins.{c.key}.count"] = c.count
    exec_ctx.update(
        _numbers(
            unranked=u["unranked_categories"],
            unranked_below=table.map.quartileRule.unrankedBelow,
            unrated=u["total"] - u["rated"],
            unrated_young=u.get("unrated_young", 0),
            unrated_small=u["unrated_small_categories"],
            unrated_gap=u.get("unrated_gap", 0),
            unrated_unknown=u.get("unrated_unknown", 0),
            outside=u.get("outside_universe", 0),
        )
    )
    out["executive"] = render_sentences(table.map.narrative("executive"), exec_ctx)
    out["kpis"] = _kpis(table, exec_ctx)
    dist_ctx = _numbers(
        rated=u["rated"],
        ranked_categories=u.get("ranked_categories", 0),
        categories=u["categories"],
        median_category=u.get("median_category_rated", 0),
        largest_category_rated=(u.get("largest_category") or {}).get("rated", 0),
    )
    dist_ctx["largest_category"] = (u.get("largest_category") or {}).get("key")
    out["distribution_narrative"] = render_sentences(table.map.narrative("distribution"), dist_ctx)
    dashboard_ctx = _numbers(
        moved=movement["moved"] if available and movement else None,
        up=movement["up"] if available and movement else None,
        down=movement["down"] if available and movement else None,
        repairs=len(movement["repairs"]) if available and movement else None,
        previous=_previous_label(movement) if available and movement else None,
        current=snaps.date_label(current) if current else None,
        held_q1=held.get("count") if held.get("available") else None,
        versions=held.get("versions") if held.get("available") else None,
        rated=u["rated"],
        categories=u["categories"],
    )
    out["narrative"] = render_sentences(table.map.narrative("dashboard"), dashboard_ctx)
    out["footer"] = table.map.footer
    return out


def _filter_entities(
    table: ResearchTable,
    q: str | None,
    category: str | None,
    amc: str | None,
    plan: str | None,
    quartile: list[int] | None,
    keys: list[str] | None,
) -> list[Entity]:
    q_key = table.primary_key("quartile")
    needle = q.casefold().strip() if q else None
    key_set = set(keys) if keys else None
    out = []
    for e in table.entities:
        if key_set is not None and e.key not in key_set:
            continue
        if (
            needle
            and needle not in e.label.casefold()
            and needle not in e.key.casefold()
            and needle not in (e.dims.get("amc") or "").casefold()
        ):
            continue
        if category and e.dims.get("category") != category:
            continue
        if amc and e.dims.get("amc") != amc:
            continue
        if plan and e.dims.get("plan") != plan:
            continue
        if quartile:
            qv = e.measures.get(q_key) if q_key else None
            if qv is None or int(qv) not in quartile:
                continue
        out.append(e)
    return out


def _band(table: ResearchTable, measure_key: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Quartile bands of a measure over rated rows: entity key -> band label, plus band order."""
    spec = table.map.measure(measure_key)
    vals = sorted(v for e in table.entities if (v := e.measures.get(measure_key)) is not None)
    if len(vals) < 4:
        return {}, []
    q = statistics.quantiles(vals, n=4)
    labels = [
        (f"Up to {fmt_measure(q[0], spec)}", "b1"),
        (f"{fmt_measure(q[0], spec)} to {fmt_measure(q[1], spec)}", "b2"),
        (f"{fmt_measure(q[1], spec)} to {fmt_measure(q[2], spec)}", "b3"),
        (f"Above {fmt_measure(q[2], spec)}", "b4"),
    ]
    out: dict[str, str] = {}
    for e in table.entities:
        v = e.measures.get(measure_key)
        if v is None:
            continue
        band = 0 if v <= q[0] else 1 if v <= q[1] else 2 if v <= q[2] else 3
        out[e.key] = labels[band][0]
    return out, [(lbl, code) for lbl, code in labels]


@router.get("/entities")
def research_entities(
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    amc: Annotated[str | None, Query()] = None,
    plan: Annotated[str | None, Query()] = None,
    quartile: Annotated[list[int] | None, Query()] = None,
    keys: Annotated[
        list[str] | None, Query(description="restrict to these identities (drill-through)")
    ] = None,
    sort: Annotated[str | None, Query()] = None,
    dir: Annotated[Literal["asc", "desc"] | None, Query()] = None,  # noqa: A002
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE)] = PAGE_SIZE,
    group_by: Annotated[
        str | None, Query(alias="groupBy", description="dimension key, or <measure>_band")
    ] = None,
    scope: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    out = _status(version, run, table, _base(session, version, run, table))
    rank_key = table.primary_key("rank")
    rows = _filter_entities(table, q, category, amc, plan, quartile, keys)
    sort_key = sort if sort and sort in table.resolved.measures else rank_key
    if sort_key:
        spec = table.map.measure(sort_key)
        direction = dir or ("asc" if spec and spec.role in ("rank", "quartile") else "desc")
        if sort_key == rank_key and dir is None:
            direction = "asc"
        rows = engine.sort_entities(table, rows, sort_key, direction)
    else:
        direction = "asc"
    # Deltas vs the previous activated version's snapshot.
    previous = _previous_version(session, version)
    prev_snap = _snapshot_of(session, previous)
    deltas: dict[str, dict[str, Any]] = {}
    if prev_snap is not None and rank_key:
        for e in rows:
            b = prev_snap.rows.get(e.key)
            if b is None:
                deltas[e.key] = {"rank": None, "new": True}
                continue
            rt = e.measures.get(rank_key)
            deltas[e.key] = {
                "rank": int(b.rank - rt) if b.rank is not None and rt is not None else None,
                "quartileFrom": int(b.quartile) if b.quartile is not None else None,
                "new": False,
            }
    # Grouping (a pivot, not a filter).
    groups: list[dict[str, Any]] | None = None
    group_of: dict[str, str] = {}
    if group_by:
        if group_by.endswith("_band") and group_by[:-5] in table.resolved.measures:
            group_of, order = _band(table, group_by[:-5])
            order_labels = [lbl for lbl, _c in order]
        elif group_by in table.resolved.dimensions:
            group_of = {e.key: (e.dims.get(group_by) or "—") for e in rows}
            order_labels = sorted({v for v in group_of.values()})
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown group_by {group_by!r}"
            )
        members: dict[str, list[Entity]] = {}
        for e in rows:
            g = group_of.get(e.key, "—")
            members.setdefault(g, []).append(e)
        numeric = [
            m for m in table.resolved.measure_specs() if m.role in ("score", "return", "factor")
        ]
        q_key = table.primary_key("quartile")
        groups = []
        for label in order_labels + [g for g in members if g not in order_labels]:
            grp = members.get(label)
            if not grp:
                continue
            subtotal: dict[str, Any] = {"count": len(grp)}
            if q_key:
                subtotal["q1"] = sum(1 for e in grp if e.measures.get(q_key) == 1)
            for m in numeric:
                vals = [v for e in grp if (v := e.measures.get(m.key)) is not None]
                subtotal[m.key] = (sum(vals) / len(vals)) if vals else None
            groups.append({"key": label, "label": label, "count": len(grp), "subtotals": subtotal})
        rows = [e for label in [g["key"] for g in groups] for e in members[label]]
    total = len(rows)
    start = (page - 1) * size
    page_rows = rows[start : start + size]
    out.update(
        {
            "total": total,
            "page": page,
            "size": size,
            "sort": sort_key,
            "dir": direction,
            "measures": _measure_meta(table),
            "dimensions": [
                {"key": k, "label": table.map.dimensions[k].label}
                for k in table.resolved.dimensions
            ],
            "facets": {
                d: sorted({v for e in table.entities if (v := e.dims.get(d))})
                for d in ("category", "amc", "plan")
                if d in table.resolved.dimensions
            },
            "previous": _version_out(previous, prev_snap, _snapshot_of(session, version, table))
            if previous
            else None,
            "groups": groups,
            "rows": [
                {**_entity_dict(table, e), "delta": deltas.get(e.key), "group": group_of.get(e.key)}
                for e in page_rows
            ],
        }
    )
    return out


def _category_rows(
    table: ResearchTable, measure: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    returns = [m for m in table.resolved.measure_specs() if m.role == "return"]
    chosen = next((m for m in returns if m.key == measure), returns[0] if returns else None)
    rows = []
    for c in table.categories.values():
        if c.count == 0:  # a key in the category-statistics table with no fund behind it
            continue
        rows.append(
            {
                "key": c.key,
                "count": c.count,
                "rated": c.rated,
                "quartiles": {str(k): v for k, v in c.quartiles.items()},
                "means": c.means,
                "spreads": c.spreads,
                "stats": {col: c.stats.get(col) for col in c.stats},
                "statLabels": table.resolved.category_stat_labels,
                "unranked": c.unranked,
                "value": c.means.get(chosen.key) if chosen else None,
                "valueLabel": fmt_measure(c.means.get(chosen.key), chosen) if chosen else "",
            }
        )
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    return rows, chosen.key if chosen else None


@router.get("/categories")
def research_categories(
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    measure: Annotated[str | None, Query()] = None,
    scope: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    out = _status(version, run, table, _base(session, version, run, table))
    rows, chosen = _category_rows(table, measure)
    spec = table.map.measure(chosen) if chosen else None
    min_group = table.map.minGroupCount
    eligible = [r for r in rows if r["rated"] >= min_group]
    widest = (
        max(
            (r for r in eligible if r["spreads"].get(chosen) is not None),
            key=lambda r: r["spreads"][chosen],
            default=None,
        )
        if chosen
        else None
    )
    best = next((r for r in eligible if r["value"] is not None), None)
    narrative_ctx = _numbers(
        categories=len(rows),
        unranked=sum(1 for r in rows if r["unranked"]),
        unranked_below=table.map.quartileRule.unrankedBelow,
        eligible=len(eligible),
        min_group=min_group,
    )
    narrative_ctx["widest"] = (
        {
            "label": widest["key"],
            "value": fmt_measure(widest["spreads"][chosen], spec)
            + (" pts" if spec and not spec.unit else ""),
        }
        if widest
        else None
    )
    narrative_ctx["best"] = {"label": best["key"], "value": best["valueLabel"]} if best else None
    narrative_ctx["measure"] = {"label": spec.label} if spec else None
    out.update(
        {
            "measure": chosen,
            "measures": [
                {"key": m.key, "label": m.label}
                for m in table.resolved.measure_specs()
                if m.role == "return"
            ],
            "unrankedBelow": table.map.quartileRule.unrankedBelow,
            "minGroupCount": min_group,
            "statsOnly": table.summary.get("stats_only_categories", 0),
            "rows": rows,
            "narrative": render_sentences(table.map.narrative("categories"), narrative_ctx),
        }
    )
    return out


@router.get("/movement")
def research_movement(
    session: SessionDep,
    version_id: Annotated[str | None, Query(alias="to")] = None,
    from_id: Annotated[str | None, Query(alias="from")] = None,
    scope: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, None, scope)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    full = _base(session, version, run, table)
    out = _status(version, run, table, full)
    base = _pick_version(session, from_id) if from_id else _previous_version(session, version)
    if base is None or base.id == version.id:
        out.update(
            {"available": False, "reason": "no earlier version with a baseline run to compare with"}
        )
        return out
    movement = compute_movement(session, base, version, table, set(full.by_key))
    out.update(movement)
    current = _snapshot_of(session, version, table)
    by_id = {s.version_id: s for s in snaps.activated_snapshots(session)}
    out["versions"] = [
        {
            **_version_out(v, by_id.get(v.id), current),
            "status": v.status,
            "activated_at": _iso(v.activated_at),
        }
        for v in workbooks.list_versions(session)
        if run_store.baseline_run(session, v.id) is not None
    ]
    if movement.get("available"):
        narrative_ctx = _numbers(
            rated=movement["rated"],
            moved=movement["moved"],
            up=movement["up"],
            down=movement["down"],
            repairs=len(movement["repairs"]),
            into_q1=movement["quartileChanges"]["into_q1"],
            out_of_q1=movement["quartileChanges"]["out_of_q1"],
            entries=len(movement["entries"]),
            exits=len(movement["exits"]),
            previous=_previous_label(movement),
            current=(
                f"the later upload of {movement['to']['date']}"
                if movement.get("same_month")
                else movement["to"]["date"]
            ),
        )
        out["narrative"] = render_sentences(table.map.narrative("movement"), narrative_ctx)
    return out


def _versions_for_insights(session: Session, table: ResearchTable) -> list[Snapshot]:
    if not any(i.mode == "acrossVersions" for i in table.map.insights):
        return []
    return _history(session, None)


def _insight_dict(ins: engine.ComputedInsight) -> dict[str, Any]:
    return {
        "key": ins.key,
        "section": ins.section,
        "eyebrow": ins.eyebrow,
        "title": ins.title,
        "sentence": ins.sentence,
        "count": ins.count,
        "total": ins.total,
        "measure": ins.measure,
        "drill": ins.drill,
        "problems": ins.problems,
        "status": ins.status,
        "note": ins.note,
        "rows": [
            {
                "key": r.key,
                "label": r.label,
                "sub": r.sub,
                "value": r.value,
                "valueLabel": r.value_label,
                "extra": r.extra,
            }
            for r in ins.rows
        ],
    }


@router.get("/insights")
def research_insights(
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    section: Annotated[str | None, Query()] = None,
    scope: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    out = _status(version, run, table, _base(session, version, run, table))
    computed = _computed(session, table, section)
    sections: list[str] = []
    for i in table.map.insights:
        if i.section not in sections:
            sections.append(i.section)
    out.update(
        {
            "sections": sections,
            "sectionLabels": table.map.sectionLabels,
            "insights": [_insight_dict(c) for c in computed],
            "footer": table.map.footer,
        }
    )
    return out


# ---- exports ------------------------------------------------------------------------------


def _send(view, fmt: str, filename: str) -> Response:
    if fmt == "csv":
        content, media = write_csv(view).encode("utf-8-sig"), "text/csv; charset=utf-8"
        name = filename + ".csv"
    else:
        import io

        buf = io.BytesIO()
        write_workbook([view], view.provenance, buf)
        content = buf.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = filename + ".xlsx"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/entities/export")
def export_entities(
    session: SessionDep,
    format: Annotated[Literal["csv", "xlsx"], Query()],  # noqa: A002
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    amc: Annotated[str | None, Query()] = None,
    plan: Annotated[str | None, Query()] = None,
    quartile: Annotated[list[int] | None, Query()] = None,
    keys: Annotated[list[str] | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
    dir: Annotated[Literal["asc", "desc"] | None, Query()] = None,  # noqa: A002
    scope: Annotated[str | None, Query()] = None,
):
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "research views are not configured", "problems": ctx["problems"]},
        )
    version, run, table = ctx
    rows = _filter_entities(table, q, category, amc, plan, quartile, keys)
    rank_key = table.primary_key("rank")
    sort_key = sort if sort in table.resolved.measures else rank_key
    if sort_key:
        rows = engine.sort_entities(table, rows, sort_key, dir or "asc")
    scope = (
        ", ".join(
            f"{k}={v}"
            for k, v in (
                ("search", q),
                ("category", category),
                ("amc", amc),
                ("plan", plan),
                ("quartile", quartile),
            )
            if v
        )
        or "all funds"
    )
    view = rexport.entities_view(session, version, run, load_dashboard_config(), table, rows, scope)
    return _send(view, format, f"funds-{version.id[:8]}")


@router.get("/categories/export")
def export_categories(
    session: SessionDep,
    format: Annotated[Literal["csv", "xlsx"], Query()],  # noqa: A002
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    measure: Annotated[str | None, Query()] = None,
    scope: Annotated[str | None, Query()] = None,
):
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "research views are not configured", "problems": ctx["problems"]},
        )
    version, run, table = ctx
    rows, _chosen = _category_rows(table, measure)
    view = rexport.categories_view(session, version, run, load_dashboard_config(), table, rows)
    return _send(view, format, f"categories-{version.id[:8]}")


@router.get("/movement/export")
def export_movement(
    session: SessionDep,
    format: Annotated[Literal["csv", "xlsx"], Query()],  # noqa: A002
    version_id: Annotated[str | None, Query(alias="to")] = None,
    from_id: Annotated[str | None, Query(alias="from")] = None,
    scope: Annotated[str | None, Query()] = None,
):
    ctx = _context(session, version_id, None, scope)
    if isinstance(ctx, dict):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "research views are not configured", "problems": ctx["problems"]},
        )
    version, run, table = ctx
    base = _pick_version(session, from_id) if from_id else _previous_version(session, version)
    if base is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no earlier version to compare with")
    movement = compute_movement(
        session, base, version, table, set(_base(session, version, run, table).by_key)
    )
    if not movement.get("available"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, movement.get("reason", "movement unavailable")
        )
    movers = movement["risers"] + movement["fallers"]
    view = rexport.movement_view(
        session,
        version,
        run,
        load_dashboard_config(),
        movers,
        f"{base.filename} → {version.filename}",
    )
    return _send(view, format, f"movement-{base.id[:8]}-{version.id[:8]}")


@router.get("/insights/export")
def export_insights(
    session: SessionDep,
    format: Annotated[Literal["csv", "xlsx"], Query()],  # noqa: A002
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    scope: Annotated[str | None, Query()] = None,
):
    ctx = _context(session, version_id, run_id, scope)
    if isinstance(ctx, dict):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "research views are not configured", "problems": ctx["problems"]},
        )
    version, run, table = ctx
    computed = _computed(session, table)
    view = rexport.insights_view(session, version, run, load_dashboard_config(), computed)
    return _send(view, format, f"insights-{version.id[:8]}")


@router.get("/entities/{key:path}")
def research_entity(
    key: str,
    session: SessionDep,
    version_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    ctx = _context(session, version_id, run_id)
    if isinstance(ctx, dict):
        return ctx
    version, run, table = ctx
    e = table.by_key.get(key)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found in this version.")
    out = _status(version, run, table)
    rank_key, q_key, score_key = (
        table.primary_key("rank"),
        table.primary_key("quartile"),
        table.primary_key("score"),
    )
    cat = e.category
    peers_all = [p for p in table.entities if cat and p.category == cat]
    info = table.categories.get(cat) if cat else None

    def cat_rank(mkey: str) -> int | None:
        spec = table.map.measure(mkey)
        v = e.measures.get(mkey)
        if v is None or spec is None:
            return None
        better = [
            p
            for p in peers_all
            if (pv := p.measures.get(mkey)) is not None
            and ((pv > v) if spec.higherIsBetter else (pv < v))
        ]
        return len(better) + 1

    measures = []
    for m in table.resolved.measure_specs():
        v = e.measures.get(m.key)
        measures.append(
            {
                "key": m.key,
                "label": m.label,
                "role": m.role,
                "value": v,
                "display": fmt_measure(v if v is not None else e.raw.get(m.key), m),
                "unit": m.unit,
                "primary": m.primary,
                "format": m.format,
                "decimals": m.decimals,
                "categoryRank": cat_rank(m.key),
                "categoryCount": sum(1 for p in peers_all if p.measures.get(m.key) is not None),
                "cell": e.cells.get(m.key),
            }
        )
    # Phases: fund vs category mean.
    phases = []
    if table.map.phases and table.resolved.phases_ok:
        for g in table.map.phases.groups:
            for letter in g.columns:
                k = f"{g.key}:{letter.upper()}"
                vals = [v for p in peers_all if (v := p.phases.get(k)) is not None]
                phases.append(
                    {
                        "group": g.key,
                        "groupLabel": g.label,
                        "label": table.resolved.phase_labels.get(g.key, {}).get(
                            letter.upper(), letter
                        ),
                        "value": e.phases.get(k),
                        "categoryMean": (sum(vals) / len(vals)) if vals else None,
                        "unit": table.map.phases.unit,
                    }
                )
    periods = []
    if table.map.periods and table.resolved.periods_ok:
        for letter in table.map.periods.columns:
            periods.append(
                {
                    "label": table.resolved.period_labels.get(letter.upper(), letter),
                    "value": e.periods.get(letter.upper()),
                    "unit": table.map.periods.unit,
                }
            )
    # Peers by primary rank.
    peers_sorted = (
        engine.sort_entities(table, peers_all, rank_key, "asc") if rank_key else peers_all
    )
    my_pos = next((i for i, p in enumerate(peers_sorted) if p.key == e.key), None)
    window: list[Entity] = peers_sorted[:5]
    if my_pos is not None:
        for p in peers_sorted[max(0, my_pos - 2) : my_pos + 3]:
            if p not in window:
                window.append(p)
    peers = [
        {
            "key": p.key,
            "label": p.label,
            "rank": p.measures.get(rank_key) if rank_key else None,
            "quartile": p.measures.get(q_key) if q_key else None,
            "score": p.measures.get(score_key) if score_key else None,
            "scoreLabel": fmt_measure(p.measures.get(score_key), table.map.measure(score_key))
            if score_key
            else "",
            "me": p.key == e.key,
        }
        for p in window
    ]
    # History across genuine activated versions (snapshots).
    current = _snapshot_of(session, version, table)
    history = []
    for s in _history(session, current):
        h = s.rows.get(e.key)
        if h is None:
            continue
        history.append(
            {
                "version_id": s.version_id,
                "filename": s.filename,
                "uploaded_at": _iso(s.uploaded_at),
                "date": snaps.date_label(s, current),
                "as_of": s.date.date().isoformat(),
                "rank": h.rank,
                "quartile": h.quartile,
                "score": h.score,
            }
        )
    # Movement vs previous and the narrative.
    previous = _previous_version(session, version)
    prev_snap = _snapshot_of(session, previous)
    delta = None
    if prev_snap is not None and rank_key:
        b = prev_snap.rows.get(e.key)
        if b is not None and b.rank is not None and e.measures.get(rank_key) is not None:
            delta = int(b.rank - e.measures[rank_key])  # type: ignore[operator]
    # The quartile rule in words: re-evaluate the quartile cell with tracing.
    explanation: list[str] | None = None
    q_cell = e.cells.get(q_key) if q_key else None
    if q_cell:
        try:
            from app.engine.lineage import narrate
            from app.model.formula.refs import parse_a1_cell

            sheet_name, addr = q_cell.rsplit("!", 1)
            eng, _model, _meta, _v = run_store.load_engine(session, version.id)
            state = run_store.state_for(session, run)
            traced = eng.evaluate_cell(sheet_name, *parse_a1_cell(addr), state)
            if traced is not None:
                explanation = narrate(traced[1], traced[0]) or None
        except Exception:  # noqa: BLE001 - explanation is optional
            explanation = None
    rank_v = e.measures.get(rank_key) if rank_key else None
    q_v = e.measures.get(q_key) if q_key else None
    narrative_ctx = _numbers(
        rank=rank_v,
        category_count=info.rated if info else None,
        delta=delta,
    )
    narrative_ctx.update(
        {
            "label": e.label,
            "category": cat,
            "quartile": f"Q{int(q_v)}" if q_v is not None else None,
            "delta_text": _fmt_delta(delta),
            "previous": snaps.date_label(prev_snap, current) if prev_snap else None,
            "score": fmt_measure(e.measures.get(score_key), table.map.measure(score_key))
            if score_key
            else None,
        }
    )
    out.update(
        {
            "entity": _entity_dict(table, e),
            "dimensions": [
                {"key": k, "label": table.map.dimensions[k].label}
                for k in table.resolved.dimensions
            ],
            "row": e.row,
            "measures": measures,
            "phases": phases,
            "periods": periods,
            "category": {
                "key": cat,
                "count": info.count if info else 0,
                "rated": info.rated if info else 0,
                "quartiles": {str(k): v for k, v in (info.quartiles if info else {}).items()},
                "means": info.means if info else {},
            },
            "peers": peers,
            "history": history,
            "delta": delta,
            "deltaLabel": _fmt_delta(delta),
            "previous": _version_out(previous, prev_snap, current) if previous else None,
            "quartileExplanation": explanation,
            "narrative": render_sentences(table.map.narrative("fund"), narrative_ctx),
            "cells": e.cells,
        }
    )
    return out


def compute_insights_for_report(
    session: Session, version: WorkbookVersion, run: Run
) -> list[engine.ComputedInsight] | None:
    """Used by the PDF report: None when the research map is not configured."""
    try:
        table = get_table(session, version, run)
    except NotConfigured:
        return None
    return _computed(session, table)


__all__ = ["router", "compute_movement", "compute_insights_for_report", "math"]
