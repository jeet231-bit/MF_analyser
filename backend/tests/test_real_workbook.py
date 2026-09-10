"""Integration checks against the real master workbook in samples/ (skipped when absent).

Run explicitly: ``uv run pytest -m real -s``. Excluded from the default run because parsing a
million-cell workbook takes about a minute.
"""

import time
from pathlib import Path

import pytest

from app.parser import load_raw_workbook

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
WORKBOOKS = sorted(SAMPLES.glob("*.xls[xm]")) if SAMPLES.exists() else []

pytestmark = pytest.mark.real


@pytest.mark.skipif(not WORKBOOKS, reason="no workbook in samples/")
def test_real_workbook_extracts_with_cached_values() -> None:
    path = WORKBOOKS[0]
    started = time.perf_counter()
    raw = load_raw_workbook(path)
    elapsed = time.perf_counter() - started
    summary = raw.summary()

    print(
        f"\n{path.name}: {summary.sheets} sheets, {summary.cells:,} cells, {summary.formula_cells:,} formulas in {elapsed:.1f}s"
    )
    print("functions:", summary.functions)
    print("warnings:", summary.warnings)

    assert summary.sheets > 0
    assert summary.formula_cells > 0
    assert summary.cells == sum(s.cell_count for s in raw.sheets)
    assert summary.formula_cells == sum(s.formula_count for s in raw.sheets)
    assert summary.distinct_functions == len(summary.functions)
    assert all(
        name.isupper() and name.replace(".", "").replace("_", "").isalnum()
        for name in summary.functions
    )

    missing = 0
    for sheet in raw.sheets:
        for formula, value_type in zip(sheet.cells.formula, sheet.cells.value_type, strict=True):
            if formula is not None and value_type == "empty":
                missing += 1
    print(f"formula cells without a cached value: {missing:,}")
    assert missing <= summary.formula_cells * 0.001
