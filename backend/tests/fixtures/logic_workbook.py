"""Extended fixture for the logic model: every classification and rule pattern in one file.

Builds on the Phase 1 fixture (Inputs / Lookup / Calc) and adds:
- Series: a 20-row table with copied formulas (one template per column), a running total
  (self-dependent block), a nested-IF band ladder, a fixed-table VLOOKUP, an IFERROR fallback,
  and a threshold against an absolute labelled cell on another sheet.
- Outputs: three formulas reading Series that nothing else reads (output role, block sinks).
- Calc gets a static note nothing references.
"""

from __future__ import annotations

from openpyxl.worksheet.formula import ArrayFormula

from tests.fixtures.workbook import (
    FIXTURE_CACHED_VALUES,
    build_fixture_workbook,
    inject_cached_values,
    workbook_bytes,
)

ROWS = 20
SALES = [90 + 7 * i for i in range(1, ROWS + 1)]  # 97 .. 230
BANDS = {"Low": 1, "Mid": 2, "High": 3}
UNITS = 120  # Inputs!B3


def band(sales: int) -> str:
    return "Low" if sales <= 120 else ("Mid" if sales <= 200 else "High")


def build_logic_fixture_workbook():
    wb = build_fixture_workbook()
    lookup = wb["Lookup"]
    for i, (name, code) in enumerate(BANDS.items(), start=1):
        lookup[f"D{i}"], lookup[f"E{i}"] = name, code

    wb["Calc"]["A14"] = "Notes: values in INR lakh"

    s = wb.create_sheet("Series")
    for col, header in zip(
        "ABCDEFG",
        ["Month", "Sales", "Cumulative", "Band", "Rated", "Safe", "Above units"],
        strict=True,
    ):
        s[f"{col}1"] = header
    for i in range(1, ROWS + 1):
        r = i + 1
        s[f"A{r}"] = i
        s[f"B{r}"] = SALES[i - 1]
        s[f"C{r}"] = "=B2" if r == 2 else f"=C{r - 1}+B{r}"
        s[f"D{r}"] = f'=IF(B{r}<=120,"Low",IF(B{r}<=200,"Mid","High"))'
        s[f"E{r}"] = f"=VLOOKUP(D{r},Lookup!$D$1:$E$3,2,FALSE)"
        s[f"F{r}"] = f'=IFERROR(E{r}/B{r},"n/a")'
        s[f"G{r}"] = f"=B{r}>Inputs!$B$3"

    o = wb.create_sheet("Outputs")
    o["A1"], o["B1"] = "Total sales", "=SUM(Series!B2:B21)"
    o["A2"], o["B2"] = "Peak cumulative", "=MAX(Series!C2:C21)"
    o["A3"], o["B3"] = "High months", '=COUNTIF(Series!D2:D21,"High")'

    # Excel semantics the engine must reproduce exactly (cached values in SEMANTICS_CACHED).
    sm = wb.create_sheet("Semantics")
    sm["A1"], sm["A2"], sm["B2"], sm["A3"], sm["B3"], sm["A4"], sm["B4"] = (
        "x",
        "y",
        7,
        "t",
        "12",
        "e",
        "=1/0",
    )
    for i, v in enumerate(["--", 1, "--", "x"], start=1):
        sm[f"D{i}"] = v
    for i, v in enumerate([2, 3, 4, 5, 6], start=1):
        sm[f"E{i}"] = v
    for addr, formula in SEMANTICS_FORMULAS.items():
        if addr in ("F1", "F2"):
            continue
        sm[addr] = formula
    sm["F1"] = ArrayFormula("F1:F2", "=E1:E2*2")
    return wb


SEMANTICS_FORMULAS: dict[str, str] = {
    "C1": "=B1+1",
    "C2": '=B1&"x"',
    "C3": "=B3+1",
    "C4": "=B4*2",
    "C5": '="a"+1',
    "C6": "=B1=0",
    "C7": '=IF(B1,"t","f")',
    "C8": '=COUNTIF(D1:D5,"<>--")',
    "C9": '=COUNTIF(D1:D5,"*-")',
    "C10": '=SUMIF(D1:D5,">0")',
    "C11": "=SUMPRODUCT(D1:D5,E1:E5)",
    "C12": '=SEARCH("ta",B3&"beta")',
    "C13": '=ISNUMBER(SEARCH("zz","abc"))',
    "C14": '=LEFT("Fund - Growth",4)',
    "C15": "=DATE(2026,1,31)",
    "C16": "=YEAR(C15)",
    "C17": "=MONTH(C15)",
    "C18": "=DAY(C15)",
    "C19": '=HLOOKUP("Rating",Lookup!$A$1:$B$4,3,FALSE)',
    "C20": '=VLOOKUP("Zed",Lookup!$A:$B,2,FALSE)',
    "C21": '=IFERROR(C20,"missing")',
    "C22": '=AVERAGEIF(E1:E5,">3")',
    "C23": "=COUNT(D1:E5)",
    "C24": '=AND(B2>5,B3="12")',
    "C25": '=OR(B2<5,B1="")',
    "C26": "=B2>B3",
    "C27": "=B3*1",
    "C28": "=Threshold*10",
    "C29": '=CONCATENATE("v",B2,"-",C6)',
    "F1": "=E1:E2*2",
    "F2": "=E1:E2*2",
}

SEMANTICS_CACHED: dict[str, object] = {
    "B4": "#DIV/0!",
    "C1": 1,
    "C2": "x",
    "C3": 13,
    "C4": "#DIV/0!",
    "C5": "#VALUE!",
    "C6": True,
    "C7": "f",
    "C8": 3,
    "C9": 2,
    "C10": 1,
    "C11": 3,
    "C12": 5,
    "C13": False,
    "C14": "Fund",
    "C15": 46053,
    "C16": 2026,
    "C17": 1,
    "C18": 31,
    "C19": 2,
    "C20": "#N/A",
    "C21": "missing",
    "C22": 5,
    "C23": 6,
    "C24": True,
    "C25": True,
    "C26": False,
    "C27": 12,
    "C28": 7.5,
    "C29": "v7-TRUE",
    "F1": 4,
    "F2": 6,
}


def logic_cached_values() -> dict[tuple[str, str], object]:
    values: dict[tuple[str, str], object] = dict(FIXTURE_CACHED_VALUES)
    cumulative = 0
    for i in range(1, ROWS + 1):
        r = i + 1
        sales = SALES[i - 1]
        cumulative += sales
        b = band(sales)
        rated = BANDS[b]
        values[("Series", f"C{r}")] = cumulative
        values[("Series", f"D{r}")] = b
        values[("Series", f"E{r}")] = rated
        values[("Series", f"F{r}")] = rated / sales
        values[("Series", f"G{r}")] = sales > UNITS
    values[("Outputs", "B1")] = sum(SALES)
    values[("Outputs", "B2")] = cumulative
    values[("Outputs", "B3")] = sum(1 for x in SALES if band(x) == "High")
    for addr, value in SEMANTICS_CACHED.items():
        values[("Semantics", addr)] = value
    return values


def logic_fixture_xlsx_bytes() -> bytes:
    return inject_cached_values(
        workbook_bytes(build_logic_fixture_workbook()), logic_cached_values()
    )


def cycle_fixture_xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cyc"
    ws["A1"], ws["B1"], ws["C1"] = "=B1+1", "=A1+1", 5
    ws["A2"] = "=C1*2"
    return inject_cached_values(
        workbook_bytes(wb), {("Cyc", "A1"): 0, ("Cyc", "B1"): 0, ("Cyc", "A2"): 10}
    )
