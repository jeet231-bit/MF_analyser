"""Formula AST. References are stored in R1C1 form relative to the template origin.

An ``Axis`` is either absolute (``abs=True``, ``v`` = row/column number) or relative
(``abs=False``, ``v`` = offset from the cell that owns the formula). Two formulas that copy
across a range therefore yield identical ASTs, which is what makes templates possible.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.model.formula.refs import MAX_COL, MAX_ROW, Rect, a1_cell, get_column_letter


class Axis(BaseModel):
    abs: bool
    v: int

    def at(self, base: int) -> int:
        return self.v if self.abs else base + self.v

    def span(self, lo: int, hi: int) -> tuple[int, int]:
        """Range of values this axis takes when the owning cell moves from ``lo`` to ``hi``."""
        return (self.v, self.v) if self.abs else (lo + self.v, hi + self.v)

    def r1c1(self, letter: str) -> str:
        if self.abs:
            return f"{letter}{self.v}"
        return letter if self.v == 0 else f"{letter}[{self.v}]"


class Number(BaseModel):
    kind: Literal["num"] = "num"
    value: float


class Text(BaseModel):
    kind: Literal["str"] = "str"
    value: str


class Bool(BaseModel):
    kind: Literal["bool"] = "bool"
    value: bool


class ErrorLit(BaseModel):
    kind: Literal["err"] = "err"
    value: str


class Empty(BaseModel):
    kind: Literal["empty"] = "empty"


class CellRef(BaseModel):
    kind: Literal["cell"] = "cell"
    sheet: str | None = None
    row: Axis
    col: Axis


class RangeRef(BaseModel):
    kind: Literal["range"] = "range"
    sheet: str | None = None
    r1: Axis
    c1: Axis
    r2: Axis
    c2: Axis


class ColumnRef(BaseModel):
    kind: Literal["cols"] = "cols"
    sheet: str | None = None
    c1: Axis
    c2: Axis


class RowRef(BaseModel):
    kind: Literal["rows"] = "rows"
    sheet: str | None = None
    r1: Axis
    r2: Axis


class NameRef(BaseModel):
    kind: Literal["name"] = "name"
    sheet: str | None = None
    name: str


class StructuredRef(BaseModel):
    kind: Literal["sref"] = "sref"
    table: str | None = None
    spec: str


class ExternalRef(BaseModel):
    kind: Literal["ext"] = "ext"
    text: str


class Unary(BaseModel):
    kind: Literal["unary"] = "unary"
    op: str
    operand: Node


class Binary(BaseModel):
    kind: Literal["binary"] = "binary"
    op: str
    left: Node
    right: Node


class Call(BaseModel):
    kind: Literal["call"] = "call"
    name: str
    args: list[Node]


class ArrayConst(BaseModel):
    kind: Literal["array"] = "array"
    rows: list[list[Node]]


Node = Annotated[
    Union[  # noqa: UP007 - Annotated discriminated union needs Union here
        Number,
        Text,
        Bool,
        ErrorLit,
        Empty,
        CellRef,
        RangeRef,
        ColumnRef,
        RowRef,
        NameRef,
        StructuredRef,
        ExternalRef,
        Unary,
        Binary,
        Call,
        ArrayConst,
    ],
    Field(discriminator="kind"),
]

for _model in (Unary, Binary, Call, ArrayConst):
    _model.model_rebuild()

RefNode = CellRef | RangeRef | ColumnRef | RowRef
AREA_REFS = (CellRef, RangeRef, ColumnRef, RowRef)

# Binding power of binary operators, used for parenthesising when rendering.
BINARY_PRECEDENCE = {
    "=": 10, "<>": 10, "<": 10, ">": 10, "<=": 10, ">=": 10,
    "&": 20,
    "+": 30, "-": 30,
    "*": 40, "/": 40,
    "^": 50,
    ":": 80,
}  # fmt: skip


def iter_nodes(node: Node) -> Iterator[Node]:
    yield node
    if isinstance(node, Unary):
        yield from iter_nodes(node.operand)
    elif isinstance(node, Binary):
        yield from iter_nodes(node.left)
        yield from iter_nodes(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            yield from iter_nodes(a)
    elif isinstance(node, ArrayConst):
        for row in node.rows:
            for a in row:
                yield from iter_nodes(a)


def iter_refs(node: Node) -> Iterator[RefNode]:
    for n in iter_nodes(node):
        if isinstance(n, AREA_REFS):
            yield n


def functions_of(node: Node) -> list[str]:
    seen: dict[str, None] = {}
    for n in iter_nodes(node):
        if isinstance(n, Call):
            seen.setdefault(n.name, None)
    return list(seen)


def quote_sheet(name: str) -> str:
    if name.replace("_", "a").replace(".", "a").isalnum() and not name[0].isdigit():
        return name
    return "'" + name.replace("'", "''") + "'"


def _prefix(sheet: str | None) -> str:
    return "" if sheet is None else quote_sheet(sheet) + "!"


def _num(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _str(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def r1c1_text(node: Node) -> str:
    """Canonical serialisation used as the template key."""
    if isinstance(node, Number):
        return _num(node.value)
    if isinstance(node, Text):
        return _str(node.value)
    if isinstance(node, Bool):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, ErrorLit):
        return node.value
    if isinstance(node, Empty):
        return ""
    if isinstance(node, CellRef):
        return _prefix(node.sheet) + node.row.r1c1("R") + node.col.r1c1("C")
    if isinstance(node, RangeRef):
        return (
            _prefix(node.sheet)
            + node.r1.r1c1("R")
            + node.c1.r1c1("C")
            + ":"
            + node.r2.r1c1("R")
            + node.c2.r1c1("C")
        )
    if isinstance(node, ColumnRef):
        return _prefix(node.sheet) + node.c1.r1c1("C") + ":" + node.c2.r1c1("C")
    if isinstance(node, RowRef):
        return _prefix(node.sheet) + node.r1.r1c1("R") + ":" + node.r2.r1c1("R")
    if isinstance(node, NameRef):
        return _prefix(node.sheet) + node.name
    if isinstance(node, StructuredRef):
        return f"{node.table or ''}[{node.spec}]"
    if isinstance(node, ExternalRef):
        return node.text
    if isinstance(node, Unary):
        inner = r1c1_text(node.operand)
        if isinstance(node.operand, Binary):
            inner = f"({inner})"
        return f"{inner}%" if node.op == "%" else f"{node.op}{inner}"
    if isinstance(node, Binary):
        return _binary(node, r1c1_text)
    if isinstance(node, Call):
        return f"{node.name}({','.join(r1c1_text(a) for a in node.args)})"
    if isinstance(node, ArrayConst):
        return "{" + ";".join(",".join(r1c1_text(a) for a in row) for row in node.rows) + "}"
    raise TypeError(f"unknown node {type(node).__name__}")


def _binary(node: Binary, render) -> str:
    p = BINARY_PRECEDENCE.get(node.op, 0)

    def side(child: Node, right: bool) -> str:
        text = render(child)
        if isinstance(child, Binary):
            cp = BINARY_PRECEDENCE.get(child.op, 0)
            if cp < p or (cp == p and right):
                return f"({text})"
        return text

    return f"{side(node.left, False)}{node.op}{side(node.right, True)}"


def _axis_a1_col(axis: Axis, base_col: int) -> str:
    col = axis.at(base_col)
    letters = get_column_letter(min(max(col, 1), MAX_COL))
    return f"${letters}" if axis.abs else letters


def _axis_a1_row(axis: Axis, base_row: int) -> str:
    row = min(max(axis.at(base_row), 1), MAX_ROW)
    return f"${row}" if axis.abs else str(row)


def a1_text(node: Node, row: int, col: int) -> str:
    """Render the AST as an A1 formula body as it would read in cell (row, col)."""

    def render(n: Node) -> str:
        if isinstance(n, CellRef):
            return _prefix(n.sheet) + _axis_a1_col(n.col, col) + _axis_a1_row(n.row, row)
        if isinstance(n, RangeRef):
            return (
                _prefix(n.sheet)
                + _axis_a1_col(n.c1, col)
                + _axis_a1_row(n.r1, row)
                + ":"
                + _axis_a1_col(n.c2, col)
                + _axis_a1_row(n.r2, row)
            )
        if isinstance(n, ColumnRef):
            return _prefix(n.sheet) + _axis_a1_col(n.c1, col) + ":" + _axis_a1_col(n.c2, col)
        if isinstance(n, RowRef):
            return _prefix(n.sheet) + _axis_a1_row(n.r1, row) + ":" + _axis_a1_row(n.r2, row)
        if isinstance(n, Unary):
            inner = render(n.operand)
            if isinstance(n.operand, Binary):
                inner = f"({inner})"
            return f"{inner}%" if n.op == "%" else f"{n.op}{inner}"
        if isinstance(n, Binary):
            return _binary(n, render)
        if isinstance(n, Call):
            return f"{n.name}({','.join(render(a) for a in n.args)})"
        if isinstance(n, ArrayConst):
            return "{" + ";".join(",".join(render(a) for a in r) for r in n.rows) + "}"
        return r1c1_text(n)

    return render(node)


def ref_rect(ref: RefNode, row: int, col: int, extent: Rect | None = None) -> Rect | None:
    """Exact rectangle a reference denotes when the formula sits at (row, col)."""
    if isinstance(ref, CellRef):
        rect = Rect.cell(ref.row.at(row), ref.col.at(col))
    elif isinstance(ref, RangeRef):
        r1, r2 = ref.r1.at(row), ref.r2.at(row)
        c1, c2 = ref.c1.at(col), ref.c2.at(col)
        rect = Rect(min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
    elif isinstance(ref, ColumnRef):
        c1, c2 = ref.c1.at(col), ref.c2.at(col)
        rect = Rect(1, min(c1, c2), MAX_ROW, max(c1, c2))
    else:
        r1, r2 = ref.r1.at(row), ref.r2.at(row)
        rect = Rect(min(r1, r2), 1, max(r1, r2), MAX_COL)
    return rect.clip(extent) if extent is not None else rect


def ref_footprint(ref: RefNode, block: Rect, extent: Rect | None = None) -> Rect | None:
    """Union of the rectangles a reference denotes across every cell of ``block``."""
    if isinstance(ref, CellRef):
        r1, r2 = ref.row.span(block.r1, block.r2)
        c1, c2 = ref.col.span(block.c1, block.c2)
    elif isinstance(ref, RangeRef):
        a1, a2 = ref.r1.span(block.r1, block.r2)
        b1, b2 = ref.r2.span(block.r1, block.r2)
        r1, r2 = min(a1, b1), max(a2, b2)
        a1, a2 = ref.c1.span(block.c1, block.c2)
        b1, b2 = ref.c2.span(block.c1, block.c2)
        c1, c2 = min(a1, b1), max(a2, b2)
    elif isinstance(ref, ColumnRef):
        a1, a2 = ref.c1.span(block.c1, block.c2)
        b1, b2 = ref.c2.span(block.c1, block.c2)
        c1, c2 = min(a1, b1), max(a2, b2)
        r1, r2 = 1, MAX_ROW
    else:
        a1, a2 = ref.r1.span(block.r1, block.r2)
        b1, b2 = ref.r2.span(block.r1, block.r2)
        r1, r2 = min(a1, b1), max(a2, b2)
        c1, c2 = 1, MAX_COL
    r1, c1 = max(r1, 1), max(c1, 1)
    if r2 < 1 or c2 < 1:
        return None
    rect = Rect(r1, c1, max(r2, r1), max(c2, c1))
    return rect.clip(extent) if extent is not None else rect


def cell_a1(row: int, col: int) -> str:
    return a1_cell(row, col)
