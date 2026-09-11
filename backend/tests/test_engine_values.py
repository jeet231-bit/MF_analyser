"""Excel semantics of the engine's value layer and of single formulas evaluated over a grid."""

import numpy as np
import pytest

from app.engine.evaluator import BlockContext, evaluate_rect
from app.engine.functions import UnsupportedFunctionError
from app.engine.lookups import IndexCache
from app.engine.values import (
    Grid,
    StringTable,
    Values,
    XlError,
    arith,
    compare,
    concat,
    general_format,
)
from app.model.formula.parser import parse_formula
from app.model.formula.refs import Rect


def make_grid(table: StringTable, rows: list[list[object]], sheet: str = "S") -> Grid:
    h, w = len(rows), max(len(r) for r in rows)
    values = Values.empty((h, w))
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = Values.from_python(v, table)
            values.kind[i, j], values.num[i, j] = cell.kind[0, 0], cell.num[0, 0]
            values.code[i, j], values.err[i, j] = cell.code[0, 0], cell.err[0, 0]
    return Grid(sheet, Rect(1, 1, h, w), values)


def evaluate(formula: str, grid: Grid, table: StringTable, cell: str = "A1", names=None) -> object:
    rect = Rect.from_a1(cell)
    ast = parse_formula(formula, grid.sheet, rect.r1, rect.c1)
    ctx = BlockContext(
        sheet=grid.sheet,
        rect=rect,
        grids={grid.sheet: grid},
        table=table,
        indexes=IndexCache(),
        names=names or {},
    )
    return evaluate_rect(ast, ctx).to_python(table)[0, 0]


@pytest.fixture
def table() -> StringTable:
    return StringTable()


@pytest.fixture
def grid(table: StringTable) -> Grid:
    # A: numbers, B: text, C: mixed, D: empty column
    return make_grid(
        table,
        [
            [10, "alpha", "--", None, "Code", "Score"],
            [20, "Beta", 5, None, "A", 1],
            [30, "gamma", None, None, "B", 2],
            ["12", "--", XlError.DIV0, None, "C", 3],
            [True, "Alpha", 0.5, None, None, None],
        ],
    )


def test_general_format() -> None:
    assert general_format(22.8) == "22.8"
    assert general_format(3.0) == "3"
    assert general_format(0.1 + 0.2) == "0.3"
    assert general_format(1e-7) == "1E-07"


def test_arithmetic_coercion(table: StringTable, grid: Grid) -> None:
    assert evaluate("=D1+1", grid, table) == 1  # empty -> 0
    assert evaluate("=A4+1", grid, table) == 13  # numeric text coerces
    assert evaluate("=B1+1", grid, table) == "#VALUE!"
    assert evaluate("=A5+1", grid, table) == 2  # TRUE -> 1
    assert evaluate("=1/0", grid, table) == "#DIV/0!"
    assert evaluate("=C4*2", grid, table) == "#DIV/0!"  # error propagates
    assert evaluate("=-A1^2", grid, table) == 100  # negation binds tighter than ^
    assert evaluate("=A1%", grid, table) == pytest.approx(0.1)


def test_comparisons(table: StringTable, grid: Grid) -> None:
    assert evaluate("=B1=B5", grid, table) is True  # case-insensitive text equality
    assert evaluate("=A1<B1", grid, table) is True  # number < text
    assert evaluate("=B1<A5", grid, table) is True  # text < bool
    assert evaluate("=A1=B1", grid, table) is False
    assert evaluate("=D1=0", grid, table) is True  # empty = 0
    assert evaluate('=D1=""', grid, table) is True  # empty = ""
    assert evaluate('=C1<>"--"', grid, table) is False
    assert evaluate('=C2<>"--"', grid, table) is True
    assert evaluate('="b">"A"', grid, table) is True
    assert evaluate("=C4=1", grid, table) == "#DIV/0!"


def test_concat_and_text(table: StringTable, grid: Grid) -> None:
    assert evaluate('=A1&"x"&D1', grid, table) == "10x"
    assert evaluate('=CONCATENATE(B2,"-",A2)', grid, table) == "Beta-20"
    assert evaluate("=LEFT(B1,3)", grid, table) == "alp"
    assert evaluate('=LEFT(B1,SEARCH("ph",B1)-1)', grid, table) == "al"
    assert evaluate('=SEARCH("ZZ",B1)', grid, table) == "#VALUE!"
    assert evaluate('=ISNUMBER(SEARCH("ALP",B1))', grid, table) is True
    assert evaluate("=ISNUMBER(A4)", grid, table) is False


def test_logic(table: StringTable, grid: Grid) -> None:
    assert evaluate('=IF(A1>5,"big","small")', grid, table) == "big"
    assert evaluate("=IF(D1,1,2)", grid, table) == 2
    assert evaluate('=IFERROR(1/0,"n/a")', grid, table) == "n/a"
    assert evaluate("=IFERROR(A1,0)", grid, table) == 10
    assert evaluate('=AND(A1>5,B1="alpha")', grid, table) is True
    assert evaluate('=OR(A1>50,C1="--")', grid, table) is True
    assert evaluate("=AND(A1:A3>15)", grid, table) is False


def test_aggregates_and_criteria(table: StringTable, grid: Grid) -> None:
    assert evaluate("=SUM(A1:A5)", grid, table) == 60  # text "12" and TRUE ignored in ranges
    assert evaluate("=SUM(A1,A4)", grid, table) == 22  # direct text arg coerces
    assert evaluate("=COUNT(A1:C5)", grid, table) == 5
    assert evaluate("=MAX(A1:A3)", grid, table) == 30
    assert evaluate("=AVERAGE(A1:A3)", grid, table) == 20
    assert evaluate('=COUNTIF(B1:B5,"alpha")', grid, table) == 2
    assert evaluate('=COUNTIF(B1:B5,"*a")', grid, table) == 4  # alpha, Beta, gamma, Alpha
    assert evaluate('=COUNTIF(C1:C5,"<>--")', grid, table) == 4  # includes the empty cell
    assert evaluate('=COUNTIF(A1:A3,">15")', grid, table) == 2
    assert evaluate('=COUNTIFS(A1:A3,">15",B1:B3,"g*")', grid, table) == 1
    assert evaluate('=SUMIF(A1:A3,">15")', grid, table) == 50
    assert evaluate('=SUMIF(E2:E4,"B",F2:F4)', grid, table) == 2
    assert evaluate('=AVERAGEIF(A1:A3,">100")', grid, table) == "#DIV/0!"
    assert evaluate("=SUMPRODUCT(A1:A3,F2:F4)", grid, table) == 10 * 1 + 20 * 2 + 30 * 3
    assert evaluate("=SUMPRODUCT(C1:C3,F2:F4)", grid, table) == 5 * 2  # text and empty count as 0


def test_lookups(table: StringTable, grid: Grid) -> None:
    assert evaluate('=VLOOKUP("b",E2:F4,2,FALSE)', grid, table) == 2  # case-insensitive
    assert evaluate('=VLOOKUP("Z",E2:F4,2,FALSE)', grid, table) == "#N/A"
    assert evaluate('=VLOOKUP("A",E2:F4,3,FALSE)', grid, table) == "#REF!"
    assert evaluate('=HLOOKUP("Score",E1:F4,3,FALSE)', grid, table) == 2
    assert (
        evaluate("=VLOOKUP(25,A1:B3,2,TRUE)", grid, table) == "Beta"
    )  # approximate: largest <= 25
    assert (
        evaluate('=VLOOKUP("A",$E:$F,2,FALSE)', grid, table) == 1
    )  # whole columns clip to the used range


def test_dates(table: StringTable, grid: Grid) -> None:
    serial = evaluate("=DATE(2026,1,31)", grid, table)
    assert serial == 46053
    assert evaluate(f"=YEAR({serial})", grid, table) == 2026
    assert evaluate(f"=MONTH({serial})", grid, table) == 1
    assert evaluate(f"=DAY({serial})", grid, table) == 31
    assert evaluate("=DATE(2026,13,1)", grid, table) == evaluate("=DATE(2027,1,1)", grid, table)


def test_unsupported_function_is_loud(table: StringTable, grid: Grid) -> None:
    with pytest.raises(UnsupportedFunctionError) as info:
        evaluate("=XLOOKUP(1,A1:A3,B1:B3)", grid, table, cell="C9")
    assert info.value.function == "XLOOKUP"
    assert info.value.cell == "C9"


def test_block_vectorisation_matches_cell_by_cell(table: StringTable, grid: Grid) -> None:
    # Evaluate a rank-style COUNTIFS over a whole block at once and compare with per-cell results.
    rect = Rect(1, 7, 3, 7)  # G1:G3
    formula = '=IF(A1>0,COUNTIFS($B$1:$B$3,"*a",$A$1:$A$3,">"&A1)+1,"--")'
    ast = parse_formula(formula, "S", 1, 7)
    ctx = BlockContext(
        sheet="S", rect=rect, grids={"S": grid}, table=table, indexes=IndexCache(), names={}
    )
    block = evaluate_rect(ast, ctx).to_python(table)[:, 0].tolist()
    singles = [
        evaluate(formula.replace("A1", f"A{r}"), grid, table, cell=f"G{r}") for r in (1, 2, 3)
    ]
    assert block == singles == [3, 2, 1]


def test_values_helpers(table: StringTable) -> None:
    a = Values.from_python("x", table)
    b = Values.from_python(2.0, table)
    assert concat(a, b, table).to_python(table)[0, 0] == "x2"
    assert arith("*", b, b, table).to_python(table)[0, 0] == 4
    assert compare("<>", a, b, table).to_python(table)[0, 0] is True
    grid = make_grid(table, [[1, None], [None, "t"]])
    assert grid.window(Rect(2, 2, 3, 3)).kind.tolist() == [
        [2, 0],
        [0, 0],
    ]  # padded outside the extent
    assert np.array_equal(grid.window(Rect(1, 1, 1, 1)).num, np.array([[1.0]]))
