"""Lookup indexes for VLOOKUP/HLOOKUP, built once per (sheet, range, axis) per run."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from app.engine.values import BOOL, ERROR, NUMBER, TEXT, StringTable, Values


def _keys(values: Values, table: StringTable) -> list[object]:
    """Normalised hashable keys for a 1-D Values (None for empty/error)."""
    out: list[object] = [None] * values.shape[0]
    kind = values.kind
    num_idx = np.flatnonzero(kind == NUMBER)
    for i in num_idx:
        out[i] = ("n", float(values.num[i]))
    bool_idx = np.flatnonzero(kind == BOOL)
    for i in bool_idx:
        out[i] = ("b", values.num[i] != 0)
    text_idx = np.flatnonzero(kind == TEXT)
    if len(text_idx):
        strings = table.decode(values.code[text_idx])
        for i, s in zip(text_idx, strings, strict=True):
            out[i] = ("t", s.casefold())
    return out


@dataclass
class ExactIndex:
    positions: dict[object, int] = field(default_factory=dict)

    @classmethod
    def build(cls, column: Values, table: StringTable) -> ExactIndex:
        idx = cls()
        for pos, key in enumerate(_keys(column, table)):
            if key is not None and key not in idx.positions:
                idx.positions[key] = pos
        return idx

    def lookup(self, keys: Values, table: StringTable) -> np.ndarray:
        """Positions (−1 for miss) for each key cell; errors/empties miss."""
        flat = keys.reshape((-1,))
        ks = _keys(flat, table)
        get = self.positions.get
        out = np.fromiter(
            (get(k, -1) if k is not None else -1 for k in ks), dtype=np.int64, count=len(ks)
        )
        return out.reshape(keys.shape)


@dataclass
class ApproximateIndex:
    """Largest key ≤ lookup key, numbers only (Excel's sorted-ascending contract)."""

    sorted_values: list[float]
    positions: list[int]

    @classmethod
    def build(cls, column: Values) -> ApproximateIndex:
        pairs = [
            (float(column.num[i]), i) for i in range(column.shape[0]) if column.kind[i] == NUMBER
        ]
        # Excel assumes ascending order; we honour the sheet order and use binary search.
        return cls([p[0] for p in pairs], [p[1] for p in pairs])

    def lookup(self, keys: Values) -> np.ndarray:
        flat = keys.reshape((-1,))
        out = np.full(flat.shape, -1, dtype=np.int64)
        for i in range(flat.shape[0]):
            if flat.kind[i] in (NUMBER, BOOL):
                j = bisect.bisect_right(self.sorted_values, float(flat.num[i])) - 1
                if j >= 0:
                    out[i] = self.positions[j]
        return out.reshape(keys.shape)


class IndexCache:
    def __init__(self) -> None:
        self._exact: dict[tuple, ExactIndex] = {}
        self._approx: dict[tuple, ApproximateIndex] = {}

    def exact(self, key: tuple, column: Values, table: StringTable) -> ExactIndex:
        idx = self._exact.get(key)
        if idx is None:
            idx = ExactIndex.build(column, table)
            self._exact[key] = idx
        return idx

    def approximate(self, key: tuple, column: Values) -> ApproximateIndex:
        idx = self._approx.get(key)
        if idx is None:
            idx = ApproximateIndex.build(column)
            self._approx[key] = idx
        return idx

    def invalidate(self) -> None:
        self._exact.clear()
        self._approx.clear()


def gather(table_values: Values, positions: np.ndarray, offsets: np.ndarray, axis: int) -> Values:
    """Pick table[pos, off] (axis 0: VLOOKUP) or table[off, pos] (axis 1: HLOOKUP) per cell.

    ``positions`` and ``offsets`` are broadcast together; invalid cells (pos < 0 or offset out of
    range) must be masked by the caller.
    """
    shape = np.broadcast_shapes(positions.shape, offsets.shape)
    p = np.broadcast_to(positions, shape)
    o = np.broadcast_to(offsets, shape)
    rows, cols = (p, o) if axis == 0 else (o, p)
    r = np.clip(rows, 0, table_values.shape[0] - 1)
    c = np.clip(cols, 0, table_values.shape[1] - 1)
    return Values(
        table_values.kind[r, c],
        table_values.num[r, c],
        table_values.code[r, c],
        table_values.err[r, c],
    )


__all__ = ["ApproximateIndex", "ExactIndex", "IndexCache", "gather", "ERROR"]
