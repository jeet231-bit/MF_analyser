"""Engine budgets and a sampled reconciliation on the real master (opt-in, ``-m real``)."""

import math
import random
import time
from pathlib import Path

import pytest

from app.dashboard_config import load_dashboard_config
from app.storage import logic, runs, workbooks
from app.storage.db import get_session_factory

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
WORKBOOKS = (
    sorted(SAMPLES.glob("*.xls[xm]"), key=lambda p: (p.name != "master.xlsx", p.name))
    if SAMPLES.exists()
    else []
)
FULL_BUDGET_S = 90
INCREMENTAL_BUDGET_S = 5
SAMPLE_SIZE = 5000

pytestmark = pytest.mark.real


def same(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


@pytest.mark.skipif(not WORKBOOKS, reason="no workbook in samples/")
def test_real_workbook_runs_within_budget(client) -> None:  # client fixture initialises the DB
    path = WORKBOOKS[0]
    with get_session_factory()() as session:
        try:
            version = workbooks.ingest_workbook(session, path, filename=path.name)
        except PermissionError:
            pytest.skip(f"{path.name} is locked by another process (is it open in Excel?)")
        model = logic.interpret_version(
            session, version.id, scope=None, config=load_dashboard_config()
        )
        assert model.cycles == [], model.cycle_descriptions

        t0 = time.perf_counter()
        full = runs.create_run(session, version.id, {}, "auto")
        full_s = time.perf_counter() - t0
        s = runs.summary_of(full)
        print(
            f"\n{path.name}: full run {full_s:.1f}s (engine {s.seconds}s) | blocks {s.blocks_evaluated} | cells {s.cells_evaluated:,} | errors {s.error_cells:,} | peak {s.peak_mb} MB"
        )
        for h in s.hot_templates:
            print(f"  hot: {h.sheet}!{h.example_cell} x{h.cells:,} -> {h.seconds}s")

        # Sampled reconciliation against Excel's cached values.
        rng = random.Random(7)
        mismatches = []
        checked = 0
        for sheet in model.scope:
            raw = workbooks.load_raw(session, version.id, sheet=sheet).sheets[0]
            formulas = list(raw.formulas())
            if not formulas:
                continue
            computed = runs.formula_values(session, full, sheet)
            share = max(1, round(SAMPLE_SIZE * len(formulas) / s.cells_evaluated))
            for addr, formula in rng.sample(formulas, min(share, len(formulas))):
                expected = raw.cell(addr).value
                got = computed.get(addr, (None, None))[0]
                checked += 1
                if not same(got, expected):
                    mismatches.append((sheet, addr, formula[:80], expected, got))
        rate = 1 - len(mismatches) / max(checked, 1)
        print(
            f"sampled reconciliation: {checked:,} cells, {len(mismatches):,} mismatches, match rate {rate:.4%}"
        )
        for m in mismatches[:15]:
            print("  mismatch:", m)

        # One-input incremental run on a master-data cell.
        # The largest input block is the master data table; a cell on its second row is a
        # typical single-input what-if (the first row may be a header).
        block = max(
            (b for b in model.input_blocks if b.kind == "input"), key=lambda b: b.cell_count
        )
        from app.model.formula.refs import a1_cell

        key = f"{block.sheet}!{a1_cell(block.rect.r1 + 1, block.rect.c1)}"
        t0 = time.perf_counter()
        inc = runs.create_run(session, version.id, {key: "override"}, "auto")
        inc_s = time.perf_counter() - t0
        si = runs.summary_of(inc)
        print(
            f"incremental run on {key}: {inc_s:.1f}s | blocks {si.blocks_evaluated} | cells {si.cells_evaluated:,}"
        )

    assert full_s < FULL_BUDGET_S
    assert rate >= 0.99
    assert inc.kind == "incremental"
    assert inc_s < INCREMENTAL_BUDGET_S
