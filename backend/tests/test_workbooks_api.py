from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.fixtures.workbook import FIXTURE_FORMULAS, as_xlsm, fixture_xlsx_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(client: TestClient, name: str, data: bytes):
    return client.post("/api/workbooks", files={"file": (name, data, XLSX)})


@pytest.fixture
def uploaded(client: TestClient) -> dict:
    response = upload(client, "fixture.xlsx", fixture_xlsx_bytes())
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_returns_version_and_summary(uploaded: dict) -> None:
    assert uploaded["status"] == "pending_review"  # the upload pipeline interprets and validates
    assert uploaded["filename"] == "fixture.xlsx"
    assert uploaded["size_bytes"] > 0
    summary = uploaded["summary"]
    assert summary["sheets"] == 3
    assert summary["formula_cells"] == len(FIXTURE_FORMULAS)
    assert summary["named_ranges"] == 1
    assert summary["tables"] == 1
    assert summary["distinct_functions"] == 6
    assert summary["functions"] == {
        "CONCATENATE": 1,
        "IF": 1,
        "IFERROR": 1,
        "SUM": 1,
        "VLOOKUP": 1,
        "XLOOKUP": 1,
    }
    assert summary["has_macros"] is False
    assert summary["warnings"] == []


def test_list_and_get(client: TestClient, uploaded: dict) -> None:
    listed = client.get("/api/workbooks").json()
    assert [v["id"] for v in listed][:1] == [uploaded["id"]]
    got = client.get(f"/api/workbooks/{uploaded['id']}").json()
    assert got["id"] == uploaded["id"]
    assert got["summary"]["sheets"] == 3
    assert client.get("/api/workbooks/does-not-exist").status_code == 404


def test_raw_round_trips_cells(client: TestClient, uploaded: dict) -> None:
    raw = client.get(f"/api/workbooks/{uploaded['id']}/raw").json()
    assert [s["name"] for s in raw["sheets"]] == ["Inputs", "Lookup", "Calc"]
    calc = next(s for s in raw["sheets"] if s["name"] == "Calc")
    cells = calc["cells"]
    i = cells["address"].index("B7")
    assert cells["formula"][i] == "=1/0"
    assert cells["value"][i] == "#DIV/0!"
    assert cells["value_type"][i] == "error"
    assert len(cells["address"]) == calc["cell_count"]
    assert raw["defined_names"][0]["name"] == "Threshold"


def test_raw_single_sheet(client: TestClient, uploaded: dict) -> None:
    raw = client.get(f"/api/workbooks/{uploaded['id']}/raw", params={"sheet": "Lookup"}).json()
    assert [s["name"] for s in raw["sheets"]] == ["Lookup"]
    assert raw["sheets"][0]["state"] == "hidden"
    assert raw["tables"][0]["display_name"] == "Ratings"
    missing = client.get(f"/api/workbooks/{uploaded['id']}/raw", params={"sheet": "Nope"})
    assert missing.status_code == 404
    assert client.get("/api/workbooks/nope/raw").status_code == 404


def test_xlsm_flagged(client: TestClient) -> None:
    response = upload(client, "macros.xlsm", as_xlsm(fixture_xlsx_bytes()))
    assert response.status_code == 201
    summary = response.json()["summary"]
    assert summary["has_macros"] is True
    assert any("macro" in w for w in summary["warnings"])


def test_xls_rejected_with_clear_message(client: TestClient) -> None:
    response = upload(client, "legacy.xls", b"\xd0\xcf\x11\xe0")
    assert response.status_code == 415
    assert "save as .xlsx" in response.json()["detail"]


def test_unknown_type_rejected(client: TestClient) -> None:
    response = upload(client, "notes.csv", b"a,b\n1,2")
    assert response.status_code == 415


def count_versions(client: TestClient) -> int:
    return len(client.get("/api/workbooks").json())


def test_corrupt_file_rejected(client: TestClient) -> None:
    before = count_versions(client)
    response = upload(client, "broken.xlsx", b"this is not a zip file")
    assert response.status_code == 422
    assert "corrupt" in response.json()["detail"]
    assert count_versions(client) == before


def test_uploaded_at_is_timezone_aware(uploaded: dict) -> None:
    assert uploaded["uploaded_at"].endswith(("Z", "+00:00"))


@pytest.fixture
def tiny_upload_limit() -> Iterator[None]:
    settings = get_settings()
    original = settings.max_upload_mb
    settings.max_upload_mb = 0
    try:
        yield
    finally:
        settings.max_upload_mb = original


def test_oversized_upload_rejected(client: TestClient, tiny_upload_limit: None) -> None:
    before = count_versions(client)
    response = upload(client, "big.xlsx", fixture_xlsx_bytes())
    assert response.status_code == 413
    assert count_versions(client) == before
