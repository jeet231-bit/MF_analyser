"""Full and incremental runs on the fixture workbook, checked against Excel-style cached values."""

import math
from pathlib import Path

import pytest

from app.engine import Engine, ModelHasCyclesError, OverrideError, UnsupportedFunctionError
from app.engine.lineage import explain
from app.model.interpreter import InterpretOptions, interpret
from app.model.schema import FormulaBlock, WorkbookLogicModel
from app.parser import RawWorkbook, load_raw_workbook
from tests.fixtures.logic_workbook import (
    ROWS,
    SEMANTICS_CACHED,
    cycle_fixture_xlsx_bytes,
    logic_fixture_xlsx_bytes,
)

ENGINE_SCOPE = [
    "Inputs",
    "Lookup",
    "Series",
    "Outputs",
    "Semantics",
]  # Calc holds XLOOKUP (out of contract)


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> RawWorkbook:
    path = tmp_path_factory.mktemp("engine") / "logic.xlsx"
    path.write_bytes(logic_fixture_xlsx_bytes())
    return load_raw_workbook(path)


def build_model(raw: RawWorkbook, scope: list[str] | None) -> WorkbookLogicModel:
    return interpret(
        raw, lambda n: raw.sheet(n), version_id="v", options=InterpretOptions(scope=scope)
    )


@pytest.fixture(scope="module")
def model(raw: RawWorkbook) -> WorkbookLogicModel:
    return build_model(raw, ENGINE_SCOPE)


@pytest.fixture(scope="module")
def engine(raw: RawWorkbook, model: WorkbookLogicModel) -> Engine:
    return Engine(model, raw, lambda n: raw.sheet(n))


def same(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def test_full_run_reproduces_every_cached_value(raw: RawWorkbook, engine: Engine) -> None:
    result = engine.run({})
    assert result.kind == "full"
    assert result.summary.blocks_evaluated == len(engine.model.formula_blocks)
    checked = 0
    mismatches = []
    for sheet in ENGINE_SCOPE:
        rs = raw.sheet(sheet)
        cols = result.formula_values(sheet)
        got = dict(zip(cols["address"], cols["value"], strict=True))
        for addr, formula in rs.formulas():
            expected = rs.cell(addr).value
            checked += 1
            if not same(got.get(addr), expected):
                mismatches.append((sheet, addr, formula, expected, got.get(addr)))
    assert checked == sum(s.formula_cells for s in engine.model.sheets if s.in_scope)
    assert mismatches == []
    assert result.summary.error_cells == sum(
        1 for v in SEMANTICS_CACHED.values() if isinstance(v, str) and v.startswith("#")
    )
    assert result.summary.hot_templates and result.summary.hot_templates[0].seconds >= 0


def test_semantics_sheet_values_are_exact(engine: Engine) -> None:
    got = dict(
        zip(
            *(engine.run({}).formula_values("Semantics")[k] for k in ("address", "value")),
            strict=True,
        )
    )
    for addr, expected in SEMANTICS_CACHED.items():
        assert same(got[addr], expected), (addr, expected, got[addr])


def test_incremental_run_recomputes_exactly_the_descendants(engine: Engine) -> None:
    baseline = engine.run({})
    seed = {s: baseline.formula_values(s) for s in ENGINE_SCOPE}
    g_block = engine.model.block_at("Series", 2, 7)
    assert isinstance(g_block, FormulaBlock)

    result = engine.run({"Inputs!B3": 200}, seed=seed)
    assert result.kind == "incremental"
    assert result.evaluated == [g_block.id]  # only "Above units" reads Inputs!B3 in this scope
    cols = result.formula_values("Series", only_evaluated=True)
    above = dict(zip(cols["address"], cols["value"], strict=True))
    assert len(above) == ROWS
    assert sum(1 for v in above.values() if v is True) == sum(
        1 for i in range(1, ROWS + 1) if 90 + 7 * i > 200
    )
    # Everything else is untouched.
    for sheet in ("Outputs", "Semantics"):
        assert result.formula_values(sheet)["value"] == baseline.formula_values(sheet)["value"]

    # A named input resolves to its cell and reaches exactly its readers.
    quiet = engine.run({"Threshold": 0.5}, seed=seed)
    c28 = engine.model.block_at("Semantics", 28, 3)  # =Threshold*10 is the only reader in scope
    assert isinstance(c28, FormulaBlock)
    assert quiet.kind == "incremental" and quiet.evaluated == [c28.id]

    # Full mode ignores the seed.
    assert engine.run({"Inputs!B3": 200}, mode="full", seed=seed).kind == "full"


def test_override_validation(engine: Engine) -> None:
    with pytest.raises(OverrideError, match="holds a formula"):
        engine.run({"Series!D2": 1}, seed={})
    with pytest.raises(OverrideError, match="not a cell address"):
        engine.run({"NoSuchName": 1}, seed={})
    with pytest.raises(OverrideError, match="not in the workbook"):
        engine.run({"Nope!A1": 1}, seed={})


def test_unsupported_function_fails_before_evaluating(raw: RawWorkbook) -> None:
    full = build_model(raw, None)  # includes Calc with _xlfn.XLOOKUP
    engine = Engine(full, raw, lambda n: raw.sheet(n))
    with pytest.raises(UnsupportedFunctionError) as info:
        engine.run({})
    assert info.value.function == "XLOOKUP"
    assert info.value.sheet == "Calc" and info.value.cell == "B11"


def test_cycles_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "cyc.xlsx"
    path.write_bytes(cycle_fixture_xlsx_bytes())
    raw = load_raw_workbook(path)
    model = build_model(raw, None)
    with pytest.raises(ModelHasCyclesError) as info:
        Engine(model, raw, lambda n: raw.sheet(n)).run({})
    assert info.value.descriptions and "Cyc" in info.value.descriptions[0]


def test_lineage_explains_a_cell(engine: Engine) -> None:
    result = engine.run({})
    values = {
        s: dict(zip(*(result.formula_values(s)[k] for k in ("address", "value")), strict=True))
        for s in ENGINE_SCOPE
    }

    def value_at(sheet: str, row: int, col: int):
        from app.model.formula.refs import a1_cell

        addr = a1_cell(row, col)
        if addr in values.get(sheet, {}):
            return values[sheet][addr], "computed"
        cell = engine.meta.sheet(sheet).cell(addr) if engine.meta.sheet(sheet) else None
        return (cell.value, cell.value_type) if cell else (None, "empty")

    node = explain(
        engine.model, "Series", 5, 6, value_at=value_at, depth=2
    )  # F5 = IFERROR(E5/B5,"n/a")
    assert node.kind == "formula"
    assert node.formula == '=IFERROR(E5/B5,"n/a")'
    reads = {r.range: r for r in node.reads}
    assert set(reads) == {"E5", "B5"}
    assert reads["B5"].cells[0].value == 90 + 7 * 4
    assert reads["E5"].node is not None and reads["E5"].node.formula.startswith("=VLOOKUP(D5,")
    assert reads["E5"].node.reads[0].range == "D5"

    total = explain(engine.model, "Outputs", 1, 2, value_at=value_at)
    assert (
        total.reads[0].range == "B2:B21"
        and total.reads[0].count == ROWS
        and not total.reads[0].truncated
    )
    inp = explain(engine.model, "Inputs", 3, 2, value_at=value_at)
    assert inp.kind == "input" and inp.value == 120
