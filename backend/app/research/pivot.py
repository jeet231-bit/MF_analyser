"""The pivot engine: recompute a workbook pivot from the engine's values.

A ``PivotFrame`` is the pivot's source range read column by column for one run (computed
formula values over the raw constants, so a what-if changes the pivot); a ``PivotQuery``
is any layout over its fields: filters, row fields, column fields and values with their
aggregation. Excel's own layout is just the default query. Nothing here knows a sheet or a
field name; they all come from the workbook's pivot definition.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.model.formula.refs import Rect
from app.parser.models import PivotSpec, PivotValue
from app.parser.pivots import is_a1_range
from app.research.table import _SheetValues
from app.storage.models import Run, WorkbookVersion

AGGREGATIONS = ("sum", "count", "average", "max", "min", "countNums", "product", "stdDev", "var")
BLANK = "(blank)"
TOTAL = "Total"


class PivotError(ValueError):
    pass


class PivotQuery(BaseModel):
    filters: dict[str, list[str]] = Field(default_factory=dict)
    rows: list[str] = Field(default_factory=list)
    cols: list[str] = Field(default_factory=list)
    values: list[PivotValue] = Field(default_factory=list)

    @classmethod
    def default_for(cls, spec: PivotSpec) -> PivotQuery:
        """Excel's saved layout: its filters, rows, columns and values."""
        return cls(
            filters=dict(spec.saved_filters),
            rows=list(spec.rows),
            cols=list(spec.cols),
            values=list(spec.values),
        )


@dataclass
class PivotFrame:
    spec: PivotSpec
    fields: list[str]
    columns: list[list[Any]]  # per field, one entry per record (float | str | None)
    live: bool  # computed from the engine (source sheet in scope) or read from cached values
    _options: dict[str, list[str]] = field(default_factory=dict)

    @property
    def records(self) -> int:
        return len(self.columns[0]) if self.columns else 0

    def column(self, name: str) -> list[Any]:
        try:
            return self.columns[self.fields.index(name)]
        except ValueError as exc:
            raise PivotError(f"unknown pivot field {name!r}") from exc

    def options(self, name: str) -> list[str]:
        """Distinct display values of a field, sorted the way Excel sorts row labels."""
        if name not in self._options:
            seen = {display(v) for v in self.column(name)}
            self._options[name] = sorted(seen, key=sort_key)
        return self._options[name]


def display(v: Any) -> str:
    if v is None:
        return BLANK
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}"
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    return s or BLANK


def sort_key(text: str) -> tuple[int, float, str]:
    if text == BLANK:
        return (2, 0.0, "")
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, text.casefold())


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int | float):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("#"):  # an Excel error text
            return None
        return s or None
    return str(v)


def load_frame(
    session: Session, version: WorkbookVersion, run: Run, spec: PivotSpec, live: bool
) -> PivotFrame:
    if not is_a1_range(spec.source_ref):
        raise PivotError(
            f"the pivot on '{spec.sheet}' reads a named source ({spec.source_ref or 'unknown'}); only A1 ranges are supported"
        )
    rect = Rect.from_a1(spec.source_ref)
    values = _SheetValues(session, run, spec.source_sheet)
    width = rect.c2 - rect.c1 + 1
    names = [f.name for f in spec.fields][:width]
    if len(names) < width:  # more columns than cache fields: name the rest by header
        for c in range(rect.c1 + len(names), rect.c2 + 1):
            header = values.value(rect.r1, c)
            names.append(display(header) if header is not None else f"Column {c}")
    columns: list[list[Any]] = [[] for _ in names]
    for r in range(rect.r1 + 1, rect.r2 + 1):
        for i in range(len(names)):
            columns[i].append(_cell(values.value(r, rect.c1 + i)))
    return PivotFrame(spec=spec, fields=names, columns=columns, live=live)


class _FrameCache:
    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self._items: OrderedDict[tuple[str, str, str], PivotFrame] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str], build: Any) -> PivotFrame:
        with self._lock:
            hit = self._items.get(key)
            if hit is not None:
                self._items.move_to_end(key)
                return hit
            frame = build()
            self._items[key] = frame
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)
            return frame

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


frame_cache = _FrameCache()


# ---- aggregation ---------------------------------------------------------------------------


def aggregate(agg: str, cells: list[Any]) -> float | None:
    nums = [v for v in cells if isinstance(v, float)]
    if agg == "count":
        return float(sum(1 for v in cells if v is not None))
    if agg == "countNums":
        return float(len(nums))
    if not nums:
        return None
    if agg == "sum":
        return _excel_sum(nums)
    if agg == "average":
        return _excel_sum(nums) / len(nums)
    if agg == "max":
        return max(nums)
    if agg == "min":
        return min(nums)
    if agg == "product":
        out = 1.0
        for v in nums:
            out *= v
        return out
    if agg == "stdDev":
        return statistics.stdev(nums) if len(nums) > 1 else None
    if agg == "var":
        return statistics.variance(nums) if len(nums) > 1 else None
    raise PivotError(f"unsupported aggregation {agg!r}")


def _excel_sum(nums: list[float]) -> float:
    total = 0.0
    for v in nums:  # one double at a time, as Excel adds
        total += v
    return total


# ---- compute ---------------------------------------------------------------------------------


def compute(frame: PivotFrame, query: PivotQuery) -> dict[str, Any]:
    for name in list(query.filters) + query.rows + query.cols + [v.field for v in query.values]:
        if name not in frame.fields:
            raise PivotError(f"unknown pivot field {name!r}")
    for v in query.values:
        if v.agg not in AGGREGATIONS:
            raise PivotError(f"unsupported aggregation {v.agg!r} for {v.field!r}")
    if not query.values:
        raise PivotError("a pivot needs at least one value")

    n = frame.records
    # Filters: a record survives when every filtered field's display is in the chosen set.
    mask = [True] * n
    for name, chosen in query.filters.items():
        if not chosen:
            continue
        allowed = set(chosen)
        col = frame.column(name)
        for i in range(n):
            if mask[i] and display(col[i]) not in allowed:
                mask[i] = False
    matched = sum(mask)

    row_cols = [frame.column(r) for r in query.rows]
    col_cols = [frame.column(c) for c in query.cols]
    value_cols = [frame.column(v.field) for v in query.values]

    groups: dict[tuple[str, ...], dict[tuple[str, ...], list[int]]] = {}
    col_keys: set[tuple[str, ...]] = set()
    for i in range(n):
        if not mask[i]:
            continue
        rk = tuple(display(c[i]) for c in row_cols)
        ck = tuple(display(c[i]) for c in col_cols)
        groups.setdefault(rk, {}).setdefault(ck, []).append(i)
        col_keys.add(ck)

    ordered_cols = sorted(col_keys, key=lambda k: tuple(sort_key(x) for x in k))
    col_layout: list[list[str]] = [list(k) for k in ordered_cols]
    if query.cols:
        col_layout.append([TOTAL])

    def cells_for(indices_by_col: dict[tuple[str, ...], list[int]]) -> list[list[float | None]]:
        out: list[list[float | None]] = []
        for ck in ordered_cols:
            idx = indices_by_col.get(ck, [])
            out.append(
                [
                    aggregate(v.agg, [value_cols[j][i] for i in idx]) if idx else None
                    for j, v in enumerate(query.values)
                ]
            )
        if query.cols:
            idx = [i for lst in indices_by_col.values() for i in lst]
            out.append(
                [
                    aggregate(v.agg, [value_cols[j][i] for i in idx]) if idx else None
                    for j, v in enumerate(query.values)
                ]
            )
        return out

    rows_out: list[dict[str, Any]] = []
    ordered_rows = sorted(groups, key=lambda k: tuple(sort_key(x) for x in k))
    depth = len(query.rows)
    # Subtotals per prefix when rows have more than one level; emitted after the group.
    prefix_members: dict[tuple[str, ...], dict[tuple[str, ...], list[int]]] = {}
    for rk in ordered_rows:
        for p in range(1, depth):
            prefix = rk[:p]
            bucket = prefix_members.setdefault(prefix, {})
            for ck, lst in groups[rk].items():
                bucket.setdefault(ck, []).extend(lst)

    def emit(rk: tuple[str, ...]) -> None:
        members = groups[rk]
        rows_out.append(
            {
                "keys": list(rk),
                "kind": "leaf",
                "n": sum(len(lst) for lst in members.values()),
                "cells": cells_for(members),
            }
        )

    if depth <= 1:
        for rk in ordered_rows:
            emit(rk)
    else:
        previous: tuple[str, ...] | None = None
        for rk in ordered_rows:
            if previous is not None:
                # Close every prefix level that changed, deepest first.
                for p in range(depth - 1, 0, -1):
                    if previous[:p] != rk[:p]:
                        rows_out.append(_subtotal(previous[:p], prefix_members, cells_for))
            emit(rk)
            previous = rk
        if previous is not None:
            for p in range(depth - 1, 0, -1):
                rows_out.append(_subtotal(previous[:p], prefix_members, cells_for))

    all_members: dict[tuple[str, ...], list[int]] = {}
    for members in groups.values():
        for ck, lst in members.items():
            all_members.setdefault(ck, []).extend(lst)
    total_row = {"keys": [TOTAL], "kind": "total", "n": matched, "cells": cells_for(all_members)}

    return {
        "rowFields": list(query.rows),
        "colFields": list(query.cols),
        "colKeys": col_layout,
        "values": [v.model_dump() for v in query.values],
        "rows": rows_out,
        "total": total_row,
        "records": n,
        "matched": matched,
        "live": frame.live,
    }


def _subtotal(
    prefix: tuple[str, ...],
    prefix_members: dict[tuple[str, ...], dict[tuple[str, ...], list[int]]],
    cells_for: Any,
) -> dict[str, Any]:
    members = prefix_members.get(prefix, {})
    return {
        "keys": list(prefix),
        "kind": "subtotal",
        "n": sum(len(lst) for lst in members.values()),
        "cells": cells_for(members),
    }


def field_kinds(frame: PivotFrame) -> dict[str, str]:
    """text | number per field, judged from the data (the cache's own flag is unreliable)."""
    out: dict[str, str] = {}
    for name, col in zip(frame.fields, frame.columns, strict=True):
        nums = sum(1 for v in col if isinstance(v, float))
        present = sum(1 for v in col if v is not None)
        out[name] = "number" if present and nums >= 0.8 * present else "text"
    return out
