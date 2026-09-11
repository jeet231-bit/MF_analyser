"""The configured sheet scope must be upstream-closed and inside the engine's function contract
(opt-in, ``-m real``)."""

from pathlib import Path

import pytest

from app.dashboard_config import load_dashboard_config
from app.engine.functions import REGISTRY
from app.engine.runner import preflight
from app.model.scope import missing_upstream, upstream_closure
from app.parser.models import RawWorkbook
from app.storage import logic, workbooks
from app.storage.db import get_session_factory

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
FIXED = SAMPLES / "master.xlsx"

pytestmark = pytest.mark.real


@pytest.mark.skipif(not FIXED.exists(), reason="no samples/master.xlsx")
def test_config_scope_is_upstream_closed_and_within_contract(client) -> None:
    config = load_dashboard_config()
    with get_session_factory()() as session:
        try:
            version = workbooks.ingest_workbook(session, FIXED, filename=FIXED.name)
        except PermissionError:
            pytest.skip("master.xlsx is locked by another process (is it open in Excel?)")
        meta = RawWorkbook.model_validate_json(version.meta_json or "{}")
        cache: dict[str, object] = {}

        def load_sheet(name: str):
            if name not in cache:
                cache[name] = workbooks.load_raw(session, version.id, sheet=name).sheets[0]
            return cache[name]

        scope = [s for s in config.sheet_scope if s in meta.sheet_names]
        assert scope == config.sheet_scope, "config names a sheet the master does not have"
        gap = missing_upstream(meta, load_sheet, scope)
        print(f"\nscope {len(scope)} sheets; upstream gap: {gap}")
        assert gap == [], f"sheetScope is not upstream-closed; add {gap}"
        # Every configured sheet earns its place: it is the closure of the output sheets plus
        # whatever the researcher listed explicitly, so nothing in scope is unreachable garbage.
        seeds = [s for s in scope if s in config.output_sheets] or scope
        print("closure of output sheets:", upstream_closure(meta, load_sheet, seeds).sheets)

        model = logic.interpret_version(session, version.id, scope=None, config=config)

    used = {f for t in model.templates for f in t.functions}
    outside = sorted(used - set(REGISTRY))
    print("functions in scope:", sorted(used))
    assert outside == [], f"functions outside the engine contract: {outside}"
    assert model.cycles == [], model.cycle_descriptions
    assert preflight(model) == set()
    assert model.summary.unresolved_references == 0
    print(
        f"templates {model.summary.templates} | blocks {model.summary.formula_blocks} | "
        f"formula cells {model.summary.formula_cells:,}"
    )
    print("roles:", {s.name: (s.role, s.role_source) for s in model.sheets if s.in_scope})
