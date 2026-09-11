from fastapi.testclient import TestClient


def test_config_endpoint_exposes_display_settings(client: TestClient) -> None:
    body = client.get("/api/config").json()
    assert set(body) == {
        "display_name",
        "sheet_scope",
        "output_sheets",
        "label_overrides",
        "number_grouping",
        "number_decimals",
    }
    assert isinstance(body["sheet_scope"], list)
    assert body["number_grouping"] in ("indian", "international")
