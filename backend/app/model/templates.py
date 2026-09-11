"""Formula templates: dedupe copied formulas into one AST per R1C1 pattern.

Two-stage keying keeps this fast on hundreds of thousands of cells: a regex converts every
formula's references to R1C1 text (no parsing), cells are grouped by that text, and only one
formula per group is parsed. Groups whose ASTs serialise identically are then merged, so
differences in spacing, casing or ``1`` vs ``1.0`` never split a template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openpyxl.utils import column_index_from_string

from app.model.formula.ast import Node, functions_of, r1c1_text
from app.model.formula.parser import FormulaParseError, parse_formula
from app.model.formula.refs import Rect, a1_cell
from app.parser.models import RawSheet

_CELL = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)")
_COLS = re.compile(r"^(\$?)([A-Za-z]{1,3}):(\$?)([A-Za-z]{1,3})$")
_ROWS = re.compile(r"^(\$?)(\d+):(\$?)(\d+)$")
_COMBINED = re.compile(
    r'"(?:[^"]|"")*"'
    r"|(?:(?:'(?:[^']|'')+'|[A-Za-z0-9_.]+)!)?"
    r"(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d+:\$?\d+)"
    r"(?![A-Za-z0-9_.(\[])"
)


def _axis_text(letter: str, absolute: str, value: int, base: int) -> str:
    if absolute:
        return f"{letter}{value}"
    d = value - base
    return letter if d == 0 else f"{letter}[{d}]"


def _cell_r1c1(m: re.Match[str], row: int, col: int) -> str:
    cabs, letters, rabs, digits = m.groups()
    return _axis_text("R", rabs, int(digits), row) + _axis_text(
        "C", cabs, column_index_from_string(letters.upper()), col
    )


def fast_r1c1_key(formula: str, row: int, col: int) -> str:
    """R1C1 text of ``formula`` relative to (row, col), leaving string literals untouched."""

    def convert(m: re.Match[str]) -> str:
        text = m.group(0)
        if text.startswith('"'):
            return text
        body = m.group(1)
        prefix = text[: len(text) - len(body)]
        if cm := _COLS.match(body):
            a1, l1, a2, l2 = cm.groups()
            body = (
                _axis_text("C", a1, column_index_from_string(l1.upper()), col)
                + ":"
                + _axis_text("C", a2, column_index_from_string(l2.upper()), col)
            )
        elif rm := _ROWS.match(body):
            a1, d1, a2, d2 = rm.groups()
            body = _axis_text("R", a1, int(d1), row) + ":" + _axis_text("R", a2, int(d2), row)
        else:
            body = _CELL.sub(lambda cm: _cell_r1c1(cm, row, col), body)
        return prefix + body

    return _COMBINED.sub(convert, formula)


@dataclass
class TemplateDraft:
    id: int
    sheet: str
    key: str
    ast: Node | None
    example_row: int
    example_col: int
    example_formula: str
    parse_error: str | None = None
    array_ref: str | None = None
    functions: list[str] = field(default_factory=list)
    cells: list[tuple[int, int]] = field(default_factory=list)
    block_rects: list[Rect] = field(default_factory=list)

    @property
    def cell_count(self) -> int:
        return len(self.cells) + sum(r.cells for r in self.block_rects)


class TemplateRegistry:
    def __init__(self) -> None:
        self.templates: list[TemplateDraft] = []
        self._by_key: dict[tuple[str, str], TemplateDraft] = {}

    def add_sheet(self, sheet: RawSheet) -> list[TemplateDraft]:
        """Group the sheet's formula cells into templates and compute their block rectangles."""
        c = sheet.cells
        groups: dict[str, list[tuple[int, int]]] = {}
        first: dict[str, tuple[int, int, str, str | None]] = {}
        for _addr, formula, row, col, array_ref in zip(
            c.address, c.formula, c.row, c.col, c.array_ref, strict=True
        ):
            if formula is None:
                continue
            if array_ref is not None:
                anchor = Rect.from_a1(array_ref)
                fast = f"{array_ref}|" + fast_r1c1_key(formula, anchor.r1, anchor.c1)
                if fast not in first:
                    first[fast] = (anchor.r1, anchor.c1, formula, array_ref)
            else:
                fast = fast_r1c1_key(formula, row, col)
                if fast not in first:
                    first[fast] = (row, col, formula, None)
            groups.setdefault(fast, []).append((row, col))

        touched: dict[int, TemplateDraft] = {}
        for fast, cells in groups.items():
            row, col, formula, array_ref = first[fast]
            ast: Node | None = None
            parse_error: str | None = None
            try:
                ast = parse_formula(formula, sheet.name, row, col)
                canonical = r1c1_text(ast)
            except FormulaParseError as exc:
                parse_error = str(exc)
                canonical = "!" + fast
            if array_ref is not None:
                canonical = f"{{{canonical}}}@{array_ref}"
            key = (sheet.name, canonical)
            draft = self._by_key.get(key)
            if draft is None:
                draft = TemplateDraft(
                    id=len(self.templates),
                    sheet=sheet.name,
                    key=canonical,
                    ast=ast,
                    example_row=row,
                    example_col=col,
                    example_formula=formula,
                    parse_error=parse_error,
                    array_ref=array_ref,
                    functions=functions_of(ast) if ast is not None else [],
                )
                self.templates.append(draft)
                self._by_key[key] = draft
            draft.cells.extend(cells)
            touched[draft.id] = draft

        for draft in touched.values():
            draft.block_rects.extend(rects_from_cells(draft.cells))
            draft.cells = []
        return list(touched.values())

    @property
    def example_cell(self) -> str:
        raise AttributeError


def example_cell(draft: TemplateDraft) -> str:
    return a1_cell(draft.example_row, draft.example_col)


def rects_from_cells(cells: list[tuple[int, int]]) -> list[Rect]:
    """Cover a set of (row, col) cells with maximal row-run rectangles (same rule as rects_from_mask)."""
    by_row: dict[int, list[int]] = {}
    for r, c in cells:
        by_row.setdefault(r, []).append(c)
    open_rects: dict[tuple[int, int], list[int]] = {}
    done: list[Rect] = []
    prev_row: int | None = None
    for r in sorted(by_row):
        if prev_row is not None and r != prev_row + 1:
            done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
            open_rects = {}
        cols = sorted(set(by_row[r]))
        runs: set[tuple[int, int]] = set()
        start = cols[0]
        last = cols[0]
        for col in cols[1:]:
            if col == last + 1:
                last = col
            else:
                runs.add((start, last))
                start = last = col
        runs.add((start, last))
        next_open: dict[tuple[int, int], list[int]] = {}
        for key in runs:
            if key in open_rects:
                open_rects[key][1] = r
                next_open[key] = open_rects.pop(key)
            else:
                next_open[key] = [r, r]
        done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
        open_rects = next_open
        prev_row = r
    done.extend(Rect(v[0], k[0], v[1], k[1]) for k, v in open_rects.items())
    return sorted(done)
