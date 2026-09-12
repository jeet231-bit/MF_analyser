"""The research table: one row per entity with its dimensions, measures, phases and periods,
built from a run's values through the resolved semantic map, plus category statistics and the
universe summary. Cached per (version, run) like the engine's own caches."""

from __future__ import annotations

import math
import re
import statistics
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openpyxl.utils.datetime import to_excel
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.model.formula.refs import a1_cell
from app.research.semantic import ResearchMap, ResolvedMap, parse_map, resolve_map
from app.storage import logic, runs, workbooks
from app.storage import views as view_store
from app.storage.models import Run, WorkbookVersion


@dataclass
class Entity:
    key: str
    label: str
    row: int
    dims: dict[str, str | None] = field(default_factory=dict)
    measures: dict[str, float | None] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    phases: dict[str, float | None] = field(default_factory=dict)  # "group:COL" -> value
    periods: dict[str, float | None] = field(default_factory=dict)  # COL -> value
    cells: dict[str, str] = field(default_factory=dict)  # measure key -> "Sheet!A1"

    @property
    def category(self) -> str | None:
        return self.dims.get("category")


@dataclass
class CategoryInfo:
    key: str
    count: int = 0
    rated: int = 0  # entities with a primary quartile
    ranked: int = 0  # entities with a primary rank (the workbook's own "< N" test counts these)
    quartiles: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0})
    means: dict[str, float | None] = field(default_factory=dict)  # return measure -> mean
    spreads: dict[str, float | None] = field(default_factory=dict)  # return measure -> max-min
    stats: dict[str, float | None] = field(default_factory=dict)  # configured stats by column
    unranked: bool = False


@dataclass
class ResearchTable:
    version_id: str
    run_id: str
    resolved: ResolvedMap
    entities: list[Entity]
    by_key: dict[str, Entity]
    categories: dict[str, CategoryInfo]
    summary: dict[str, Any]
    quantiles: dict[str, tuple[float, float]] = field(default_factory=dict)  # measure -> (q1, q3)
    as_of: Any = None
    constants: dict[str, float | None] = field(default_factory=dict)  # declared constants, resolved
    _sorted: dict[str, list[float]] = field(default_factory=dict, repr=False)

    @property
    def map(self) -> ResearchMap:
        return self.resolved.map

    def primary_key(self, role: str) -> str | None:
        m = self.map.primary(role)  # type: ignore[arg-type]
        return m.key if m is not None and m.key in self.resolved.measures else None

    def rated(self, e: Entity) -> bool:
        q = self.primary_key("quartile")
        return q is not None and e.measures.get(q) is not None

    def sorted_values(self, key: str) -> list[float]:
        """Ascending values of a measure over rated entities (memoised)."""
        if key not in self._sorted:
            self._sorted[key] = sorted(
                v for e in self.entities if self.rated(e) and (v := e.measures.get(key)) is not None
            )
        return self._sorted[key]

    def quantile_bounds(self, key: str) -> tuple[float, float] | None:
        if key in self.quantiles:
            return self.quantiles[key]
        vals = self.sorted_values(key)
        if len(vals) < 4:
            return None
        q = statistics.quantiles(vals, n=4)
        self.quantiles[key] = (q[0], q[2])
        return self.quantiles[key]


def _number(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float) and math.isfinite(float(v)):
        return float(v)
    return None


def _text(v: Any) -> str | None:
    if isinstance(v, str):
        s = v.strip()
        return s or None
    if isinstance(v, int | float) and not isinstance(v, bool):
        return str(v)
    return None


class _SheetValues:
    """Values of one sheet for a run: computed formula values over the raw constants."""

    def __init__(self, session: Session, run: Run, sheet: str) -> None:
        self.idx = view_store.sheet_cache.get(session, run.version_id, sheet)
        self.computed = runs.formula_values(session, run, sheet)
        self._keys: dict[int, dict[str, int]] = {}

    def value(self, row: int, col: int) -> Any:
        addr = a1_cell(row, col)
        hit = self.computed.get(addr)
        if hit is not None:
            return hit[0]
        return self.idx.value(row, col)

    def key_rows(self, col: int) -> dict[str, int]:
        """Identity text -> row (first occurrence), for joins; case-insensitive fallback keys too."""
        if col not in self._keys:
            table: dict[str, int] = {}
            if self.idx.used is not None:
                for row in range(self.idx.used.r1, self.idx.used.r2 + 1):
                    t = _text(self.value(row, col))
                    if t is None:
                        continue
                    table.setdefault(t, row)
                    table.setdefault("\0" + t.casefold(), row)
            self._keys[col] = table
        return self._keys[col]

    def find(self, col: int, key: str) -> int | None:
        table = self.key_rows(col)
        return table.get(key) or table.get("\0" + key.casefold())


def build_table(
    session: Session, version: WorkbookVersion, run: Run, resolved: ResolvedMap
) -> ResearchTable:
    from openpyxl.utils import column_index_from_string as ci

    rmap = resolved.map
    ent = rmap.entity
    sheets: dict[str, _SheetValues] = {}

    def sv(name: str) -> _SheetValues:
        if name not in sheets:
            sheets[name] = _SheetValues(session, run, name)
        return sheets[name]

    esv = sv(ent.sheet)
    r1, r2 = resolved.entity_rows
    include = ent.includeWhen
    include_col = ci(include.column) if include else None
    universe = ent.universe
    universe_col = ci(universe.column) if universe else None
    inside: dict[str, bool] = {}
    entities: list[Entity] = []
    for row in range(r1, r2 + 1):
        key = _text(esv.value(row, resolved.entity_key_col))
        if key is None:
            continue
        if include is not None and include_col is not None:
            if _text(esv.value(row, include_col)) != _text(include.equals):
                continue
        label = (
            _text(esv.value(row, resolved.entity_label_col)) if resolved.entity_label_col else None
        )
        entities.append(Entity(key=key, label=label or key, row=row))
        if universe is not None and universe_col is not None:
            inside[key] = _text(esv.value(row, universe_col)) == _text(universe.equals)

    # Dimensions.
    for dkey, ref in resolved.dimensions.items():
        src = sv(ref.sheet)
        spec = rmap.dimensions[dkey]
        if ref.sheet == ent.sheet:
            for e in entities:
                e.dims[dkey] = _text(src.value(e.row, ref.col))
        else:
            kcol = ci(spec.keyColumn) if spec.keyColumn else resolved.entity_key_col
            for e in entities:
                row = src.find(kcol, e.key)
                e.dims[dkey] = _text(src.value(row, ref.col)) if row else None

    # Measures.
    for m in resolved.measure_specs():
        ref = resolved.measures[m.key]
        src = sv(ref.sheet)
        if ref.sheet == ent.sheet:
            rows = {e.key: e.row for e in entities}
        else:
            kcol = ci(m.keyColumn) if m.keyColumn else resolved.entity_key_col
            rows = {e.key: src.find(kcol, e.key) for e in entities}
        for e in entities:
            row = rows.get(e.key)
            if row is None:
                e.measures[m.key] = None
                e.raw[m.key] = None
                continue
            v = src.value(row, ref.col)
            e.measures[m.key] = _number(v)
            e.raw[m.key] = v
            e.cells[m.key] = f"{ref.sheet}!{a1_cell(row, ref.col)}"

    # Phases and periods.
    if rmap.phases and resolved.phases_ok:
        p = rmap.phases
        src = sv(p.sheet)
        kcol = ci(p.keyColumn)
        for e in entities:
            row = src.find(kcol, e.key) if p.sheet != ent.sheet else e.row
            for g in p.groups:
                for letter in g.columns:
                    e.phases[f"{g.key}:{letter.upper()}"] = (
                        _number(src.value(row, ci(letter))) if row else None
                    )
    if rmap.periods and resolved.periods_ok:
        p = rmap.periods
        src = sv(p.sheet)
        kcol = ci(p.keyColumn)
        for e in entities:
            row = src.find(kcol, e.key) if p.sheet != ent.sheet else e.row
            for letter in p.columns:
                e.periods[letter.upper()] = _number(src.value(row, ci(letter))) if row else None

    # Categories: configured stats, then derived stats.
    categories: dict[str, CategoryInfo] = {}
    if rmap.categoryStats and resolved.category_stats_ok:
        cs = rmap.categoryStats
        src = sv(cs.sheet)
        kcol = ci(cs.keyColumn)
        rows = cs.rows or ((src.idx.used.r1, src.idx.used.r2) if src.idx.used else (1, 0))
        for row in range(rows[0], rows[1] + 1):
            key = _text(src.value(row, kcol))
            if not key:
                continue
            info = categories.setdefault(key, CategoryInfo(key=key))
            for letter in cs.columns:
                info.stats[letter.upper()] = _number(src.value(row, ci(letter)))
    qkey = rmap.primary("quartile")
    qkey = qkey.key if qkey and qkey.key in resolved.measures else None
    rkey = rmap.primary("rank")
    rkey = rkey.key if rkey and rkey.key in resolved.measures else None
    return_keys = [m.key for m in resolved.measure_specs() if m.role == "return"]
    members: dict[str, list[Entity]] = {}
    for e in entities:
        cat = e.category
        if cat is None:
            continue
        members.setdefault(cat, []).append(e)
    for cat, group in members.items():
        info = categories.setdefault(cat, CategoryInfo(key=cat))
        info.count = len(group)
        for e in group:
            if rkey and e.measures.get(rkey) is not None:
                info.ranked += 1
            q = e.measures.get(qkey) if qkey else None
            if q is not None:
                info.rated += 1
                qi = int(q)
                if qi in info.quartiles:
                    info.quartiles[qi] += 1
        for rk in return_keys:
            vals = [v for e in group if (v := e.measures.get(rk)) is not None]
            info.means[rk] = (sum(vals) / len(vals)) if vals else None
            info.spreads[rk] = (max(vals) - min(vals)) if len(vals) >= 2 else None
        # The workbook's rule: fewer than N ranked funds in the category means no quartiles.
        info.unranked = (info.ranked if rkey else info.count) < rmap.quartileRule.unrankedBelow

    rated = [e for e in entities if qkey and e.measures.get(qkey) is not None]
    dist = {q: 0 for q in (1, 2, 3, 4)}
    for e in rated:
        qi = int(e.measures[qkey])  # type: ignore[index]
        if qi in dist:
            dist[qi] += 1
    # Why the rest are unrated: a category too small for the workbook's rule, or missing data.
    small = {c.key for c in categories.values() if c.count and c.unranked}
    # The unrated set partitions into: outside the universe flag; a missing composite (score
    # "--", whatever the category size), which coverage splits further; and, for the rest, a
    # category too small for the workbook's quartile rule.
    skey = rmap.primary("score")
    skey = skey.key if skey and skey.key in resolved.measures else None
    unrated = [e for e in entities if not qkey or e.measures.get(qkey) is None]
    outside = [e for e in unrated if universe is not None and not inside.get(e.key, False)]
    outside_keys = {e.key for e in outside}
    composite_missing = [
        e
        for e in unrated
        if e.key not in outside_keys and e.measures.get(skey if skey else (qkey or "")) is None
    ]
    missing_keys = {e.key for e in composite_missing}
    unrated_small = sum(
        1
        for e in unrated
        if e.category in small and e.key not in outside_keys and e.key not in missing_keys
    )
    unrated_other = len(composite_missing)
    primary_keys = [k for k in (rmap.primary(r) for r in ("score", "rank", "quartile")) if k]
    complete = sum(
        1
        for e in entities
        if all(
            e.measures.get(m.key) is not None for m in primary_keys if m.key in resolved.measures
        )
        and all(e.measures.get(k) is not None for k in return_keys)
    )
    constants: dict[str, float | None] = {}
    for name, (sheet_name, r, c) in resolved.constant_cells.items():
        try:
            constants[name] = parse_constant(sv(sheet_name).value(r, c), rmap.constants[name].parse)
        except Exception:  # noqa: BLE001 - a broken constant reads as unavailable
            constants[name] = None
    # Coverage: why the "--" funds are unrated (too young, or a data gap).
    unrated_young = unrated_gap = unrated_unknown = 0
    cov = rmap.coverage
    if cov and cov.measure in resolved.measures and constants.get(cov.constant) is not None:
        since = constants[cov.constant]
        for e in composite_missing:
            inception = e.measures.get(cov.measure)
            if inception is None:
                unrated_unknown += 1
            elif inception >= since:  # type: ignore[operator]
                unrated_young += 1
            else:
                unrated_gap += 1
    as_of = None
    if ent.asOf and "!" in ent.asOf:
        sheet_name, addr = ent.asOf.rsplit("!", 1)
        try:
            from app.model.formula.refs import parse_a1_cell

            r, c = parse_a1_cell(addr)
            as_of = sv(sheet_name.strip("'")).value(r, c)
        except Exception:  # noqa: BLE001 - as-of is decorative
            as_of = None

    table = ResearchTable(
        version_id=version.id,
        run_id=run.id,
        resolved=resolved,
        entities=entities,
        by_key={e.key: e for e in entities},
        categories=categories,
        summary={
            "total": len(entities),
            "rated": len(rated),
            "complete": complete,
            "quartiles": dist,
            "categories": len(members),
            "unranked_categories": len(small),
            "unrated_small_categories": unrated_small,
            "unrated_missing_data": unrated_other,
            "outside_universe": len(outside),
            "unrated_young": unrated_young,
            "unrated_gap": unrated_gap,
            "unrated_unknown": unrated_unknown,
            "stats_only_categories": sum(1 for c in categories.values() if c.count == 0),
        },
        as_of=as_of,
        constants=constants,
    )
    return table


_DATE_TOKEN = re.compile(r"\b(\d{1,2})[ -]([A-Za-z]{3,9})[ -](\d{4})\b")


def parse_constant(value: Any, parse: str) -> float | None:
    """A constant read from a cell: a number as is, or the first / last 'dd Mon yyyy' date in a
    text such as '11 Feb 2016 To 28 Aug 2018', returned as an Excel serial."""
    if parse == "number":
        return _number(value)
    if not isinstance(value, str):
        return _number(value)
    hits = _DATE_TOKEN.findall(value)
    if not hits:
        return None
    d, mon, y = hits[0] if parse == "firstDate" else hits[-1]
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return float(to_excel(datetime.strptime(f"{d} {mon} {y}", fmt)))
        except ValueError:
            continue
    return None


# ---- cache and access ---------------------------------------------------------------------


class _TableCache:
    def __init__(self, capacity: int = 6) -> None:
        self.capacity = capacity
        self._items: dict[tuple[str, str], ResearchTable] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> ResearchTable | None:
        with self._lock:
            item = self._items.get(key)
            if item is not None:
                self._items.pop(key)
                self._items[key] = item
            return item

    def put(self, key: tuple[str, str], table: ResearchTable) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = table
            while len(self._items) > self.capacity:
                self._items.pop(next(iter(self._items)))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


table_cache = _TableCache()
_build_lock = threading.Lock()


class NotConfigured(Exception):  # noqa: N818 - read as a state, not an error
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def resolve_for_version(session: Session, version_id: str) -> ResolvedMap:
    """Parse the config's research section and resolve it against one version's model."""
    cfg = load_dashboard_config()
    rmap, problems = parse_map(cfg.research)
    if rmap is None:
        raise NotConfigured(problems)
    try:
        model = logic.get_model(session, version_id)
    except logic.ModelNotFoundError as exc:
        raise NotConfigured([f"version {version_id[:8]} has no logic model yet"]) from exc

    def sheet_index(name: str):
        return view_store.sheet_cache.get(session, version_id, name)

    resolved = resolve_map(rmap, model, sheet_index)
    if isinstance(resolved, list):
        raise NotConfigured(problems + resolved)
    resolved.problems = problems + resolved.problems
    return resolved


def get_table(session: Session, version: WorkbookVersion, run: Run) -> ResearchTable:
    key = (version.id, run.id)
    hit = table_cache.get(key)
    if hit is not None:
        return hit
    with _build_lock:
        hit = table_cache.get(key)
        if hit is not None:
            return hit
        resolved = resolve_for_version(session, version.id)
        table = build_table(session, version, run, resolved)
        table_cache.put(key, table)
        return table


def baseline_tables(session: Session) -> list[tuple[WorkbookVersion, Run, ResearchTable]]:
    """Every stored version that has a logic model and a baseline run, oldest first, with its
    table; versions whose map does not resolve are skipped (they are reported by /config)."""
    out = []
    for version in sorted(workbooks.list_versions(session), key=lambda v: v.uploaded_at):
        run = runs.baseline_run(session, version.id)
        if run is None:
            continue
        try:
            out.append((version, run, get_table(session, version, run)))
        except NotConfigured:
            continue
    return out
