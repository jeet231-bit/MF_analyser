"""The whole chain: upload -> interpret -> validate -> activate -> override run -> export."""

import csv
import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from tests.fixtures.logic_workbook import ROWS, UNITS, logic_fixture_xlsx_bytes, sales_for

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPE = ["Inputs", "Lookup", "Series", "Outputs", "Semantics"]


def test_end_to_end(client: TestClient) -> None:
    # 1. Upload: the pipeline interprets, validates and lands the version as pending review.
    uploaded = client.post(
        "/api/workbooks", files={"file": ("master.xlsx", logic_fixture_xlsx_bytes(), XLSX)}
    )
    assert uploaded.status_code == 201, uploaded.text
    version = uploaded.json()
    vid = version["id"]
    assert version["status"] == "pending_review"
    assert version["summary"]["formula_cells"] > 100

    # 2. Interpret with the explicit scope (the fixture's out-of-contract sheet stays out).
    interpreted = client.post(f"/api/workbooks/{vid}/interpret", json={"sheets": SCOPE})
    assert interpreted.status_code == 200
    assert interpreted.json()["cycles"] == []
    model = client.get(f"/api/workbooks/{vid}/model").json()
    assert {s["name"] for s in model["sheets"] if s["in_scope"]} == set(SCOPE)

    # 3. Validate: every formula cell reconciles against Excel's cached values.
    report = client.post(f"/api/workbooks/{vid}/validate").json()
    assert report["status"] in ("passed", "passed_with_warnings"), report["reasons"]
    assert report["totals"]["mismatched"] == 0 and report["totals"]["checked"] > 100

    # 4. Activate through the gate.
    activated = client.post(f"/api/workbooks/{vid}/activate", json={})
    assert activated.status_code == 200 and activated.json()["status"] == "active"
    assert activated.json()["activation_override"] is False

    # 5. Baseline outputs, then an override run with deltas.
    baseline = client.get(f"/api/workbooks/{vid}/outputs").json()
    assert baseline["baseline_run_id"] is None
    total_sales = sum(sales_for(i) for i in range(1, ROWS + 1))
    metrics = {m["label"]: m for m in baseline["sheets"][0]["metrics"]}
    assert metrics["Total sales"]["value"] == total_sales

    inputs = client.get(f"/api/workbooks/{vid}/inputs").json()
    units = next(
        c
        for s in inputs["sheets"]
        for b in s["blocks"]
        for c in b["cells"]
        if c["label"] == "Units"
    )
    assert units["value"] == UNITS and units["address"] == "B3"
    run = client.post(f"/api/workbooks/{vid}/runs", json={"overrides": {"Inputs!B3": 200}})
    assert run.status_code == 201
    run_id = run.json()["id"]
    assert run.json()["kind"] == "incremental"

    what_if = client.get(f"/api/workbooks/{vid}/outputs", params={"run_id": run_id}).json()
    assert what_if["baseline_run_id"] is not None
    grid = client.get(f"/api/runs/{run_id}/grid", params={"sheet": "Series"}).json()
    above = next(i for i, c in enumerate(grid["columns"]) if c["label"] == "Above units")
    flipped = [r["row"] for r in grid["rows"] if r["cells"][above] and "b" in r["cells"][above]]
    assert flipped == [i + 1 for i in range(1, ROWS + 1) if UNITS < sales_for(i) <= 200]

    # 6. Explain a number on the what-if run.
    node = client.get(
        f"/api/workbooks/{vid}/lineage/Series!G{flipped[0]}", params={"run_id": run_id}
    ).json()
    assert node["value"] is False and node["formula"].endswith("Inputs!$B$3")

    # 7. Export the what-if: csv of the window, xlsx with provenance, the report.
    csv_out = client.get(
        f"/api/runs/{run_id}/export", params={"format": "csv", "sheet": "Series", "window": "A2:G4"}
    )
    assert csv_out.status_code == 200
    rows = list(csv.reader(io.StringIO(csv_out.text.lstrip("﻿"))))
    assert rows[0][-1] == "Above units" and rows[1][-1] == "FALSE"

    xlsx_out = client.get(f"/api/runs/{run_id}/export", params={"format": "xlsx"})
    assert xlsx_out.status_code == 200
    wb = load_workbook(io.BytesIO(xlsx_out.content), read_only=True)
    cover = {
        row[0].value: row[1].value
        for row in wb["Cover"].iter_rows()
        if len(row) > 1 and row[0].value
    }
    assert cover["Overrides"] == "Inputs!B3 = 200"
    assert cover["Validation"] in ("passed", "passed with warnings")
    outputs_sheet = wb["Outputs"]
    assert next(outputs_sheet.iter_rows(min_row=1, max_row=1))[1].value == total_sales

    html = client.get(f"/api/runs/{run_id}/report.html").text
    assert "what-if with 1 override(s)" in html and "Inputs!B3" in html

    # 8. Rollback path stays open: the version list shows exactly one active version.
    versions = client.get("/api/workbooks").json()
    assert [v["status"] for v in versions if v["id"] == vid] == ["active"]
