"""Evaluate one template over one block rectangle, vectorised over the block.

Every AST node evaluates to either a ``Values`` broadcastable to the block shape (R, C) or a
``RangeOperand``: a 4-D window (R', C', h, w) over a sheet grid where R' ∈ {1, R} and
C' ∈ {1, C} depending on whether the range slides with the cell. Relative ranges are
zero-copy sliding-window views.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.engine import functions as F
from app.engine.lookups import IndexCache
from app.engine.values import (
    EMPTY,
    ERROR,
    Grid,
    StringTable,
    Values,
    XlError,
    arith,
    compare,
    concat,
    to_number,
)
from app.model.formula.ast import (
    ArrayConst,
    Axis,
    Binary,
    Bool,
    Call,
    CellRef,
    ColumnRef,
    Empty,
    ErrorLit,
    ExternalRef,
    NameRef,
    Node,
    Number,
    RangeRef,
    RowRef,
    StructuredRef,
    Text,
    Unary,
)
from app.model.formula.refs import MAX_COL, MAX_ROW, Rect


@dataclass
class RangeOperand:
    values: Values  # (R', C', h, w)
    sheet: str
    rect: Rect  # bounding rect on the sheet
    fixed: bool
    valid: np.ndarray | None = None  # (R', C', h, w) mask for ranges whose size varies per cell


class BlockContext:
    def __init__(
        self,
        *,
        sheet: str,
        rect: Rect,
        grids: dict[str, Grid],
        table: StringTable,
        indexes: IndexCache,
        names: dict[str, tuple[str, Rect]],
    ) -> None:
        self.sheet = sheet
        self.rect = rect
        self.grids = grids
        self.table = table
        self.indexes = indexes
        self.names = names
        self.shape = (rect.rows, rect.cols)
        self.current_function = ""

    # ---- helpers used by functions ---------------------------------------------------------
    def value(self, node: Node) -> Values:
        out = self.eval(node)
        if isinstance(out, RangeOperand):
            return self._implicit(out)
        return out

    def range(self, node: Node) -> RangeOperand:
        out = self.eval(node)
        if isinstance(out, RangeOperand):
            return out
        # A scalar/array used where a range is expected: a 1x1 window per cell.
        v = out.broadcast_to(self.shape)
        return RangeOperand(v.reshape((*self.shape, 1, 1)), self.sheet, self.rect, fixed=False)

    def any(self, node: Node) -> Values | RangeOperand:
        return self.eval(node)

    @staticmethod
    def is_range(operand: Values | RangeOperand) -> bool:
        return isinstance(operand, RangeOperand)

    def _implicit(self, rng: RangeOperand) -> Values:
        """Implicit intersection is not supported; a single-cell window degrades gracefully."""
        h, w = rng.values.shape[-2:]
        if h == 1 and w == 1:
            return rng.values[:, :, 0, 0]
        return Values.error(XlError.VALUE)

    def grid(self, sheet: str) -> Grid | None:
        return self.grids.get(sheet)

    def _scalar_binary(self, op: str, left: Values, right: Values) -> Values:
        if op in ("+", "-", "*", "/", "^"):
            return arith(op, left, right, self.table)
        if op == "&":
            return concat(left, right, self.table)
        return compare(op, left, right, self.table)

    def _array_binary(
        self, op: str, left: Values | RangeOperand, right: Values | RangeOperand
    ) -> RangeOperand:
        """Element-wise operator over ranges (array context, e.g. inside AND/SUMPRODUCT)."""

        def lift(x: Values | RangeOperand) -> tuple[Values, np.ndarray | None]:
            if isinstance(x, RangeOperand):
                return x.values, x.valid
            v = x.broadcast_to(self.shape) if x.shape != (1, 1) else x
            return v.reshape((*v.shape, 1, 1)), None

        lv, lvalid = lift(left)
        rv, rvalid = lift(right)
        out = self._scalar_binary(op, lv, rv)
        valid = lvalid if rvalid is None else (rvalid if lvalid is None else (lvalid & rvalid))
        ref = left if isinstance(left, RangeOperand) else right
        assert isinstance(ref, RangeOperand)
        fixed = (
            all(not isinstance(x, RangeOperand) or x.fixed for x in (left, right))
            and out.shape[0] == 1
            and out.shape[1] == 1
        )
        return RangeOperand(out, ref.sheet, ref.rect, fixed=fixed, valid=valid)

    # ---- references ---------------------------------------------------------------------------
    def _axis_bounds(self, axis: Axis, lo: int, hi: int) -> tuple[int, int, bool]:
        """(first, last, slides) for an axis over block coordinates lo..hi."""
        if axis.abs:
            return axis.v, axis.v, False
        return lo + axis.v, hi + axis.v, True

    def cell_operand(self, ref: CellRef) -> Values:
        grid = self.grid(ref.sheet or self.sheet)
        r1, r2, rs = self._axis_bounds(ref.row, self.rect.r1, self.rect.r2)
        c1, c2, cs = self._axis_bounds(ref.col, self.rect.c1, self.rect.c2)
        if r1 < 1 or c1 < 1:
            return Values.error(XlError.REF, self.shape)
        if grid is None:
            return Values.empty((self.rect.rows if rs else 1, self.rect.cols if cs else 1))
        return grid.window(Rect(r1, c1, r2, c2))

    def range_operand(self, ref: RangeRef | ColumnRef | RowRef) -> RangeOperand:
        sheet = ref.sheet or self.sheet
        grid = self.grid(sheet)
        extent = grid.extent if grid is not None else Rect(1, 1, 1, 1)
        R, C = self.shape
        if isinstance(ref, RangeRef):
            ra, rb = ref.r1, ref.r2
            ca, cb = ref.c1, ref.c2
        elif isinstance(ref, ColumnRef):
            ra, rb = Axis(abs=True, v=extent.r1), Axis(abs=True, v=extent.r2)
            ca, cb = ref.c1, ref.c2
        else:
            ra, rb = ref.r1, ref.r2
            ca, cb = Axis(abs=True, v=extent.c1), Axis(abs=True, v=extent.c2)

        def span(a: Axis, b: Axis, lo: int, hi: int, cap: int):
            a_first, a_last, a_slides = self._axis_bounds(a, lo, hi)
            b_first, b_last, b_slides = self._axis_bounds(b, lo, hi)
            first = max(1, min(a_first, b_first))
            last = min(cap, max(a_last, b_last))
            constant = (a_slides == b_slides) or (
                not a_slides and not b_slides
            )  # same offset growth => constant size
            size = (b.at(lo) - a.at(lo) + 1) if constant else None
            return first, last, a_slides or b_slides, size, a, b

        rf, rl, r_slides, r_size, ra_, rb_ = span(ra, rb, self.rect.r1, self.rect.r2, MAX_ROW)
        cf, cl, c_slides, c_size, ca_, cb_ = span(ca, cb, self.rect.c1, self.rect.c2, MAX_COL)
        if rf > rl or cf > cl:
            empty = Values.empty((1, 1, 1, 1))
            return RangeOperand(empty, sheet, Rect(1, 1, 1, 1), fixed=True)
        bound = Rect(rf, cf, rl, cl)
        if grid is None:
            values = Values.empty((bound.rows, bound.cols))
        else:
            values = grid.window(bound)
        fixed = not r_slides and not c_slides
        if fixed:
            return RangeOperand(
                values.reshape((1, 1, bound.rows, bound.cols)), sheet, bound, fixed=True
            )

        if r_size is not None and c_size is not None and r_size > 0 and c_size > 0:
            h = min(r_size, bound.rows)
            w = min(c_size, bound.cols)
            win = Values(
                sliding_window_view(values.kind, (h, w)),
                sliding_window_view(values.num, (h, w)),
                sliding_window_view(values.code, (h, w)),
                sliding_window_view(values.err, (h, w)),
            )
            # Expected (R or 1, C or 1, h, w); clipping at the sheet edge can shorten it.
            want_r = R if r_slides else 1
            want_c = C if c_slides else 1
            if win.shape[0] != want_r or win.shape[1] != want_c:
                win = _pad_windows(win, want_r, want_c)
            # A single window (1x1 block, or no sliding after clipping) is a fixed range.
            return RangeOperand(win, sheet, bound, fixed=(want_r == 1 and want_c == 1))

        # Varying-size range (e.g. B$2:B2 running total): bounding window plus validity mask.
        rows = np.arange(bound.r1, bound.r2 + 1)
        cols = np.arange(bound.c1, bound.c2 + 1)
        block_rows = (
            np.arange(self.rect.r1, self.rect.r2 + 1) if r_slides else np.array([self.rect.r1])
        )
        block_cols = (
            np.arange(self.rect.c1, self.rect.c2 + 1) if c_slides else np.array([self.rect.c1])
        )
        r_lo = np.array([min(ra_.at(r), rb_.at(r)) for r in block_rows])
        r_hi = np.array([max(ra_.at(r), rb_.at(r)) for r in block_rows])
        c_lo = np.array([min(ca_.at(c), cb_.at(c)) for c in block_cols])
        c_hi = np.array([max(ca_.at(c), cb_.at(c)) for c in block_cols])
        valid_r = (rows[None, :] >= r_lo[:, None]) & (rows[None, :] <= r_hi[:, None])  # (R', h)
        valid_c = (cols[None, :] >= c_lo[:, None]) & (cols[None, :] <= c_hi[:, None])  # (C', w)
        valid = valid_r[:, None, :, None] & valid_c[None, :, None, :]
        full = values.reshape((1, 1, bound.rows, bound.cols))
        return RangeOperand(full, sheet, bound, fixed=False, valid=valid)

    # ---- evaluation -----------------------------------------------------------------------
    def eval(self, node: Node) -> Values | RangeOperand:
        if isinstance(node, Number):
            return Values.number(node.value)
        if isinstance(node, Text):
            return Values.text(self.table.intern(node.value))
        if isinstance(node, Bool):
            return Values.boolean(node.value)
        if isinstance(node, ErrorLit):
            return Values.error(XlError.from_text(node.value) or XlError.VALUE)
        if isinstance(node, Empty):
            return Values.empty((1, 1))
        if isinstance(node, CellRef):
            return self.cell_operand(node)
        if isinstance(node, RangeRef | ColumnRef | RowRef):
            return self.range_operand(node)
        if isinstance(node, NameRef):
            target = self.names.get(node.name)
            if target is None:
                return Values.error(XlError.NAME)
            sheet, rect = target
            if rect.cells == 1:
                grid = self.grid(sheet)
                return grid.window(rect) if grid else Values.empty((1, 1))
            return self.range_operand(
                RangeRef(
                    sheet=sheet,
                    r1=Axis(abs=True, v=rect.r1),
                    c1=Axis(abs=True, v=rect.c1),
                    r2=Axis(abs=True, v=rect.r2),
                    c2=Axis(abs=True, v=rect.c2),
                )
            )
        if isinstance(node, StructuredRef | ExternalRef):
            return Values.error(XlError.REF)
        if isinstance(node, Unary):
            operand = self.value(node.operand)
            if node.op == "-":
                return arith("-", Values.number(0.0), operand, self.table)
            if node.op == "%":
                return arith("/", operand, Values.number(100.0), self.table)
            return to_number(operand, self.table)
        if isinstance(node, Binary):
            if node.op == ":":
                return Values.error(XlError.REF)
            left_any = self.any(node.left)
            right_any = self.any(node.right)
            if isinstance(left_any, RangeOperand) or isinstance(right_any, RangeOperand):
                return self._array_binary(node.op, left_any, right_any)
            return self._scalar_binary(node.op, left_any, right_any)
        if isinstance(node, Call):
            impl = F.REGISTRY.get(node.name)
            if impl is None:
                raise F.UnsupportedFunctionError(node.name, self.sheet, self.rect.to_a1())
            previous = self.current_function
            self.current_function = node.name
            try:
                return impl(self, node.args)
            finally:
                self.current_function = previous
        if isinstance(node, ArrayConst):
            rows = [[self.value(a) for a in row] for row in node.rows]
            h, w = len(rows), max(len(r) for r in rows)
            out = Values.empty((1, 1, h, w))
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    out.kind[0, 0, i, j] = v.kind.reshape(-1)[0]
                    out.num[0, 0, i, j] = v.num.reshape(-1)[0]
                    out.code[0, 0, i, j] = v.code.reshape(-1)[0]
                    out.err[0, 0, i, j] = v.err.reshape(-1)[0]
            return RangeOperand(out, self.sheet, Rect(1, 1, h, w), fixed=True)
        raise TypeError(f"cannot evaluate {type(node).__name__}")


def _pad_windows(win: Values, want_r: int, want_c: int) -> Values:
    """Sliding windows near the sheet edge come up short; pad with EMPTY windows."""
    r, c, h, w = win.shape
    out = Values.empty((want_r, want_c, h, w))
    rr, cc = min(r, want_r), min(c, want_c)
    out.kind[:rr, :cc] = win.kind[:rr, :cc]
    out.num[:rr, :cc] = win.num[:rr, :cc]
    out.code[:rr, :cc] = win.code[:rr, :cc]
    out.err[:rr, :cc] = win.err[:rr, :cc]
    return out


def evaluate_rect(ast: Node, ctx: BlockContext) -> Values:
    """Evaluate a template's AST over ctx.rect and return a (R, C) Values."""
    out = ctx.value(ast)
    if out.shape != ctx.shape:
        out = out.materialise(ctx.shape)
    elif not out.kind.flags.writeable:
        out = out.copy()
    return out


def evaluate_array(ast: Node, ctx: BlockContext, target: Rect) -> Values:
    """Array formula: evaluate at the anchor (ctx.rect is 1x1) and spill over ``target``."""
    out = ctx.any(ast)
    result = Values.empty((target.rows, target.cols))
    if isinstance(out, RangeOperand):
        arr = out.values[0, 0]  # (h, w)
        h, w = min(arr.shape[0], target.rows), min(arr.shape[1], target.cols)
        result.kind[:h, :w], result.num[:h, :w] = arr.kind[:h, :w], arr.num[:h, :w]
        result.code[:h, :w], result.err[:h, :w] = arr.code[:h, :w], arr.err[:h, :w]
        if h < target.rows or w < target.cols:  # Excel shows #N/A where the array is shorter
            mask = np.ones((target.rows, target.cols), dtype=bool)
            mask[:h, :w] = False
            result.kind[mask] = ERROR
            result.err[mask] = int(XlError.NA)
        return result
    return out.materialise((target.rows, target.cols))


def evaluate_block(
    ast: Node,
    *,
    sheet: str,
    rect: Rect,
    grids: dict[str, Grid],
    table: StringTable,
    indexes: IndexCache,
    names: dict[str, tuple[str, Rect]],
    self_order: str | None = None,
) -> Values:
    """Evaluate a block; self-dependent blocks are evaluated column- or row-wise in order."""
    if self_order == "left_to_right" and rect.cols > 1:
        out = Values.empty((rect.rows, rect.cols))
        for j in range(rect.cols):
            sub = Rect(rect.r1, rect.c1 + j, rect.r2, rect.c1 + j)
            ctx = BlockContext(
                sheet=sheet, rect=sub, grids=grids, table=table, indexes=indexes, names=names
            )
            part = evaluate_rect(ast, ctx)
            grids[sheet].write(sub, part)
            out.kind[:, j : j + 1], out.num[:, j : j + 1] = part.kind, part.num
            out.code[:, j : j + 1], out.err[:, j : j + 1] = part.code, part.err
        return out
    if self_order == "top_to_bottom" and rect.rows > 1:
        out = Values.empty((rect.rows, rect.cols))
        for i in range(rect.rows):
            sub = Rect(rect.r1 + i, rect.c1, rect.r1 + i, rect.c2)
            ctx = BlockContext(
                sheet=sheet, rect=sub, grids=grids, table=table, indexes=indexes, names=names
            )
            part = evaluate_rect(ast, ctx)
            grids[sheet].write(sub, part)
            out.kind[i : i + 1, :], out.num[i : i + 1, :] = part.kind, part.num
            out.code[i : i + 1, :], out.err[i : i + 1, :] = part.code, part.err
        return out
    if self_order == "row_major" and rect.cells > 1:
        out = Values.empty((rect.rows, rect.cols))
        for i in range(rect.rows):
            for j in range(rect.cols):
                sub = Rect.cell(rect.r1 + i, rect.c1 + j)
                ctx = BlockContext(
                    sheet=sheet, rect=sub, grids=grids, table=table, indexes=indexes, names=names
                )
                part = evaluate_rect(ast, ctx)
                grids[sheet].write(sub, part)
                out.kind[i, j], out.num[i, j] = part.kind[0, 0], part.num[0, 0]
                out.code[i, j], out.err[i, j] = part.code[0, 0], part.err[0, 0]
        return out
    ctx = BlockContext(
        sheet=sheet, rect=rect, grids=grids, table=table, indexes=indexes, names=names
    )
    result = evaluate_rect(ast, ctx)
    grids[sheet].write(rect, result)
    return result


__all__ = ["BlockContext", "RangeOperand", "evaluate_block", "evaluate_rect", "EMPTY", "ERROR"]
