"""Fixture workbooks for validation: one with every structural anomaly class, one with a perturbed cached value."""

from __future__ import annotations

import openpyxl

from tests.fixtures.logic_workbook import logic_cached_values
from tests.fixtures.workbook import (
    build_logic_fixture_workbook_bytes,
    inject_cached_values,
    workbook_bytes,
)

ROWS = 60
PASTED_ROW = 30
DUP_ROW = 50  # Data!A50 repeats the key of row 6


def build_anomaly_workbook() -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    data = wb.active
    data.title = "Data"
    data["A1"], data["B1"] = "Key", "Val"
    for i in range(1, ROWS + 1):
        r = i + 1
        data[f"A{r}"] = "K5" if r == DUP_ROW else f"K{i}"
        data[f"B{r}"] = 100 + i

    calc = wb.create_sheet("Calc")
    calc["A1"], calc["B1"], calc["C1"] = "Key", "Double", "Looked"
    for i in range(1, ROWS + 1):
        r = i + 1
        calc[f"A{r}"] = f"K{i}"
        calc[f"B{r}"] = f"=Data!B{r + 30}*2" if r == PASTED_ROW else f"=Data!B{r}*2"
        calc[f"C{r}"] = f"=VLOOKUP(A{r},Data!$A:$B,2,FALSE)"

    stale = wb.create_sheet("Stale")
    stale["A1"], stale["B1"] = "fresh", "=2+2"
    stale["A2"], stale["B2"] = "stale", "=1+1"
    return wb


def anomaly_cached_values() -> dict[tuple[str, str], object]:
    values: dict[tuple[str, str], object] = {}
    data_val = {i + 1: 100 + i for i in range(1, ROWS + 1)}  # row -> Data!B value
    for i in range(1, ROWS + 1):
        r = i + 1
        values[("Calc", f"B{r}")] = (
            data_val.get(r + 30, 0) if r == PASTED_ROW else data_val[r]
        ) * 2
        # Data!A30 holds "K5" instead of "K29", so the lookup for K29 misses.
        values[("Calc", f"C{r}")] = "#N/A" if r == DUP_ROW else data_val[r]
    values[("Stale", "B1")] = 4  # B2 deliberately left without a cached value
    return values


def anomaly_fixture_xlsx_bytes() -> bytes:
    return inject_cached_values(workbook_bytes(build_anomaly_workbook()), anomaly_cached_values())


def perturbed_fixture_xlsx_bytes() -> bytes:
    """The logic fixture with one wrong cached value (Series!C21 off by one)."""
    values = logic_cached_values()
    values[("Series", "C21")] = values[("Series", "C21")] + 1
    return inject_cached_values(build_logic_fixture_workbook_bytes(), values)
