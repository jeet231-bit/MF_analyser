import pytest

from app.model.formula import (
    FormulaParseError,
    Rect,
    a1_text,
    functions_of,
    iter_refs,
    parse_formula,
    r1c1_text,
)
from app.model.formula.ast import (
    Binary,
    Call,
    CellRef,
    ColumnRef,
    RangeRef,
    Unary,
    ref_footprint,
    ref_rect,
)
from app.model.formula.refs import rects_from_mask
from app.model.formula.tokens import tokenize


def key(formula: str, sheet: str = "Calc", row: int = 10, col: int = 5) -> str:
    return r1c1_text(parse_formula(formula, sheet, row, col))


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=A1", "R[-9]C[-4]"),
        ("=$A$1", "R1C1"),
        ("=E10", "RC"),
        ("=E$10", "R10C"),
        ("=Inputs!B3", "Inputs!R[-7]C[-3]"),
        ("='P2P Perf'!$AG:$BH", "'P2P Perf'!C33:C60"),
        ("=Calc!A1", "R[-9]C[-4]"),  # own-sheet prefix is dropped
        ("=$3:$4", "R3:R4"),
        ("=A:M", "C[-4]:C[8]"),
        ("=SUM(A1:A3)*2", "SUM(R[-9]C[-4]:R[-7]C[-4])*2"),
        ('=IF(B3>100,"High","Low")', 'IF(R[-7]C[-3]>100,"High","Low")'),
        ("=sum(a1)", "SUM(R[-9]C[-4])"),
        ("=1.0+2", "1+2"),
        ("= 1 + 2 ", "1+2"),
        ("=-2^2", "-2^2"),
        ("=2^3^2", "2^3^2"),
        ("=2^(3^2)", "2^(3^2)"),
        ("=1+2*3", "1+2*3"),
        ("=(1+2)*3", "(1+2)*3"),
        ('="a""b"&C1', '"a""b"&R[-9]C[-2]'),
        ("=10%", "10%"),
        ("=Threshold*2", "Threshold*2"),
        ("=Inputs!Threshold", "Inputs!Threshold"),
        ("=TRUE", "TRUE"),
        ("=#N/A", "#N/A"),
        ("=IF(A1,,B1)", "IF(R[-9]C[-4],,R[-9]C[-3])"),
        ("=_xlfn.XLOOKUP(1,A:A,B:B)", "XLOOKUP(1,C[-4]:C[-4],C[-3]:C[-3])"),
        ("=Ratings[Rating]", "Ratings[Rating]"),
        ("={1,2;3,4}", "{1,2;3,4}"),
        ("=[1]Sheet1!A1", "[1]Sheet1!A1"),
        ("=A1:INDEX(B:B,3)", "R[-9]C[-4]:INDEX(C[-3]:C[-3],3)"),
        ("=LOG10(A1)", "LOG10(R[-9]C[-4])"),
        ("=1E3", "1000"),
        ("=A1<>B1", "R[-9]C[-4]<>R[-9]C[-3]"),
        ('="x"&A1>=B1', '"x"&R[-9]C[-4]>=R[-9]C[-3]'),
    ],
)
def test_r1c1_canonical_text(formula: str, expected: str) -> None:
    assert key(formula) == expected


def test_copied_formulas_share_a_template() -> None:
    assert key("=B2*$A$1", row=2, col=3) == key("=B9*$A$1", row=9, col=3)
    assert key("=B2*$A$1", row=2, col=3) != key("=B2*$A$1", row=3, col=3)


def test_real_workbook_shapes_parse() -> None:
    f = '=IF(AND($O10="Yes",W10<>"--"),COUNTIFS($V$10:$V$3259,$V10,W$10:W$3259,">"&W10)+1,"--")'
    node = parse_formula(f, "S", 10, 28)
    assert functions_of(node) == ["IF", "AND", "COUNTIFS"]
    shifted = f.replace("$O10", "$O11").replace("W10", "W11").replace("$V10", "$V11")
    assert key(f, "S", 10, 28) == key(shifted, "S", 11, 28)
    g = "=VLOOKUP($P10,$A:$M,HLOOKUP(W$9,$3:$4,2,FALSE),FALSE)"
    node = parse_formula(g, "S", 10, 23)
    refs = list(iter_refs(node))
    assert [type(r).__name__ for r in refs] == ["CellRef", "ColumnRef", "CellRef", "RowRef"]
    assert a1_text(node, 10, 23) == "VLOOKUP($P10,$A:$M,HLOOKUP(W$9,$3:$4,2,FALSE),FALSE)"


def test_a1_rendering_round_trips_at_other_cells() -> None:
    node = parse_formula("=SUM(A1:A3)+Inputs!$B$2", "Calc", 5, 2)
    assert a1_text(node, 5, 2) == "SUM(A1:A3)+Inputs!$B$2"
    assert a1_text(node, 7, 3) == "SUM(B3:B5)+Inputs!$B$2"


def test_structure() -> None:
    node = parse_formula("=IF(A1>1,SUM(B1:B2),-C1)", "S", 1, 1)
    assert isinstance(node, Call) and node.name == "IF"
    cond, then, other = node.args
    assert isinstance(cond, Binary) and cond.op == ">"
    assert isinstance(then, Call) and isinstance(then.args[0], RangeRef)
    assert isinstance(other, Unary) and isinstance(other.operand, CellRef)


@pytest.mark.parametrize("bad", ["=SUM(A1", "=1+", "=A1 B1", "=)", "=IF(A1,1,2))", "=Table[Col"])
def test_parse_errors_are_loud(bad: str) -> None:
    with pytest.raises(FormulaParseError):
        parse_formula(bad, "S", 1, 1)


def test_tokenizer_edge_cases() -> None:
    kinds = [(t.kind, t.text) for t in tokenize('ZZZZ1+XFD1+"a""b"+TRUE+true(1)')][:-1]
    assert kinds[0] == ("name", "ZZZZ1")
    assert kinds[2] == ("ref", "XFD1")
    assert kinds[4] == ("string", '"a""b"')
    assert kinds[6] == ("bool", "TRUE")
    assert kinds[8] == ("func", "true")


def test_ref_rect_and_footprint() -> None:
    node = parse_formula("=SUM(B$2:B2)", "S", 2, 3)
    (ref,) = iter_refs(node)
    assert ref_rect(ref, 2, 3) == Rect(2, 2, 2, 2)
    assert ref_rect(ref, 9, 3) == Rect(2, 2, 9, 2)
    assert ref_footprint(ref, Rect(2, 3, 20, 3)) == Rect(2, 2, 20, 2)

    node = parse_formula("=VLOOKUP($A1,Other!$A:$M,2,FALSE)", "S", 1, 5)
    refs = list(iter_refs(node))
    col = next(r for r in refs if isinstance(r, ColumnRef))
    assert ref_footprint(col, Rect(1, 5, 100, 5), extent=Rect(1, 1, 500, 40)) == Rect(1, 1, 500, 13)
    assert ref_footprint(refs[0], Rect(1, 5, 100, 5)) == Rect(1, 1, 100, 1)


def test_rects_from_mask() -> None:
    import numpy as np

    mask = np.array(
        [
            [1, 1, 0, 1],
            [1, 1, 0, 1],
            [0, 0, 0, 1],
            [1, 0, 0, 0],
        ],
        dtype=bool,
    )
    assert rects_from_mask(mask, row_offset=1, col_offset=1) == [
        Rect(1, 1, 2, 2),
        Rect(1, 4, 3, 4),
        Rect(4, 1, 4, 1),
    ]
    assert rects_from_mask(np.zeros((2, 2), dtype=bool)) == []


def test_rect_from_a1() -> None:
    assert Rect.from_a1("B2:C3") == Rect(2, 2, 3, 3)
    assert Rect.from_a1("A1").to_a1() == "A1"
    assert Rect.from_a1("$A:$C").c2 == 3
    assert Rect(2, 2, 3, 3).intersection(Rect(3, 3, 9, 9)) == Rect(3, 3, 3, 3)
    assert Rect(2, 2, 3, 3).intersection(Rect(4, 4, 9, 9)) is None
