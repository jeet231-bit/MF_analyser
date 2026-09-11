"""Real regression pair: the older defective master vs the fixed master (opt-in, ``-m real``)."""

from pathlib import Path

import pytest

from app.dashboard_config import load_dashboard_config
from app.storage import diffs, logic, validation, workbooks
from app.storage.db import get_session_factory

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
FIXED = SAMPLES / "master.xlsx"
OLD = sorted(p for p in SAMPLES.glob("*.xls[xm]") if p.name != "master.xlsx")

pytestmark = pytest.mark.real


@pytest.mark.skipif(
    not (FIXED.exists() and OLD), reason="needs both the old and the fixed master in samples/"
)
def test_old_vs_fixed_master_diff(client) -> None:
    with get_session_factory()() as session:
        ids = []
        for path in (OLD[0], FIXED):
            try:
                version = workbooks.ingest_workbook(session, path, filename=path.name)
            except PermissionError:
                pytest.skip(f"{path.name} is locked by another process")
            logic.interpret_version(session, version.id, scope=None, config=load_dashboard_config())
            validation.validate_version(session, version.id)
            ids.append(version.id)
        report = diffs.compute_diff(session, ids[0], ids[1])

    print(f"\n{OLD[0].name} -> master.xlsx: {report.headline}")
    for c in report.logic:
        print(
            f"  LOGIC {c.kind} {c.sheet} {c.location}: {c.cells} cells | {c.description[:100]} | outputs {c.affected_output_count}".encode(
                "ascii", "replace"
            ).decode()
        )
    for d in report.data:
        print(f"  DATA {d.description}")
    for s in report.structural:
        print(f"  STRUCTURAL {s.kind}: {s.description[:110]}".encode("ascii", "replace").decode())

    repairs = [c for c in report.logic if c.kind == "template_changed"]
    assert sum(c.cells for c in repairs) == 46
    assert len(repairs) == 2  # one merged entry per repaired row
    assert {c.sheet for c in repairs} == {"Roll Perf", "Bull-Bear Returns"}
    assert all(c.detail.get("repair") for c in repairs)
    assert all(c.affected_output_count > 0 for c in repairs)
    resolved = [
        s
        for s in report.structural
        if s.kind == "anomaly_resolved" and s.detail["kind"] == "own_row"
    ]
    assert {s.sheet for s in resolved} == {"Roll Perf", "Bull-Bear Returns"}
    assert not any(
        s.kind == "anomaly_new" and s.detail["kind"] == "own_row" for s in report.structural
    )
