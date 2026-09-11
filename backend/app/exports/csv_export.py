"""CSV export: exactly what a view shows, one header row of labels, values as Excel would type
them (numbers unquoted, booleans TRUE/FALSE, errors as their text, dates as ISO when known)."""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl.utils.datetime import from_excel

from app.exports.descriptor import ExportView


def _text(value: Any, vtype: str | None, fmt: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        if fmt == "date" or vtype == "date":
            try:
                return from_excel(float(value)).date().isoformat()
            except (ValueError, OverflowError, TypeError):
                return repr(value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


def write_csv(view: ExportView) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([view.row_label_header] + [c.label for c in view.columns])
    for r, values in enumerate(view.rows):
        types = view.types[r] if view.types else [None] * len(values)
        label = view.row_labels[r] if r < len(view.row_labels) else ""
        w.writerow(
            [label or ""]
            + [
                _text(v, t, col.format)
                for v, t, col in zip(values, types, view.columns, strict=True)
            ]
        )
    return buf.getvalue()
