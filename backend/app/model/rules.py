"""Business-rule extraction from template ASTs (one pass per template, never per cell)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.model.formula.ast import (
    AREA_REFS,
    Binary,
    Call,
    CellRef,
    ColumnRef,
    Node,
    Number,
    RangeRef,
    RowRef,
    a1_text,
    iter_nodes,
    ref_rect,
)
from app.model.formula.refs import Rect, a1_cell
from app.model.schema import BusinessRule, Template

COMPARISONS = {"=", "<>", "<", ">", "<=", ">="}
LOOKUPS = {"VLOOKUP": 1, "HLOOKUP": 1, "XLOOKUP": 1, "LOOKUP": 1}
SMALL_TABLE_ROWS = 50
SMALL_TABLE_COLS = 10

ValuesProvider = Callable[[str, Rect], list[list[Any]] | None]
LabelProvider = Callable[[str, int, int], str | None]


def _abs_cell(node: Node) -> bool:
    return isinstance(node, CellRef) and node.row.abs and node.col.abs


def _is_if(node: Node) -> bool:
    return isinstance(node, Call) and node.name in ("IF", "IFS")


def _bands(node: Call, render: Callable[[Node], str]) -> tuple[list[dict[str, str]], str | None]:
    bands: list[dict[str, str]] = []
    default: str | None = None
    current: Node | None = node
    while current is not None:
        if isinstance(current, Call) and current.name == "IF":
            args = current.args + [None] * (3 - len(current.args))  # type: ignore[list-item]
            cond, then, other = args[0], args[1], args[2]
            bands.append(
                {"condition": render(cond), "result": render(then) if then is not None else "TRUE"}
            )
            current = other
            if current is not None and not _is_if(current):
                default = render(current)
                current = None
        elif isinstance(current, Call) and current.name == "IFS":
            pairs = current.args
            for i in range(0, len(pairs) - 1, 2):
                bands.append({"condition": render(pairs[i]), "result": render(pairs[i + 1])})
            current = None
        else:
            current = None
    return bands, default


def _describe_bands(bands: list[dict[str, str]], default: str | None) -> str:
    parts = [f"if {b['condition']} → {b['result']}" for b in bands]
    if default is not None:
        parts.append(f"otherwise → {default}")
    return "; ".join(parts)


def extract_rules(
    template: Template,
    block_ranges: list[str],
    *,
    values: ValuesProvider,
    label: LabelProvider,
    next_id: Callable[[], int],
) -> list[BusinessRule]:
    if template.ast is None:
        return []
    ast = template.ast
    r, c = _example_rc(template)
    sheet = template.sheet

    def render(node: Node) -> str:
        return a1_text(node, r, c)

    rules: list[BusinessRule] = []

    # Condition trees: outermost IF/IFS nodes only; nested else-chains become bands.
    outer_ifs = _outermost(ast, _is_if)
    for node in outer_ifs:
        bands, default = _bands(node, render)  # type: ignore[arg-type]
        rules.append(
            BusinessRule(
                id=next_id(),
                kind="condition",
                template_id=template.id,
                sheet=sheet,
                cells=block_ranges,
                description=_describe_bands(bands, default),
                detail={"bands": bands, "default": default, "nested": len(bands) > 1},
            )
        )

    # Thresholds: comparisons against literals or absolute single cells.
    comparisons: list[dict[str, Any]] = []
    for node in iter_nodes(ast):
        if not (isinstance(node, Binary) and node.op in COMPARISONS):
            continue
        for side, other in ((node.right, node.left), (node.left, node.right)):
            reference = None
            if isinstance(side, Number):
                kind = "literal"
            elif _abs_cell(side):
                kind = "cell"
                rect = ref_rect(side, r, c)
                target_sheet = side.sheet or sheet
                assert rect is not None
                cell_values = values(target_sheet, rect)
                reference = {
                    "sheet": target_sheet,
                    "cell": rect.to_a1(),
                    "label": label(target_sheet, rect.r1, rect.c1),
                    "value": cell_values[0][0] if cell_values else None,
                }
            else:
                continue
            comparisons.append(
                {
                    "left": render(other),
                    "op": node.op,
                    "right": render(side),
                    "against": kind,
                    "reference": reference,
                }
            )
            break
    if comparisons:
        text = "; ".join(f"{cmp['left']} {cmp['op']} {cmp['right']}" for cmp in comparisons)
        rules.append(
            BusinessRule(
                id=next_id(),
                kind="threshold",
                template_id=template.id,
                sheet=sheet,
                cells=block_ranges,
                description=text,
                detail={"comparisons": comparisons},
            )
        )

    # Lookups: classification bands when the table is small and constant.
    for node in iter_nodes(ast):
        if not (isinstance(node, Call) and node.name in LOOKUPS and len(node.args) >= 2):
            continue
        range_node = node.args[LOOKUPS[node.name]]
        if not isinstance(range_node, AREA_REFS):
            continue
        target_sheet = range_node.sheet or sheet
        rect = ref_rect(range_node, r, c)
        table = None
        fixed = _fully_absolute(range_node)
        if (
            rect is not None
            and fixed
            and rect.rows <= SMALL_TABLE_ROWS
            and rect.cols <= SMALL_TABLE_COLS
        ):
            table = values(target_sheet, rect)
        exact = None
        if node.name in ("VLOOKUP", "HLOOKUP") and len(node.args) >= 4:
            exact = render(node.args[3]).upper() in ("FALSE", "0")
        detail: dict[str, Any] = {
            "function": node.name,
            "key": render(node.args[0]),
            "sheet": target_sheet,
            "range": render(range_node),
            "fixed_table": fixed,
            "exact_match": exact,
            "return": render(node.args[2]) if len(node.args) > 2 else None,
            "table": table,
        }
        desc = f"{node.name}: look up {detail['key']} in {target_sheet}!{detail['range']}"
        if detail["return"] is not None:
            desc += f", return {detail['return']}"
        if exact is not None:
            desc += " (exact match)" if exact else " (approximate match)"
        if table:
            desc += f"; table of {len(table)} rows"
        rules.append(
            BusinessRule(
                id=next_id(),
                kind="lookup",
                template_id=template.id,
                sheet=sheet,
                cells=block_ranges,
                description=desc,
                detail=detail,
            )
        )

    # Error fallbacks.
    for node in iter_nodes(ast):
        if isinstance(node, Call) and node.name == "IFERROR" and len(node.args) == 2:
            rules.append(
                BusinessRule(
                    id=next_id(),
                    kind="error_fallback",
                    template_id=template.id,
                    sheet=sheet,
                    cells=block_ranges,
                    description=f"if {render(node.args[0])} errors → {render(node.args[1])}",
                    detail={"expression": render(node.args[0]), "fallback": render(node.args[1])},
                )
            )
    return rules


def _outermost(ast: Node, pred: Callable[[Node], bool]) -> list[Node]:
    found: list[Node] = []

    def walk(node: Node) -> None:
        if pred(node):
            found.append(node)
            return
        for child in _children(node):
            walk(child)

    walk(ast)
    return found


def _children(node: Node) -> list[Node]:
    from app.model.formula.ast import ArrayConst, Unary

    if isinstance(node, Unary):
        return [node.operand]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, Call):
        return list(node.args)
    if isinstance(node, ArrayConst):
        return [a for row in node.rows for a in row]
    return []


def _fully_absolute(ref: Node) -> bool:
    if isinstance(ref, CellRef):
        return ref.row.abs and ref.col.abs
    if isinstance(ref, RangeRef):
        return all(a.abs for a in (ref.r1, ref.c1, ref.r2, ref.c2))
    if isinstance(ref, ColumnRef):
        return ref.c1.abs and ref.c2.abs
    if isinstance(ref, RowRef):
        return ref.r1.abs and ref.r2.abs
    return False


def _example_rc(template: Template) -> tuple[int, int]:
    from app.model.formula.refs import parse_a1_cell

    return parse_a1_cell(template.example_cell)


def block_ranges_a1(rects: list[Rect]) -> list[str]:
    return [r.to_a1() for r in rects]


__all__ = ["extract_rules", "block_ranges_a1", "a1_cell"]
