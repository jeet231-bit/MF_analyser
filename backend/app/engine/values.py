"""Struct-of-arrays cell values with Excel semantics.

A ``Values`` holds four parallel numpy arrays (kind, num, code, err). Text is interned in a
run-scoped ``StringTable`` so equality is integer comparison; ordering comparisons on text
materialise strings (rare). Every Excel coercion and comparison rule lives in this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from app.model.formula.refs import Rect
from app.parser.models import RawSheet

EMPTY, NUMBER, TEXT, BOOL, ERROR = 0, 1, 2, 3, 4
KIND_NAMES = {EMPTY: "empty", NUMBER: "number", TEXT: "text", BOOL: "bool", ERROR: "error"}


class XlError(IntEnum):
    NULL = 1
    DIV0 = 2
    VALUE = 3
    REF = 4
    NAME = 5
    NUM = 6
    NA = 7

    @property
    def text(self) -> str:
        return _ERROR_TEXT[self]

    @classmethod
    def from_text(cls, text: str) -> XlError | None:
        return _ERROR_BY_TEXT.get(text)


_ERROR_TEXT = {
    XlError.NULL: "#NULL!",
    XlError.DIV0: "#DIV/0!",
    XlError.VALUE: "#VALUE!",
    XlError.REF: "#REF!",
    XlError.NAME: "#NAME?",
    XlError.NUM: "#NUM!",
    XlError.NA: "#N/A",
}
_ERROR_BY_TEXT = {v: k for k, v in _ERROR_TEXT.items()}
_ERROR_BY_TEXT["#GETTING_DATA"] = XlError.NA
_ERROR_BY_TEXT["#SPILL!"] = XlError.VALUE
_ERROR_BY_TEXT["#CALC!"] = XlError.VALUE


class StringTable:
    """Interns strings to int32 codes; ``fold_of`` maps a code to its case-insensitive group."""

    def __init__(self) -> None:
        self.strings: list[str] = []
        self.fold_of: list[int] = []
        self._codes: dict[str, int] = {}
        self._folds: dict[str, int] = {}
        self._arr: np.ndarray | None = None
        self._fold_arr: np.ndarray | None = None

    def clone(self) -> StringTable:
        other = StringTable()
        other.strings = list(self.strings)
        other.fold_of = list(self.fold_of)
        other._codes = dict(self._codes)
        other._folds = dict(self._folds)
        return other

    def intern(self, s: str) -> int:
        code = self._codes.get(s)
        if code is None:
            code = len(self.strings)
            self._codes[s] = code
            self.strings.append(s)
            key = s.casefold()
            fold = self._folds.get(key)
            if fold is None:
                fold = len(self._folds)
                self._folds[key] = fold
            self.fold_of.append(fold)
            self._arr = None
            self._fold_arr = None
        return code

    def intern_many(self, items) -> np.ndarray:
        get = self._codes.get
        out = np.empty(len(items), dtype=np.int32)
        for i, s in enumerate(items):
            code = get(s)
            out[i] = self.intern(s) if code is None else code
        return out

    def strings_array(self) -> np.ndarray:
        if self._arr is None or len(self._arr) != len(self.strings):
            self._arr = np.array(self.strings, dtype=object)
        return self._arr

    def fold_array(self) -> np.ndarray:
        if self._fold_arr is None or len(self._fold_arr) != len(self.fold_of):
            self._fold_arr = np.asarray(self.fold_of, dtype=np.int32)
        return self._fold_arr

    def decode(self, codes: np.ndarray) -> np.ndarray:
        """Object array of strings for an int32 code array (codes < 0 decode to '')."""
        arr = self.strings_array()
        safe = np.where(codes < 0, 0, codes)
        out = arr[safe] if len(arr) else np.full(codes.shape, "", dtype=object)
        if (codes < 0).any():
            out = out.copy()
            out[codes < 0] = ""
        return out


@dataclass(slots=True)
class Values:
    kind: np.ndarray
    num: np.ndarray
    code: np.ndarray
    err: np.ndarray

    @property
    def shape(self) -> tuple[int, ...]:
        return self.kind.shape

    @property
    def ndim(self) -> int:
        return self.kind.ndim

    @staticmethod
    def empty(shape: tuple[int, ...]) -> Values:
        return Values(
            np.zeros(shape, dtype=np.int8),
            np.zeros(shape, dtype=np.float64),
            np.full(shape, -1, dtype=np.int32),
            np.zeros(shape, dtype=np.int8),
        )

    @staticmethod
    def number(x: float, shape: tuple[int, ...] = (1, 1)) -> Values:
        v = Values.empty(shape)
        v.kind[...] = NUMBER
        v.num[...] = x
        return v

    @staticmethod
    def boolean(b: bool, shape: tuple[int, ...] = (1, 1)) -> Values:
        v = Values.empty(shape)
        v.kind[...] = BOOL
        v.num[...] = 1.0 if b else 0.0
        return v

    @staticmethod
    def text(code: int, shape: tuple[int, ...] = (1, 1)) -> Values:
        v = Values.empty(shape)
        v.kind[...] = TEXT
        v.code[...] = code
        return v

    @staticmethod
    def error(e: XlError, shape: tuple[int, ...] = (1, 1)) -> Values:
        v = Values.empty(shape)
        v.kind[...] = ERROR
        v.err[...] = int(e)
        return v

    @staticmethod
    def from_python(value: object, table: StringTable, shape: tuple[int, ...] = (1, 1)) -> Values:
        if value is None:
            return Values.empty(shape)
        if isinstance(value, XlError):  # IntEnum: must precede the numeric check
            return Values.error(value, shape)
        if isinstance(value, bool):
            return Values.boolean(value, shape)
        if isinstance(value, int | float):
            return Values.number(float(value), shape)
        if isinstance(value, str):
            err = XlError.from_text(value)
            if err is not None:
                return Values.error(err, shape)
            return Values.text(table.intern(value), shape)
        return Values.text(table.intern(str(value)), shape)

    def __getitem__(self, idx) -> Values:
        return Values(self.kind[idx], self.num[idx], self.code[idx], self.err[idx])

    def copy(self) -> Values:
        return Values(self.kind.copy(), self.num.copy(), self.code.copy(), self.err.copy())

    def reshape(self, shape: tuple[int, ...]) -> Values:
        return Values(
            self.kind.reshape(shape),
            self.num.reshape(shape),
            self.code.reshape(shape),
            self.err.reshape(shape),
        )

    def broadcast_to(self, shape: tuple[int, ...]) -> Values:
        return Values(
            np.broadcast_to(self.kind, shape),
            np.broadcast_to(self.num, shape),
            np.broadcast_to(self.code, shape),
            np.broadcast_to(self.err, shape),
        )

    def materialise(self, shape: tuple[int, ...]) -> Values:
        return Values(
            np.array(np.broadcast_to(self.kind, shape)),
            np.array(np.broadcast_to(self.num, shape)),
            np.array(np.broadcast_to(self.code, shape)),
            np.array(np.broadcast_to(self.err, shape)),
        )

    def assign(self, mask: np.ndarray, other: Values) -> None:
        """In place: where mask, take other's cells (other broadcastable to self)."""
        o = other.broadcast_to(self.shape)
        self.kind[mask] = o.kind[mask]
        self.num[mask] = o.num[mask]
        self.code[mask] = o.code[mask]
        self.err[mask] = o.err[mask]

    def to_python(self, table: StringTable) -> np.ndarray:
        """Object array of Python values (None, float, str, bool, error text)."""
        out = np.empty(self.shape, dtype=object)
        out[...] = None
        num_mask = self.kind == NUMBER
        out[num_mask] = self.num[num_mask]
        bool_mask = self.kind == BOOL
        out[bool_mask] = self.num[bool_mask] != 0
        text_mask = self.kind == TEXT
        if text_mask.any():
            out[text_mask] = table.decode(self.code[text_mask])
        err_mask = self.kind == ERROR
        if err_mask.any():
            errs = np.array(
                [_ERROR_TEXT[XlError(int(e))] for e in self.err[err_mask]], dtype=object
            )
            out[err_mask] = errs
        return out


def select(mask: np.ndarray, a: Values, b: Values) -> Values:
    """Element-wise choice: mask ? a : b, all broadcast to a common shape."""
    shape = np.broadcast_shapes(mask.shape, a.shape, b.shape)
    m = np.broadcast_to(mask, shape)
    a2, b2 = a.broadcast_to(shape), b.broadcast_to(shape)
    return Values(
        np.where(m, a2.kind, b2.kind),
        np.where(m, a2.num, b2.num),
        np.where(m, a2.code, b2.code),
        np.where(m, a2.err, b2.err),
    )


# ---- formatting and parsing -----------------------------------------------------------------


def general_format(x: float) -> str:
    """Excel 'General' rendering of a number as text."""
    if math.isnan(x) or math.isinf(x):
        return "#NUM!"
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    text = f"{x:.15g}"
    if "e" in text or "E" in text:
        mantissa, exp = text.split("e") if "e" in text else text.split("E")
        return f"{mantissa}E{int(exp):+03d}"
    return text


def round15(values: np.ndarray | float) -> np.ndarray:
    """Round to 15 significant digits: Excel compares numbers at that precision, which is also
    why a number never exceeds its own text form (``">"&A1``)."""
    # Decimal formatting, not scaled arithmetic: it must agree digit-for-digit with the text
    # conversion in general_format, otherwise a cell can exceed its own ">"&A1 threshold.
    v = np.asarray(values, dtype=np.float64)
    flat = v.reshape(-1)
    out = flat.copy()
    idx = np.flatnonzero(np.isfinite(flat) & (flat != 0))
    if len(idx):
        uniq, inv = np.unique(flat[idx], return_inverse=True)
        rounded = np.fromiter((float(f"{x:.15g}") for x in uniq), dtype=np.float64, count=len(uniq))
        out[idx] = rounded[inv.reshape(-1)]
    return out.reshape(v.shape)


def parse_number_text(s: str) -> float | None:
    t = s.strip()
    if not t:
        return None
    try:
        if t.endswith("%"):
            return float(t[:-1]) / 100.0
        return float(t.replace(",", ""))
    except ValueError:
        return None


# ---- coercions -------------------------------------------------------------------------------


def to_number(v: Values, table: StringTable) -> Values:
    """Excel numeric coercion: empty→0, bool→0/1, numeric text→number, other text→#VALUE!."""
    out = Values(
        np.full(v.shape, NUMBER, dtype=np.int8),
        np.where((v.kind == NUMBER) | (v.kind == BOOL), v.num, 0.0),
        np.full(v.shape, -1, dtype=np.int32),
        np.zeros(v.shape, dtype=np.int8),
    )
    err = v.kind == ERROR
    if err.any():
        out.kind[err] = ERROR
        out.err[err] = v.err[err]
    text = v.kind == TEXT
    if text.any():
        strings = table.decode(v.code[text])
        parsed = np.array([parse_number_text(s) for s in strings], dtype=object)
        ok = np.array([p is not None for p in parsed], dtype=bool)
        idx = np.flatnonzero(text.ravel())
        flat_num = out.num.reshape(-1)
        flat_kind = out.kind.reshape(-1)
        flat_err = out.err.reshape(-1)
        flat_num[idx[ok]] = np.array([p for p in parsed[ok]], dtype=np.float64) if ok.any() else []
        flat_kind[idx[~ok]] = ERROR
        flat_err[idx[~ok]] = int(XlError.VALUE)
        out.num = flat_num.reshape(v.shape)
        out.kind = flat_kind.reshape(v.shape)
        out.err = flat_err.reshape(v.shape)
    return out


def to_bool(v: Values, table: StringTable) -> Values:
    out = Values(
        np.full(v.shape, BOOL, dtype=np.int8),
        np.where((v.kind == NUMBER) | (v.kind == BOOL), (v.num != 0).astype(np.float64), 0.0),
        np.full(v.shape, -1, dtype=np.int32),
        np.zeros(v.shape, dtype=np.int8),
    )
    err = v.kind == ERROR
    if err.any():
        out.kind[err] = ERROR
        out.err[err] = v.err[err]
    text = v.kind == TEXT
    if text.any():
        strings = table.decode(v.code[text])
        vals = np.array([s.strip().upper() for s in strings], dtype=object)
        is_true = vals == "TRUE"
        is_false = vals == "FALSE"
        idx = np.flatnonzero(text.ravel())
        flat_num, flat_kind, flat_err = (
            out.num.reshape(-1),
            out.kind.reshape(-1),
            out.err.reshape(-1),
        )
        flat_num[idx[is_true]] = 1.0
        bad = ~(is_true | is_false)
        flat_kind[idx[bad]] = ERROR
        flat_err[idx[bad]] = int(XlError.VALUE)
        out.num, out.kind, out.err = (
            flat_num.reshape(v.shape),
            flat_kind.reshape(v.shape),
            flat_err.reshape(v.shape),
        )
    return out


def to_text(v: Values, table: StringTable) -> tuple[np.ndarray, np.ndarray]:
    """(object array of str, bool mask of error cells). Errors keep their text for display."""
    out = np.empty(v.shape, dtype=object)
    out[...] = ""
    num = v.kind == NUMBER
    if num.any():
        out[num] = np.array([general_format(x) for x in v.num[num]], dtype=object)
    b = v.kind == BOOL
    if b.any():
        out[b] = np.where(v.num[b] != 0, "TRUE", "FALSE").astype(object)
    t = v.kind == TEXT
    if t.any():
        out[t] = table.decode(v.code[t])
    e = v.kind == ERROR
    if e.any():
        out[e] = np.array([_ERROR_TEXT[XlError(int(x))] for x in v.err[e]], dtype=object)
    return out, e


def from_strings(strings: np.ndarray, table: StringTable) -> Values:
    codes = table.intern_many(list(strings.ravel())).reshape(strings.shape)
    return Values(
        np.full(strings.shape, TEXT, dtype=np.int8),
        np.zeros(strings.shape, dtype=np.float64),
        codes.astype(np.int32),
        np.zeros(strings.shape, dtype=np.int8),
    )


def propagate_errors(result: Values, *sources: Values) -> Values:
    """First error left-to-right wins, per cell."""
    for src in sources:
        s = src.broadcast_to(result.shape)
        m = (s.kind == ERROR) & (result.kind != ERROR)
        if m.any():
            result.kind[m] = ERROR
            result.err[m] = s.err[m]
    return result


# ---- operators --------------------------------------------------------------------------------


def arith(op: str, a: Values, b: Values, table: StringTable) -> Values:
    shape = np.broadcast_shapes(a.shape, b.shape)
    A = to_number(a.broadcast_to(shape), table)
    B = to_number(b.broadcast_to(shape), table)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if op == "+":
            num = A.num + B.num
        elif op == "-":
            num = A.num - B.num
        elif op == "*":
            num = A.num * B.num
        elif op == "/":
            num = A.num / B.num
        elif op == "^":
            num = np.power(A.num, B.num)
        else:
            raise ValueError(f"unknown arithmetic operator {op!r}")
    out = Values(
        np.full(shape, NUMBER, dtype=np.int8),
        num,
        np.full(shape, -1, dtype=np.int32),
        np.zeros(shape, dtype=np.int8),
    )
    if op == "/":
        z = (B.num == 0) & (B.kind != ERROR)
        out.kind[z] = ERROR
        out.err[z] = int(XlError.DIV0)
    bad = ~np.isfinite(num) & (out.kind != ERROR)
    if bad.any():
        out.kind[bad] = ERROR
        out.err[bad] = int(XlError.NUM)
        out.num[bad] = 0.0
    return propagate_errors(out, A, B)


_RANK = {EMPTY: 0, NUMBER: 0, TEXT: 1, BOOL: 2, ERROR: 3}


def compare(op: str, a: Values, b: Values, table: StringTable) -> Values:
    """Excel comparison: number < text < bool; equality across kinds is FALSE; text is
    case-insensitive; empty acts as 0 against numbers/bools and as "" against text."""
    shape = np.broadcast_shapes(a.shape, b.shape)
    A, B = a.broadcast_to(shape), b.broadcast_to(shape)
    ka, kb = A.kind.copy(), B.kind.copy()
    # Empty adopts the other side's family.
    ka = np.where((ka == EMPTY) & (kb == TEXT), TEXT, ka)
    kb = np.where((kb == EMPTY) & (ka == TEXT), TEXT, kb)
    ka = np.where(ka == EMPTY, NUMBER, ka)
    kb = np.where(kb == EMPTY, NUMBER, kb)
    ra = np.vectorize(_RANK.get, otypes=[np.int8])(ka) if ka.size else ka
    rb = np.vectorize(_RANK.get, otypes=[np.int8])(kb) if kb.size else kb

    cmp = np.sign(ra.astype(np.int16) - rb.astype(np.int16)).astype(np.int8)  # -1, 0, 1
    same = ra == rb
    # numbers & bools: numeric comparison
    numeric = same & ((ka == NUMBER) | (ka == BOOL))
    if numeric.any():
        an = round15(np.where(A.kind == EMPTY, 0.0, A.num))
        bn = round15(np.where(B.kind == EMPTY, 0.0, B.num))
        cmp = np.where(numeric, np.sign(an - bn).astype(np.int8), cmp)
    texty = same & (ka == TEXT)
    if texty.any():
        empty_fold = table.fold_of[table.intern("")]  # an empty cell compares as ""
        fold = table.fold_array()
        fa = np.where(A.kind == TEXT, fold[np.where(A.code < 0, 0, A.code)], empty_fold)
        fb = np.where(B.kind == TEXT, fold[np.where(B.code < 0, 0, B.code)], empty_fold)
        if op in ("=", "<>"):
            cmp = np.where(texty, np.where(fa == fb, 0, 1).astype(np.int8), cmp)
        else:
            sa = np.where(
                A.kind == TEXT, table.decode(np.where(A.kind == TEXT, A.code, 0)), ""
            ).astype(object)
            sb = np.where(
                B.kind == TEXT, table.decode(np.where(B.kind == TEXT, B.code, 0)), ""
            ).astype(object)
            fa_s = np.array([s.casefold() for s in sa.ravel()], dtype=object).reshape(shape)
            fb_s = np.array([s.casefold() for s in sb.ravel()], dtype=object).reshape(shape)
            lt = (fa_s < fb_s).astype(np.int8)
            gt = (fa_s > fb_s).astype(np.int8)
            cmp = np.where(texty, gt - lt, cmp)
    if op == "=":
        res = cmp == 0
    elif op == "<>":
        res = cmp != 0
    elif op == "<":
        res = cmp < 0
    elif op == "<=":
        res = cmp <= 0
    elif op == ">":
        res = cmp > 0
    elif op == ">=":
        res = cmp >= 0
    else:
        raise ValueError(f"unknown comparison {op!r}")
    out = Values(
        np.full(shape, BOOL, dtype=np.int8),
        res.astype(np.float64),
        np.full(shape, -1, dtype=np.int32),
        np.zeros(shape, dtype=np.int8),
    )
    return propagate_errors(out, A, B)


def concat(a: Values, b: Values, table: StringTable) -> Values:
    shape = np.broadcast_shapes(a.shape, b.shape)
    A, B = a.broadcast_to(shape), b.broadcast_to(shape)
    sa, ea = to_text(A, table)
    sb, eb = to_text(B, table)
    joined = np.array(
        [x + y for x, y in zip(sa.ravel(), sb.ravel(), strict=True)], dtype=object
    ).reshape(shape)
    out = from_strings(joined, table)
    return propagate_errors(out, A, B)


# ---- grids ----------------------------------------------------------------------------------


class Grid:
    """One sheet's values over its used range, 1-based addressing via ``extent``."""

    def __init__(self, sheet: str, extent: Rect, values: Values) -> None:
        self.sheet = sheet
        self.extent = extent
        self.values = values

    @classmethod
    def from_raw(cls, raw: RawSheet, extent: Rect, table: StringTable) -> Grid:
        shape = (extent.rows, extent.cols)
        values = Values.empty(shape)
        c = raw.cells
        rows = np.asarray(c.row, dtype=np.int64) - extent.r1
        cols = np.asarray(c.col, dtype=np.int64) - extent.c1
        inside = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
        types = np.asarray(c.value_type, dtype=object)
        for kind_name, kind in (("number", NUMBER), ("date", NUMBER), ("bool", BOOL)):
            m = inside & (types == kind_name)
            if m.any():
                idx = np.flatnonzero(m)
                values.kind[rows[idx], cols[idx]] = kind
                values.num[rows[idx], cols[idx]] = np.array(
                    [float(c.value[i]) if c.value[i] is not None else 0.0 for i in idx],
                    dtype=np.float64,
                )
        m = inside & (types == "text")
        if m.any():
            idx = np.flatnonzero(m)
            values.kind[rows[idx], cols[idx]] = TEXT
            values.code[rows[idx], cols[idx]] = table.intern_many([str(c.value[i]) for i in idx])
        m = inside & (types == "error")
        if m.any():
            idx = np.flatnonzero(m)
            values.kind[rows[idx], cols[idx]] = ERROR
            values.err[rows[idx], cols[idx]] = np.array(
                [int(XlError.from_text(str(c.value[i])) or XlError.VALUE) for i in idx],
                dtype=np.int8,
            )
        return cls(raw.name, extent, values)

    def window(self, rect: Rect) -> Values:
        """Values for ``rect``; a view when inside the extent, else a padded copy (EMPTY outside)."""
        e = self.extent
        if rect.r1 >= e.r1 and rect.r2 <= e.r2 and rect.c1 >= e.c1 and rect.c2 <= e.c2:
            return self.values[
                rect.r1 - e.r1 : rect.r2 - e.r1 + 1, rect.c1 - e.c1 : rect.c2 - e.c1 + 1
            ]
        out = Values.empty((rect.rows, rect.cols))
        inter = rect.intersection(e)
        if inter is not None:
            src = self.values[
                inter.r1 - e.r1 : inter.r2 - e.r1 + 1, inter.c1 - e.c1 : inter.c2 - e.c1 + 1
            ]
            rs = slice(inter.r1 - rect.r1, inter.r2 - rect.r1 + 1)
            cs = slice(inter.c1 - rect.c1, inter.c2 - rect.c1 + 1)
            out.kind[rs, cs] = src.kind
            out.num[rs, cs] = src.num
            out.code[rs, cs] = src.code
            out.err[rs, cs] = src.err
        return out

    def write(self, rect: Rect, values: Values) -> None:
        e = self.extent
        inter = rect.intersection(e)
        if inter is None:
            return
        v = values.broadcast_to((rect.rows, rect.cols))
        rs_src = slice(inter.r1 - rect.r1, inter.r2 - rect.r1 + 1)
        cs_src = slice(inter.c1 - rect.c1, inter.c2 - rect.c1 + 1)
        rs = slice(inter.r1 - e.r1, inter.r2 - e.r1 + 1)
        cs = slice(inter.c1 - e.c1, inter.c2 - e.c1 + 1)
        self.values.kind[rs, cs] = v.kind[rs_src, cs_src]
        self.values.num[rs, cs] = v.num[rs_src, cs_src]
        self.values.code[rs, cs] = v.code[rs_src, cs_src]
        self.values.err[rs, cs] = v.err[rs_src, cs_src]

    def cell(self, row: int, col: int) -> Values:
        return self.window(Rect.cell(row, col))

    def write_columnar(self, columns: dict[str, list], table: StringTable) -> None:
        """Bulk write from {address, value, type} lists (a run's stored formula values)."""
        from app.model.formula.refs import parse_a1_cell

        e = self.extent
        rows: list[int] = []
        cols: list[int] = []
        kinds: list[int] = []
        nums: list[float] = []
        texts: list[str] = []
        text_pos: list[int] = []
        errs: list[int] = []
        for _i, (addr, value, vtype) in enumerate(
            zip(columns["address"], columns["value"], columns["type"], strict=True)
        ):
            r, c = parse_a1_cell(addr)
            if not (e.r1 <= r <= e.r2 and e.c1 <= c <= e.c2):
                continue
            rows.append(r - e.r1)
            cols.append(c - e.c1)
            if vtype == "number" and value is not None:
                kinds.append(NUMBER)
                nums.append(float(value))
                errs.append(0)
            elif vtype == "bool":
                kinds.append(BOOL)
                nums.append(1.0 if value else 0.0)
                errs.append(0)
            elif vtype == "text":
                kinds.append(TEXT)
                nums.append(0.0)
                errs.append(0)
                texts.append("" if value is None else str(value))
                text_pos.append(len(rows) - 1)
            elif vtype == "error":
                kinds.append(ERROR)
                nums.append(0.0)
                errs.append(int(XlError.from_text(str(value)) or XlError.VALUE))
            else:
                kinds.append(EMPTY)
                nums.append(0.0)
                errs.append(0)
        if not rows:
            return
        r_arr = np.asarray(rows)
        c_arr = np.asarray(cols)
        self.values.kind[r_arr, c_arr] = np.asarray(kinds, dtype=np.int8)
        self.values.num[r_arr, c_arr] = np.asarray(nums, dtype=np.float64)
        self.values.err[r_arr, c_arr] = np.asarray(errs, dtype=np.int8)
        codes = np.full(len(rows), -1, dtype=np.int32)
        if texts:
            codes[np.asarray(text_pos)] = table.intern_many(texts)
        self.values.code[r_arr, c_arr] = codes
