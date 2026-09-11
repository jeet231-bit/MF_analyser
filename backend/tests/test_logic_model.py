from pathlib import Path

import pytest

from app.model.formula.refs import Rect
from app.model.interpreter import InterpretOptions, cell_dependencies, cell_dependents, interpret
from app.model.schema import FormulaBlock, WorkbookLogicModel
from app.parser import RawWorkbook, load_raw_workbook
from tests.fixtures.logic_workbook import ROWS, cycle_fixture_xlsx_bytes, logic_fixture_xlsx_bytes


def build(raw: RawWorkbook, **kwargs) -> WorkbookLogicModel:
    return interpret(
        raw, lambda name: raw.sheet(name), version_id="v1", options=InterpretOptions(**kwargs)
    )


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> RawWorkbook:
    path = tmp_path_factory.mktemp("logic") / "logic.xlsx"
    path.write_bytes(logic_fixture_xlsx_bytes())
    return load_raw_workbook(path)


@pytest.fixture(scope="module")
def model(raw: RawWorkbook) -> WorkbookLogicModel:
    return build(raw)


def block_of(model: WorkbookLogicModel, sheet: str, addr: str) -> FormulaBlock:
    r, c = Rect.from_a1(addr).r1, Rect.from_a1(addr).c1
    b = model.block_at(sheet, r, c)
    assert isinstance(b, FormulaBlock), f"{sheet}!{addr} is not in a formula block"
    return b


def test_templates_collapse_copied_formulas(model: WorkbookLogicModel) -> None:
    series = [t for t in model.templates if t.sheet == "Series"]
    assert len(series) == 6  # C2, C3:C21, D, E, F, G
    by_cell = {t.example_cell: t for t in series}
    assert by_cell["D2"].cell_count == ROWS
    assert by_cell["D2"].r1c1 == 'IF(RC[-2]<=120,"Low",IF(RC[-2]<=200,"Mid","High"))'
    assert by_cell["C3"].cell_count == ROWS - 1
    assert by_cell["C3"].r1c1 == "R[-1]C+RC[-1]"
    assert by_cell["E2"].functions == ["VLOOKUP"]
    assert model.summary.parse_errors == 0
    assert model.summary.formula_cells == sum(s.formula_count for s in raw_sheets(model))


def raw_sheets(model: WorkbookLogicModel):
    class _S:
        def __init__(self, n: int) -> None:
            self.formula_count = n

    return [_S(s.formula_cells) for s in model.sheets if s.in_scope]


def test_every_formula_cell_is_in_exactly_one_block(model: WorkbookLogicModel) -> None:
    assert sum(b.cell_count for b in model.formula_blocks) == model.summary.formula_cells
    assert sum(t.cell_count for t in model.templates) == model.summary.formula_cells
    d = block_of(model, "Series", "D2")
    assert d.rect.a1 == "D2:D21"
    assert block_of(model, "Series", "D21").id == d.id


def test_self_dependent_running_total(model: WorkbookLogicModel) -> None:
    b = block_of(model, "Series", "C5")
    assert b.rect.a1 == "C3:C21"
    assert b.self_dependent is True
    assert b.self_order == "top_to_bottom"
    assert model.summary.self_dependent_blocks == 1
    assert model.summary.cycles == 0
    first = block_of(model, "Series", "C2")
    assert model.execution_order.index(first.id) < model.execution_order.index(b.id)


def test_footprints_and_input_blocks(model: WorkbookLogicModel) -> None:
    d = block_of(model, "Series", "D2")
    assert [(f.sheet, f.rect.a1) for f in d.footprints] == [("Series", "B2:B21")]
    g = block_of(model, "Series", "G2")
    assert {(f.sheet, f.rect.a1) for f in g.footprints} == {("Series", "B2:B21"), ("Inputs", "B3")}
    series_inputs = [b for b in model.input_blocks if b.sheet == "Series"]
    assert [b.rect.a1 for b in series_inputs] == ["B2:B21"]
    assert series_inputs[0].cell_count == ROWS
    assert series_inputs[0].value_types == {"number": ROWS}
    assert series_inputs[0].column_labels == ["Sales"]
    sheet = model.sheet("Series")
    assert sheet.input_cells == ROWS
    assert sheet.static_cells == 7 + ROWS  # headers + the unreferenced Month column
    inputs_sheet = model.sheet("Inputs")
    assert {b.rect.a1 for b in model.input_blocks if b.sheet == "Inputs"} == {"B2:B3", "B5"}
    assert inputs_sheet.static_cells == 12 - 3


def test_classification_and_outputs(model: WorkbookLogicModel) -> None:
    assert block_of(model, "Series", "D2").classification == "calculation"  # read by E and Outputs
    assert block_of(model, "Series", "E2").classification == "calculation"  # read by F
    assert block_of(model, "Series", "F2").classification == "output"
    assert block_of(model, "Series", "G2").classification == "output"
    assert all(b.classification == "output" for b in model.formula_blocks if b.sheet == "Outputs")
    assert model.sheet("Outputs").output_cells == 3
    assert model.sheet("Series").output_cells == 2 * ROWS


def test_labels(model: WorkbookLogicModel) -> None:
    assert block_of(model, "Series", "D2").column_labels == ["Band"]
    assert block_of(model, "Series", "C3").column_labels == ["Cumulative"]
    out = block_of(model, "Outputs", "B1")
    assert out.rect.a1 == "B1"  # three different formulas: three templates, three blocks
    assert out.row_label_col == 1
    assert block_of(model, "Outputs", "B3").row_label_col == 1
    inp = next(b for b in model.input_blocks if b.sheet == "Inputs" and b.rect.a1 == "B2:B3")
    assert inp.row_label_col == 1
    assert inp.column_labels == ["Value"]


def test_sheet_roles_and_graph(model: WorkbookLogicModel) -> None:
    roles = {s.name: s.role for s in model.sheets}
    assert roles == {
        "Inputs": "input",
        "Lookup": "reference",
        "Calc": "output",
        "Series": "calculation",
        "Outputs": "output",
        "Semantics": "output",
    }
    assert all(s.role_source == "heuristic" for s in model.sheets)
    edges = {(e.source, e.target) for e in model.sheet_edges}
    assert edges == {
        ("Inputs", "Calc"),
        ("Inputs", "Series"),
        ("Inputs", "Semantics"),
        ("Lookup", "Calc"),
        ("Lookup", "Series"),
        ("Lookup", "Semantics"),
        ("Series", "Outputs"),
    }
    assert model.sheet("Series").feeds == ["Outputs"]
    assert sorted(model.sheet("Series").reads) == ["Inputs", "Lookup"]
    assert model.cycles == []
    assert model.unresolved == []


def test_config_and_user_overrides(raw: RawWorkbook) -> None:
    m = build(
        raw,
        config_role_overrides={"Series": "transformation"},
        user_role_overrides={"Calc": ("calculation", "reviewed")},
    )
    assert m.sheet("Series").role == "transformation"
    assert m.sheet("Series").role_source == "config"
    assert m.sheet("Calc").role == "calculation"
    assert m.sheet("Calc").role_source == "override"
    assert m.sheet("Calc").role_reason == "reviewed"
    m2 = build(raw, output_sheets=["Series"])
    assert m2.sheet("Series").role == "output"
    assert all(b.classification == "output" for b in m2.formula_blocks if b.sheet == "Series")


def test_rules(model: WorkbookLogicModel) -> None:
    by_kind = {}
    for r in model.rules:
        by_kind.setdefault((r.sheet, r.kind), []).append(r)

    band = next(r for r in by_kind[("Series", "condition")] if "Low" in r.description)
    assert band.detail["bands"] == [
        {"condition": "B2<=120", "result": '"Low"'},
        {"condition": "B2<=200", "result": '"Mid"'},
    ]
    assert band.detail["default"] == '"High"'
    assert band.cells == ["D2:D21"]
    assert band.description == 'if B2<=120 → "Low"; if B2<=200 → "Mid"; otherwise → "High"'

    thr = next(r for r in by_kind[("Series", "threshold")] if r.cells == ["G2:G21"])
    (cmp,) = thr.detail["comparisons"]
    assert cmp["op"] == ">"
    assert cmp["reference"] == {"sheet": "Inputs", "cell": "B3", "label": "Units", "value": 120}

    look = next(r for r in by_kind[("Series", "lookup")])
    assert look.detail["table"] == [["Low", 1], ["Mid", 2], ["High", 3]]
    assert look.detail["exact_match"] is True
    assert look.detail["fixed_table"] is True
    assert "Lookup!$D$1:$E$3" in look.description

    fb = next(r for r in by_kind[("Series", "error_fallback")])
    assert fb.detail == {"expression": "E2/B2", "fallback": '"n/a"'}

    calc_lookup = next(r for r in by_kind[("Calc", "lookup")] if r.detail["function"] == "VLOOKUP")
    assert calc_lookup.detail["table"] is None  # relative range: not a fixed table
    assert model.summary.rules == len(model.rules) > 8


def test_scope_makes_out_of_scope_sheets_external(raw: RawWorkbook) -> None:
    m = build(raw, scope=["Lookup", "Calc", "Series", "Outputs"])
    assert m.scope == ["Lookup", "Calc", "Series", "Outputs"]
    assert m.sheet("Inputs").in_scope is False
    ext = [b for b in m.input_blocks if b.kind == "external"]
    assert {b.rect.a1 for b in ext} == {"B2:B3", "B5"}
    assert m.summary.external_blocks == 2
    assert m.summary.sheets_in_scope == 4
    assert m.sheet("Series").role == "calculation"
    with pytest.raises(ValueError, match="not in workbook"):
        build(raw, scope=["Nope"])


def test_cycle_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "cyc.xlsx"
    path.write_bytes(cycle_fixture_xlsx_bytes())
    raw = load_raw_workbook(path)
    m = build(raw)
    assert m.summary.cycles == 1
    assert len(m.cycles) == 1 and len(m.cycles[0]) == 2
    (desc,) = m.cycle_descriptions
    assert desc.startswith("2 blocks on Cyc form a reference cycle [Cyc!A1, Cyc!B1]")
    assert "A1 reads B1 (hits B1)" in desc and "B1 reads A1 (hits A1)" in desc
    a2 = m.block_at("Cyc", 2, 1)
    assert isinstance(a2, FormulaBlock) and a2.id not in m.cycles[0]
    assert set(m.execution_order) == {b.id for b in m.formula_blocks}


def test_lazy_cell_level_dependencies(model: WorkbookLogicModel) -> None:
    assert cell_dependencies(model, "Series", 5, 4) == [("Series", Rect(5, 2, 5, 2))]
    assert cell_dependencies(model, "Outputs", 1, 2) == [("Series", Rect(2, 2, 21, 2))]
    assert cell_dependencies(model, "Series", 2, 1) == []
    dependents = cell_dependents(model, "Series", 5, 2)
    readers = {(b.sheet, b.rect.a1): cells for b, cells in dependents}
    assert readers[("Series", "D2:D21")] == ["D5"]
    assert readers[("Series", "C3:C21")] == ["C5"]
    assert readers[("Outputs", "B1")] == ["B1"]
    assert ("Outputs", "B2") not in readers
    assert ("Series", "E2:E21") not in readers


def test_model_json_round_trip(model: WorkbookLogicModel) -> None:
    again = WorkbookLogicModel.model_validate_json(model.model_dump_json())
    assert again.summary == model.summary
    assert again.templates[0].ast is not None
    assert len(again.model_dump_json()) < 200_000
