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
Explainer = Callable[[str, int, int], "tuple[Any, list[dict]] | None"]
INLINE_LIMIT = 50
SAMPLE = 8


def _fmt(v: Any) -> str:
    if v is None:
        return "empty"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return f"{v:.15g}"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def narrate(trace: list[dict], result: Any) -> list[str]:
    """Turn an IF / IFERROR trace into readable lines, innermost decision last."""
    lines: list[str] = []
    for entry in trace:
        if entry.get("kind") == "if":
            outcome = entry.get("result")
            verdict = "TRUE" if outcome else ("FALSE" if outcome is False else "an error")
            if "op" in entry:
                lines.append(
                    f"{entry['condition']}: {_fmt(entry.get('left'))} {entry['op']} "
                    f"{_fmt(entry.get('right'))} is {verdict}"
                )
            else:
                lines.append(f"{entry['condition']} is {verdict}")
        elif entry.get("kind") == "iferror":
            if entry.get("errored"):
                lines.append(
                    f"{entry['expression']} gave {entry.get('error')}; "
                    f"fallback {_fmt(entry.get('fallback'))} used"
                )
            else:
                lines.append(f"{entry['expression']} did not error")
    if lines:
        lines.append(f"Result: {_fmt(result)}")
    return lines


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
    explanation: list[str] | None = Field(
        default=None, description="Which IF / IFERROR branches the formula took, in words"
    )
    rule: str | None = Field(default=None, description="The business rule this template encodes")


LineageRange.model_rebuild()
LineageNode.model_rebuild()

_RULE_PRIORITY = {"condition": 0, "threshold": 1, "lookup": 2, "error_fallback": 3}


def rule_for(model: WorkbookLogicModel, template_id: int) -> str | None:
    rules = sorted(
        (r for r in model.rules if r.template_id == template_id),
        key=lambda r: _RULE_PRIORITY.get(r.kind, 9),
    )
    return rules[0].description if rules else None


def explain(
    model: WorkbookLogicModel,
    sheet: str,
    row: int,
    col: int,
    *,
    value_at: ValueLookup,
    depth: int = 1,
    explainer: Explainer | None = None,
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
            rule=rule_for(model, tpl.id),
        )
        if explainer is not None:
            traced = explainer(sheet, row, col)
            if traced is not None:
                node.explanation = narrate(traced[1], traced[0]) or None
        for dep_sheet, rect in cell_dependencies(model, sheet, row, col):
            node.reads.append(_range(model, dep_sheet, rect, value_at, depth, explainer))
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
    model: WorkbookLogicModel,
    sheet: str,
    rect: Rect,
    value_at: ValueLookup,
    depth: int,
    explainer: Explainer | None = None,
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
        out.node = explain(
            model, sheet, rect.r1, rect.c1, value_at=value_at, depth=depth - 1, explainer=explainer
        )
    return out
