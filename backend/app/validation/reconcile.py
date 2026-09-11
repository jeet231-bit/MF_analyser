"""Cell-by-cell reconciliation of engine output against Excel's cached values."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from app.engine.values import round15
from app.model.formula.ast import a1_text
from app.model.formula.refs import parse_a1_cell
from app.model.schema import FormulaBlock, WorkbookLogicModel
from app.parser.models import RawSheet
from app.validation.schema import (
    Mismatch,
    SheetCoverage,
    Totals,
    UnsupportedTemplate,
    ValidationPolicy,
)

MISMATCH_CAP = 2000
ComputedLookup = Callable[[str], dict[str, tuple[Any, str]]]  # sheet -> address -> (value, type)


def values_equal(excel: Any, engine: Any, digits: int = 15) -> bool:
    """Numbers equal at 15 significant digits (the engine's own rule); everything else exact."""
    if isinstance(excel, bool) or isinstance(engine, bool):
        return excel is engine
    if isinstance(excel, int | float) and isinstance(engine, int | float):
        if excel == engine:
            return True
        if digits == 15:
            return float(round15(excel)) == float(round15(engine))
        return f"{excel:.{digits}g}" == f"{engine:.{digits}g}"
    return excel == engine


def classify(excel: Any, engine: Any) -> tuple[str, float | None]:
    numeric = (
        isinstance(excel, int | float)
        and isinstance(engine, int | float)
        and not isinstance(excel, bool)
        and not isinstance(engine, bool)
    )
    if numeric:
        delta = float(engine) - float(excel)
        close = math.isclose(float(excel), float(engine), rel_tol=1e-9, abs_tol=1e-12)
        return ("precision" if close else "semantics"), delta
    excel_err = isinstance(excel, str) and excel.startswith("#")
    engine_err = isinstance(engine, str) and engine.startswith("#")
    if excel_err != engine_err:
        return "data", None
    return "semantics", None


def reconcile(
    model: WorkbookLogicModel,
    raw_sheets: dict[str, RawSheet],
    computed: ComputedLookup,
    unsupported_template_ids: set[int],
    policy: ValidationPolicy,
) -> tuple[Totals, list[SheetCoverage], list[Mismatch], bool, list[UnsupportedTemplate]]:
    totals = Totals()
    coverage: list[SheetCoverage] = []
    mismatches: list[Mismatch] = []
    truncated = False
    unsupported: dict[int, UnsupportedTemplate] = {}
    blocks_by_sheet: dict[str, list[FormulaBlock]] = {}
    for b in model.formula_blocks:
        blocks_by_sheet.setdefault(b.sheet, []).append(b)

    for sheet_model in model.sheets:
        if not sheet_model.in_scope:
            continue
        raw = raw_sheets.get(sheet_model.name)
        if raw is None or raw.formula_count == 0:
            coverage.append(
                SheetCoverage(
                    sheet=sheet_model.name,
                    formula_cells=0,
                    checked=0,
                    matched=0,
                    mismatched=0,
                    skipped_unsupported=0,
                    skipped_stale=0,
                )
            )
            continue
        engine_values = computed(sheet_model.name)
        blocks = blocks_by_sheet.get(sheet_model.name, [])
        cov = SheetCoverage(
            sheet=sheet_model.name,
            formula_cells=raw.formula_count,
            checked=0,
            matched=0,
            mismatched=0,
            skipped_unsupported=0,
            skipped_stale=0,
        )
        for addr, formula in raw.formulas():
            row, col = parse_a1_cell(addr)
            block = next((b for b in blocks if b.rect.rect().contains(row, col)), None)
            template_id = block.template_id if block else None
            if template_id is not None and template_id in unsupported_template_ids:
                cov.skipped_unsupported += 1
                tpl = model.template(template_id)
                entry = unsupported.get(template_id)
                if entry is None:
                    fn = next((f for f in tpl.functions if f not in _supported()), "<unparsed>")
                    unsupported[template_id] = UnsupportedTemplate(
                        function=fn, sheet=tpl.sheet, cell=tpl.example_cell, cells=1
                    )
                else:
                    entry.cells += 1
                continue
            cell = raw.cell(addr)
            if cell is None or cell.value_type == "empty":
                cov.skipped_stale += 1
                continue
            excel = cell.value
            if cell.value_type == "date":
                excel = float(excel)
            engine = engine_values.get(addr, (None, "empty"))[0]
            cov.checked += 1
            if values_equal(excel, engine, policy.significant_digits):
                cov.matched += 1
                continue
            cov.mismatched += 1
            if len(mismatches) >= MISMATCH_CAP:
                truncated = True
                continue
            kind, delta = classify(excel, engine)
            tpl = model.template(template_id) if template_id is not None else None
            rendered = (
                ("=" + a1_text(tpl.ast, row, col))
                if tpl is not None and tpl.ast is not None
                else formula
            )
            mismatches.append(
                Mismatch(
                    sheet=sheet_model.name,
                    cell=addr,
                    template_id=template_id,
                    formula=rendered,
                    excel=excel,
                    engine=engine,
                    delta=delta,
                    classification=kind,  # type: ignore[arg-type]
                )
            )
        coverage.append(cov)
        totals.checked += cov.checked
        totals.matched += cov.matched
        totals.mismatched += cov.mismatched
        totals.skipped_unsupported += cov.skipped_unsupported
        totals.skipped_stale += cov.skipped_stale
    return totals, coverage, mismatches, truncated, list(unsupported.values())


def _supported() -> set[str]:
    from app.engine.functions import REGISTRY

    return set(REGISTRY)
