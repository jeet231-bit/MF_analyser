"""Validation reports, anomaly detection and the activation gate, via the API."""

import pytest
from fastapi.testclient import TestClient

from app.validation.reconcile import classify, values_equal
from tests.fixtures.anomaly_workbook import (
    DUP_ROW,
    PASTED_ROW,
    anomaly_fixture_xlsx_bytes,
    perturbed_fixture_xlsx_bytes,
)
from tests.fixtures.logic_workbook import cycle_fixture_xlsx_bytes, logic_fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CLEAN_SCOPE = ["Inputs", "Lookup", "Series", "Outputs", "Semantics"]


def upload_and_interpret(
    client: TestClient, name: str, data: bytes, sheets: list[str] | None
) -> str:
    response = client.post("/api/workbooks", files={"file": (name, data, XLSX)})
    assert response.status_code == 201, response.text
    vid = response.json()["id"]
    assert (
        client.post(f"/api/workbooks/{vid}/interpret", json={"sheets": sheets}).status_code == 200
    )
    return vid


def test_values_equal_policy() -> None:
    assert values_equal(8.351422680412375, 8.35142268041237)  # 15 significant digits
    assert not values_equal(1.0, 1.0000001)
    assert values_equal("Alpha", "Alpha") and not values_equal("Alpha", "alpha")  # text exact
    assert values_equal(True, True) and not values_equal(True, 1)
    assert values_equal("#N/A", "#N/A") and not values_equal("#N/A", "#DIV/0!")
    assert classify(1.0, 1.0 + 1e-12) == ("precision", pytest.approx(1e-12))
    assert classify(1.0, 2.0)[0] == "semantics"
    assert classify("#N/A", 5)[0] == "data"
    assert classify("a", "b")[0] == "semantics"


def test_clean_fixture_passes(client: TestClient) -> None:
    vid = upload_and_interpret(client, "clean.xlsx", logic_fixture_xlsx_bytes(), CLEAN_SCOPE)
    assert (
        client.get(f"/api/workbooks/{vid}/validation").status_code == 200
    )  # auto-validated on upload
    report = client.post(f"/api/workbooks/{vid}/validate").json()
    assert report["status"] == "passed", report["reasons"]
    t = report["totals"]
    assert t["mismatched"] == 0 and t["skipped_unsupported"] == 0 and t["skipped_stale"] == 0
    assert t["checked"] == t["matched"] == sum(s["formula_cells"] for s in report["by_sheet"])
    assert report["anomalies"] == [] and report["anomaly_counts"] == {}
    assert report["run_id"]
    assert client.get(f"/api/workbooks/{vid}/validation").json()["id"] == report["id"]
    assert client.get(f"/api/workbooks/{vid}").json()["status"] in ("validated", "pending_review")


def test_unsupported_functions_are_skipped_not_mismatched(client: TestClient) -> None:
    vid = upload_and_interpret(
        client, "full.xlsx", logic_fixture_xlsx_bytes(), None
    )  # Calc has XLOOKUP
    report = client.post(f"/api/workbooks/{vid}/validate").json()
    assert report["status"] == "passed_with_warnings"
    assert report["totals"]["mismatched"] == 0
    assert report["totals"]["skipped_unsupported"] == 1
    assert report["unsupported"] == [
        {"function": "XLOOKUP", "sheet": "Calc", "cell": "B11", "cells": 1}
    ]
    calc = next(s for s in report["by_sheet"] if s["sheet"] == "Calc")
    assert calc["skipped_unsupported"] == 1 and calc["checked"] == calc["formula_cells"] - 1
    assert any("XLOOKUP" in r or "not support" in r for r in report["reasons"])


def test_perturbed_cached_value_fails_with_detail(client: TestClient) -> None:
    vid = upload_and_interpret(
        client, "perturbed.xlsx", perturbed_fixture_xlsx_bytes(), CLEAN_SCOPE
    )
    report = client.post(f"/api/workbooks/{vid}/validate").json()
    assert report["status"] == "failed"
    assert report["totals"]["mismatched"] == 1
    (m,) = report["mismatches"]
    assert m["sheet"] == "Series" and m["cell"] == "C21"
    assert m["formula"] == "=C20+B21"
    assert m["excel"] == m["engine"] + 1 and m["delta"] == -1
    assert m["classification"] == "semantics"
    assert "differ from Excel" in report["reasons"][0]

    # Gate: failed needs an explicit override reason.
    refused = client.post(f"/api/workbooks/{vid}/activate", json={})
    assert refused.status_code == 409
    assert refused.json()["detail"]["validation_status"] == "failed"
    forced = client.post(
        f"/api/workbooks/{vid}/activate", json={"override_reason": "known perturbation"}
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "active"
    assert forced.json()["activation_override"] is True
    assert forced.json()["activation_reason"] == "known perturbation"


def test_anomaly_classes(client: TestClient) -> None:
    vid = upload_and_interpret(client, "anomalies.xlsx", anomaly_fixture_xlsx_bytes(), None)
    report = client.post(f"/api/workbooks/{vid}/validate").json()
    assert report["totals"]["mismatched"] == 0
    assert report["status"] == "passed_with_warnings"
    kinds = {a["kind"]: a for a in report["anomalies"]}
    assert set(kinds) == {"fragmentation", "own_row", "duplicate_keys", "stale"}
    assert report["anomaly_counts"] == {
        "fragmentation": 1,
        "own_row": 1,
        "duplicate_keys": 1,
        "stale": 1,
    }

    frag = kinds["fragmentation"]
    assert frag["sheet"] == "Calc" and frag["location"] == f"B{PASTED_ROW}"
    assert "break the surrounding pattern" in frag["title"]

    own = kinds["own_row"]
    assert own["location"] == f"B{PASTED_ROW}"
    assert own["detail"]["reads_rows"] == [PASTED_ROW + 30]
    assert f"read row {PASTED_ROW + 30}" in own["title"]
    assert "cut-and-pasted" in own["explanation"]

    dup = kinds["duplicate_keys"]
    assert (
        dup["sheet"] == "Data" and dup["location"] == "A1:B61"
    )  # the lookup range; keys are its first column
    assert dup["detail"]["duplicates"] == [
        {"key": "K5", "cells": ["A6", f"A{DUP_ROW}"], "count": 2}
    ]

    stale = kinds["stale"]
    assert stale["sheet"] == "Stale" and stale["detail"] == {"count": 1, "cells": ["B2"]}
    assert report["totals"]["skipped_stale"] == 1
    assert "F9" in stale["explanation"]

    # Warnings never block activation.
    activated = client.post(f"/api/workbooks/{vid}/activate", json={})
    assert activated.status_code == 200
    assert activated.json()["activation_override"] is False
    assert activated.json()["activation_reason"] == "validation passed with warnings"


def test_activation_requires_validation_and_deactivates_previous(client: TestClient) -> None:
    # A model with cycles validates as failed without a run, so it can never be activated,
    # not even with an override reason.
    cyc = upload_and_interpret(client, "cyc.xlsx", cycle_fixture_xlsx_bytes(), None)
    refused = client.post(f"/api/workbooks/{cyc}/activate", json={"override_reason": "try"})
    assert refused.status_code == 409 and refused.json()["detail"]["validation_status"] == "failed"
    assert "circular" in refused.json()["detail"]["message"]
    first = upload_and_interpret(client, "first.xlsx", logic_fixture_xlsx_bytes(), CLEAN_SCOPE)
    client.post(f"/api/workbooks/{first}/validate")
    assert client.post(f"/api/workbooks/{first}/activate", json={}).json()["status"] == "active"

    second = upload_and_interpret(client, "second.xlsx", logic_fixture_xlsx_bytes(), CLEAN_SCOPE)
    client.post(f"/api/workbooks/{second}/validate")
    assert client.post(f"/api/workbooks/{second}/activate", json={}).json()["status"] == "active"
    assert client.get(f"/api/workbooks/{first}").json()["status"] == "validated"
    assert client.get(f"/api/workbooks/{second}").json()["status"] == "active"
    assert client.post("/api/workbooks/nope/validate").status_code == 404


def test_cycle_model_validates_as_failed_with_structural_report(client: TestClient) -> None:
    vid = upload_and_interpret(client, "cyc.xlsx", cycle_fixture_xlsx_bytes(), None)
    response = client.post(f"/api/workbooks/{vid}/validate")
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "failed"
    assert report["run_id"] is None
    assert report["totals"]["checked"] == 0
    assert "circular reference" in report["reasons"][0]
    assert any("reference cycle" in r for r in report["reasons"][1:])
