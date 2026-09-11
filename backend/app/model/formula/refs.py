"""Cell addresses and rectangle arithmetic. Everything block-level in the logic model is a Rect."""

from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.utils import column_index_from_string, get_column_letter

MAX_ROW = 1_048_576
MAX_COL = 16_384

_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
_COLS = re.compile(r"^\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})$")
_ROWS = re.compile(r"^\$?(\d+):\$?(\d+)$")


def parse_a1_cell(addr: str) -> tuple[int, int]:
    m = _CELL.match(addr)
    if not m:
        raise ValueError(f"not a cell address: {addr!r}")
    return int(m.group(2)), column_index_from_string(m.group(1).upper())


def a1_cell(row: int, col: int) -> str:
    return f"{get_column_letter(col)}{row}"


@dataclass(frozen=True, order=True)
class Rect:
    """Inclusive, 1-based rectangle of cells on one (implicit) sheet."""

    r1: int
    c1: int
    r2: int
    c2: int

    def __post_init__(self) -> None:
        if self.r1 > self.r2 or self.c1 > self.c2 or self.r1 < 1 or self.c1 < 1:
            raise ValueError(f"invalid rect {self!r}")

    @property
    def rows(self) -> int:
        return self.r2 - self.r1 + 1

    @property
    def cols(self) -> int:
        return self.c2 - self.c1 + 1

    @property
    def cells(self) -> int:
        return self.rows * self.cols

    def contains(self, row: int, col: int) -> bool:
        return self.r1 <= row <= self.r2 and self.c1 <= col <= self.c2

    def intersects(self, other: Rect) -> bool:
        return not (
            other.r2 < self.r1 or other.r1 > self.r2 or other.c2 < self.c1 or other.c1 > self.c2
        )

    def intersection(self, other: Rect) -> Rect | None:
        if not self.intersects(other):
            return None
        return Rect(
            max(self.r1, other.r1),
            max(self.c1, other.c1),
            min(self.r2, other.r2),
            min(self.c2, other.c2),
        )

    def shift(self, dr: int, dc: int) -> Rect:
        return Rect(self.r1 + dr, self.c1 + dc, self.r2 + dr, self.c2 + dc)

    def bbox(self, other: Rect) -> Rect:
        return Rect(
            min(self.r1, other.r1),
            min(self.c1, other.c1),
            max(self.r2, other.r2),
            max(self.c2, other.c2),
        )

    def clip(self, extent: Rect) -> Rect | None:
        return self.intersection(extent)

    def to_a1(self) -> str:
        start = a1_cell(self.r1, self.c1)
        if self.r1 == self.r2 and self.c1 == self.c2:
            return start
        return f"{start}:{a1_cell(self.r2, self.c2)}"

    @classmethod
    def from_a1(cls, ref: str) -> Rect:
        ref = ref.strip()
        if m := _COLS.match(ref):
            return cls(
                1,
                column_index_from_string(m.group(1).upper()),
                MAX_ROW,
                column_index_from_string(m.group(2).upper()),
            )
        if m := _ROWS.match(ref):
            return cls(int(m.group(1)), 1, int(m.group(2)), MAX_COL)
        if ":" in ref:
            a, b = ref.split(":", 1)
            r1, c1 = parse_a1_cell(a)
            r2, c2 = parse_a1_cell(b)
            return cls(min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
        r, c = parse_a1_cell(ref)
        return cls(r, c, r, c)

    @classmethod
    def cell(cls, row: int, col: int) -> Rect:
        return cls(row, col, row, col)


def rects_from_mask(mask, row_offset: int = 1, col_offset: int = 1) -> list[Rect]:
    """Cover the True cells of a 2-D boolean array with maximal row-run rectangles.

    Rows are scanned top to bottom; each row is split into runs of True cells, and a run
    that exactly repeats the run directly above extends that rectangle. Returned rects are
    1-based and offset so mask[0][0] maps to (row_offset, col_offset).
    """
    import numpy as np

    open_rects: dict[tuple[int, int], list[int]] = {}  # (c1, c2) -> [r1, r2]
    done: list[Rect] = []
    for i in range(mask.shape[0]):
        row = mask[i]
        if not row.any():
            done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
            open_rects = {}
            continue
        padded = np.concatenate(([False], row, [False]))
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = {
            (int(s) + col_offset, int(e) - 1 + col_offset)
            for s, e in zip(edges[::2], edges[1::2], strict=True)
        }
        r = i + row_offset
        next_open: dict[tuple[int, int], list[int]] = {}
        for key in runs:
            if key in open_rects:
                open_rects[key][1] = r
                next_open[key] = open_rects.pop(key)
            else:
                next_open[key] = [r, r]
        done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
        open_rects = next_open
    done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
    return sorted(done)
