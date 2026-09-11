"""Validation on the real master and the anomaly regression on the older file (opt-in, ``-m real``)."""

from pathlib import Path

import pytest

from app.dashboard_config import load_dashboard_config
from app.storage import logic, validation, workbooks
from app.storage.db import get_session_factory

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
FIXED = SAMPLES / "master.xlsx"
OLD = sorted(p for p in SAMPLES.glob("*.xls[xm]") if p.name != "master.xlsx")

pytestmark = pytest.mark.real


def _ingest(session, path: Path):
    try:
        version = workbooks.ingest_workbook(session, path, filename=path.name)
    except PermissionError:
        pytest.skip(f"{path.name} is locked by another process (is it open in Excel?)")
    logic.interpret_version(session, version.id, scope=None, config=load_dashboard_config())
    return version


@pytest.mark.skipif(not FIXED.exists(), reason="no samples/master.xlsx")
def test_fixed_master_validates_clean(client) -> None:
    with get_session_factory()() as session:
        version = _ingest(session, FIXED)
        report = validation.validate_version(session, version.id)
    t = report.totals
    print(
        f"\nmaster.xlsx: {report.status} | checked {t.checked:,} matched {t.matched:,} mismatched {t.mismatched:,} "
        f"skipped {t.skipped_unsupported + t.skipped_stale:,} | anomalies {report.anomaly_counts} | {report.seconds}s"
    )
    for a in report.anomalies[:10]:
        print("  anomaly:", a.kind, a.sheet, a.location, "|", a.title)
    for m in report.mismatches[:5]:
        print("  mismatch:", m.sheet, m.cell, m.excel, m.engine, m.classification)
    assert t.mismatched == 0
    assert t.checked == t.matched
    assert report.status in ("passed", "passed_with_warnings")
    flagged = {
        (a.sheet, a.location) for a in report.anomalies if a.kind in ("own_row", "fragmentation")
    }
    assert not any(
        loc.endswith("3181") or "3181:" in loc for s, loc in flagged if s == "Roll Perf"
    ), flagged
    assert not any("3182" in loc for s, loc in flagged if s == "Bull-Bear Returns"), flagged


@pytest.mark.skipif(not OLD, reason="no older workbook in samples/")
def test_old_master_anomaly_regression(client) -> None:
    with get_session_factory()() as session:
        version = _ingest(session, OLD[0])
        report = validation.validate_version(session, version.id)
    print(
        f"\n{OLD[0].name}: {report.status} | anomalies {report.anomaly_counts} | mismatched {report.totals.mismatched:,}"
    )
    own_rows = [a for a in report.anomalies if a.kind == "own_row"]
    for a in own_rows:
        print("  own_row:", a.sheet, a.location, "|", a.title)
    assert any(a.sheet == "Roll Perf" and "3181" in a.location for a in own_rows)
    assert any(a.sheet == "Bull-Bear Returns" and "3182" in a.location for a in own_rows)
    assert any(
        a.kind == "fragmentation" and a.sheet == "Bull-Bear Returns" and "3182" in a.location
        for a in report.anomalies
    )
