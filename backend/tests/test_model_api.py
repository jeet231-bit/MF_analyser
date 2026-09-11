import pytest
from fastapi.testclient import TestClient

from tests.fixtures.logic_workbook import ROWS, logic_fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def version_id(client: TestClient) -> str:
    response = client.post(
        "/api/workbooks", files={"file": ("logic.xlsx", logic_fixture_xlsx_bytes(), XLSX)}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def interpreted(client: TestClient, version_id: str) -> str:
    response = client.post(f"/api/workbooks/{version_id}/interpret", json={"sheets": None})
    assert response.status_code == 200, response.text
    return version_id


def test_interpret_returns_summary_and_roles(client: TestClient, version_id: str) -> None:
    before = client.get(f"/api/workbooks/{version_id}/model")
    assert before.status_code == 404
    response = client.post(f"/api/workbooks/{version_id}/interpret")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["templates"] >= 6
    assert body["summary"]["parse_errors"] == 0
    assert body["summary"]["cycles"] == 0
    assert body["summary"]["seconds"] >= 0
    roles = {s["name"]: s["role"] for s in body["sheets"]}
    assert roles["Outputs"] == "output"
    assert roles["Inputs"] == "input"
    assert client.get(f"/api/workbooks/{version_id}").json()["status"] == "interpreted"


def test_interpret_with_explicit_scope(client: TestClient, version_id: str) -> None:
    response = client.post(
        f"/api/workbooks/{version_id}/interpret", json={"sheets": ["Series", "Outputs"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == ["Series", "Outputs"]
    assert body["summary"]["external_blocks"] >= 2  # Inputs!B3 and Lookup!D1:E3
    bad = client.post(f"/api/workbooks/{version_id}/interpret", json={"sheets": ["Nope"]})
    assert bad.status_code == 422
    assert client.post("/api/workbooks/missing/interpret").status_code == 404


def test_model_endpoint(client: TestClient, interpreted: str) -> None:
    full = client.get(f"/api/workbooks/{interpreted}/model").json()
    assert {s["name"] for s in full["sheets"]} == {"Inputs", "Lookup", "Calc", "Series", "Outputs"}
    assert full["templates"] and "ast" not in full["templates"][0]
    with_ast = client.get(f"/api/workbooks/{interpreted}/model", params={"include": "ast"}).json()
    assert with_ast["templates"][0]["ast"]["kind"]
    one = client.get(f"/api/workbooks/{interpreted}/model", params={"sheet": "Series"}).json()
    assert {b["sheet"] for b in one["formula_blocks"]} == {"Series"}
    assert {t["sheet"] for t in one["templates"]} == {"Series"}
    assert {r["sheet"] for r in one["rules"]} == {"Series"}
    assert (
        client.get(f"/api/workbooks/{interpreted}/model", params={"sheet": "Nope"}).status_code
        == 404
    )


def test_graph_levels(client: TestClient, interpreted: str) -> None:
    sheet = client.get(f"/api/workbooks/{interpreted}/graph", params={"level": "sheet"}).json()
    ids = {n["id"] for n in sheet["nodes"]}
    assert ids == {"Inputs", "Lookup", "Calc", "Series", "Outputs"}
    depth = {n["id"]: n["depth"] for n in sheet["nodes"]}
    assert depth["Inputs"] == 0 and depth["Series"] == 1 and depth["Outputs"] == 2
    # B1 reads the Sales input block, B2 reads both Cumulative blocks, B3 reads the Band block.
    assert {"source": "Series", "target": "Outputs", "weight": 4, "label": None} in sheet["edges"]

    block = client.get(f"/api/workbooks/{interpreted}/graph", params={"level": "block"}).json()
    kinds = {n["kind"] for n in block["nodes"]}
    assert kinds >= {"calculation", "output", "input"}
    assert block["edges"]

    cell = client.get(
        f"/api/workbooks/{interpreted}/graph",
        params={"level": "cell", "cell": "Series!D5", "depth": 2},
    ).json()
    labels = {n["id"] for n in cell["nodes"]}
    assert {"Series!D5", "Series!B5"} <= labels
    assert any(e["label"] == "read by" and e["target"] == "Series!E5" for e in cell["edges"])
    assert any(e["label"] == "reads" and e["source"] == "Series!B5" for e in cell["edges"])
    assert (
        client.get(f"/api/workbooks/{interpreted}/graph", params={"level": "cell"}).status_code
        == 422
    )


def test_rules_endpoint(client: TestClient, interpreted: str) -> None:
    rules = client.get(
        f"/api/workbooks/{interpreted}/rules", params={"sheet": "Series", "kind": "lookup"}
    ).json()
    assert len(rules) == 1
    assert rules[0]["detail"]["table"] == [["Low", 1], ["Mid", 2], ["High", 3]]
    assert rules[0]["cells"] == ["E2:E21"]
    everything = client.get(f"/api/workbooks/{interpreted}/rules").json()
    assert len(everything) > len(rules)


def test_role_override_persists_and_reclassifies(client: TestClient, interpreted: str) -> None:
    response = client.patch(
        f"/api/workbooks/{interpreted}/model/sheets/Series",
        json={"role": "output", "reason": "final table"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "output"
    assert response.json()["role_source"] == "override"
    model = client.get(f"/api/workbooks/{interpreted}/model", params={"sheet": "Series"}).json()
    assert all(b["classification"] == "output" for b in model["formula_blocks"])
    assert model["sheets"][3]["output_cells"] == 5 * ROWS  # every formula cell on the sheet
    # Re-interpreting keeps the stored override.
    again = client.post(f"/api/workbooks/{interpreted}/interpret").json()
    series = next(s for s in again["sheets"] if s["name"] == "Series")
    assert series["role"] == "output" and series["role_source"] == "override"
    assert (
        client.patch(
            f"/api/workbooks/{interpreted}/model/sheets/Nope", json={"role": "input"}
        ).status_code
        == 404
    )
