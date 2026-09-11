"""Logic diff: DATA vs LOGIC vs STRUCTURAL classification with impact, and the upload pipeline."""

import pytest
from fastapi.testclient import TestClient

from app.model.diff import describe_ast_change
from app.model.formula.parser import parse_formula
from tests.fixtures.anomaly_workbook import PASTED_ROW, anomaly_fixture_xlsx_bytes
from tests.fixtures.logic_workbook import ROWS, logic_fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPE = ["Inputs", "Lookup", "Series", "Outputs", "Semantics"]


def upload(client: TestClient, name: str, data: bytes, sheets: list[str] | None = None) -> str:
    response = client.post("/api/workbooks", files={"file": (name, data, XLSX)})
    assert response.status_code == 201, response.text
    vid = response.json()["id"]
    if sheets is not None:
        assert (
            client.post(f"/api/workbooks/{vid}/interpret", json={"sheets": sheets}).status_code
            == 200
        )
    return vid


def diff(client: TestClient, a: str, b: str) -> dict:
    response = client.get(f"/api/workbooks/{a}/diff/{b}", params={"refresh": "true"})
    assert response.status_code == 200, response.text
    return response.json()


def test_describe_ast_change_reads_like_a_changelog() -> None:
    old = parse_formula('=IF(B2<=120,"Low",IF(B2<=200,"Mid","High"))', "S", 2, 4)
    new = parse_formula('=IF(B2<=130,"Low",IF(B2<=200,"Mid","High"))', "S", 2, 4)
    assert describe_ast_change(old, new, 2, 4) == ["threshold B2 <= 120 → 130"]
    old = parse_formula("=SUM(Series!B2:B21)", "O", 1, 2)
    new = parse_formula("=SUM(Series!B2:B26)", "O", 1, 2)
    assert describe_ast_change(old, new, 1, 2) == [
        "SUM argument 1: range Series!B2:B21 → Series!B2:B26"
    ]
    old = parse_formula("=A1*2", "S", 1, 2)
    new = parse_formula("=A1*3+1", "S", 1, 2)
    assert describe_ast_change(old, new, 1, 2)[0].startswith("formula: A1*2 → A1*3+1")


def test_identical_versions_report_no_changes(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    b = upload(client, "b.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    report = diff(client, a, b)
    assert report["headline"] == "No changes"
    assert report["logic"] == [] and report["data"] == [] and report["structural"] == []
    assert report["summary"]["outputs_total"] > 0


def test_threshold_change_is_a_logic_change_with_impact(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    b = upload(client, "b.xlsx", logic_fixture_xlsx_bytes(threshold=130), SCOPE)
    report = diff(client, a, b)
    assert report["data"] == []
    (change,) = report["logic"]
    assert change["kind"] == "template_changed"
    assert (
        change["sheet"] == "Series" and change["location"] == "D2:D21" and change["cells"] == ROWS
    )
    assert change["description"] == "threshold B2 <= 120 → 130"
    assert change["detail"]["old_formula"] == '=IF(B2<=120,"Low",IF(B2<=200,"Mid","High"))'
    outputs = {(o["sheet"], o["range"]) for o in change["affected_outputs"]}
    # D feeds E (calculation), F (output), and Outputs!B3 (COUNTIF of "High").
    assert ("Series", "F2:F21") in outputs and ("Outputs", "B3") in outputs
    assert change["affected_output_count"] == len(outputs) >= 2
    assert report["summary"]["logic_changes"] == 1
    assert report["summary"]["outputs_affected_by_logic"] == len(outputs)
    assert report["headline"].startswith("1 logic change affecting")


def test_rows_appended_is_data_not_logic(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    b = upload(client, "b.xlsx", logic_fixture_xlsx_bytes(rows=25), SCOPE)
    report = diff(client, a, b)
    data = {d["kind"]: d for d in report["data"] if d["sheet"] == "Series"}
    assert data["rows_added"]["count"] == 5
    assert (
        data["rows_added"]["detail"]["first_row"] == 22
        and data["rows_added"]["detail"]["last_row"] == 26
    )
    assert data["values_changed"]["detail"]["added"] == 10  # 5 months + 5 sales values
    # The Outputs formulas now span more rows: that is a range extension, itemised as logic.
    kinds = {(c["sheet"], c["kind"]) for c in report["logic"]}
    assert kinds == {("Outputs", "template_changed")}
    descriptions = {c["description"] for c in report["logic"]}
    assert any("range Series!B2:B21 → Series!B2:B26" in d for d in descriptions)
    assert report["summary"]["outputs_affected_by_data"] >= 1


def test_sheet_rename_with_threshold_change(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    b = upload(
        client,
        "b.xlsx",
        logic_fixture_xlsx_bytes(series_name="Timeline", threshold=125),
        ["Inputs", "Lookup", "Timeline", "Outputs", "Semantics"],
    )
    report = diff(client, a, b)
    assert report["sheet_map"]["Series"] == "Timeline"
    renames = [s for s in report["structural"] if s["kind"] == "sheet_renamed"]
    assert renames and renames[0]["detail"] == {"from": "Series", "to": "Timeline"}
    assert not any(s["kind"] in ("sheet_added", "sheet_removed") for s in report["structural"])
    logic = [c for c in report["logic"] if c["kind"].startswith("template")]
    assert len(logic) == 1 and logic[0]["sheet"] == "Timeline"
    assert logic[0]["description"] == "threshold B2 <= 120 → 125"
    # Outputs formulas only changed their sheet prefix: no logic change reported for them.
    assert not any(c["sheet"] == "Outputs" for c in report["logic"])


def test_named_range_and_role_changes(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), None)
    b = upload(client, "b.xlsx", logic_fixture_xlsx_bytes(name_ref="Inputs!$B$3"), None)
    client.patch(
        f"/api/workbooks/{b}/model/sheets/Series", json={"role": "output", "reason": "review"}
    )
    report = diff(client, a, b)
    names = [c for c in report["logic"] if c["kind"] == "name_changed"]
    assert names and names[0]["description"] == "Inputs!$B$2 → Inputs!$B$3"
    roles = [s for s in report["structural"] if s["kind"] == "role_changed"]
    assert roles and roles[0]["detail"] == {
        "from": "calculation",
        "to": "output",
        "source": "override",
    }


def test_repaired_pasted_row_and_anomaly_delta(client: TestClient) -> None:
    a = upload(client, "old.xlsx", anomaly_fixture_xlsx_bytes(), None)
    b = upload(client, "new.xlsx", anomaly_fixture_xlsx_bytes(fixed=True), None)
    for vid in (a, b):
        assert client.post(f"/api/workbooks/{vid}/validate").status_code == 200
    report = diff(client, a, b)
    (repair,) = [c for c in report["logic"] if c["kind"].startswith("template")]
    assert repair["kind"] == "template_changed" and repair["cells"] == 1
    assert repair["location"] == f"B{PASTED_ROW}" and repair["detail"]["repair"] is True
    assert "now follow the column pattern" in repair["title"]
    resolved = {
        s["detail"]["kind"] for s in report["structural"] if s["kind"] == "anomaly_resolved"
    }
    assert resolved == {"own_row", "fragmentation"}
    assert not any(s["kind"] == "anomaly_new" for s in report["structural"])
    assert any(s["kind"] == "blocks_merged" for s in report["structural"])


def test_diff_requires_interpreted_versions(client: TestClient) -> None:
    a = upload(client, "a.xlsx", logic_fixture_xlsx_bytes(), SCOPE)
    assert client.get(f"/api/workbooks/{a}/diff/missing").status_code == 404
    response = client.post(
        "/api/workbooks", files={"file": ("raw.xlsx", logic_fixture_xlsx_bytes(), XLSX)}
    )
    raw = response.json()["id"]
    # The upload pipeline interprets automatically, so the diff is available.
    assert client.get(f"/api/workbooks/{a}/diff/{raw}").status_code == 200


def test_upload_pipeline_lands_as_pending_review_with_diff(client: TestClient) -> None:
    # Both versions go through the auto-pipeline so they share the same (full) scope.
    first = upload(client, "first.xlsx", logic_fixture_xlsx_bytes(), None)
    assert client.post(f"/api/workbooks/{first}/activate", json={}).status_code == 200

    response = client.post(
        "/api/workbooks",
        files={"file": ("second.xlsx", logic_fixture_xlsx_bytes(threshold=130), XLSX)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending_review"
    assert body["validation_status"] in ("passed", "passed_with_warnings")
    assert body["diff_base_id"] == first
    assert body["diff_headline"].startswith("1 logic change")
    assert any(n.startswith("validation") for n in body["pipeline_notes"])
    listed = {v["id"]: v for v in client.get("/api/workbooks").json()}
    assert listed[body["id"]]["diff_headline"] == body["diff_headline"]
    assert listed[first]["status"] == "active"
    assert listed[first]["validation_status"] in ("passed", "passed_with_warnings")

    # Activate the new one, then roll back by re-activating the old one.
    assert (
        client.post(f"/api/workbooks/{body['id']}/activate", json={}).json()["status"] == "active"
    )
    assert client.get(f"/api/workbooks/{first}").json()["status"] == "validated"
    assert client.post(f"/api/workbooks/{first}/activate", json={}).json()["status"] == "active"
    assert client.get(f"/api/workbooks/{body['id']}").json()["status"] == "validated"


@pytest.mark.parametrize("name", ["cyc.xlsx"])
def test_upload_pipeline_survives_cycles(client: TestClient, name: str) -> None:
    from tests.fixtures.logic_workbook import cycle_fixture_xlsx_bytes

    response = client.post(
        "/api/workbooks", files={"file": (name, cycle_fixture_xlsx_bytes(), XLSX)}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_review"
    assert body["validation_status"] == "failed"
    assert any("circular" in n for n in body["pipeline_notes"])
