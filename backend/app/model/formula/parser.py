"""Pratt parser producing an R1C1-relative AST for a formula at a given cell.

Excel precedence, tightest first: reference ':' , negation, '%', '^', '* /', '+ -', '&',
comparisons. Note that in Excel negation binds tighter than '^' (so -2^2 = 4) and '^' is
left-associative.
"""

from __future__ import annotations

from openpyxl.utils import column_index_from_string

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
from app.model.formula.tokens import Token, TokenizeError, tokenize
from app.parser.inventory import normalise_function_name

COMPARISON = ("=", "<>", "<", ">", "<=", ">=")
# (left binding power, right binding power)
BINARY_BP: dict[str, tuple[int, int]] = {
    **{op: (10, 11) for op in COMPARISON},
    "&": (20, 21),
    "+": (30, 31),
    "-": (30, 31),
    "*": (40, 41),
    "/": (40, 41),
    "^": (50, 51),
    ":": (80, 81),
}
PREFIX_BP = 60
POSTFIX_PERCENT_BP = 70


class FormulaParseError(ValueError):
    def __init__(self, message: str, formula: str, pos: int | None = None) -> None:
        where = f" at position {pos}" if pos is not None else ""
        super().__init__(f"{message}{where} in {formula!r}")
        self.formula = formula
        self.pos = pos


def _axis(token_part: str, is_col: bool, base: int) -> Axis:
    absolute = token_part.startswith("$")
    raw = token_part.lstrip("$")
    value = column_index_from_string(raw.upper()) if is_col else int(raw)
    return Axis(abs=True, v=value) if absolute else Axis(abs=False, v=value - base)


def _split_cell(part: str) -> tuple[str, str]:
    """'$AB$12' -> ('$AB', '$12')."""
    i = 0
    if part[i] == "$":
        i += 1
    while i < len(part) and part[i].isalpha():
        i += 1
    return part[:i], part[i:]


def make_ref(body: str, sheet: str | None, own_sheet: str, row: int, col: int) -> Node:
    if sheet is not None and sheet.casefold() == own_sheet.casefold():
        sheet = None
    parts = body.split(":")
    if len(parts) == 1:
        c, r = _split_cell(parts[0])
        return CellRef(sheet=sheet, row=_axis(r, False, row), col=_axis(c, True, col))
    a, b = parts
    if a.lstrip("$").isdigit():
        return RowRef(sheet=sheet, r1=_axis(a, False, row), r2=_axis(b, False, row))
    if a.lstrip("$").isalpha():
        return ColumnRef(sheet=sheet, c1=_axis(a, True, col), c2=_axis(b, True, col))
    ca, ra = _split_cell(a)
    cb, rb = _split_cell(b)
    return RangeRef(
        sheet=sheet,
        r1=_axis(ra, False, row),
        c1=_axis(ca, True, col),
        r2=_axis(rb, False, row),
        c2=_axis(cb, True, col),
    )


class _Parser:
    def __init__(self, tokens: list[Token], formula: str, sheet: str, row: int, col: int) -> None:
        self.tokens = tokens
        self.i = 0
        self.formula = formula
        self.sheet = sheet
        self.row = row
        self.col = col

    def peek(self) -> Token:
        return self.tokens[self.i]

    def next(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect_op(self, text: str) -> None:
        tok = self.next()
        if tok.kind != "op" or tok.text != text:
            raise FormulaParseError(f"expected {text!r}, found {tok.text!r}", self.formula, tok.pos)

    def error(self, message: str, tok: Token) -> FormulaParseError:
        return FormulaParseError(message, self.formula, tok.pos)

    def parse(self) -> Node:
        node = self.expression(0)
        tok = self.peek()
        if tok.kind != "eof":
            raise self.error(f"unexpected {tok.text!r}", tok)
        return node

    def expression(self, min_bp: int) -> Node:
        left = self.prefix()
        while True:
            tok = self.peek()
            if tok.kind != "op":
                break
            if tok.text == "%":
                if POSTFIX_PERCENT_BP < min_bp:
                    break
                self.next()
                left = Unary(op="%", operand=left)
                continue
            bp = BINARY_BP.get(tok.text)
            if bp is None:
                break
            lbp, rbp = bp
            if lbp < min_bp:
                break
            self.next()
            right = self.expression(rbp)
            left = Binary(op=tok.text, left=left, right=right)
        return left

    def prefix(self) -> Node:
        tok = self.next()
        if tok.kind == "number":
            return Number(value=float(tok.text))
        if tok.kind == "string":
            return Text(value=tok.text[1:-1].replace('""', '"'))
        if tok.kind == "bool":
            return Bool(value=tok.text == "TRUE")
        if tok.kind == "error":
            return ErrorLit(value=tok.text)
        if tok.kind == "ref":
            return make_ref(tok.text, tok.sheet, self.sheet, self.row, self.col)
        if tok.kind == "external":
            return ExternalRef(text=tok.text)
        if tok.kind == "name":
            return NameRef(sheet=tok.sheet, name=tok.text)
        if tok.kind == "sref":
            table, _, spec = tok.text.partition("[")
            return StructuredRef(table=table or None, spec=spec[:-1])
        if tok.kind == "func":
            return self.call(tok)
        if tok.kind == "op":
            if tok.text == "(":
                node = self.expression(0)
                self.expect_op(")")
                return node
            if tok.text in ("-", "+"):
                operand = self.expression(PREFIX_BP)
                return Unary(op=tok.text, operand=operand)
            if tok.text == "{":
                return self.array()
        raise self.error(
            f"unexpected {tok.text!r}" if tok.text else "unexpected end of formula", tok
        )

    def call(self, func: Token) -> Node:
        name = normalise_function_name(func.text)
        self.expect_op("(")
        args: list[Node] = []
        if self.peek().kind == "op" and self.peek().text == ")":
            self.next()
            return Call(name=name, args=args)
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.text in (",", ")"):
                args.append(Empty())
            else:
                args.append(self.expression(0))
            tok = self.next()
            if tok.kind == "op" and tok.text == ",":
                continue
            if tok.kind == "op" and tok.text == ")":
                return Call(name=name, args=args)
            raise self.error(f"expected ',' or ')' in {name}(), found {tok.text!r}", tok)

    def array(self) -> Node:
        rows: list[list[Node]] = [[]]
        while True:
            rows[-1].append(self.expression(0))
            tok = self.next()
            if tok.kind == "op" and tok.text == ",":
                continue
            if tok.kind == "op" and tok.text == ";":
                rows.append([])
                continue
            if tok.kind == "op" and tok.text == "}":
                return ArrayConst(rows=rows)
            raise self.error(f"unexpected {tok.text!r} in array constant", tok)


def parse_formula(formula: str, sheet: str, row: int, col: int) -> Node:
    """Parse ``formula`` (with or without leading '=') as it sits in cell (row, col) of ``sheet``."""
    body = formula.strip()
    if body.startswith("{=") and body.endswith("}"):
        body = body[2:-1]
    elif body.startswith("="):
        body = body[1:]
    try:
        tokens = tokenize(body)
    except TokenizeError as exc:
        raise FormulaParseError(str(exc), formula, exc.pos) from exc
    return _Parser(tokens, formula, sheet, row, col).parse()
