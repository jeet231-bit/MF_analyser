"""The dashboard.config.json overlay: the only place workbook-specific names may live (CLAUDE.md rule 3)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import BACKEND_ROOT, get_settings

DEFAULT_PATH = BACKEND_ROOT.parent / "dashboard.config.json"


class WorkbookDisplay(BaseModel):
    display_name: str | None = Field(default=None, alias="displayName")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class NumberFormat(BaseModel):
    grouping: str = "indian"
    decimals: int = 2

    model_config = {"extra": "ignore"}


class DashboardConfig(BaseModel):
    version: int = 1
    workbook: WorkbookDisplay = Field(default_factory=WorkbookDisplay)
    sheet_scope: list[str] = Field(default_factory=list, alias="sheetScope")
    sheet_role_overrides: dict[str, str] = Field(default_factory=dict, alias="sheetRoleOverrides")
    output_sheets: list[str] = Field(default_factory=list, alias="outputSheets")
    label_overrides: dict[str, str] = Field(default_factory=dict, alias="labelOverrides")
    number_format: NumberFormat = Field(default_factory=NumberFormat, alias="numberFormat")
    # The semantic map for the research views; validated by app.research.semantic, not here,
    # so a broken map degrades to a "not configured" state instead of breaking every page.
    research: Any | None = None

    model_config = {"populate_by_name": True, "extra": "ignore"}


def load_dashboard_config(path: Path | None = None) -> DashboardConfig:
    """The config file: an explicit path, else ``MFA_DASHBOARD_CONFIG``, else the repo root."""
    override = get_settings().dashboard_config_path
    target = path or (Path(override) if override else DEFAULT_PATH)
    return _load(target)


@lru_cache
def _load(target: Path) -> DashboardConfig:
    if not target.exists():
        return DashboardConfig()
    with target.open(encoding="utf-8") as fh:
        return DashboardConfig.model_validate(json.load(fh))
