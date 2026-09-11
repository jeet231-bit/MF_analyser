import pytest
from fastapi.testclient import TestClient

from tests.fixtures.logic_workbook import ROWS, cycle_fixture_xlsx_bytes, logic_fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPE = ["Inputs", "Lookup", "Series", "Outputs", "Semantics"]


@pytest.fixture
def version_id(client: TestClient) -> str:
    response = client.post(
        "/api/workbooks", files={"file": ("logic.xlsx", logic_fixture_xlsx_bytes(), XLSX)}
    )
    assert response.status_code == 201, response.text
    vid = response.json()["id"]
    assert client.post(f"/api/workbooks/{vid}/interpret", json={"sheets": SCOPE}).status_code == 200
    return vid


def test_full_then_incremental_run(client: TestClient, version_id: str) -> None:
    first = client.post(f"/api/workbooks/{version_id}/runs", json={})
    assert first.status_code == 201, first.text
    base = first.json()
    assert base["kind"] == "full" and base["parent_run_id"] is None
    assert base["summary"]["blocks_evaluated"] > 10
    assert base["summary"]["error_cells"] == 4  # Semantics B4, C4, C5, C20

    second = client.post(
        f"/api/workbooks/{version_id}/runs", json={"overrides": {"Inputs!B3": 200}}
    )
    assert second.status_code == 201, second.text
    inc = second.json()
    assert inc["kind"] == "incremental" and inc["parent_run_id"] == base["id"]
    assert inc["summary"]["blocks_evaluated"] == 1
    assert inc["overrides"] == {"Inputs!B3": 200}

    listed = client.get(f"/api/workbooks/{version_id}/runs").json()
    assert [r["id"] for r in listed] == [inc["id"], base["id"]]
    assert client.get(f"/api/runs/{inc['id']}").json()["kind"] == "incremental"
    assert client.get("/api/runs/nope").status_code == 404

    values = client.get(
        f"/api/runs/{inc['id']}/values", params={"sheet": "Series", "range": "G2:G21"}
    ).json()
    assert values["count"] == ROWS
    assert sum(1 for c in values["cells"] if c["value"] is True) == 5
    # Unchanged sheets compose from the baseline; overridden inputs are marked.
    inputs = client.get(f"/api/runs/{inc['id']}/values", params={"sheet": "Inputs"}).json()
    b3 = next(c for c in inputs["cells"] if c["address"] == "B3")
    assert b3 == {
        "address": "B3",
        "value": 200,
        "type": "number",
        "formula": False,
        "override": True,
    }
    outputs = client.get(f"/api/runs/{inc['id']}/values", params={"sheet": "Outputs"}).json()
    assert next(c for c in outputs["cells"] if c["address"] == "B1")["value"] == sum(
        90 + 7 * i for i in range(1, ROWS + 1)
    )
    assert client.get(f"/api/runs/{inc['id']}/values", params={"sheet": "Nope"}).status_code == 404
    assert (
        client.get(
            f"/api/runs/{inc['id']}/values", params={"sheet": "Series", "range": "zz"}
        ).status_code
        == 422
    )


def test_lineage_endpoint(client: TestClient, version_id: str) -> None:
    assert (
        client.get(f"/api/workbooks/{version_id}/lineage/Series!D5").status_code == 404
    )  # no run yet
    client.post(f"/api/workbooks/{version_id}/runs", json={})
    node = client.get(f"/api/workbooks/{version_id}/lineage/Series!D5", params={"depth": 2}).json()
    assert node["formula"] == '=IF(B5<=120,"Low",IF(B5<=200,"Mid","High"))'
    assert node["value"] == "Low"
    assert node["reads"][0]["range"] == "B5" and node["reads"][0]["cells"][0]["value"] == 118
    deep = client.get(f"/api/workbooks/{version_id}/lineage/Series!F5", params={"depth": 2}).json()
    e5 = next(r for r in deep["reads"] if r["range"] == "E5")
    assert e5["node"]["formula"].startswith("=VLOOKUP(")
    assert client.get(f"/api/workbooks/{version_id}/lineage/Nope!A1").status_code == 404
    assert client.get(f"/api/workbooks/{version_id}/lineage/Series").status_code == 422


def test_run_refusals(client: TestClient, version_id: str) -> None:
    bad = client.post(f"/api/workbooks/{version_id}/runs", json={"overrides": {"Series!D2": 1}})
    assert bad.status_code == 422 and "holds a formula" in bad.json()["detail"]

    # Full scope includes Calc!B11 = _xlfn.XLOOKUP: refused before any block runs.
    client.post(f"/api/workbooks/{version_id}/interpret", json={"sheets": None})
    unsupported = client.post(f"/api/workbooks/{version_id}/runs", json={})
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["function"] == "XLOOKUP"
    assert unsupported.json()["detail"]["cell"] == "B11"

    assert client.post("/api/workbooks/missing/runs", json={}).status_code == 404


def test_cycle_model_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/workbooks", files={"file": ("cyc.xlsx", cycle_fixture_xlsx_bytes(), XLSX)}
    )
    vid = response.json()["id"]
    client.post(f"/api/workbooks/{vid}/interpret")
    refused = client.post(f"/api/workbooks/{vid}/runs", json={})
    assert refused.status_code == 409
    assert "reference cycle" in refused.json()["detail"]["cycles"][0]
