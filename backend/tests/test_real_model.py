"""Scale test: interpret the real master workbook within budget (opt-in, ``-m real``)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dashboard_config import load_dashboard_config
from app.storage import logic, workbooks
from app.storage.db import get_session_factory

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
WORKBOOKS = sorted(SAMPLES.glob("*.xls[xm]")) if SAMPLES.exists() else []
TIME_BUDGET_SECONDS = 120

pytestmark = pytest.mark.real


@pytest.mark.skipif(not WORKBOOKS, reason="no workbook in samples/")
def test_real_workbook_interprets_within_budget(client: TestClient) -> None:
    path = WORKBOOKS[0]
    config = load_dashboard_config()
    with get_session_factory()() as session:
        t0 = time.perf_counter()
        try:
            version = workbooks.ingest_workbook(session, path, filename=path.name)
        except PermissionError:
            pytest.skip(f"{path.name} is locked by another process (is it open in Excel?)")
        ingest_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        model = logic.interpret_version(session, version.id, scope=None, config=config)
        interpret_s = time.perf_counter() - t0

    s = model.summary
    print(
        f"\n{path.name}: ingest {ingest_s:.1f}s | interpret {interpret_s:.1f}s (engine {s.seconds}s) | peak {s.peak_mb} MB"
    )
    print(
        f"scope {len(model.scope)} sheets | templates {s.templates} | formula blocks {s.formula_blocks} | "
        f"input blocks {s.input_blocks} | external {s.external_blocks} | formula cells {s.formula_cells:,} | "
        f"input cells {s.input_cells:,} | output cells {s.output_cells:,} | static {s.static_cells:,} | rules {s.rules}"
    )
    print("roles:", {sh.name: sh.role for sh in model.sheets if sh.in_scope})
    print("sheet edges:", [(e.source, e.target, e.weight) for e in model.sheet_edges])
    print(
        "cycles:",
        model.cycles,
        "| self-dependent blocks:",
        s.self_dependent_blocks,
        "| unresolved:",
        model.unresolved[:5],
    )
    if s.parse_errors:
        print("parse errors:", [t.example_formula for t in model.templates if t.parse_error][:5])

    for text in model.cycle_descriptions:
        print("cycle:", text)

    assert interpret_s < TIME_BUDGET_SECONDS
    assert 100 <= s.templates <= 1000
    assert s.parse_errors == 0
    # The master has one known reference-level circularity (scratch statistics cells parked in
    # a header row that whole-row HLOOKUPs scan). It must be reported, readably, and nothing else.
    assert len(model.cycles) <= 1
    assert len(model.cycle_descriptions) == len(model.cycles)
    assert sum(sh.formula_cells for sh in model.sheets if sh.in_scope) == s.formula_cells
    assert sum(b.cell_count for b in model.formula_blocks) == s.formula_cells  # zero unclassified
    assert s.unresolved_references == 0

    response = client.get(f"/api/workbooks/{version.id}/graph", params={"level": "sheet"})
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == len(model.scope)
