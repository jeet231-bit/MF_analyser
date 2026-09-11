"""The dashboard.config.json overlay: the only place workbook-specific names may live (CLAUDE.md rule 3)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import BACKEND_ROOT

DEFAULT_PATH = BACKEND_ROOT.parent / "dashboard.config.json"


class DashboardConfig(BaseModel):
    version: int = 1
    sheet_scope: list[str] = Field(default_factory=list, alias="sheetScope")
    sheet_role_overrides: dict[str, str] = Field(default_factory=dict, alias="sheetRoleOverrides")
    output_sheets: list[str] = Field(default_factory=list, alias="outputSheets")
    label_overrides: dict[str, str] = Field(default_factory=dict, alias="labelOverrides")

    model_config = {"populate_by_name": True, "extra": "ignore"}


@lru_cache
def load_dashboard_config(path: Path | None = None) -> DashboardConfig:
    target = path or DEFAULT_PATH
    if not target.exists():
        return DashboardConfig()
    with target.open(encoding="utf-8") as fh:
        return DashboardConfig.model_validate(json.load(fh))
