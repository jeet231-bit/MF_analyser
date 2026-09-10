"""Coercion of openpyxl cell values into the RawWorkbook value model.

Dates become Excel serial numbers (the engine's native representation); the number format
string is what tells a consumer to render them as dates.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, to_excel

from app.parser.models import EXCEL_ERRORS, CellValue, ValueType


def _epoch_datetime(epoch: int) -> dt.datetime:
    return CALENDAR_MAC_1904 if epoch == 1904 else CALENDAR_WINDOWS_1900


def coerce_value(raw: Any, data_type: str | None, epoch: int = 1900) -> tuple[CellValue, ValueType]:
    """Return (value, value_type) for a cached (non-formula) cell value."""
    if raw is None:
        return None, "empty"
    if isinstance(raw, bool):
        return raw, "bool"
    if isinstance(raw, int | float):
        return raw, "number"
    if isinstance(raw, dt.datetime | dt.date | dt.time | dt.timedelta):
        serial = to_excel(raw, _epoch_datetime(epoch))
        if isinstance(serial, float) and serial.is_integer():
            serial = int(serial)
        return serial, "date"
    if isinstance(raw, str):
        if data_type == "e" or raw in EXCEL_ERRORS:
            return raw, "error"
        return raw, "text"
    # Rich text, CellRichText and other exotic objects: keep their string form.
    return str(raw), "text"
