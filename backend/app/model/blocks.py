"""Sheet-level array views, input blocks from footprints, and label detection."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.model.formula.refs import Rect, rects_from_mask
from app.parser.models import CellValue, RawSheet

TYPE_CODES = {"empty": 0, "number": 1, "text": 2, "date": 3, "bool": 4, "error": 5}
TYPE_NAMES = {v: k for k, v in TYPE_CODES.items()}
LABEL_SEARCH_ROWS = 5
LABEL_SEARCH_COLS = 3


@dataclass
class SheetArrays:
    """Dense boolean/typed views of one sheet over its used range (row/col 1-based via extent)."""

    name: str
    extent: Rect
    formula: np.ndarray  # bool
    const: np.ndarray  # bool: non-empty, non-formula
    types: np.ndarray  # int8 codes for every cell (0 = empty)
    text_at: dict[tuple[int, int], str] = field(default_factory=dict)
    values_at: dict[tuple[int, int], CellValue] = field(default_factory=dict)

    def local(self, rect: Rect) -> tuple[slice, slice]:
        r = rect.intersection(self.extent)
        if r is None:
            return slice(0, 0), slice(0, 0)
        return (
            slice(r.r1 - self.extent.r1, r.r2 - self.extent.r1 + 1),
            slice(r.c1 - self.extent.c1, r.c2 - self.extent.c1 + 1),
        )

    def mask_like(self) -> np.ndarray:
        return np.zeros(self.formula.shape, dtype=bool)


def sheet_arrays(sheet: RawSheet, extent: Rect, *, keep_values: bool = False) -> SheetArrays:
    rows = np.asarray(sheet.cells.row, dtype=np.int64) - extent.r1
    cols = np.asarray(sheet.cells.col, dtype=np.int64) - extent.c1
    shape = (extent.rows, extent.cols)
    inside = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    rows, cols = rows[inside], cols[inside]
    has_formula = np.fromiter(
        (f is not None for f in sheet.cells.formula), dtype=bool, count=len(sheet.cells)
    )[inside]
    codes = np.fromiter(
        (TYPE_CODES[t] for t in sheet.cells.value_type), dtype=np.int8, count=len(sheet.cells)
    )[inside]

    formula = np.zeros(shape, dtype=bool)
    formula[rows, cols] = has_formula
    types = np.zeros(shape, dtype=np.int8)
    types[rows, cols] = codes
    const = (types != 0) & ~formula

    arrays = SheetArrays(sheet.name, extent, formula, const, types)
    idx = np.flatnonzero(inside)
    for i, r, c in zip(idx.tolist(), rows.tolist(), cols.tolist(), strict=True):
        if sheet.cells.formula[i] is None and sheet.cells.value_type[i] == "text":
            arrays.text_at[(r + extent.r1, c + extent.c1)] = str(sheet.cells.value[i])
        if keep_values:
            arrays.values_at[(r + extent.r1, c + extent.c1)] = sheet.cells.value[i]
    return arrays


def coverage_mask(arrays: SheetArrays, footprints: list[Rect]) -> np.ndarray:
    covered = arrays.mask_like()
    for rect in footprints:
        rs, cs = arrays.local(rect)
        covered[rs, cs] = True
    return covered


def input_rects(arrays: SheetArrays, covered: np.ndarray) -> list[Rect]:
    """Rectangles of referenced non-formula cells, ignoring rects that hold no constants."""
    region = covered & ~arrays.formula
    rects = rects_from_mask(region, arrays.extent.r1, arrays.extent.c1)
    out: list[Rect] = []
    for rect in rects:
        rs, cs = arrays.local(rect)
        if arrays.const[rs, cs].any():
            out.append(rect)
    return out


def constants_in(arrays: SheetArrays, rect: Rect) -> int:
    rs, cs = arrays.local(rect)
    return int(arrays.const[rs, cs].sum())


def value_types_in(arrays: SheetArrays, rect: Rect) -> dict[str, int]:
    rs, cs = arrays.local(rect)
    codes = arrays.types[rs, cs][~arrays.formula[rs, cs]]
    counts = np.bincount(codes.ravel(), minlength=6)
    return {TYPE_NAMES[i]: int(n) for i, n in enumerate(counts) if n and i != 0}


def static_count(arrays: SheetArrays, covered: np.ndarray) -> int:
    return int((arrays.const & ~covered).sum())


def column_labels(arrays: SheetArrays, rect: Rect) -> list[str | None]:
    labels: list[str | None] = []
    for c in range(rect.c1, rect.c2 + 1):
        label = None
        for r in range(rect.r1 - 1, max(0, rect.r1 - 1 - LABEL_SEARCH_ROWS), -1):
            text = arrays.text_at.get((r, c))
            if text:
                label = text
                break
        labels.append(label)
    return labels


def row_label_column(arrays: SheetArrays, rect: Rect) -> int | None:
    """The nearest column to the left whose text cells label most of the block's rows."""
    rows = range(rect.r1, rect.r2 + 1)
    needed = max(1, int(0.6 * rect.rows))
    for c in range(rect.c1 - 1, max(0, rect.c1 - 1 - LABEL_SEARCH_COLS), -1):
        hits = sum(1 for r in rows if (r, c) in arrays.text_at)
        if hits >= needed:
            return c
    return None


def values_in(arrays: SheetArrays, rect: Rect) -> list[list[CellValue]] | None:
    """Constant values inside ``rect`` as rows; None if any cell there holds a formula."""
    rs, cs = arrays.local(rect)
    if arrays.formula[rs, cs].any():
        return None
    return [
        [arrays.values_at.get((r, c)) for c in range(rect.c1, rect.c2 + 1)]
        for r in range(rect.r1, rect.r2 + 1)
    ]
