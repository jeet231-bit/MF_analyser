"""Expose the display parts of dashboard.config.json to the frontend."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.dashboard_config import load_dashboard_config

router = APIRouter(prefix="/config")


class DashboardConfigOut(BaseModel):
    display_name: str | None
    sheet_scope: list[str]
    number_grouping: str
    number_decimals: int


@router.get("", response_model=DashboardConfigOut)
def get_config() -> DashboardConfigOut:
    cfg = load_dashboard_config()
    return DashboardConfigOut(
        display_name=cfg.workbook.display_name,
        sheet_scope=cfg.sheet_scope,
        number_grouping=cfg.number_format.grouping,
        number_decimals=cfg.number_format.decimals,
    )
