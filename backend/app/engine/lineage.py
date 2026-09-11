"""Explain a cell: its formula, the values it consumed, recursively (lazy cell-level derivation)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.model.formula.ast import a1_text
from app.model.formula.refs import Rect, a1_cell
from app.model.interpreter import cell_dependencies
from app.model.schema import FormulaBlock, InputBlock, WorkbookLogicModel

ValueLookup = Callable[[str, int, int], tuple[Any, str]]  # (sheet, row, col) -> (value, type)
INLINE_LIMIT = 50
SAMPLE = 8


class LineageCell(BaseModel):
    address: str
    value: Any = None
    type: str = "empty"


class LineageRange(BaseModel):
    sheet: str
    range: str
    count: int
    cells: list[LineageCell] = Field(default_factory=list)
    truncated: bool = False
    node: LineageNode | None = None


class LineageNode(BaseModel):
    sheet: str
    cell: str
    kind: str  # formula | input | external | static
    formula: str | None = None
    template_id: int | None = None
    value: Any = None
    type: str = "empty"
    reads: list[LineageRange] = Field(default_factory=list)


LineageRange.model_rebuild()
LineageNode.model_rebuild()


def explain(
    model: WorkbookLogicModel,
    sheet: str,
    row: int,
    col: int,
    *,
    value_at: ValueLookup,
    depth: int = 1,
) -> LineageNode:
    block = model.block_at(sheet, row, col)
    value, vtype = value_at(sheet, row, col)
    if isinstance(block, FormulaBlock):
        tpl = model.template(block.template_id)
        formula = "=" + a1_text(tpl.ast, row, col) if tpl.ast is not None else tpl.example_formula
        node = LineageNode(
            sheet=sheet,
            cell=a1_cell(row, col),
            kind="formula",
            formula=formula,
            template_id=tpl.id,
            value=value,
            type=vtype,
        )
        for dep_sheet, rect in cell_dependencies(model, sheet, row, col):
            node.reads.append(_range(model, dep_sheet, rect, value_at, depth))
        return node
    kind = (
        "input"
        if isinstance(block, InputBlock) and block.kind == "input"
        else "external"
        if isinstance(block, InputBlock)
        else "static"
    )
    return LineageNode(sheet=sheet, cell=a1_cell(row, col), kind=kind, value=value, type=vtype)


def _range(
    model: WorkbookLogicModel, sheet: str, rect: Rect, value_at: ValueLookup, depth: int
) -> LineageRange:
    out = LineageRange(sheet=sheet, range=rect.to_a1(), count=rect.cells)
    limit = INLINE_LIMIT if rect.cells <= INLINE_LIMIT else SAMPLE
    n = 0
    for r in range(rect.r1, rect.r2 + 1):
        for c in range(rect.c1, rect.c2 + 1):
            if n >= limit:
                out.truncated = True
                break
            value, vtype = value_at(sheet, r, c)
            out.cells.append(LineageCell(address=a1_cell(r, c), value=value, type=vtype))
            n += 1
        if out.truncated:
            break
    if (
        rect.cells == 1
        and depth > 1
        and isinstance(model.block_at(sheet, rect.r1, rect.c1), FormulaBlock)
    ):
        out.node = explain(model, sheet, rect.r1, rect.c1, value_at=value_at, depth=depth - 1)
    return out
