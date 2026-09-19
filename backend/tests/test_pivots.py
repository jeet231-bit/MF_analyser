"""Pivots: parsed from the workbook's own pivot parts, recomputed from the engine's values."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.parser.pivots import parse_pivots
from app.research import pivot as engine
from app.research import table as table_store
from tests.fixtures.pivot_workbook import RECORDS, pivot_fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _fresh_database(tmp_path, monkeypatch):
    from app.storage import pivots as pivot_store
    from app.storage.db import get_engine, get_session_factory

    monkeypatch.setenv("MFA_DATA_DIR", str(tmp_path / "data"))
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    table_store.clear_all()
    pivot_store.clear()
    engine.frame_cache.clear()
    yield
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()


def _upload(client: TestClient) -> str:
    r = client.post(
        "/api/workbooks", files={"file": ("pivots.xlsx", pivot_fixture_xlsx_bytes(), XLSX)}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["validation_status"] in ("passed", "passed_with_warnings"), body["pipeline_notes"]
    assert client.post(f"/api/workbooks/{body['id']}/activate", json={}).status_code == 200
    return body["id"]


def test_parser_reads_layout_and_saved_filters() -> None:
    specs = parse_pivots(io.BytesIO(pivot_fixture_xlsx_bytes()))
    assert len(specs) == 1
    s = specs[0]
    assert (s.name, s.sheet, s.source_sheet, s.source_ref, s.records) == (
        "PivotFunds",
        "Pivot",
        "Data",
        "A1:E9",
        8,
    )
    assert [f.name for f in s.fields] == ["Name", "Group", "Plan", "Corpus", "Score"]
    assert s.rows == ["Group"] and s.cols == [] and s.filters == ["Plan"]
    assert [(v.label, v.field, v.agg) for v in s.values] == [
        ("Average of Corpus", "Corpus", "average"),
        ("Count of Name", "Name", "count"),
    ]
    assert s.saved_filters == {"Plan": ["Direct"]}


def test_list_and_default_layout(client: TestClient) -> None:
    assert client.get("/api/research/pivots").json()["configured"] is False
    _upload(client)
    listing = client.get("/api/research/pivots").json()
    assert listing["configured"] is True and len(listing["pivots"]) == 1
    p = listing["pivots"][0]
    assert p["id"] == "Pivot::PivotFunds"
    assert p["source"]["refreshed"].startswith("2025-")  # Excel's cache refresh stamp
    assert {k: v for k, v in p["source"].items() if k != "refreshed"} == {
        "sheet": "Data",
        "ref": "A1:E9",
        "records": 8,
        "live": True,
    }
    assert p["layout"]["rows"] == ["Group"] and p["savedFilters"] == {"Plan": ["Direct"]}

    # Excel's layout: Plan = Direct, rows by Group, average corpus and count.
    body = client.get("/api/research/pivot", params={"id": "Pivot::PivotFunds"}).json()
    assert body["configured"] and body["live"] is True
    assert body["matched"] == 5 and body["records"] == 8
    rows = {r["keys"][0]: r for r in body["rows"]}
    assert set(rows) == {"Large", "Mid", "Small"}
    assert rows["Large"]["cells"] == [[800.0, 2.0]]  # (1200 + 400) / 2 direct funds
    assert rows["Small"]["cells"] == [[150.0, 2.0]]
    assert body["total"]["cells"] == [[560.0, 5.0]]
    assert body["options"]["Plan"] == ["Direct", "Regular"]
    assert body["fieldKinds"] == {
        "Name": "text",
        "Group": "text",
        "Plan": "text",
        "Corpus": "number",
        "Score": "number",
    }
    assert body["query"]["filters"] == {"Plan": ["Direct"]}


def test_any_layout_over_the_fields(client: TestClient) -> None:
    _upload(client)

    def q(spec: dict) -> dict:
        r = client.get(
            "/api/research/pivot", params={"id": "Pivot::PivotFunds", "spec": json.dumps(spec)}
        )
        assert r.status_code == 200, r.text
        return r.json()

    # No filter, two-level rows with subtotals, a formula value (Score) from the engine.
    body = q(
        {
            "filters": {},
            "rows": ["Group", "Plan"],
            "values": [{"label": "Score", "field": "Score", "agg": "sum"}],
        }
    )
    kinds = [(r["kind"], r["keys"]) for r in body["rows"]]
    assert kinds[:3] == [
        ("leaf", ["Large", "Direct"]),
        ("leaf", ["Large", "Regular"]),
        ("subtotal", ["Large"]),
    ]
    large = next(r for r in body["rows"] if r["kind"] == "subtotal" and r["keys"] == ["Large"])
    assert large["cells"] == [[24.0]] and large["n"] == 3  # (1200 + 800 + 400) / 100
    assert body["total"]["cells"] == [[sum(r[3] for r in RECORDS) / 100]]

    # A column field makes a cross-tab with a Total column; min/max/countNums aggregations.
    body = q(
        {
            "rows": ["Group"],
            "cols": ["Plan"],
            "values": [
                {"label": "Max corpus", "field": "Corpus", "agg": "max"},
                {"label": "n", "field": "Corpus", "agg": "countNums"},
            ],
        }
    )
    assert body["colKeys"] == [["Direct"], ["Regular"], ["Total"]]
    mid = next(r for r in body["rows"] if r["keys"] == ["Mid"])
    assert mid["cells"] == [[900.0, 1.0], [300.0, 1.0], [900.0, 2.0]]

    # A filter on a field that is not one of Excel's page fields still works, and appears in options.
    body = q(
        {
            "filters": {"Group": ["Small"]},
            "rows": ["Name"],
            "values": [{"label": "c", "field": "Corpus", "agg": "min"}],
        }
    )
    assert [r["keys"][0] for r in body["rows"]] == ["Delta One", "Gamma One", "Gamma One - Reg"]
    assert body["options"]["Group"] == ["Large", "Mid", "Small"] and "Plan" in body["options"]

    # Bad requests are 422 with a reason, unknown pivots 404.
    r = client.get(
        "/api/research/pivot",
        params={
            "id": "Pivot::PivotFunds",
            "spec": json.dumps(
                {"rows": ["Nope"], "values": [{"label": "x", "field": "Corpus", "agg": "sum"}]}
            ),
        },
    )
    assert r.status_code == 422 and "Nope" in r.json()["detail"]
    r = client.get(
        "/api/research/pivot",
        params={"id": "Pivot::PivotFunds", "spec": json.dumps({"rows": ["Group"], "values": []})},
    )
    assert r.status_code == 422
    assert client.get("/api/research/pivot", params={"id": "Nowhere::X"}).status_code == 404


def test_export_csv_and_xlsx(client: TestClient) -> None:
    _upload(client)
    r = client.get(
        "/api/research/pivot/export", params={"id": "Pivot::PivotFunds", "format": "csv"}
    )
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["Row", "Group", "Row type", "Records", "Average of Corpus", "Count of Name"]
    assert rows[-1][0] == "Total" and rows[-1][2] == "total"
    x = client.get(
        "/api/research/pivot/export", params={"id": "Pivot::PivotFunds", "format": "xlsx"}
    )
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_engine_aggregations_and_display() -> None:
    assert engine.aggregate("average", [1.0, 2.0, None, "x"]) == 1.5
    assert engine.aggregate("count", [1.0, None, "x"]) == 2.0
    assert engine.aggregate("countNums", [1.0, None, "x"]) == 1.0
    assert engine.aggregate("sum", []) is None
    assert (
        engine.display(None) == "(blank)"
        and engine.display(3.0) == "3"
        and engine.display(2.5) == "2.5"
    )
    assert sorted(["b", "10", "2", "(blank)", "a"], key=engine.sort_key) == [
        "2",
        "10",
        "a",
        "b",
        "(blank)",
    ]
