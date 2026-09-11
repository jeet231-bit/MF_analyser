"""Interpret a RawWorkbook into a WorkbookLogicModel.

Streams sheets one at a time through a loader callable, so the interpreter never holds more
than one sheet's cells plus the (small) block-level model. See the Phase 2 plan for the
template / block / footprint design.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.model import blocks as blk
from app.model.formula.ast import (
    AREA_REFS,
    Call,
    CellRef,
    NameRef,
    Node,
    RangeRef,
    StructuredRef,
    iter_nodes,
    iter_refs,
    r1c1_text,
    ref_footprint,
    ref_rect,
)
from app.model.formula.parser import FormulaParseError, parse_formula
from app.model.formula.refs import Rect, a1_cell
from app.model.graph import (
    analyse_graph,
    analyse_self_dependency,
    build_edges,
    describe_cycles,
    sheet_edges,
)
from app.model.roles import LOOKUP_FUNCTIONS, infer_role
from app.model.rules import extract_rules
from app.model.schema import (
    Footprint,
    FormulaBlock,
    InputBlock,
    ModelSummary,
    RectModel,
    SheetModel,
    Template,
    WorkbookLogicModel,
)
from app.model.templates import TemplateDraft, TemplateRegistry
from app.parser.models import RawSheet, RawWorkbook

log = logging.getLogger(__name__)

SheetLoader = Callable[[str], RawSheet]


@dataclass
class InterpretOptions:
    scope: list[str] | None = None
    config_role_overrides: dict[str, str] = field(default_factory=dict)
    user_role_overrides: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    output_sheets: list[str] = field(default_factory=list)


def peak_memory_mb() -> float:
    try:
        if sys.platform == "win32":
            import psutil

            return psutil.Process().memory_info().peak_wset / (1024 * 1024)
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / 1024 if sys.platform != "darwin" else rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return 0.0


def resolve_scope(meta: RawWorkbook, scope: list[str] | None) -> list[str]:
    names = meta.sheet_names
    if not scope:
        return list(names)
    unknown = [s for s in scope if s not in names]
    if unknown:
        raise ValueError(f"sheets not in workbook: {unknown}")
    return [s for s in names if s in scope]


def interpret(
    meta: RawWorkbook,
    load_sheet: SheetLoader,
    *,
    version_id: str,
    options: InterpretOptions | None = None,
) -> WorkbookLogicModel:
    options = options or InterpretOptions()
    started = time.perf_counter()
    scope = resolve_scope(meta, options.scope)
    in_scope = set(scope)
    extents: dict[str, Rect] = {
        s.name: Rect.from_a1(s.used_range) for s in meta.sheets if s.used_range
    }
    defined_names = {n.name: n for n in meta.defined_names if not n.builtin}
    tables = {t.display_name: t for t in meta.tables}
    unresolved: list[str] = []

    # ---- Pass A: templates and formula blocks per in-scope sheet ---------------------------
    registry = TemplateRegistry()
    sheet_meta = {s.name: s for s in meta.sheets}
    for name in scope:
        sm = sheet_meta[name]
        if sm.formula_count == 0:
            continue
        t0 = time.perf_counter()
        raw = load_sheet(name)
        touched = registry.add_sheet(raw)
        log.info(
            "templates: %r %d formulas -> %d templates touched in %.1fs",
            name,
            raw.formula_count,
            len(touched),
            time.perf_counter() - t0,
        )
        del raw

    templates: list[Template] = []
    formula_blocks: list[FormulaBlock] = []
    draft_of_block: dict[int, TemplateDraft] = {}
    for draft in registry.templates:
        block_ids: list[int] = []
        for rect in draft.block_rects:
            block = FormulaBlock(
                id=len(formula_blocks),
                sheet=draft.sheet,
                template_id=draft.id,
                rect=RectModel.of(rect),
                cell_count=rect.cells,
            )
            formula_blocks.append(block)
            draft_of_block[block.id] = draft
            block_ids.append(block.id)
        templates.append(
            Template(
                id=draft.id,
                sheet=draft.sheet,
                r1c1=draft.key,
                ast=draft.ast,
                example_cell=a1_cell(draft.example_row, draft.example_col),
                example_formula=draft.example_formula,
                cell_count=sum(r.cells for r in draft.block_rects),
                block_ids=block_ids,
                functions=draft.functions,
                array_ref=draft.array_ref,
                parse_error=draft.parse_error,
            )
        )

    # ---- Footprints ----------------------------------------------------------------------
    footprints_by_sheet: dict[str, list[Rect]] = {}
    lookup_only_readers: dict[str, bool] = {}  # sheet -> read only via lookup functions so far
    value_requests: dict[str, set[Rect]] = {}

    def add_request(sheet: str, rect: Rect) -> None:
        if rect.rows <= 50 and rect.cols <= 10:
            value_requests.setdefault(sheet, set()).add(rect)

    for block in formula_blocks:
        draft = draft_of_block[block.id]
        if draft.ast is None:
            continue
        # An array formula evaluates once at its anchor; its references do not slide per cell.
        rect = (
            Rect.cell(draft.example_row, draft.example_col)
            if draft.array_ref
            else block.rect.rect()
        )
        seen: set[str] = set()
        lookup_ranges = _lookup_range_ids(draft.ast)
        for ref in iter_refs(draft.ast):
            text = r1c1_text(ref)
            if text in seen:
                continue
            seen.add(text)
            target = ref.sheet or block.sheet
            extent = extents.get(target)
            if extent is None:
                if target not in sheet_meta:
                    unresolved.append(f"{block.sheet}!{block.rect.a1}: unknown sheet {target!r}")
                continue
            fp = ref_footprint(ref, rect, extent)
            if fp is None:
                continue
            block.footprints.append(Footprint(sheet=target, rect=RectModel.of(fp), ref=text))
            footprints_by_sheet.setdefault(target, []).append(fp)
            if target != block.sheet:
                is_lookup = id(ref) in lookup_ranges
                lookup_only_readers[target] = lookup_only_readers.get(target, True) and is_lookup
        for node in iter_nodes(draft.ast):
            if isinstance(node, NameRef):
                dn = defined_names.get(node.name)
                if dn is None:
                    unresolved.append(f"{block.sheet}!{block.rect.a1}: unknown name {node.name!r}")
                    continue
                resolved = _resolve_defined_name(dn.refers_to, extents, sheet_meta)
                if resolved is None:
                    unresolved.append(f"name {node.name!r} refers to {dn.refers_to!r}, not a range")
                    continue
                target, fp = resolved
                block.footprints.append(
                    Footprint(sheet=target, rect=RectModel.of(fp), ref=node.name)
                )
                footprints_by_sheet.setdefault(target, []).append(fp)
            elif isinstance(node, StructuredRef):
                table = tables.get(node.table or "")
                if table is None:
                    unresolved.append(
                        f"{block.sheet}!{block.rect.a1}: unknown table {node.table!r}"
                    )
                    continue
                fp = Rect.from_a1(table.ref)
                block.footprints.append(
                    Footprint(
                        sheet=table.sheet,
                        rect=RectModel.of(fp),
                        ref=f"{table.display_name}[{node.spec}]",
                    )
                )
                footprints_by_sheet.setdefault(table.sheet, []).append(fp)
        # Values needed later for rules (small fixed lookup tables, absolute threshold cells).
        for node in iter_nodes(draft.ast):
            if (
                isinstance(node, Call)
                and node.name in ("VLOOKUP", "HLOOKUP", "XLOOKUP", "LOOKUP")
                and len(node.args) > 1
            ):
                rng = node.args[1]
                if isinstance(rng, AREA_REFS) and _fully_absolute(rng):
                    target = rng.sheet or block.sheet
                    rr = ref_rect(rng, draft.example_row, draft.example_col, extents.get(target))
                    if rr is not None:
                        add_request(target, rr)
            if isinstance(node, CellRef) and node.row.abs and node.col.abs:
                target = node.sheet or block.sheet
                if target in extents:
                    add_request(target, Rect.cell(node.row.v, node.col.v))

    # ---- Pass B: input blocks, labels, static counts, values for rules ---------------------
    input_blocks: list[InputBlock] = []
    sheet_models: dict[str, SheetModel] = {}
    table_values: dict[tuple[str, Rect], list[list[object]] | None] = {}
    labels_at: dict[tuple[str, int, int], str] = {}
    blocks_on_sheet: dict[str, list[FormulaBlock]] = {}
    for b in formula_blocks:
        blocks_on_sheet.setdefault(b.sheet, []).append(b)

    referenced = set(footprints_by_sheet) | in_scope
    for name in meta.sheet_names:
        sm = sheet_meta[name]
        model = SheetModel(
            name=name,
            index=sm.index,
            state=sm.state,
            in_scope=name in in_scope,
            used_range=sm.used_range,
            cell_count=sm.cell_count,
            formula_cells=sm.formula_count if name in in_scope else 0,
        )
        sheet_models[name] = model
        if name not in referenced or name not in extents:
            continue
        t0 = time.perf_counter()
        raw = load_sheet(name)
        wants_values = bool(value_requests.get(name))
        arrays = blk.sheet_arrays(raw, extents[name], keep_values=wants_values)
        del raw
        covered = blk.coverage_mask(arrays, footprints_by_sheet.get(name, []))
        kind = "input" if name in in_scope else "external"
        for rect in blk.input_rects(arrays, covered):
            ib = InputBlock(
                id=len(formula_blocks) + len(input_blocks),
                sheet=name,
                rect=RectModel.of(rect),
                cell_count=blk.constants_in(arrays, rect),
                kind=kind,
                value_types=blk.value_types_in(arrays, rect),
                column_labels=blk.column_labels(arrays, rect),
                row_label_col=blk.row_label_column(arrays, rect),
            )
            input_blocks.append(ib)
            model.input_block_ids.append(ib.id)
            model.input_cells += ib.cell_count
        model.static_cells = blk.static_count(arrays, covered)
        for fb in blocks_on_sheet.get(name, []):
            r = fb.rect.rect()
            fb.column_labels = blk.column_labels(arrays, r)
            fb.row_label_col = blk.row_label_column(arrays, r)
            model.formula_block_ids.append(fb.id)
        for rect in value_requests.get(name, ()):
            table_values[(name, rect)] = blk.values_in(arrays, rect)
            for rr in range(rect.r1, rect.r2 + 1):
                for cc in range(rect.c1, rect.c2 + 1):
                    lbl = _label_near(arrays, rr, cc)
                    if lbl:
                        labels_at[(name, rr, cc)] = lbl
        log.info("classified %r in %.1fs", name, time.perf_counter() - t0)
        del arrays, covered

    # ---- Graph ----------------------------------------------------------------------------
    edges = build_edges(formula_blocks, input_blocks)
    for block in formula_blocks:
        block.self_dependent, block.self_order = analyse_self_dependency(
            block, draft_of_block[block.id].ast
        )
    order, cycles = analyse_graph(formula_blocks, edges)
    cycle_descriptions = describe_cycles(cycles, formula_blocks, edges)
    for block in formula_blocks:
        if block.self_order == "cycle":
            cycle_descriptions.append(
                f"{block.sheet}!{block.rect.a1} reads its own cells in a way that has no evaluation order"
            )
    s_edges = sheet_edges(edges, formula_blocks, input_blocks)
    for e in s_edges:
        sheet_models[e.source].feeds.append(e.target)
        sheet_models[e.target].reads.append(e.source)

    # ---- Sheet roles (heuristic -> config -> user override) ---------------------------------
    for name, model in sheet_models.items():
        if not model.in_scope:
            continue
        own = sum(len(b.footprints) for b in blocks_on_sheet.get(name, []))
        cross = sum(
            1 for b in blocks_on_sheet.get(name, []) for fp in b.footprints if fp.sheet != name
        )
        share = cross / own if own else 0.0
        role, reason = infer_role(
            model,
            read_by_lookup_only=lookup_only_readers.get(name, False),
            cross_sheet_read_share=share,
        )
        model.role, model.role_reason, model.role_source = role, reason, "heuristic"
        if name in options.output_sheets:
            model.role, model.role_source, model.role_reason = (
                "output",
                "config",
                "listed in dashboard.config.json outputSheets",
            )
        if name in options.config_role_overrides:
            model.role = options.config_role_overrides[name]  # type: ignore[assignment]
            model.role_source, model.role_reason = (
                "config",
                "dashboard.config.json sheetRoleOverrides",
            )
        if name in options.user_role_overrides:
            role_o, reason_o = options.user_role_overrides[name]
            model.role, model.role_source = role_o, "override"  # type: ignore[assignment]
            model.role_reason = reason_o or "user override"

    # ---- Block classification -------------------------------------------------------------
    readers: dict[int, int] = {b.id: 0 for b in formula_blocks}
    for e in edges:
        if e.source in readers and e.source != e.target:
            readers[e.source] += 1
    for block in formula_blocks:
        is_output = readers[block.id] == 0 or sheet_models[block.sheet].role == "output"
        block.classification = "output" if is_output else "calculation"
        if is_output:
            sheet_models[block.sheet].output_cells += block.cell_count

    # ---- Rules ------------------------------------------------------------------------------
    counter = iter(range(1_000_000))

    def values(sheet: str, rect: Rect):
        return table_values.get((sheet, rect))

    def label(sheet: str, row: int, col: int) -> str | None:
        return labels_at.get((sheet, row, col))

    rules = []
    for tpl in templates:
        ranges = [formula_blocks[bid].rect.a1 for bid in tpl.block_ids]
        rules.extend(
            extract_rules(tpl, ranges, values=values, label=label, next_id=lambda: next(counter))
        )

    seconds = time.perf_counter() - started
    summary = ModelSummary(
        sheets_in_scope=len(scope),
        templates=len(templates),
        formula_blocks=len(formula_blocks),
        input_blocks=sum(1 for b in input_blocks if b.kind == "input"),
        external_blocks=sum(1 for b in input_blocks if b.kind == "external"),
        formula_cells=sum(t.cell_count for t in templates),
        input_cells=sum(m.input_cells for m in sheet_models.values() if m.in_scope),
        output_cells=sum(m.output_cells for m in sheet_models.values()),
        static_cells=sum(m.static_cells for m in sheet_models.values() if m.in_scope),
        rules=len(rules),
        parse_errors=sum(1 for t in templates if t.parse_error),
        cycles=len(cycles) + sum(1 for b in formula_blocks if b.self_order == "cycle"),
        self_dependent_blocks=sum(1 for b in formula_blocks if b.self_dependent),
        unresolved_references=len(unresolved),
        seconds=round(seconds, 2),
        peak_mb=round(peak_memory_mb(), 1),
    )
    log.info("interpreted %s: %s", version_id, summary.model_dump())
    return WorkbookLogicModel(
        version_id=version_id,
        created_at=datetime.now(UTC),
        scope=scope,
        sheets=[sheet_models[n] for n in meta.sheet_names],
        templates=templates,
        formula_blocks=formula_blocks,
        input_blocks=input_blocks,
        edges=edges,
        sheet_edges=s_edges,
        execution_order=order,
        cycles=cycles,
        cycle_descriptions=cycle_descriptions,
        unresolved=sorted(set(unresolved)),
        rules=rules,
        summary=summary,
    )


def _lookup_range_ids(ast: Node) -> set[int]:
    ids: set[int] = set()
    for node in iter_nodes(ast):
        if isinstance(node, Call) and node.name in LOOKUP_FUNCTIONS:
            for arg in node.args:
                if isinstance(arg, AREA_REFS):
                    ids.add(id(arg))
    return ids


def _fully_absolute(ref: Node) -> bool:
    if isinstance(ref, CellRef):
        return ref.row.abs and ref.col.abs
    if isinstance(ref, RangeRef):
        return all(a.abs for a in (ref.r1, ref.c1, ref.r2, ref.c2))
    return all(
        a.abs for a in (getattr(ref, "c1", None), getattr(ref, "c2", None)) if a is not None
    ) and all(a.abs for a in (getattr(ref, "r1", None), getattr(ref, "r2", None)) if a is not None)


def _resolve_defined_name(
    refers_to: str, extents: dict[str, Rect], sheet_meta
) -> tuple[str, Rect] | None:
    text = refers_to.lstrip("=")
    try:
        node = parse_formula("=" + text, "", 1, 1)
    except FormulaParseError:
        return None
    refs = list(iter_refs(node))
    if len(refs) != 1 or refs[0].sheet is None:
        return None
    ref = refs[0]
    if ref.sheet not in sheet_meta:
        return None
    rect = ref_rect(ref, 1, 1, extents.get(ref.sheet))
    if rect is None:
        return None
    return ref.sheet, rect


def _label_near(arrays: blk.SheetArrays, row: int, col: int) -> str | None:
    for c in range(col - 1, max(0, col - 1 - blk.LABEL_SEARCH_COLS), -1):
        text = arrays.text_at.get((row, c))
        if text:
            return text
    for r in range(row - 1, max(0, row - 1 - blk.LABEL_SEARCH_ROWS), -1):
        text = arrays.text_at.get((r, col))
        if text:
            return text
    return None


def cell_dependencies(
    model: WorkbookLogicModel, sheet: str, row: int, col: int
) -> list[tuple[str, Rect]]:
    """Exact ranges a formula cell reads, derived from its template at that cell."""
    block = model.block_at(sheet, row, col)
    if not isinstance(block, FormulaBlock):
        return []
    tpl = model.template(block.template_id)
    if tpl.ast is None:
        return []
    if tpl.array_ref:
        anchor = Rect.from_a1(tpl.array_ref)
        row, col = anchor.r1, anchor.c1
    out: list[tuple[str, Rect]] = []
    seen: set[tuple[str, Rect]] = set()
    for ref in iter_refs(tpl.ast):
        target = ref.sheet or sheet
        target_sheet = model.sheet(target)
        extent = (
            Rect.from_a1(target_sheet.used_range)
            if target_sheet is not None and target_sheet.used_range
            else None
        )
        rect = ref_rect(ref, row, col, extent)
        if rect is None:
            continue
        key = (target, rect)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def cell_dependents(
    model: WorkbookLogicModel, sheet: str, row: int, col: int
) -> list[tuple[FormulaBlock, list[str]]]:
    """Formula blocks (and the exact cells inside them) that read the given cell."""
    result: list[tuple[FormulaBlock, list[str]]] = []
    for block in model.formula_blocks:
        if not any(
            fp.sheet == sheet and fp.rect.rect().contains(row, col) for fp in block.footprints
        ):
            continue
        tpl = model.template(block.template_id)
        if tpl.ast is None:
            continue
        rect = block.rect.rect()
        cells: list[str] = []
        for ref in iter_refs(tpl.ast):
            if (ref.sheet or block.sheet) != sheet:
                continue
            for r in range(rect.r1, rect.r2 + 1):
                for c in range(rect.c1, rect.c2 + 1):
                    rr = ref_rect(ref, r, c)
                    if rr is not None and rr.contains(row, col):
                        cells.append(a1_cell(r, c))
                if len(cells) > 200:
                    break
        if cells:
            result.append((block, sorted(set(cells))))
    return result


__all__ = ["InterpretOptions", "interpret", "cell_dependencies", "cell_dependents", "np"]
