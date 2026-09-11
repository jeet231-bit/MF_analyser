"""Run a WorkbookLogicModel: full runs and incremental (override-driven) runs.

The engine never touches the original file. Inputs come from the stored RawSheet cached
values, formula cells are recomputed block by block in topological order, template-at-a-time.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from app.engine.evaluator import BlockContext, evaluate_array, evaluate_block
from app.engine.functions import REGISTRY, UnsupportedFunctionError
from app.engine.lookups import IndexCache
from app.engine.values import ERROR, KIND_NAMES, Grid, StringTable, Values
from app.model.formula.refs import Rect, a1_cell, parse_a1_cell
from app.model.interpreter import _resolve_defined_name, peak_memory_mb
from app.model.schema import FormulaBlock, WorkbookLogicModel
from app.parser.models import RawSheet, RawWorkbook

log = logging.getLogger(__name__)

SheetLoader = Callable[[str], RawSheet]
SeedValues = dict[str, dict[str, list]]  # sheet -> {address, value, type} columns of a previous run


class ModelHasCyclesError(Exception):
    def __init__(self, descriptions: list[str]) -> None:
        super().__init__(
            "the logic model contains circular references; fix the workbook and upload a new version"
        )
        self.descriptions = descriptions


class OverrideError(ValueError):
    pass


class HotTemplate(BaseModel):
    template_id: int
    sheet: str
    example_cell: str
    cells: int
    seconds: float


class RunSummary(BaseModel):
    kind: str
    blocks_evaluated: int
    cells_evaluated: int
    seconds: float
    peak_mb: float
    error_cells: int
    hot_templates: list[HotTemplate] = Field(default_factory=list)
    evaluated_block_ids: list[int] = Field(default_factory=list)
    skipped_blocks: int = 0
    skipped_template_ids: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@dataclass
class RunResult:
    kind: str
    overrides: dict[str, Any]
    summary: RunSummary
    grids: dict[str, Grid]
    table: StringTable
    evaluated: list[int]
    model: WorkbookLogicModel

    def formula_values(self, sheet: str, *, only_evaluated: bool = False) -> dict[str, list]:
        """Columnar {address, value, type} for the formula cells of one sheet."""
        grid = self.grids.get(sheet)
        addresses: list[str] = []
        values: list[object] = []
        types: list[str] = []
        if grid is None:
            return {"address": addresses, "value": values, "type": types}
        wanted = set(self.evaluated) if only_evaluated else None
        for block in self.model.formula_blocks:
            if block.sheet != sheet or (wanted is not None and block.id not in wanted):
                continue
            rect = block.rect.rect()
            py = grid.window(rect).to_python(self.table)
            kinds = grid.window(rect).kind
            for i in range(rect.rows):
                for j in range(rect.cols):
                    addresses.append(a1_cell(rect.r1 + i, rect.c1 + j))
                    v = py[i, j]
                    values.append(v.item() if hasattr(v, "item") else v)
                    types.append(KIND_NAMES[int(kinds[i, j])])
        return {"address": addresses, "value": values, "type": types}


def preflight(model: WorkbookLogicModel, *, skip_unsupported: bool = False) -> set[int]:
    """Refuse models with cycles; refuse (or, when skipping, list) out-of-contract templates.

    Returns the ids of templates the run must skip (empty unless ``skip_unsupported``).
    """
    if model.cycles or any(b.self_order == "cycle" for b in model.formula_blocks):
        raise ModelHasCyclesError(model.cycle_descriptions)
    skipped: set[int] = set()
    for tpl in model.templates:
        offending = (
            "<unparsed formula>"
            if tpl.parse_error
            else next((name for name in tpl.functions if name not in REGISTRY), None)
        )
        if offending is None:
            continue
        if not skip_unsupported:
            raise UnsupportedFunctionError(offending, tpl.sheet, tpl.example_cell)
        skipped.add(tpl.id)
    return skipped


def resolve_override(
    key: str, meta: RawWorkbook, model: WorkbookLogicModel
) -> tuple[str, int, int]:
    """'Sheet!A1' or a defined name -> (sheet, row, col); formula cells cannot be overridden."""
    if "!" in key:
        sheet, addr = key.rsplit("!", 1)
        sheet = sheet.strip("'")
        try:
            row, col = parse_a1_cell(addr)
        except ValueError as exc:
            raise OverrideError(f"{key!r}: not a cell address") from exc
    else:
        dn = next((n for n in meta.defined_names if n.name == key and not n.builtin), None)
        if dn is None:
            raise OverrideError(f"{key!r}: not a cell address or a defined name")
        extents = {s.name: Rect.from_a1(s.used_range) for s in meta.sheets if s.used_range}
        resolved = _resolve_defined_name(dn.refers_to, extents, {s.name: s for s in meta.sheets})
        if resolved is None or resolved[1].cells != 1:
            raise OverrideError(f"{key!r}: name does not refer to a single cell")
        sheet, rect = resolved
        row, col = rect.r1, rect.c1
    if model.sheet(sheet) is None:
        raise OverrideError(f"{key!r}: sheet {sheet!r} not in the workbook")
    if isinstance(model.block_at(sheet, row, col), FormulaBlock):
        raise OverrideError(
            f"{key!r}: {sheet}!{a1_cell(row, col)} holds a formula; only inputs can be overridden"
        )
    return sheet, row, col


class Engine:
    def __init__(
        self, model: WorkbookLogicModel, meta: RawWorkbook, load_sheet: SheetLoader
    ) -> None:
        self.model = model
        self.meta = meta
        self.load_sheet = load_sheet
        self.extents = {s.name: Rect.from_a1(s.used_range) for s in meta.sheets if s.used_range}
        self.sheet_meta = {s.name: s for s in meta.sheets}
        self.names: dict[str, tuple[str, Rect]] = {}
        for dn in meta.defined_names:
            if dn.builtin:
                continue
            resolved = _resolve_defined_name(dn.refers_to, self.extents, self.sheet_meta)
            if resolved is not None:
                self.names[dn.name] = resolved
        self._graph: nx.DiGraph | None = None

    # ---- state ----------------------------------------------------------------------------
    def sheets_needed(self) -> list[str]:
        needed = {s.name for s in self.model.sheets if s.in_scope}
        needed.update(b.sheet for b in self.model.input_blocks)
        return [s.name for s in self.meta.sheets if s.name in needed and s.name in self.extents]

    def load_state(self, table: StringTable, seed: SeedValues | None = None) -> dict[str, Grid]:
        grids: dict[str, Grid] = {}
        for name in self.sheets_needed():
            raw = self.load_sheet(name)
            grid = Grid.from_raw(raw, self.extents[name], table)
            if seed and name in seed:
                grid.write_columnar(seed[name], table)
            grids[name] = grid
        return grids

    def block_graph(self) -> nx.DiGraph:
        if self._graph is None:
            g = nx.DiGraph()
            g.add_nodes_from(b.id for b in self.model.formula_blocks)
            g.add_nodes_from(b.id for b in self.model.input_blocks)
            g.add_edges_from((e.source, e.target) for e in self.model.edges if e.source != e.target)
            self._graph = g
        return self._graph

    def affected_blocks(self, cells: list[tuple[str, int, int]]) -> list[int]:
        """Formula blocks downstream of the given input cells, in execution order.

        The first hop is cell-precise (blocks whose footprints contain the exact cell), so an
        override on one cell of an input block does not drag in readers of its neighbours.
        """
        start: set[int] = set()
        for sheet, row, col in cells:
            for fb in self.model.formula_blocks:
                if any(
                    fp.sheet == sheet and fp.rect.rect().contains(row, col) for fp in fb.footprints
                ):
                    start.add(fb.id)
        g = self.block_graph()
        targets: set[int] = set()
        for s in start:
            if s in g:
                targets.add(s)
                targets.update(nx.descendants(g, s))
        formula_ids = {b.id for b in self.model.formula_blocks}
        return [b for b in self.model.execution_order if b in targets and b in formula_ids]

    # ---- runs -------------------------------------------------------------------------------
    def run(
        self,
        overrides: dict[str, Any] | None = None,
        *,
        mode: str = "auto",
        seed: SeedValues | None = None,
        state: tuple[dict[str, Grid], StringTable] | None = None,
        skip_unsupported: bool = False,
    ) -> RunResult:
        """``seed`` are a previous run's stored values; ``state`` is a previous run's in-memory
        grids and string table (cloned here), which avoids reloading and reseeding.
        ``skip_unsupported`` leaves out-of-contract templates at their cached values (validation)."""
        overrides = overrides or {}
        skipped_templates = preflight(self.model, skip_unsupported=skip_unsupported)
        started = time.perf_counter()
        if state is not None:
            src_grids, src_table = state
            table = src_table.clone()
            grids = {
                name: Grid(g.sheet, g.extent, g.values.copy()) for name, g in src_grids.items()
            }
            seed = seed or {}
        else:
            table = StringTable()
            grids = self.load_state(table, seed)
        indexes = IndexCache()

        cells: list[tuple[str, int, int]] = []
        for key, value in overrides.items():
            sheet, row, col = resolve_override(key, self.meta, self.model)
            if sheet not in grids:
                raise OverrideError(f"{key!r}: sheet {sheet!r} is not part of this model's scope")
            grids[sheet].write(Rect.cell(row, col), Values.from_python(value, table))
            cells.append((sheet, row, col))

        incremental = mode != "full" and (seed is not None or state is not None) and bool(overrides)
        if incremental:
            order = self.affected_blocks(cells)
            kind = "incremental"
        else:
            order = list(self.model.execution_order)
            kind = "full"

        by_id = {b.id: b for b in self.model.formula_blocks}
        timings: dict[int, float] = defaultdict(float)
        cells_evaluated = 0
        skipped_blocks = 0
        if skipped_templates:
            kept = []
            for block_id in order:
                if by_id[block_id].template_id in skipped_templates:
                    skipped_blocks += 1
                else:
                    kept.append(block_id)
            order = kept
        for block_id in order:
            block = by_id[block_id]
            tpl = self.model.template(block.template_id)
            if tpl.ast is None:
                raise UnsupportedFunctionError("<unparsed formula>", tpl.sheet, tpl.example_cell)
            rect = block.rect.rect()
            t0 = time.perf_counter()
            if tpl.array_ref:
                anchor = Rect.from_a1(tpl.array_ref)
                ctx = BlockContext(
                    sheet=block.sheet,
                    rect=Rect.cell(anchor.r1, anchor.c1),
                    grids=grids,
                    table=table,
                    indexes=indexes,
                    names=self.names,
                )
                spilled = evaluate_array(tpl.ast, ctx, anchor)
                # This block may be a sub-rectangle of the array ref.
                sub = spilled[
                    rect.r1 - anchor.r1 : rect.r2 - anchor.r1 + 1,
                    rect.c1 - anchor.c1 : rect.c2 - anchor.c1 + 1,
                ]
                grids[block.sheet].write(rect, sub)
            else:
                evaluate_block(
                    tpl.ast,
                    sheet=block.sheet,
                    rect=rect,
                    grids=grids,
                    table=table,
                    indexes=indexes,
                    names=self.names,
                    self_order=block.self_order if block.self_dependent else None,
                )
            timings[tpl.id] += time.perf_counter() - t0
            cells_evaluated += rect.cells

        error_cells = 0
        for block in self.model.formula_blocks:
            if block.id in set(order) or not incremental:
                g = grids.get(block.sheet)
                if g is not None:
                    error_cells += int((g.window(block.rect.rect()).kind == ERROR).sum())

        hot = sorted(timings.items(), key=lambda kv: -kv[1])[:5]
        summary = RunSummary(
            kind=kind,
            blocks_evaluated=len(order),
            cells_evaluated=cells_evaluated,
            seconds=round(time.perf_counter() - started, 3),
            peak_mb=round(peak_memory_mb(), 1),
            error_cells=error_cells,
            hot_templates=[
                HotTemplate(
                    template_id=tid,
                    sheet=self.model.template(tid).sheet,
                    example_cell=self.model.template(tid).example_cell,
                    cells=self.model.template(tid).cell_count,
                    seconds=round(sec, 3),
                )
                for tid, sec in hot
            ],
            evaluated_block_ids=list(order),
            skipped_blocks=skipped_blocks,
            skipped_template_ids=sorted(skipped_templates),
            notes=(
                ["incremental: block-level descendants; cell-level narrowing not applied"]
                if incremental
                else []
            )
            + (
                [f"{skipped_blocks} block(s) with unsupported functions left at cached values"]
                if skipped_blocks
                else []
            ),
        )
        log.info("run %s: %s", kind, summary.model_dump(exclude={"evaluated_block_ids"}))
        return RunResult(kind, dict(overrides), summary, grids, table, list(order), self.model)


__all__ = [
    "Engine",
    "HotTemplate",
    "ModelHasCyclesError",
    "OverrideError",
    "RunResult",
    "RunSummary",
    "preflight",
    "resolve_override",
]
