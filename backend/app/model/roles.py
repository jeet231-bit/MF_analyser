"""Sheet role heuristics. Defaults only: config and user overrides win (see interpreter)."""

from __future__ import annotations

from app.model.schema import SheetModel, SheetRole

LOOKUP_FUNCTIONS = {"VLOOKUP", "HLOOKUP", "XLOOKUP", "LOOKUP", "INDEX", "MATCH"}


def infer_role(
    sheet: SheetModel,
    *,
    read_by_lookup_only: bool,
    cross_sheet_read_share: float,
) -> tuple[SheetRole, str]:
    """Return (role, reason).

    - reads no other sheet and is consumed only through lookup functions → reference
      (a lookup table, whatever its size, even if it derives some of its own columns)
    - no formulas → input
    - formulas, nothing reads it → output
    - formulas, mostly reads other sheets → transformation
    - otherwise → calculation
    """
    readers = [s for s in sheet.feeds if s != sheet.name]
    reads_others = [s for s in sheet.reads if s != sheet.name]
    if readers and read_by_lookup_only and not reads_others:
        how = (
            "no formulas"
            if sheet.formula_cells == 0
            else f"{sheet.formula_cells} formula cells over its own data only"
        )
        return "reference", f"{how}; read only through lookup functions by {', '.join(readers)}"
    if sheet.formula_cells == 0:
        if readers:
            return "input", f"no formulas; read by {', '.join(readers)}"
        return "input", "no formulas and nothing reads it"
    if not readers:
        return "output", f"{sheet.formula_cells} formula cells and no sheet reads them"
    if cross_sheet_read_share >= 0.5:
        return (
            "transformation",
            f"{cross_sheet_read_share:.0%} of its references read other sheets; feeds {', '.join(readers)}",
        )
    return (
        "calculation",
        f"{sheet.formula_cells} formula cells, mostly over its own data; feeds {', '.join(readers)}",
    )
