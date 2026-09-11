"""Scope closure: which sheets a set of sheets reads, derived from formula text alone."""

from pathlib import Path

import pytest

from app.model.scope import missing_upstream, sheet_references, upstream_closure
from app.parser import RawWorkbook, load_raw_workbook
from tests.fixtures.logic_workbook import logic_fixture_xlsx_bytes


def _raw(tmp_path: Path, **variant) -> RawWorkbook:
    path = tmp_path / "logic.xlsx"
    path.write_bytes(logic_fixture_xlsx_bytes(**variant))
    return load_raw_workbook(path)


def _loader(raw: RawWorkbook):
    return lambda name: raw.sheet(name)


def test_sheet_references_counts_other_sheets_and_ignores_string_literals(tmp_path) -> None:
    raw = _raw(tmp_path)
    refs = sheet_references(raw.sheet("Series"))
    assert set(refs) == {"Lookup", "Inputs"}
    assert refs["Lookup"] == 20  # one VLOOKUP per row
    assert "Series" not in sheet_references(raw.sheet("Semantics"))  # no cross-sheet formulas


def test_upstream_closure_is_transitive_and_in_workbook_order(tmp_path) -> None:
    raw = _raw(tmp_path)
    closure = upstream_closure(raw, _loader(raw), ["Outputs"])
    assert closure.sheets == ["Inputs", "Lookup", "Series", "Outputs"]
    assert closure.unresolved == []
    assert upstream_closure(raw, _loader(raw), ["Calc"]).sheets == ["Inputs", "Lookup", "Calc"]
    # Semantics' HLOOKUP-over-headers case reads the Lookup sheet.
    assert upstream_closure(raw, _loader(raw), ["Semantics"]).sheets == ["Lookup", "Semantics"]


def test_quoted_sheet_names_are_followed(tmp_path) -> None:
    raw = _raw(tmp_path, series_name="My Series")
    closure = upstream_closure(raw, _loader(raw), ["Outputs"])
    assert closure.sheets == ["Inputs", "Lookup", "My Series", "Outputs"]


def test_missing_upstream_names_the_gap(tmp_path) -> None:
    raw = _raw(tmp_path)
    assert missing_upstream(raw, _loader(raw), ["Series", "Outputs"]) == ["Inputs", "Lookup"]
    assert missing_upstream(raw, _loader(raw), ["Inputs", "Lookup", "Series", "Outputs"]) == []


def test_unknown_seed_is_an_error(tmp_path) -> None:
    raw = _raw(tmp_path)
    with pytest.raises(ValueError, match="Nope"):
        upstream_closure(raw, _loader(raw), ["Nope"])
