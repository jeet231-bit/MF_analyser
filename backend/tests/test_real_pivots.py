"""The master's pivots against Excel's own cached pivot output (opt-in, ``-m real``): the
pivot Excel refreshed last (the composite one) must reconcile cell for cell; every other
pivot must compute without error, and the refresh dates say which cached outputs are stale."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.dashboard_config import load_dashboard_config
from app.model.formula.refs import Rect
from app.research import pivot as pe
from app.storage import logic, validation, workbooks
from app.storage import pivots as pivot_store
from app.storage import runs as run_store
from app.storage import views as view_store
from app.storage.db import get_session_factory
from tests.test_real_engine import WORKBOOKS  # the same sample discovery

pytestmark = pytest.mark.real


@pytest.mark.skipif(not WORKBOOKS, reason="no workbook in samples/")
def test_pivots_recompute_and_the_freshest_reconciles(client: TestClient) -> None:
    with get_session_factory()() as session:
        try:
            version = workbooks.ingest_workbook(session, WORKBOOKS[0], filename=WORKBOOKS[0].name)
        except PermissionError:
            pytest.skip("master is locked by another process")
        logic.interpret_version(session, version.id, scope=None, config=load_dashboard_config())
        validation.validate_version(session, version.id)
        run = run_store.baseline_run(session, version.id)
        assert run is not None
        specs = pivot_store.specs_for(session, version)
        assert len(specs) >= 10, [s.sheet for s in specs]
        model = logic.get_model(session, version.id)
        in_scope = {m.name for m in model.sheets if m.in_scope}

        freshest = max(specs, key=lambda s: s.refreshed or "")
        report = []
        for spec in specs:
            frame = pe.load_frame(session, version, run, spec, spec.source_sheet in in_scope)
            table = pe.compute(frame, pe.PivotQuery.default_for(spec))
            assert table["records"] == spec.records, spec.sheet
            report.append((spec.sheet, spec.refreshed, frame.live, table["matched"]))
        print("\npivots:", *report, sep="\n  ")

        # Single-row-field pivots refreshed the same day as the freshest one: compare with
        # Excel's cached output (compact layout: label in the first column, values follow).
        checked = mismatches = 0
        for spec in specs:
            if (
                len(spec.rows) != 1
                or spec.cols
                or (spec.refreshed or "")[:10] != (freshest.refreshed or "")[:10]
            ):
                continue
            frame = pe.load_frame(session, version, run, spec, spec.source_sheet in in_scope)
            table = pe.compute(frame, pe.PivotQuery.default_for(spec))
            ours = {r["keys"][0]: [c for g in r["cells"] for c in g] for r in table["rows"]}
            ours["Grand Total"] = [c for g in table["total"]["cells"] for c in g]
            idx = view_store.sheet_cache.get(session, version.id, spec.sheet)
            rect = Rect.from_a1(spec.anchor)
            for r in range(rect.r1 + 1, rect.r2 + 1):
                label = idx.value(r, rect.c1)
                if label is None or str(label).strip() not in ours:
                    continue
                cached = [idx.value(r, c) for c in range(rect.c1 + 1, rect.c2 + 1)]
                for a, b in zip(cached, ours[str(label).strip()], strict=False):
                    if (
                        isinstance(a, int | float)
                        and not isinstance(a, bool)
                        and isinstance(b, float)
                    ):
                        checked += 1
                        if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
                            mismatches += 1
        assert checked > 100 and mismatches == 0, (checked, mismatches)
