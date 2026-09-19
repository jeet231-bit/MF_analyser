"""The insight engine: declarative questions over the research table, each with a computed
sentence. Config describes the question; this module evaluates it. Sentences are templates
with a fixed vocabulary of placeholders, validated at load, so a card is either fully computed
or reported, never rendered with holes. A sentence whose trigger count is zero uses its ``zero``
variant or is omitted: a sentence made of zeros is never emitted."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from openpyxl.utils.datetime import from_excel

from app.exports.report import _group
from app.research.semantic import (
    SENTENCE_PLACEHOLDER,
    InsightSpec,
    MeasureSpec,
    Predicate,
    SentenceSpec,
)
from app.research.snapshots import Snapshot, SnapshotRow
from app.research.table import Entity, ResearchTable

INDIAN = True


@dataclass
class InsightRow:
    key: str | None
    label: str
    sub: str | None = None
    value: Any = None
    value_label: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComputedInsight:
    key: str
    section: str
    eyebrow: str
    title: str
    sentence: str
    rows: list[InsightRow]
    count: int
    total: int
    drill: dict[str, Any]
    measure: str | None = None
    problems: list[str] = field(default_factory=list)
    status: str = "ok"  # ok | empty | unavailable | problem
    note: str | None = None  # why an unavailable or empty card shows a placeholder
    context: dict[str, Any] = field(default_factory=dict)  # the sentence placeholders, formatted
    numbers: dict[str, Any] = field(default_factory=dict)  # the same, raw, for zero tests


# ---- formatting -------------------------------------------------------------------------


def fmt_inr_crore(x: float) -> str:
    """Indian currency for amounts held in crore: ₹39.1 lakh crore, ₹86,785 crore, ₹45.3 crore."""
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e5:
        return f"{sign}₹{_group(a / 1e5, 1, INDIAN)} lakh crore"
    if a >= 100:
        return f"{sign}₹{_group(a, 0, INDIAN)} crore"
    return f"{sign}₹{_group(a, 1, INDIAN)} crore"


def fmt_measure(value: Any, spec: MeasureSpec | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        return str(value)
    x = float(value)
    if spec is None:
        return _group(x, 0 if x.is_integer() else 2, INDIAN)
    if spec.format == "inr_crore":
        return fmt_inr_crore(x)
    if spec.format == "date":
        try:
            return from_excel(x).strftime("%d %b %Y").lstrip("0")
        except (ValueError, OverflowError, TypeError):
            return str(value)
    decimals = spec.decimals
    if decimals is None:
        decimals = 0 if spec.format == "integer" or spec.role in ("rank", "quartile") else 2
    if spec.format == "percent":
        return _group(x * 100, decimals, INDIAN) + "%"
    text = _group(x, decimals, INDIAN)
    return f"{text}{spec.unit}" if spec.unit else text


def fmt_count(n: float) -> str:
    return _group(float(n), 0, INDIAN)


def _lookup(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").rstrip("%").strip())
        except ValueError:
            return None
    return None


def render_sentence(template: str, ctx: dict[str, Any]) -> str | None:
    """Fill a template; None when any placeholder is missing or None (never a hole).
    ``{n|fund|funds}`` renders the number and the right word; ``{n?is|are}`` only the word."""
    numbers: dict[str, Any] = ctx.get("_n") or {}
    missing = False

    def fill(m: re.Match[str]) -> str:
        nonlocal missing
        name, mode, one, many = m.group(1), m.group(2), m.group(3), m.group(4)
        v = _lookup(ctx, name)
        if v is None:
            missing = True
            return ""
        if not mode:
            return str(v)
        n = _as_number(numbers.get(name)) if name in numbers else _as_number(v)
        word = one if n == 1 else many
        return word if mode == "?" else f"{v} {word}"

    out = SENTENCE_PLACEHOLDER.sub(fill, template)
    return None if missing else out


def _is_zero(value: Any) -> bool:
    n = _as_number(value)
    return n is not None and n == 0


def render_sentences(
    specs: list[SentenceSpec], ctx: dict[str, Any], capitalize: bool = True
) -> str | None:
    """Render every sentence that can be completed, choosing the zero variant when the trigger
    placeholder is zero and omitting the sentence when it is zero without a variant. Raw numbers
    for the zero test come from ``ctx['_n']`` when present, else from the formatted value."""
    numbers: dict[str, Any] = ctx.get("_n") or {}

    def raw(ph: str) -> Any:
        return numbers.get(ph) if ph in numbers else _lookup(ctx, ph)

    parts: list[str] = []
    for spec in specs:
        if any(raw(ph) is None or _is_zero(raw(ph)) for ph in spec.requires):
            continue
        if any(raw(ph) is not None and not _is_zero(raw(ph)) for ph in spec.unless):
            continue
        triggers = spec.trigger_keys
        if triggers and all(_is_zero(raw(t)) for t in triggers):
            if not spec.zero:
                continue
            text = render_sentence(spec.zero, ctx)
        elif spec.one and len(triggers) == 1 and _as_number(raw(triggers[0])) == 1:
            text = render_sentence(spec.one, ctx)
        else:
            text = render_sentence(spec.default, ctx)
        if text:
            parts.append(text[0].upper() + text[1:] if capitalize else text)
    return " ".join(parts) or None


# ---- predicates -------------------------------------------------------------------------


def _top_bottom(table: ResearchTable, spec: MeasureSpec, e: Entity, pred: Predicate) -> bool:
    top = pred.op == "top"
    v = e.measures.get(spec.key)
    if v is None:
        return False
    if spec.role == "quartile":
        return v == (1 if top else 4)
    if spec.role == "rank":
        info = table.categories.get(e.category) if e.category else None
        n = info.rated if info and info.rated else None
        if not n:
            return False
        return _rank_in_share(v, n, pred.fraction, top)
    return _value_in_share(table, spec, v, pred.fraction, top)


def _rank_in_share(rank: float, n: int, fraction: float, top: bool) -> bool:
    cut = math.ceil(n * fraction)
    return rank <= cut if top else rank > n - cut


def _value_in_share(
    table: ResearchTable, spec: MeasureSpec, v: float, fraction: float, top: bool
) -> bool:
    vals = table.sorted_values(spec.key)
    if len(vals) < 4:
        return False
    k = max(1, math.ceil(len(vals) * fraction))
    best_high = spec.higherIsBetter
    if top:
        threshold = vals[-k] if best_high else vals[k - 1]
        return v >= threshold if best_high else v <= threshold
    threshold = vals[k - 1] if best_high else vals[-k]
    return v <= threshold if best_high else v >= threshold


def _target(table: ResearchTable, value: Any) -> Any:
    """A literal, or a declared constant when the value is '$name' (None when unresolved)."""
    if isinstance(value, str) and value.startswith("$"):
        return table.constants.get(value[1:])
    return value


def matches(table: ResearchTable, e: Entity, pred: Predicate) -> bool:
    if pred.dimension is not None:
        return _matches_dimension(e.dims.get(pred.dimension), pred)
    if pred.measure is None:
        return False
    spec = table.map.measure(pred.measure)
    if spec is None or pred.measure not in table.resolved.measures:
        return False
    v = e.measures.get(pred.measure)
    op = pred.op
    if op == "notnull":
        return v is not None
    if op == "isnull":
        return v is None
    if op in ("top", "bottom"):
        return _top_bottom(table, spec, e, pred)
    if v is None:
        return False
    target = _target(table, pred.value)
    if target is None and op != "in":
        return False
    return _compare(v, op, target)


def _matches_dimension(v: str | None, pred: Predicate) -> bool:
    op = pred.op
    if op == "notnull":
        return v is not None
    if op == "isnull":
        return v is None
    if v is None:
        return False
    if op == "in":
        return v in [str(x) for x in (pred.value or [])]
    if op == "eq":
        return v == str(pred.value)
    if op == "ne":
        return v != str(pred.value)
    return False


def _compare(v: float, op: str, target: Any) -> bool:
    if op == "in":
        return v in [float(x) for x in (target or [])]
    try:
        t = float(target)
    except (TypeError, ValueError):
        return False
    return {
        "eq": v == t,
        "ne": v != t,
        "lt": v < t,
        "lte": v <= t,
        "gt": v > t,
        "gte": v >= t,
    }[op]


def matches_snapshot(
    table: ResearchTable, snap: Snapshot, row: SnapshotRow, pred: Predicate
) -> bool:
    """A predicate over a snapshot row: only the primary score / rank / quartile exist there."""
    spec = table.map.measure(pred.measure)
    if spec is None:
        return False
    v = {"rank": row.rank, "quartile": row.quartile, "score": row.score}.get(spec.role)
    op = pred.op
    if op == "notnull":
        return v is not None
    if v is None:
        return False
    if op in ("top", "bottom"):
        top = op == "top"
        if spec.role == "quartile":
            return v == (1 if top else 4)
        if spec.role == "rank":
            n = snap.rated_in_category(row.category)
            return bool(n) and _rank_in_share(v, n, pred.fraction, top)
        return False
    return _compare(v, op, pred.value)


def select(table: ResearchTable, preds: list[Predicate]) -> list[Entity]:
    return [e for e in table.entities if all(matches(table, e, p) for p in preds)]


def sort_entities(
    table: ResearchTable, rows: list[Entity], key: str, direction: str
) -> list[Entity]:
    spec = table.map.measure(key)
    if spec is None:
        return rows
    desc = direction == "desc"

    def sort_key(e: Entity):
        v = e.measures.get(key)
        return (v is None, (-v if desc else v) if v is not None else 0.0)

    return sorted(rows, key=sort_key)


def entity_sub(e: Entity) -> str | None:
    parts = [e.dims.get("plan"), e.dims.get("amc")]
    return " · ".join(p for p in parts if p) or None


# ---- the engine -------------------------------------------------------------------------


def _result(
    spec: InsightSpec,
    sentence: str,
    rows: list[InsightRow],
    count: int,
    total: int,
    drill: dict[str, Any],
    measure_key: str | None,
    problems: list[str],
    status: str = "ok",
    note: str | None = None,
) -> ComputedInsight:
    return ComputedInsight(
        spec.key,
        spec.section,
        spec.eyebrow,
        spec.title,
        sentence,
        rows,
        count,
        total,
        drill,
        measure_key,
        problems,
        status,
        note,
    )


def compute_insight(
    table: ResearchTable,
    spec: InsightSpec,
    snapshots: list[Snapshot] | None = None,
) -> ComputedInsight:
    """``snapshots``: one per genuine (distinct-month) activated version, oldest first, for
    acrossVersions insights."""
    problems: list[str] = []
    needed = [p.measure for p in spec.where if p.measure] + (
        [spec.sort.measure] if spec.sort else []
    )
    if spec.groupBy:
        needed += [p.measure for p in spec.groupBy.where if p.measure] + (
            [spec.groupBy.measure] if spec.groupBy.measure else []
        )
    if spec.aggregate:
        needed.append(spec.aggregate.measure)
    if spec.across:
        needed += [p.measure for p in spec.across.where if p.measure]
    missing = sorted({m for m in needed if m not in table.resolved.measures})
    if missing:
        problems.append(f"measure(s) not resolved on this version: {', '.join(missing)}")
    rated_total = table.summary["rated"] or table.summary["total"]
    numbers: dict[str, Any] = {"total": rated_total, "versions": len(snapshots or [])}
    ctx: dict[str, Any] = {
        "total": fmt_count(rated_total),
        "versions": len(snapshots or []),
        "_n": numbers,
    }
    rows: list[InsightRow] = []
    count = 0
    drill: dict[str, Any] = dict(spec.drill)
    measure_key = (
        spec.sort.measure if spec.sort else (spec.aggregate.measure if spec.aggregate else None)
    )

    if problems:
        return _result(spec, "", [], 0, rated_total, drill, measure_key, problems, "problem")
    where_text = "in this scope" if table.scope_key else "on this version"
    if table.summary["rated"] == 0 and _rating_dependent(table, spec):
        return _result(
            spec,
            "",
            [],
            0,
            0,
            drill,
            measure_key,
            [],
            "unavailable",
            f"No rated fund {where_text}: this question needs composite ranks.",
        )

    if spec.mode == "filter":
        found = select(table, spec.where)
        if spec.minGroupCount:
            eligible = {c.key for c in table.categories.values() if c.rated >= spec.minGroupCount}
            found = [e for e in found if e.category in eligible]
            numbers["groups"] = len(eligible)
            ctx["groups"] = fmt_count(len(eligible))
            ctx["min_group"] = spec.minGroupCount
        if spec.sort:
            found = sort_entities(table, found, spec.sort.measure, spec.sort.dir)
            drill.setdefault("sort", spec.sort.measure)
            drill.setdefault("dir", spec.sort.dir)
        count = len(found)
        show_spec = table.map.measure(measure_key) if measure_key else None
        for e in found[: spec.limit]:
            rows.append(_entity_row(table, e, spec, show_spec))
        drill.setdefault("keys", [e.key for e in found[:200]])
    elif spec.mode == "groupBy" and spec.groupBy:
        rows, count, gctx, gnumbers = _group_by(table, spec)
        ctx.update(gctx)
        numbers.update(gnumbers)
        considered = gnumbers.get("groups", 0)
        if considered < 2:
            dim = table.map.dimensions[spec.groupBy.dimension].label.lower()
            note = (
                f"No {dim} has {ctx['min_group']} or more rated funds {where_text}."
                if considered == 0
                else f"Only one {dim} has {ctx['min_group']} or more rated funds {where_text}: "
                "nothing to compare."
            )
            return _result(
                spec, "", rows, count, rated_total, drill, measure_key, [], "unavailable", note
            )
    elif spec.mode == "acrossVersions" and spec.across:
        if len(snapshots or []) < 2:
            note = (
                "Becomes available after a second genuine monthly upload; every activated "
                "version so far carries the same as-of date."
                if snapshots
                else "Becomes available once two activated versions with different as-of dates exist."
            )
            return _result(
                spec, "", [], 0, rated_total, drill, measure_key, [], "unavailable", note
            )
        rows, count, actx, anumbers = _across_versions(table, spec, snapshots or [])
        ctx.update(actx)
        numbers.update(anumbers)
    elif spec.mode == "aggregate" and spec.aggregate:
        found = select(table, spec.where)
        agg = table.map.measure(spec.aggregate.measure)
        vals = [(e, v) for e in found if (v := e.measures.get(spec.aggregate.measure)) is not None]
        total_sum = sum(v for _e, v in vals)
        count = len(vals)
        ctx["sum"] = fmt_measure(total_sum, agg)
        numbers["sum"] = total_sum
        vals.sort(key=lambda ev: -ev[1])
        for e, v in vals[: spec.limit]:
            rows.append(InsightRow(e.key, e.label, entity_sub(e), v, fmt_measure(v, agg)))
        drill.setdefault("keys", [e.key for e, _v in vals[:200]])

    ctx["count"] = fmt_count(count)
    numbers["count"] = count
    ctx["pct"] = f"{(100 * count / rated_total):.0f}%" if rated_total else None
    if rows:
        ctx["top"] = {
            "label": rows[0].label,
            "value": rows[0].value_label,
            "sub": rows[0].sub or "",
            "group": rows[0].extra.get("group") or "",
        }
    if measure_key and table.map.measure(measure_key):
        ctx["measure"] = {"label": table.map.measure(measure_key).label}  # type: ignore[union-attr]
    sentence = render_sentences(spec.sentences, ctx)
    status = "ok"
    note = None
    if sentence is None:
        if count == 0:
            status, note = "empty", f"No fund meets this test {where_text}."
        else:
            problems.append(
                "sentence could not be completed: an input is unavailable on this version"
            )
            status = "problem"
        sentence = ""
    out = _result(
        spec, sentence, rows, count, rated_total, drill, measure_key, problems, status, note
    )
    out.context = {k: v for k, v in ctx.items() if k != "_n"}
    out.numbers = dict(numbers)
    return out


def _rating_dependent(table: ResearchTable, spec: InsightSpec) -> bool:
    """Does the question presuppose composite ranks? True when a predicate other than
    ``isnull`` tests a rank or quartile measure (or the primary score), or the sort does."""
    primary_score = table.primary_key("score")
    keys = [p.measure for p in spec.where if p.measure and p.op != "isnull"]
    if spec.groupBy:
        keys += [p.measure for p in spec.groupBy.where if p.measure and p.op != "isnull"]
    if spec.across:
        keys += [p.measure for p in spec.across.where if p.measure and p.op != "isnull"]
    if spec.sort:
        keys.append(spec.sort.measure)
    for key in keys:
        m = table.map.measure(key)
        if m is not None and (m.role in ("rank", "quartile") or key == primary_score):
            return True
    return False


def _entity_row(
    table: ResearchTable, e: Entity, spec: InsightSpec, show_spec: MeasureSpec | None
) -> InsightRow:
    extra: dict[str, Any] = {p.measure: e.measures.get(p.measure) for p in spec.where if p.measure}
    extra["group"] = e.category
    if "quartile_pair" in spec.show and len(spec.where) >= 2:
        a, b = spec.where[0].measure, spec.where[1].measure
        va, vb = e.measures.get(a), e.measures.get(b)
        label = f"Q{int(va)} / Q{int(vb)}" if va is not None and vb is not None else "—"
        return InsightRow(e.key, e.label, entity_sub(e), None, label, extra)
    for item in spec.show:
        if item.startswith("measure:"):
            key = item.split(":", 1)[1]
            v = e.measures.get(key)
            return InsightRow(
                e.key, e.label, entity_sub(e), v, fmt_measure(v, table.map.measure(key)), extra
            )
    if show_spec is not None:
        v = e.measures.get(show_spec.key)
        return InsightRow(e.key, e.label, entity_sub(e), v, fmt_measure(v, show_spec), extra)
    first = spec.where[0].measure if spec.where else None
    if first:
        v = e.measures.get(first)
        return InsightRow(
            e.key, e.label, entity_sub(e), v, fmt_measure(v, table.map.measure(first)), extra
        )
    return InsightRow(e.key, e.label, entity_sub(e), None, "", extra)


_FRACTION = {0.25: "quarter", 0.5: "half", 0.1: "tenth", 0.2: "fifth", 1 / 3: "third"}
_SYMBOL = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "ne": "≠"}


def rule_text(table: ResearchTable, spec: InsightSpec) -> str | None:
    """The insight's test in the workbook's own terms: the column header the map resolved,
    the sheet and the column letter, so a reader can check it in Excel."""
    predicates = list(spec.where)
    if spec.groupBy is not None:
        predicates += spec.groupBy.where
    if spec.across is not None:
        predicates += spec.across.where
    parts: list[str] = []
    for p in predicates:
        if p.measure:
            ref = table.resolved.measures.get(p.measure)
            m = table.map.measure(p.measure)
            name = (ref.label if ref and ref.label else None) or (m.label if m else p.measure)
            where = f" ({ref.sheet}, column {ref.column})" if ref else ""
        elif p.dimension:
            ref = table.resolved.dimensions.get(p.dimension)
            d = table.map.dimensions.get(p.dimension)
            name = (ref.label if ref and ref.label else None) or (d.label if d else p.dimension)
            where = f" ({ref.sheet}, column {ref.column})" if ref else ""
        else:
            continue
        value = p.value
        if isinstance(value, str) and value.startswith("$"):
            value = value[1:].replace("_", " ")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        share = next(
            (w for f, w in _FRACTION.items() if abs(f - p.fraction) < 1e-9), f"{p.fraction:.0%}"
        )
        phrase = {
            "eq": f"{name} = {value}",
            "in": f"{name} is one of {', '.join(str(v) for v in value) if isinstance(value, list) else value}",
            "top": f"{name} in the best {share}",
            "bottom": f"{name} in the worst {share}",
            "notnull": f"{name} has a value",
            "isnull": f"{name} is blank or --",
        }.get(p.op) or f"{name} {_SYMBOL.get(p.op, p.op)} {value}"
        parts.append(phrase + where)
    return " and ".join(parts) or None


def group_values(table: ResearchTable, dimension: str, e: Entity) -> list[str]:
    """The group(s) an entity belongs to on a dimension; a ``split`` separator yields several."""
    v = e.dims.get(dimension)
    if not v:
        return []
    spec = table.map.dimensions.get(dimension)
    if spec is not None and spec.split and spec.attribute == "person":
        return spec.members(v)
    return [v]


def _group_by(table: ResearchTable, spec: InsightSpec):
    g = spec.groupBy
    assert g is not None
    base = select(table, spec.where) if spec.where else list(table.entities)
    groups: dict[str, list[Entity]] = {}
    for e in base:
        for v in group_values(table, g.dimension, e):
            groups.setdefault(v, []).append(e)
    threshold = spec.minGroupCount if spec.minGroupCount is not None else table.map.minGroupCount
    threshold = max(threshold, g.minMembers)
    scored: list[tuple[str, float, int, int]] = []  # label, value, count, total
    mspec = table.map.measure(g.measure) if g.measure else None
    considered = 0
    for label, members in groups.items():
        rated = [e for e in members if table.rated(e)]
        if len(rated) < threshold:
            continue
        considered += 1
        if g.aggregate in ("count_where", "hit_rate"):
            hits = [e for e in rated if all(matches(table, e, p) for p in g.where)]
            value = (
                len(hits)
                if g.aggregate == "count_where"
                else (len(hits) / len(rated) if rated else 0.0)
            )
            scored.append((label, float(value), len(hits), len(rated)))
        elif mspec is not None:
            vals = [v for e in rated if (v := e.measures.get(mspec.key)) is not None]
            if not vals:
                continue
            value = (sum(vals) / len(vals)) if g.aggregate == "mean" else (max(vals) - min(vals))
            scored.append((label, value, len(vals), len(rated)))
    scored.sort(key=lambda t: -t[1])
    rows: list[InsightRow] = []
    for label, value, cnt, total in scored[: spec.limit]:
        if g.aggregate == "count_where":
            vl = f"{cnt} / {total}"
        elif g.aggregate == "hit_rate":
            vl = f"{value * 100:.0f}% · {cnt} / {total}"
        else:
            vl = fmt_measure(value, mspec) + (
                " pts" if g.aggregate == "dispersion" and mspec and not mspec.unit else ""
            )
        rows.append(
            InsightRow(
                None,
                _joined(table, g.dimension, label),
                None,
                value,
                vl,
                {"count": cnt, "total": total, "raw": label},
            )
        )
    ctx: dict[str, Any] = {"groups": fmt_count(considered), "min_group": threshold}
    numbers: dict[str, Any] = {"groups": considered}
    if scored:
        top = scored[0]
        ctx["group"] = {
            "label": _phrase(table, g.dimension, top[0]),
            "value": rows[0].value_label if rows else top[1],
            "count": top[2],
            "total": top[3],
        }
        numbers["group.count"] = top[2]
        if g.aggregate == "count_where":
            best = max(scored, key=lambda t: t[2] / t[3])
            ctx["hit"] = {
                "label": _phrase(table, g.dimension, best[0]),
                "value": f"{100 * best[2] / best[3]:.0f}%",
                "count": best[2],
                "total": best[3],
            }
    return rows, len(scored), ctx, numbers


def _joined(table: ResearchTable, dimension: str, value: str) -> str:
    spec = table.map.dimensions.get(dimension)
    return spec.joined(value) if spec else value


def _phrase(table: ResearchTable, dimension: str, value: str) -> str:
    spec = table.map.dimensions.get(dimension)
    return spec.phrase(value) if spec else value


def _across_versions(table: ResearchTable, spec: InsightSpec, snapshots: list[Snapshot]):
    a = spec.across
    assert a is not None
    n_versions = len(snapshots)
    need = a.minVersions or n_versions
    tallies: dict[str, int] = {}
    for snap in snapshots:
        for key, row in snap.rows.items():
            if all(matches_snapshot(table, snap, row, p) for p in a.where):
                tallies[key] = tallies.get(key, 0) + 1
    current_ok = {e.key for e in table.entities if all(matches(table, e, p) for p in a.where)}
    held = [k for k, c in tallies.items() if c >= need and k in current_ok]
    rank_key = table.primary_key("rank")

    def order(k: str):
        e = table.by_key.get(k)
        r = e.measures.get(rank_key) if e and rank_key else None
        return (-(tallies[k]), r is None, r or 0)

    held.sort(key=order)
    rows = []
    for k in held[: spec.limit]:
        e = table.by_key[k]
        rows.append(
            InsightRow(k, e.label, entity_sub(e), tallies[k], f"{tallies[k]} / {n_versions}")
        )
    ctx = {"versions": n_versions, "total": fmt_count(len(current_ok))}
    numbers = {"versions": n_versions, "total": len(current_ok)}
    return rows, len(held), ctx, numbers


def compute_all(
    table: ResearchTable,
    snapshots: list[Snapshot] | None = None,
    section: str | None = None,
) -> list[ComputedInsight]:
    out = []
    for spec in table.map.insights:
        if section and spec.section != section:
            continue
        out.append(compute_insight(table, spec, snapshots))
    return out
