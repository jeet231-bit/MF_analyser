"""Sheet role heuristics. Defaults only: config and user overrides win (see interpreter)."""

from __future__ import annotations

from app.model.schema import SheetModel, SheetRole

LOOKUP_FUNCTIONS = {"VLOOKUP", "HLOOKUP", "XLOOKUP", "LOOKUP", "INDEX", "MATCH"}
REFERENCE_MAX_CELLS = 2000


def infer_role(
    sheet: SheetModel,
    *,
    read_by_lookup_only: bool,
    cross_sheet_read_share: float,
) -> tuple[SheetRole, str]:
    """Return (role, reason).

    - no formulas, read by others via lookups and small → reference
    - no formulas → input
    - formulas, nothing reads it → output
    - formulas, mostly reads other sheets → transformation
    - otherwise → calculation
    """
    readers = [s for s in sheet.feeds if s != sheet.name]
    if sheet.formula_cells == 0:
        if readers and read_by_lookup_only and sheet.cell_count <= REFERENCE_MAX_CELLS:
            return (
                "reference",
                f"no formulas; {sheet.cell_count} cells read only through lookup functions",
            )
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
