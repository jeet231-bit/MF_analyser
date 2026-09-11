"""The Excel function registry: the engine's whole coverage contract (CLAUDE.md).

Each function receives the evaluation context and the raw argument nodes, evaluates what it
needs (values or ranges) and returns a Values broadcastable to the block. Vectorised over the
block wherever the argument shapes allow.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from openpyxl.utils.datetime import from_excel, to_excel

from app.engine.criteria import criterion_mask, parse_criterion
from app.engine.lookups import gather
from app.engine.values import (
    BOOL,
    EMPTY,
    ERROR,
    NUMBER,
    TEXT,
    StringTable,
    Values,
    XlError,
    from_strings,
    parse_number_text,
    propagate_errors,
    round15,
    select,
    to_bool,
    to_number,
    to_text,
)
from app.model.formula.ast import Node

if TYPE_CHECKING:
    from app.engine.evaluator import BlockContext, RangeOperand


class UnsupportedFunctionError(Exception):
    def __init__(self, function: str, sheet: str, cell: str) -> None:
        super().__init__(f"unsupported Excel function {function} in {sheet}!{cell}")
        self.function = function
        self.sheet = sheet
        self.cell = cell


FunctionImpl = Callable[["BlockContext", list[Node]], Values]
REGISTRY: dict[str, FunctionImpl] = {}


def register(*names: str):
    def deco(fn: FunctionImpl) -> FunctionImpl:
        for n in names:
            REGISTRY[n] = fn
        return fn

    return deco


def _shape(ctx: BlockContext) -> tuple[int, int]:
    return ctx.shape


# ---- helpers over ranges ------------------------------------------------------------------


def window_sum(arr: np.ndarray) -> np.ndarray:
    """Sum a window's last two axes in Excel's order: one double addition at a time, row-major.

    numpy's reduction is pairwise and 8-way unrolled, which differs from sequential addition in
    the last digit once a window holds more than a handful of numbers. Excel adds sequentially,
    and reconciliation at 15 significant digits (and every `">"&A1` threshold built from a sum)
    needs the same digits, so every SUM/SUMIF/AVERAGEIF/SUMPRODUCT goes through here.
    """
    flat = arr.reshape(*arr.shape[:-2], -1)
    if flat.shape[-1] == 0:
        return np.zeros(flat.shape[:-1], dtype=np.float64)
    return np.cumsum(flat, axis=-1, dtype=np.float64)[..., -1]


def _reduce_numeric(rng: RangeOperand, fn: str) -> Values:
    """Reduce a 4-D range over its window axes; text/bool/empty ignored, errors propagate."""
    v = rng.values
    kind, num = v.kind, v.num
    numeric = kind == NUMBER
    if rng.valid is not None:
        numeric = numeric & rng.valid
    err_any = (kind == ERROR) if rng.valid is None else ((kind == ERROR) & rng.valid)
    nums = np.where(numeric, num, 0.0)
    if fn == "sum":
        out = window_sum(nums)
    elif fn == "count":
        out = numeric.sum(axis=(-2, -1)).astype(np.float64)
        res = Values.number(0.0, out.shape)
        res.num = out
        return res  # COUNT ignores errors and text
    elif fn == "max":
        out = np.where(numeric, num, -np.inf).max(axis=(-2, -1))
        out = np.where(numeric.any(axis=(-2, -1)), out, 0.0)
    elif fn == "min":
        out = np.where(numeric, num, np.inf).min(axis=(-2, -1))
        out = np.where(numeric.any(axis=(-2, -1)), out, 0.0)
    elif fn == "average":
        n = numeric.sum(axis=(-2, -1))
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(n > 0, window_sum(nums) / np.maximum(n, 1), 0.0)
        res = Values.number(0.0, out.shape)
        res.num = out
        res.kind[n == 0] = ERROR
        res.err[n == 0] = int(XlError.DIV0)
        return _propagate_range_errors(res, err_any, v)
    else:
        raise ValueError(fn)
    res = Values.number(0.0, out.shape)
    res.num = out
    return _propagate_range_errors(res, err_any, v)


def _propagate_range_errors(res: Values, err_any: np.ndarray, v: Values) -> Values:
    has_err = err_any.any(axis=(-2, -1))
    if has_err.any():
        # first error in window order
        first = np.argmax(err_any.reshape(*err_any.shape[:-2], -1), axis=-1)
        errs = np.take_along_axis(v.err.reshape(*v.err.shape[:-2], -1), first[..., None], axis=-1)[
            ..., 0
        ]
        res.kind[has_err] = ERROR
        res.err[has_err] = errs[has_err]
    return res


def _aggregate(ctx: BlockContext, args: list[Node], fn: str) -> Values:
    total: Values | None = None
    counts = None
    parts: list[Values] = []
    for node in args:
        operand = ctx.any(node)
        if ctx.is_range(operand):
            parts.append(_reduce_numeric(operand, fn if fn != "average" else "sum"))
            if fn == "average":
                counts = (
                    _reduce_numeric(operand, "count")
                    if counts is None
                    else _add(counts, _reduce_numeric(operand, "count"), ctx.table)
                )
        else:
            val = to_number(operand, ctx.table)
            parts.append(val)
            if fn == "average":
                one = Values.number(1.0, val.shape)
                counts = one if counts is None else _add(counts, one, ctx.table)
    if not parts:
        return Values.number(0.0)
    if fn in ("sum", "count", "average"):
        total = parts[0]
        for p in parts[1:]:
            total = _add(total, p, ctx.table)
        if fn == "average":
            assert counts is not None
            shape = np.broadcast_shapes(total.shape, counts.shape)
            t, c = total.broadcast_to(shape), counts.broadcast_to(shape)
            out = Values.number(0.0, shape)
            zero = c.num == 0
            with np.errstate(divide="ignore", invalid="ignore"):
                out.num = np.where(zero, 0.0, t.num / np.maximum(c.num, 1))
            out.kind[zero] = ERROR
            out.err[zero] = int(XlError.DIV0)
            return propagate_errors(out, t)
        return total
    # max / min across parts
    shape = np.broadcast_shapes(*(p.shape for p in parts))
    stack_num = np.stack([np.broadcast_to(p.num, shape) for p in parts])
    out = Values.number(0.0, shape)
    out.num = stack_num.max(axis=0) if fn == "max" else stack_num.min(axis=0)
    return propagate_errors(out, *parts)


def _add(a: Values, b: Values, table: StringTable) -> Values:
    from app.engine.values import arith

    return arith("+", a, b, table)


def _criteria_pairs(ctx: BlockContext, args: list[Node]) -> list[tuple[RangeOperand, Values]]:
    pairs = []
    for i in range(0, len(args) - 1, 2):
        rng = ctx.range(args[i])
        crit = ctx.value(args[i + 1])
        pairs.append((rng, crit))
    return pairs


def _masks_for(ctx: BlockContext, rng: RangeOperand, crit: Values) -> np.ndarray:
    """Boolean (R', C', h, w) broadcastable mask for a per-cell criterion over a range."""
    v = rng.values
    crit_b = crit.broadcast_to(ctx.shape)
    py = crit_b.to_python(ctx.table)
    flat = py.reshape(-1)
    uniques: dict[object, list[int]] = {}
    for i, val in enumerate(flat):
        key = val if not isinstance(val, float) or val == val else "nan"
        uniques.setdefault(key, []).append(i)
    R, C = ctx.shape
    h, w = v.shape[-2:]
    Rp, Cp = v.shape[0], v.shape[1]
    rounded = round15(v.num)  # once per range, not once per distinct criterion
    # Result mask has shape (R, C, h, w) when the criterion varies per cell; cheaper cases collapse.
    if len(uniques) == 1:
        (val,) = uniques
        m = criterion_mask(v, parse_criterion(val), ctx.table, rounded)
        if rng.valid is not None:
            m = m & rng.valid
        return m
    out = np.zeros((R, C, h, w), dtype=bool)
    per_cell = {}
    for val, idxs in uniques.items():
        m = criterion_mask(v, parse_criterion(val), ctx.table, rounded)  # (Rp, Cp, h, w)
        if rng.valid is not None:
            m = m & rng.valid
        per_cell[val] = m
        for i in idxs:
            r, c = divmod(i, C)
            out[r, c] = m[r if Rp > 1 else 0, c if Cp > 1 else 0]
    return out


@register("COUNTIF")
def fn_countif(ctx: BlockContext, args: list[Node]) -> Values:
    return fn_countifs(ctx, args)


_OP_PREFIXES = ("<>", "<=", ">=", "<", ">", "=")


def _group_rank_fast_path(
    ctx: BlockContext, pairs: list[tuple[RangeOperand, Values]]
) -> Values | None:
    """COUNTIFS(group_col, key, value_col, "<op>"&number): sort once per column, then binary search.

    This is the rank pattern that dominates research workbooks. Returns None when the shape is
    anything else, and the general path takes over.
    """
    if len(pairs) != 2:
        return None
    (rng1, crit1), (rng2, crit2) = pairs
    v1, v2 = rng1.values, rng2.values
    if rng1.valid is not None or rng2.valid is not None:
        return None
    if v1.shape[0] != 1 or v1.shape[1] != 1 or v1.shape[3] != 1 or v2.shape[3] != 1:
        return None
    if v2.shape[0] != 1 or v2.shape[2] != v1.shape[2]:
        return None
    R, C = ctx.shape
    if v2.shape[1] not in (1, C):
        return None
    table = ctx.table

    # Criterion 2: uniform comparison operator with a numeric threshold per cell.
    c2 = crit2.broadcast_to((R, C))
    if not (c2.kind == TEXT).all():
        return None
    strings = table.decode(c2.code).reshape(-1)
    op = None
    thresholds = np.full(R * C, np.nan, dtype=np.float64)
    text_thresholds: dict[str, list[int]] = {}  # e.g. ">--" -> flat cell indexes (sentinel rows)
    for i, s in enumerate(strings):
        prefix = next((p for p in _OP_PREFIXES if s.startswith(p)), None)
        if prefix is None:
            return None
        if op is None:
            op = prefix
        elif prefix != op:
            return None
        num = parse_number_text(s[len(prefix) :])
        if num is None:
            text_thresholds.setdefault(s, []).append(i)
        else:
            thresholds[i] = num
    thresholds = round15(thresholds).reshape(R, C)

    # Criterion 1: plain equality on text or numbers (no operators, no wildcards).
    c1 = crit1.broadcast_to((R, C))
    if not ((c1.kind == TEXT) | (c1.kind == NUMBER)).all():
        return None
    col1 = v1[0, 0, :, 0]
    h = col1.shape[0]
    gid = np.full(h, -1, dtype=np.int64)
    num_rows = col1.kind == NUMBER
    uniq_nums = np.unique(round15(col1.num[num_rows])) if num_rows.any() else np.empty(0)
    if num_rows.any():
        gid[num_rows] = np.searchsorted(uniq_nums, round15(col1.num[num_rows]))
    k = len(uniq_nums)
    text_rows = col1.kind == TEXT
    if text_rows.any():
        gid[text_rows] = k + table.fold_array()[col1.code[text_rows]]

    cell_gid = np.full(R * C, -2, dtype=np.int64)
    flat_kind, flat_num, flat_code = c1.kind.reshape(-1), c1.num.reshape(-1), c1.code.reshape(-1)
    is_num = flat_kind == NUMBER
    if is_num.any():
        q = round15(flat_num[is_num])
        pos = np.searchsorted(uniq_nums, q)
        found = (
            (pos < k) & (uniq_nums[np.minimum(pos, max(k - 1, 0))] == q)
            if k
            else np.zeros(len(q), bool)
        )
        cell_gid[np.flatnonzero(is_num)[found]] = pos[found]
    is_text = flat_kind == TEXT
    if is_text.any():
        crit_strings = table.decode(flat_code[is_text])
        for idx, s in zip(np.flatnonzero(is_text), crit_strings, strict=True):
            if any(ch in s for ch in "*?~") or s.startswith(_OP_PREFIXES):
                return None
            fold = table._folds.get(s.casefold())  # noqa: SLF001 - same package
            if fold is not None:
                cell_gid[idx] = k + fold
    cell_gid = cell_gid.reshape(R, C)

    out = np.zeros((R, C), dtype=np.float64)
    per_column = v2.shape[1] == C
    for j in range(v2.shape[1]):
        col2 = v2[0, j, :, 0]
        rows_ok = (col2.kind == NUMBER) & (gid >= 0)
        g = gid[rows_ok]
        vals = round15(col2.num[rows_ok])
        order = np.lexsort((vals, g))
        gs, vs = g[order], vals[order]
        cols = [j] if per_column else list(range(C))
        for c in cols:
            cg = cell_gid[:, c]
            t = thresholds[:, c]
            lo = np.searchsorted(gs, cg, side="left")
            hi = np.searchsorted(gs, cg, side="right")
            size = hi - lo
            le = np.zeros(R, dtype=np.int64)
            lt = np.zeros(R, dtype=np.int64)
            for grp in np.unique(cg[size > 0]):
                sel = np.flatnonzero(cg == grp)
                seg = vs[lo[sel[0]] : hi[sel[0]]]
                le[sel] = np.searchsorted(seg, t[sel], side="right")
                lt[sel] = np.searchsorted(seg, t[sel], side="left")
            if op == ">":
                res = size - le
            elif op == ">=":
                res = size - lt
            elif op == "<":
                res = lt
            elif op == "<=":
                res = le
            elif op == "=":
                res = le - lt
            else:  # <>
                res = size - (le - lt)
            out[:, c] = res
        # Cells whose threshold is text (e.g. ">--"): count text rows of the group per Excel rules.
        if text_thresholds:
            max_gid = int(gid.max()) if gid.size else 0
            for crit_text, idxs in text_thresholds.items():
                mask = criterion_mask(col2, parse_criterion(crit_text), table) & (gid >= 0)
                counts = np.bincount(gid[mask], minlength=max_gid + 1)
                for flat in idxs:
                    r, c = divmod(flat, C)
                    if per_column and c != j:
                        continue
                    g = cell_gid[r, c]
                    out[r, c] = counts[g] if 0 <= g <= max_gid else 0
    result = Values.number(0.0, (R, C))
    result.num = out
    return result


@register("COUNTIFS")
def fn_countifs(ctx: BlockContext, args: list[Node]) -> Values:
    pairs = _criteria_pairs(ctx, args)
    fast = _group_rank_fast_path(ctx, pairs)
    if fast is not None:
        return fast
    mask = None
    for rng, crit in pairs:
        m = _masks_for(ctx, rng, crit)
        mask = m if mask is None else (mask & m)
    assert mask is not None
    counts = mask.sum(axis=(-2, -1)).astype(np.float64)
    out = Values.number(0.0, counts.shape)
    out.num = counts
    return out


@register("SUMIF", "AVERAGEIF")
def fn_sumif(ctx: BlockContext, args: list[Node]) -> Values:
    fname = ctx.current_function
    rng = ctx.range(args[0])
    crit = ctx.value(args[1])
    target = ctx.range(args[2]) if len(args) > 2 else rng
    mask = _masks_for(ctx, rng, crit)
    tv = target.values
    numeric = tv.kind == NUMBER
    shape = np.broadcast_shapes(mask.shape, tv.kind.shape)
    m = np.broadcast_to(mask, shape) & np.broadcast_to(numeric, shape)
    nums = np.where(m, np.broadcast_to(tv.num, shape), 0.0)
    total = window_sum(nums)
    out = Values.number(0.0, total.shape)
    if fname == "AVERAGEIF":
        n = m.sum(axis=(-2, -1))
        with np.errstate(divide="ignore", invalid="ignore"):
            out.num = np.where(n > 0, total / np.maximum(n, 1), 0.0)
        out.kind[n == 0] = ERROR
        out.err[n == 0] = int(XlError.DIV0)
    else:
        out.num = total
    return out


@register("SUMPRODUCT")
def fn_sumproduct(ctx: BlockContext, args: list[Node]) -> Values:
    ranges = [ctx.range(a) for a in args]
    shape = np.broadcast_shapes(*(r.values.kind.shape for r in ranges))
    prod = np.ones(shape, dtype=np.float64)
    err_res: Values | None = None
    for r in ranges:
        v = r.values
        numeric = np.broadcast_to((v.kind == NUMBER) | (v.kind == BOOL), shape)
        prod = prod * np.where(numeric, np.broadcast_to(v.num, shape), 0.0)
        e = np.broadcast_to(v.kind == ERROR, shape)
        if e.any():
            res = Values.number(0.0, shape[:-2])
            has = e.any(axis=(-2, -1))
            res.kind[has] = ERROR
            res.err[has] = int(XlError.VALUE)
            err_res = res if err_res is None else err_res
    total = window_sum(prod)
    out = Values.number(0.0, total.shape)
    out.num = total
    if err_res is not None:
        out = propagate_errors(out, err_res)
    return out


@register("SUM")
def fn_sum(ctx: BlockContext, args: list[Node]) -> Values:
    return _aggregate(ctx, args, "sum")


@register("COUNT")
def fn_count(ctx: BlockContext, args: list[Node]) -> Values:
    total: Values | None = None
    for node in args:
        operand = ctx.any(node)
        if ctx.is_range(operand):
            part = _reduce_numeric(operand, "count")
        else:
            part = Values.number(0.0, operand.shape)
            part.num = (operand.kind == NUMBER).astype(np.float64)
        total = part if total is None else _add(total, part, ctx.table)
    return total if total is not None else Values.number(0.0)


@register("MAX")
def fn_max(ctx: BlockContext, args: list[Node]) -> Values:
    return _aggregate(ctx, args, "max")


@register("MIN")
def fn_min(ctx: BlockContext, args: list[Node]) -> Values:
    return _aggregate(ctx, args, "min")


@register("AVERAGE")
def fn_average(ctx: BlockContext, args: list[Node]) -> Values:
    return _aggregate(ctx, args, "average")


# ---- logical ----------------------------------------------------------------------------------


@register("IF")
def fn_if(ctx: BlockContext, args: list[Node]) -> Values:
    cond = to_bool(ctx.value(args[0]), ctx.table)
    then = ctx.value(args[1]) if len(args) > 1 else Values.boolean(True)
    other = ctx.value(args[2]) if len(args) > 2 else Values.boolean(False)
    out = select(cond.num != 0, then, other)
    return propagate_errors(
        out.materialise(out.shape) if not out.kind.flags.writeable else out, cond
    )


@register("IFERROR")
def fn_iferror(ctx: BlockContext, args: list[Node]) -> Values:
    value = ctx.value(args[0])
    fallback = ctx.value(args[1]) if len(args) > 1 else Values.empty((1, 1))
    return select(value.kind == ERROR, fallback, value)


def _logical(ctx: BlockContext, args: list[Node], op: str) -> Values:
    acc: np.ndarray | None = None
    errs: list[Values] = []
    shape = ctx.shape
    for node in args:
        operand = ctx.any(node)
        if ctx.is_range(operand):
            v = operand.values
            usable = (v.kind == NUMBER) | (v.kind == BOOL)
            if operand.valid is not None:
                usable = usable & operand.valid
            truth = usable & (v.num != 0)
            part = truth.any(axis=(-2, -1)) if op == "or" else (~usable | truth).all(axis=(-2, -1))
            e = Values.number(0.0, part.shape)
            has = (v.kind == ERROR).any(axis=(-2, -1))
            e.kind[has] = ERROR
            e.err[has] = int(XlError.VALUE)
            errs.append(e)
        else:
            b = to_bool(operand, ctx.table)
            part = b.num != 0
            errs.append(b)
        part = np.broadcast_to(part, np.broadcast_shapes(part.shape, shape))
        acc = part if acc is None else ((acc | part) if op == "or" else (acc & part))
    assert acc is not None
    out = Values.boolean(False, acc.shape)
    out.num = acc.astype(np.float64)
    return propagate_errors(out, *errs)


@register("AND")
def fn_and(ctx: BlockContext, args: list[Node]) -> Values:
    return _logical(ctx, args, "and")


@register("OR")
def fn_or(ctx: BlockContext, args: list[Node]) -> Values:
    return _logical(ctx, args, "or")


@register("ISNUMBER")
def fn_isnumber(ctx: BlockContext, args: list[Node]) -> Values:
    v = ctx.value(args[0])
    out = Values.boolean(False, v.shape)
    out.num = (v.kind == NUMBER).astype(np.float64)
    return out


# ---- text ---------------------------------------------------------------------------------------


@register("SEARCH")
def fn_search(ctx: BlockContext, args: list[Node]) -> Values:
    find = ctx.value(args[0])
    within = ctx.value(args[1])
    start = to_number(ctx.value(args[2]), ctx.table) if len(args) > 2 else Values.number(1.0)
    shape = np.broadcast_shapes(find.shape, within.shape, start.shape)
    f, _ = to_text(find.broadcast_to(shape), ctx.table)
    w, _ = to_text(within.broadcast_to(shape), ctx.table)
    s = np.broadcast_to(start.num, shape)
    out = Values.number(0.0, shape)
    flat_out = out.num.reshape(-1)
    flat_kind = out.kind.reshape(-1)
    flat_err = out.err.reshape(-1)
    for i, (needle, hay, st) in enumerate(zip(f.ravel(), w.ravel(), s.ravel(), strict=True)):
        st_i = int(st)
        if st_i < 1 or st_i > len(hay) + 1:
            flat_kind[i] = ERROR
            flat_err[i] = int(XlError.VALUE)
            continue
        pos = hay.casefold().find(needle.casefold(), st_i - 1)
        if pos < 0:
            flat_kind[i] = ERROR
            flat_err[i] = int(XlError.VALUE)
        else:
            flat_out[i] = pos + 1
    out.num, out.kind, out.err = (
        flat_out.reshape(shape),
        flat_kind.reshape(shape),
        flat_err.reshape(shape),
    )
    return propagate_errors(
        out, find.broadcast_to(shape), within.broadcast_to(shape), start.broadcast_to(shape)
    )


@register("LEFT")
def fn_left(ctx: BlockContext, args: list[Node]) -> Values:
    text = ctx.value(args[0])
    n = to_number(ctx.value(args[1]), ctx.table) if len(args) > 1 else Values.number(1.0)
    shape = np.broadcast_shapes(text.shape, n.shape)
    s, _ = to_text(text.broadcast_to(shape), ctx.table)
    counts = np.broadcast_to(n.num, shape)
    strings = np.array(
        [
            x[: max(0, int(k))] if k >= 0 else ""
            for x, k in zip(s.ravel(), counts.ravel(), strict=True)
        ],
        dtype=object,
    ).reshape(shape)
    out = from_strings(strings, ctx.table)
    neg = counts < 0
    out.kind[neg] = ERROR
    out.err[neg] = int(XlError.VALUE)
    return propagate_errors(out, text.broadcast_to(shape), n.broadcast_to(shape))


@register("CONCATENATE", "CONCAT")
def fn_concatenate(ctx: BlockContext, args: list[Node]) -> Values:
    from app.engine.values import concat

    acc = ctx.value(args[0]) if args else Values.text(ctx.table.intern(""))
    if not args:
        return acc
    acc_text = concat(Values.text(ctx.table.intern("")), acc, ctx.table)
    for node in args[1:]:
        acc_text = concat(acc_text, ctx.value(node), ctx.table)
    return acc_text


# ---- lookup ------------------------------------------------------------------------------------


def _lookup(ctx: BlockContext, args: list[Node], axis: int) -> Values:
    key = ctx.value(args[0])
    rng = ctx.range(args[1])
    index = to_number(ctx.value(args[2]), ctx.table)
    exact = True
    if len(args) > 3:
        flag = to_bool(ctx.value(args[3]), ctx.table)
        exact = bool((flag.num == 0).all())  # FALSE / 0 → exact match
        mixed = (flag.num != 0).any() and (flag.num == 0).any()
        if mixed:
            raise ValueError("VLOOKUP/HLOOKUP match-type varies within a block")
    if not rng.fixed:
        raise ValueError("lookup table must be a fixed range within a block")
    table_values = rng.values[0, 0]  # (h, w)
    first = table_values[:, 0] if axis == 0 else table_values[0, :]
    cache_key = (rng.sheet, rng.rect, axis, exact)
    if exact:
        idx = ctx.indexes.exact(cache_key, first, ctx.table)
        positions = idx.lookup(key, ctx.table)
    else:
        idx = ctx.indexes.approximate(cache_key, first)
        positions = idx.lookup(key)
    offsets = (index.num - 1).astype(np.int64)
    shape = np.broadcast_shapes(positions.shape, offsets.shape)
    positions_b = np.broadcast_to(positions, shape)
    offsets_b = np.broadcast_to(offsets, shape)
    limit = table_values.shape[1] if axis == 0 else table_values.shape[0]
    out = gather(table_values, positions_b, offsets_b, axis).copy()
    miss = positions_b < 0
    out.kind[miss] = ERROR
    out.err[miss] = int(XlError.NA)
    bad = (offsets_b < 0) | (offsets_b >= limit)
    out.kind[bad & ~miss] = ERROR
    out.err[bad & ~miss] = int(XlError.REF)
    return propagate_errors(out, key.broadcast_to(shape), index.broadcast_to(shape))


@register("VLOOKUP")
def fn_vlookup(ctx: BlockContext, args: list[Node]) -> Values:
    return _lookup(ctx, args, 0)


@register("HLOOKUP")
def fn_hlookup(ctx: BlockContext, args: list[Node]) -> Values:
    return _lookup(ctx, args, 1)


# ---- dates ------------------------------------------------------------------------------------


def _serial_parts(ctx: BlockContext, node: Node, part: str) -> Values:
    v = to_number(ctx.value(node), ctx.table)
    out = Values.number(0.0, v.shape)
    flat = out.num.reshape(-1)
    for i, serial in enumerate(v.num.ravel()):
        try:
            d = from_excel(float(serial))
        except (ValueError, OverflowError, TypeError):
            d = None
        if d is None:
            out.kind.reshape(-1)[i] = ERROR
            out.err.reshape(-1)[i] = int(XlError.NUM)
            continue
        flat[i] = getattr(d, part)
    out.num = flat.reshape(v.shape)
    return propagate_errors(out, v)


@register("YEAR")
def fn_year(ctx: BlockContext, args: list[Node]) -> Values:
    return _serial_parts(ctx, args[0], "year")


@register("MONTH")
def fn_month(ctx: BlockContext, args: list[Node]) -> Values:
    return _serial_parts(ctx, args[0], "month")


@register("DAY")
def fn_day(ctx: BlockContext, args: list[Node]) -> Values:
    return _serial_parts(ctx, args[0], "day")


@register("DATE")
def fn_date(ctx: BlockContext, args: list[Node]) -> Values:
    y = to_number(ctx.value(args[0]), ctx.table)
    m = to_number(ctx.value(args[1]), ctx.table)
    d = to_number(ctx.value(args[2]), ctx.table)
    shape = np.broadcast_shapes(y.shape, m.shape, d.shape)
    out = Values.number(0.0, shape)
    flat = out.num.reshape(-1)
    ys, ms, ds = (np.broadcast_to(x.num, shape).ravel() for x in (y, m, d))
    for i in range(flat.shape[0]):
        year, month, day = int(ys[i]), int(ms[i]), int(ds[i])
        if year < 1900:
            year += 1900
        # Excel normalises month/day overflow.
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1
        try:
            base = dt.date(year, month, 1) + dt.timedelta(days=day - 1)
            flat[i] = float(to_excel(base))
        except (ValueError, OverflowError):
            out.kind.reshape(-1)[i] = ERROR
            out.err.reshape(-1)[i] = int(XlError.NUM)
    out.num = flat.reshape(shape)
    return propagate_errors(
        out, y.broadcast_to(shape), m.broadcast_to(shape), d.broadcast_to(shape)
    )


SUPPORTED_FUNCTIONS = frozenset(REGISTRY)
__all__ = ["REGISTRY", "SUPPORTED_FUNCTIONS", "UnsupportedFunctionError", "EMPTY", "TEXT", "BOOL"]
