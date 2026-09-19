"""Cross-tabs over the joined research table, with the change since the previous month.

One question shape answers most of them: *show <measure> by <dimension>, against last
month*. Every fund in scope is grouped by one dimension (or by a factor's band), each group
is summarised, and the same grouping of the previous genuine version is matched against it,
so every number carries its own change.

This is the part the workbook cannot do. Its pivots read one flat sheet and know only the
month they were last refreshed in; this reads the joined table (rank, quartile, returns,
bull and bear, cost, corpus, all per fund) and compares two months.

Two traps of the workbook's own rules are handled here, not left to the reader:

* Ranks and quartiles are computed **within each category**. A grouping made of whole
  categories (the category itself, the plan, the sub-nature) therefore splits into four
  equal quartiles by construction; the view says so (``quartilesByConstruction``) instead of
  presenting 25 % as a finding.
* A raw rank depends on the size of its category (5th of 8 is not 5th of 200), so a group's
  rank is reported as its **median position**, the rank divided by the ranked funds in the
  fund's own category: 0.2 reads "top 20 %" in any category.
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
SORTS = ("value", "q1_share", "funds", "rated", "median_position", "change", "label")
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
    median_position: float | None = None  # rank / ranked funds in the fund's own category

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


def nests_categories(table: ResearchTable, groups: dict[str, list[Entity]]) -> bool:
    """True when every rated fund's category sits wholly inside one group. Quartiles are cut
    within categories, so such a grouping splits into four equal parts by construction."""
    owner: dict[str, str] = {}
    seen = False
    for label, rows in groups.items():
        for e in rows:
            if not table.rated(e) or e.category is None:
                continue
            seen = True
            if owner.setdefault(e.category, label) != label:
                return False
    return seen


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


def position_of(table: ResearchTable, e: Entity) -> float | None:
    """A rated fund's rank as a share of the ranked funds in its own category (0.2 = top 20 %)."""
    rank_key = table.primary_key("rank")
    if rank_key is None or not table.rated(e) or e.category is None:
        return None
    rank = e.measures.get(rank_key)
    info = table.categories.get(e.category)
    if rank is None or info is None or info.ranked <= 0:
        return None
    return rank / info.ranked


def summarise(
    table: ResearchTable, key: str, rows: list[Entity], measure_key: str, agg: str
) -> GroupSummary:
    q_key = table.primary_key("quartile")
    out = GroupSummary(key=key, label=key, funds=len(rows))
    values: list[float] = []
    positions: list[float] = []
    for e in rows:
        if q_key is not None and (q := e.measures.get(q_key)) is not None:
            out.rated += 1
            if int(q) in out.quartiles:
                out.quartiles[int(q)] += 1
        if (v := e.measures.get(measure_key)) is not None:
            values.append(v)
        if (p := position_of(table, e)) is not None:
            positions.append(p)
    out.value = _aggregate(agg, values)
    out.median_position = statistics.median(positions) if positions else None
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


def _sort_raw(row: dict[str, Any], sort: str) -> float | None:
    return {
        "value": row["value"],
        "q1_share": row["q1Share"],
        "funds": float(row["funds"]),
        "rated": float(row["rated"]),
        "median_position": row["medianPosition"],
        "change": (row["delta"] or {}).get("value"),
    }[sort]


def _row(
    key: str, s: GroupSummary, was: GroupSummary | None, compared: bool, min_group: int
) -> dict[str, Any]:
    delta: dict[str, Any] | None = None
    if compared:
        delta = {
            "funds": s.funds - was.funds if was else None,
            "rated": s.rated - was.rated if was else None,
            "q1": s.quartiles[1] - was.quartiles[1] if was else None,
            "q1Share": _delta(s.q1_share, was.q1_share) if was else None,
            "value": _delta(s.value, was.value) if was else None,
            "medianPosition": _delta(s.median_position, was.median_position) if was else None,
            "new": was is None,
        }
    return {
        "key": key,
        "label": s.label,
        "funds": s.funds,
        "rated": s.rated,
        "quartiles": {str(q): n for q, n in s.quartiles.items()},
        "q1Share": s.q1_share,
        "value": s.value,
        "medianPosition": s.median_position,
        "small": s.rated < min_group,
        "delta": delta,
    }


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
    by_construction = nests_categories(table, groups)
    summaries = {k: summarise(table, k, rows, spec.key, agg) for k, rows in groups.items()}
    before: dict[str, GroupSummary] = {}
    if previous is not None:
        prev_groups = group_entities(previous, by_key, kind)
        before = {k: summarise(previous, k, rows, spec.key, agg) for k, rows in prev_groups.items()}
    rows = [
        _row(k, s, before.get(k), previous is not None, min_group) for k, s in summaries.items()
    ]

    # A quartile share means nothing when it is 25 % by construction, so it never leads there.
    sort_key = sort or ("q1_share" if spec.role == "quartile" and not by_construction else "value")
    if direction is None:
        lower_first = (sort_key in ("value", "change") and not spec.higherIsBetter) or sort_key in (
            "median_position",
            "label",
        )
        direction = "asc" if lower_first else "desc"
    reverse = direction == "desc"
    # Listed, never ranked: groups below the minimum sit after every eligible group, and a
    # missing value sits last within its tier, whichever direction was asked for.
    ranked = [r for r in rows if not r["small"]]
    few = [r for r in rows if r["small"]]

    def ordered(tier: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if sort_key == "label":
            return sorted(tier, key=lambda r: r["label"].casefold(), reverse=reverse)
        present = [r for r in tier if _sort_raw(r, sort_key) is not None]
        missing = [r for r in tier if _sort_raw(r, sort_key) is None]
        present.sort(key=lambda r: r["label"].casefold())
        present.sort(key=lambda r: _sort_raw(r, sort_key), reverse=reverse)
        return present + sorted(missing, key=lambda r: r["label"].casefold())

    rows = ordered(ranked) + ordered(few)

    total = summarise(table, "", table.entities, spec.key, agg)
    total_was = (
        summarise(previous, "", previous.entities, spec.key, agg) if previous is not None else None
    )
    totals = _row("", total, total_was, previous is not None, 0)
    for key in ("key", "label", "small"):
        totals.pop(key)
    if totals["delta"] is not None:
        totals["delta"]["new"] = False

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
        "quartilesByConstruction": by_construction,
        "groups": shown,
        "groupCount": len(rows),
        "smallCount": len(few),
        "totals": totals,
        "facts": _facts(rows, by_label, spec, min_group, previous is not None, by_construction),
    }


def _facts(
    rows: list[dict[str, Any]],
    by_label: str,
    spec: MeasureSpec,
    min_group: int,
    compared: bool,
    by_construction: bool,
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
        if not by_construction:  # "most Q1 funds" is only a size contest when quartiles are equal
            top = max(eligible, key=lambda r: (r["q1Share"] or 0, r["rated"]))
            facts.update(
                {"top": top["label"], "top_q1": top["quartiles"]["1"], "top_rated": top["rated"]}
            )
        valued = [r for r in eligible if r["value"] is not None]
        # Averaged within-category ranks and quartiles are also equal by construction there.
        if by_construction and spec.role in ("rank", "quartile"):
            valued = []
        if valued:
            best = (max if spec.higherIsBetter else min)(valued, key=lambda r: r["value"])
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
