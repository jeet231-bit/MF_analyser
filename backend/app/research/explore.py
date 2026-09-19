"""Cross-tabs over the joined research table, with the change since the previous month.

One question shape answers most of them: *show <measure> by <dimension>, against last
month*. Every fund in scope is grouped by one dimension (or by a factor's band), each group
is summarised, and the same grouping of the previous genuine version is matched against it,
so every number carries its own change.

This is the part the workbook cannot do. Its pivots read one flat sheet and know only the
month they were last refreshed in; this reads the joined table (rank, quartile, returns,
bull and bear, cost, corpus, all per fund) and compares two months.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.research.insights import group_values
from app.research.scope import band_bounds, band_labels, band_of
from app.research.semantic import MeasureSpec
from app.research.table import Entity, ResearchTable

AGGREGATIONS = ("mean", "median", "sum", "min", "max")
SORTS = ("value", "q1_share", "funds", "rated", "median_rank", "change", "label")
BAND_SUFFIX = "_band"
DEFAULT_LIMIT = 15


class ExploreError(ValueError):
    pass


@dataclass
class GroupSummary:
    key: str
    label: str
    funds: int = 0
    rated: int = 0
    quartiles: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0})
    value: float | None = None
    median_rank: float | None = None

    @property
    def q1_share(self) -> float | None:
        return self.quartiles[1] / self.rated if self.rated else None


# ---- what can be grouped by, and what can be measured ----------------------------------------


def by_options(table: ResearchTable) -> list[dict[str, Any]]:
    """Everything a fund can be grouped by: the map's dimensions, then the factor bands."""
    out: list[dict[str, Any]] = []
    for key, spec in table.map.dimensions.items():
        if key not in table.resolved.dimensions:
            continue
        distinct = len({v for e in table.entities if (v := e.dims.get(key))})
        if distinct > 400:  # free text (a team list), not a grouping
            continue
        out.append({"key": key, "label": spec.label, "kind": "dimension", "groups": distinct})
    for m in table.resolved.measure_specs():
        if m.role != "factor" or m.format == "date":
            continue
        labels = band_labels(table, m.key)
        if labels:
            out.append(
                {
                    "key": m.key + BAND_SUFFIX,
                    "label": f"{m.label} band",
                    "kind": "band",
                    "groups": len(labels),
                }
            )
    return out


def measure_options(table: ResearchTable) -> list[dict[str, Any]]:
    return [
        {
            "key": m.key,
            "label": m.label,
            "role": m.role,
            "format": m.format,
            "unit": m.unit,
            "higherIsBetter": m.higherIsBetter,
            "primary": m.primary,
        }
        for m in table.resolved.measure_specs()
        if m.format != "date"
    ]


def resolve_by(table: ResearchTable, by: str | None) -> tuple[str, str, str]:
    """(key, label, kind) for the grouping, defaulting to the first dimension offered."""
    options = by_options(table)
    if not options:
        raise ExploreError("this workbook's map declares nothing to group by")
    chosen = next((o for o in options if o["key"] == by), options[0])
    return chosen["key"], chosen["label"], chosen["kind"]


def resolve_measure(table: ResearchTable, key: str | None) -> MeasureSpec:
    specs = [m for m in table.resolved.measure_specs() if m.format != "date"]
    if not specs:
        raise ExploreError("this workbook's map declares no measure to summarise")
    hit = next((m for m in specs if m.key == key), None)
    if hit is not None:
        return hit
    primary = table.primary_key("score") or table.primary_key("rank")
    return next((m for m in specs if m.key == primary), specs[0])


# ---- grouping ---------------------------------------------------------------------------------


def group_labels_of(
    table: ResearchTable,
    e: Entity,
    by: str,
    kind: str,
    bounds: list[float] | None,
    band_map: dict[str, str],
) -> list[str]:
    """The groups one fund belongs to. A dimension that splits into people puts the fund in
    each person's group; a team dimension keeps the team as one group (the map decides)."""
    if kind == "band":
        measure = by[: -len(BAND_SUFFIX)]
        v = e.measures.get(measure)
        if v is None or bounds is None:
            return []
        code = band_of(v, bounds)
        return [band_map.get(code, code)]
    return group_values(table, by, e)  # the same split rule the insight engine uses


def group_entities(table: ResearchTable, by: str, kind: str) -> dict[str, list[Entity]]:
    bounds = None
    band_map: dict[str, str] = {}
    if kind == "band":
        measure = by[: -len(BAND_SUFFIX)]
        bounds = band_bounds(table, measure)
        band_map = dict(band_labels(table, measure))
    groups: dict[str, list[Entity]] = {}
    for e in table.entities:
        for label in group_labels_of(table, e, by, kind, bounds, band_map):
            groups.setdefault(label, []).append(e)
    return groups


def _aggregate(agg: str, values: list[float]) -> float | None:
    if not values:
        return None
    if agg == "mean":
        return statistics.fmean(values)
    if agg == "median":
        return statistics.median(values)
    if agg == "sum":
        total = 0.0
        for v in values:  # one double at a time, as the engine and Excel add
            total += v
        return total
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    raise ExploreError(f"unsupported aggregation {agg!r}")


def summarise(
    table: ResearchTable, key: str, rows: list[Entity], measure_key: str, agg: str
) -> GroupSummary:
    q_key = table.primary_key("quartile")
    rank_key = table.primary_key("rank")
    out = GroupSummary(key=key, label=key, funds=len(rows))
    values: list[float] = []
    ranks: list[float] = []
    for e in rows:
        if q_key is not None and (q := e.measures.get(q_key)) is not None:
            out.rated += 1
            if int(q) in out.quartiles:
                out.quartiles[int(q)] += 1
        if (v := e.measures.get(measure_key)) is not None:
            values.append(v)
        if rank_key is not None and (r := e.measures.get(rank_key)) is not None:
            ranks.append(r)
    out.value = _aggregate(agg, values)
    out.median_rank = statistics.median(ranks) if ranks else None
    return out


# ---- the view ---------------------------------------------------------------------------------


def display_decimals(spec: MeasureSpec, agg: str) -> int | None:
    integerish = spec.format == "integer" or spec.role in ("rank", "quartile")
    if agg in ("mean", "median") and integerish:
        return 1
    return spec.decimals


def _delta(now: float | None, then: float | None) -> float | None:
    if now is None or then is None:
        return None
    return now - then


def _sort_value(row: dict[str, Any], sort: str, higher_is_better: bool) -> tuple[int, float]:
    """Missing values always sort last, whichever direction the caller asked for."""
    raw = {
        "value": row["value"],
        "q1_share": row["q1Share"],
        "funds": float(row["funds"]),
        "rated": float(row["rated"]),
        "median_rank": row["medianRank"],
        "change": (row["delta"] or {}).get("value"),
        "label": None,
    }[sort]
    if sort == "label":
        return (0, 0.0)
    if raw is None:
        return (1, 0.0)
    del higher_is_better
    return (0, float(raw))


def explore(
    table: ResearchTable,
    previous: ResearchTable | None,
    *,
    by: str | None = None,
    measure: str | None = None,
    agg: str = "mean",
    sort: str | None = None,
    direction: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if agg not in AGGREGATIONS:
        raise ExploreError(f"unsupported aggregation {agg!r}")
    if sort is not None and sort not in SORTS:
        raise ExploreError(f"cannot sort by {sort!r}")
    by_key, by_label, kind = resolve_by(table, by)
    spec = resolve_measure(table, measure)
    min_group = table.map.minGroupCount

    groups = group_entities(table, by_key, kind)
    summaries = {k: summarise(table, k, rows, spec.key, agg) for k, rows in groups.items()}
    before: dict[str, GroupSummary] = {}
    if previous is not None:
        prev_groups = group_entities(previous, by_key, kind)
        before = {k: summarise(previous, k, rows, spec.key, agg) for k, rows in prev_groups.items()}

    rows: list[dict[str, Any]] = []
    for key, s in summaries.items():
        was = before.get(key)
        delta: dict[str, Any] | None = None
        if previous is not None:
            delta = {
                "funds": s.funds - was.funds if was else None,
                "rated": s.rated - was.rated if was else None,
                "q1": s.quartiles[1] - was.quartiles[1] if was else None,
                "q1Share": _delta(s.q1_share, was.q1_share) if was else None,
                "value": _delta(s.value, was.value) if was else None,
                "medianRank": _delta(s.median_rank, was.median_rank) if was else None,
                "new": was is None,
            }
        rows.append(
            {
                "key": key,
                "label": s.label,
                "funds": s.funds,
                "rated": s.rated,
                "quartiles": {str(q): n for q, n in s.quartiles.items()},
                "q1Share": s.q1_share,
                "value": s.value,
                "medianRank": s.median_rank,
                "small": s.rated < min_group,
                "delta": delta,
            }
        )

    sort_key = sort or ("q1_share" if spec.role == "quartile" else "value")
    if direction is None:
        direction = (
            "asc"
            if (sort_key in ("value", "change") and not spec.higherIsBetter)
            or sort_key in ("median_rank", "label")
            else "desc"
        )
    reverse = direction == "desc"
    if sort_key == "label":
        rows.sort(key=lambda r: r["label"].casefold(), reverse=reverse)
    else:
        rows.sort(
            key=lambda r: (_sort_value(r, sort_key, spec.higherIsBetter), r["label"].casefold())
        )
        present = [r for r in rows if _sort_value(r, sort_key, spec.higherIsBetter)[0] == 0]
        missing = [r for r in rows if _sort_value(r, sort_key, spec.higherIsBetter)[0] == 1]
        present.sort(
            key=lambda r: _sort_value(r, sort_key, spec.higherIsBetter)[1], reverse=reverse
        )
        rows = present + missing

    total = summarise(table, "", table.entities, spec.key, agg)
    total_was = (
        summarise(previous, "", previous.entities, spec.key, agg) if previous is not None else None
    )
    totals = {
        "funds": total.funds,
        "rated": total.rated,
        "quartiles": {str(q): n for q, n in total.quartiles.items()},
        "q1Share": total.q1_share,
        "value": total.value,
        "medianRank": total.median_rank,
        "delta": None
        if total_was is None
        else {
            "funds": total.funds - total_was.funds,
            "rated": total.rated - total_was.rated,
            "q1": total.quartiles[1] - total_was.quartiles[1],
            "q1Share": _delta(total.q1_share, total_was.q1_share),
            "value": _delta(total.value, total_was.value),
            "medianRank": _delta(total.median_rank, total_was.median_rank),
            "new": False,
        },
    }

    shown = rows if limit <= 0 else rows[:limit]
    return {
        "by": {"key": by_key, "label": by_label, "kind": kind},
        "measure": {
            "key": spec.key,
            "label": spec.label,
            "role": spec.role,
            "format": spec.format,
            "unit": spec.unit,
            "higherIsBetter": spec.higherIsBetter,
            # The average of a rank is not a rank: show it with a decimal so "9.7" does not
            # read as "10" and lose the thing that makes two houses different.
            "decimals": display_decimals(spec, agg),
        },
        "agg": agg,
        "sort": sort_key,
        "dir": direction,
        "limit": limit,
        "minGroupCount": min_group,
        "groups": shown,
        "groupCount": len(rows),
        "totals": totals,
        "facts": _facts(rows, by_label, spec, min_group, previous is not None),
    }


def _facts(
    rows: list[dict[str, Any]], by_label: str, spec: MeasureSpec, min_group: int, compared: bool
) -> dict[str, Any]:
    """Raw numbers the narrative sentences read; formatting happens in the API layer."""
    eligible = [r for r in rows if not r["small"] and r["rated"] > 0]
    facts: dict[str, Any] = {
        "dimension": by_label,
        "measure": spec.label,
        "groups": len(rows),
        "eligible": len(eligible),
        "min_group": min_group,
    }
    if eligible:
        top = max(eligible, key=lambda r: (r["quartiles"]["1"], r["rated"]))
        facts.update(
            {"top": top["label"], "top_q1": top["quartiles"]["1"], "top_rated": top["rated"]}
        )
        ranked = [r for r in eligible if r["value"] is not None]
        if ranked:
            best = (max if spec.higherIsBetter else min)(ranked, key=lambda r: r["value"])
            facts.update({"best": best["label"], "best_value": best["value"]})
    if compared:
        moved = [r for r in eligible if (r["delta"] or {}).get("value") is not None]
        if moved:
            better = (max if spec.higherIsBetter else min)(moved, key=lambda r: r["delta"]["value"])
            worse = (min if spec.higherIsBetter else max)(moved, key=lambda r: r["delta"]["value"])
            if better["label"] != worse["label"]:
                facts.update(
                    {
                        "riser": better["label"],
                        "riser_delta": abs(better["delta"]["value"]),
                        "faller": worse["label"],
                        "faller_delta": abs(worse["delta"]["value"]),
                    }
                )
    return facts
