"""The global scope: one filter that every research view, sentence and export honours.

A scope is a small JSON object (``{"dims": {...}, "quartile": [...], "bands": {...},
"rated": "all|only|unrated", "q": "..."}``). ``apply_scope`` returns a ResearchTable derived from
the full one, so category statistics, the universe summary, insights and movement all describe
the same funds. Band boundaries always come from the full table, so "top corpus band" means the
same thing whatever else is selected."""

from __future__ import annotations

import json
import statistics
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.research.table import Entity, ResearchTable, assemble, register_cache

BAND_CODES = ("b1", "b2", "b3", "b4")


class Scope(BaseModel):
    dims: dict[str, str] = Field(default_factory=dict)
    quartile: list[int] = Field(default_factory=list)
    bands: dict[str, str] = Field(default_factory=dict)  # measure key -> b1..b4
    rated: Literal["all", "only", "unrated"] = "all"
    q: str | None = None

    @property
    def is_empty(self) -> bool:
        return (
            not self.dims
            and not self.quartile
            and not self.bands
            and self.rated == "all"
            and not self.q
        )

    def key(self) -> str:
        """Canonical JSON: the cache key and the value the frontend echoes back."""
        if self.is_empty:
            return ""
        body = {
            "dims": dict(sorted((k, v) for k, v in self.dims.items() if v)),
            "quartile": sorted(set(self.quartile)),
            "bands": dict(sorted((k, v) for k, v in self.bands.items() if v)),
            "rated": self.rated,
            "q": (self.q or "").strip() or None,
        }
        return json.dumps(body, separators=(",", ":"), sort_keys=True)


class ScopeError(ValueError):
    pass


def parse_scope(raw: str | None) -> Scope:
    if not raw or not raw.strip():
        return Scope()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ScopeError(f"scope is not valid JSON: {exc}") from exc
    try:
        return Scope.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ScopeError(f"scope.{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc


# ---- bands ------------------------------------------------------------------------------------


def band_bounds(table: ResearchTable, measure_key: str) -> list[float] | None:
    """Quartile boundaries of a measure over the full table's rated rows."""
    vals = table.sorted_values(measure_key)
    if len(vals) < 4:
        return None
    return statistics.quantiles(vals, n=4)


def band_of(value: float, q: list[float]) -> str:
    return BAND_CODES[0 if value <= q[0] else 1 if value <= q[1] else 2 if value <= q[2] else 3]


def band_labels(table: ResearchTable, measure_key: str) -> list[tuple[str, str]]:
    from app.research.insights import fmt_measure

    spec = table.map.measure(measure_key)
    q = band_bounds(table, measure_key)
    if q is None:
        return []
    return [
        ("b1", f"Up to {fmt_measure(q[0], spec)}"),
        ("b2", f"{fmt_measure(q[0], spec)} to {fmt_measure(q[1], spec)}"),
        ("b3", f"{fmt_measure(q[1], spec)} to {fmt_measure(q[2], spec)}"),
        ("b4", f"Above {fmt_measure(q[2], spec)}"),
    ]


# ---- applying ---------------------------------------------------------------------------------


def _matches(
    table: ResearchTable, e: Entity, scope: Scope, q_key: str | None, bounds: dict[str, list[float]]
) -> bool:
    for dkey, value in scope.dims.items():
        if value and e.dims.get(dkey) != value:
            return False
    qv = e.measures.get(q_key) if q_key else None
    if scope.rated == "only" and qv is None:
        return False
    if scope.rated == "unrated" and qv is not None:
        return False
    if scope.quartile and (qv is None or int(qv) not in scope.quartile):
        return False
    for mkey, code in scope.bands.items():
        if not code:
            continue
        v = e.measures.get(mkey)
        q = bounds.get(mkey)
        if v is None or q is None or band_of(v, q) != code:
            return False
    if scope.q:
        needle = scope.q.casefold().strip()
        hay = " ".join([e.label, e.key, *[v for v in e.dims.values() if v]]).casefold()
        if needle not in hay:
            return False
    return True


class _ScopeCache:
    def __init__(self, capacity: int = 24) -> None:
        self.capacity = capacity
        self._items: dict[tuple[str, str, str], ResearchTable] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str]) -> ResearchTable | None:
        with self._lock:
            hit = self._items.get(key)
            if hit is not None:
                self._items.pop(key)
                self._items[key] = hit
            return hit

    def put(self, key: tuple[str, str, str], table: ResearchTable) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = table
            while len(self._items) > self.capacity:
                self._items.pop(next(iter(self._items)))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


scope_cache = _ScopeCache()
register_cache(scope_cache)


def apply_scope(table: ResearchTable, scope: Scope) -> ResearchTable:
    """The table restricted to the scope, with its own category statistics and summary."""
    key = scope.key()
    if not key:
        return table
    cache_key = (table.version_id, table.run_id, key)
    hit = scope_cache.get(cache_key)
    if hit is not None:
        return hit
    q_key = table.primary_key("quartile")
    bounds = {m: b for m in scope.bands if (b := band_bounds(table, m)) is not None}
    entities = [e for e in table.entities if _matches(table, e, scope, q_key, bounds)]
    scoped = assemble(
        table.version_id,
        table.run_id,
        table.resolved,
        entities,
        table.stat_rows,
        table.constants,
        table.as_of,
        key,
    )
    scope_cache.put(cache_key, scoped)
    return scoped


# ---- describing and offering ------------------------------------------------------------------


def describe(table: ResearchTable, scope: Scope) -> list[str]:
    """Header pieces: 'All funds · every category · every AMC · both plans' or the selections."""
    rmap = table.map
    parts: list[str] = []
    parts.append(
        {"all": "All funds", "only": "Rated funds only", "unrated": "Unrated funds only"}[
            scope.rated
        ]
    )
    if scope.quartile:
        qs = sorted(set(scope.quartile))
        parts.append(
            "Q" + " and Q".join(str(q) for q in qs)
            if len(qs) <= 2
            else "Q" + "–Q".join((str(qs[0]), str(qs[-1])))
        )
    for dkey in rmap.dimensions:
        value = scope.dims.get(dkey)
        if value:
            parts.append(value)
        elif dkey == "category":
            parts.append("every category")
        elif dkey == "amc":
            parts.append("every AMC")
        elif dkey == "plan":
            parts.append("both plans")
    for mkey, code in scope.bands.items():
        if not code:
            continue
        spec = rmap.measure(mkey)
        label = dict(band_labels(table, mkey)).get(code, code)
        parts.append(f"{spec.label.lower() if spec else mkey} {label.lower()}")
    if scope.q:
        parts.append(f"matching “{scope.q.strip()}”")
    return parts


def options(table: ResearchTable) -> dict[str, Any]:
    """What the scope bar can offer: dimension values, band labels, quartiles, rating status."""
    rmap = table.map
    dims = []
    for dkey, spec in rmap.dimensions.items():
        if dkey not in table.resolved.dimensions:
            continue
        values = sorted({v for e in table.entities if (v := e.dims.get(dkey))})
        if len(values) > 400:  # a free-text column such as a team list is not a filter
            continue
        dims.append({"key": dkey, "label": spec.label, "values": values})
    bands = [
        {
            "key": m.key,
            "label": m.label,
            "options": [{"code": c, "label": lbl} for c, lbl in band_labels(table, m.key)],
        }
        for m in table.resolved.measure_specs()
        if m.role == "factor" and m.format != "date" and band_labels(table, m.key)
    ]
    return {
        "dims": dims,
        "bands": bands,
        "quartiles": [1, 2, 3, 4],
        "rated": ["all", "only", "unrated"],
    }
