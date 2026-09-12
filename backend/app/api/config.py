"""Expose the display parts of dashboard.config.json to the frontend."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.dashboard_config import load_dashboard_config

router = APIRouter(prefix="/config")


class DashboardConfigOut(BaseModel):
    display_name: str | None
    sheet_scope: list[str]
    output_sheets: list[str]
    label_overrides: dict[str, str]
    number_grouping: str
    number_decimals: int
    viewer_name: str | None = None


@router.get("", response_model=DashboardConfigOut)
def get_config() -> DashboardConfigOut:
    cfg = load_dashboard_config()
    return DashboardConfigOut(
        display_name=cfg.workbook.display_name,
        sheet_scope=cfg.sheet_scope,
        output_sheets=cfg.output_sheets,
        label_overrides=cfg.label_overrides,
        number_grouping=cfg.number_format.grouping,
        number_decimals=cfg.number_format.decimals,
        viewer_name=(cfg.viewer or {}).get("defaultName") or None,
    )
