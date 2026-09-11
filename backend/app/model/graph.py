"""Block-level dependency graph: edges, self-dependency analysis, cycles, execution order."""

from __future__ import annotations

from collections import Counter

import networkx as nx

from app.model.formula.ast import (
    CellRef,
    ColumnRef,
    Node,
    RangeRef,
    RefNode,
    RowRef,
    iter_refs,
    r1c1_text,
)
from app.model.formula.refs import Rect
from app.model.schema import BlockEdge, FormulaBlock, InputBlock, SheetEdge


def build_edges(
    formula_blocks: list[FormulaBlock], input_blocks: list[InputBlock]
) -> list[BlockEdge]:
    """Edge source → target when a footprint of ``target`` intersects ``source``'s rect."""
    by_sheet: dict[str, list[tuple[int, Rect]]] = {}
    for b in formula_blocks:
        by_sheet.setdefault(b.sheet, []).append((b.id, b.rect.rect()))
    for b in input_blocks:
        by_sheet.setdefault(b.sheet, []).append((b.id, b.rect.rect()))

    edges: set[tuple[int, int]] = set()
    for target in formula_blocks:
        for fp in target.footprints:
            rect = fp.rect.rect()
            for source_id, source_rect in by_sheet.get(fp.sheet, ()):
                if source_rect.intersects(rect):
                    edges.add((source_id, target.id))
    return [BlockEdge(source=s, target=t) for s, t in sorted(edges)]


def _self_intersecting_refs(block: FormulaBlock, ast: Node) -> list[RefNode]:
    own = block.rect.rect()
    from app.model.formula.ast import ref_footprint

    out: list[RefNode] = []
    for ref in iter_refs(ast):
        if ref.sheet is not None and ref.sheet != block.sheet:
            continue
        fp = ref_footprint(ref, own)
        if fp is not None and fp.intersects(own):
            out.append(ref)
    return out


def analyse_self_dependency(block: FormulaBlock, ast: Node | None) -> tuple[bool, str | None]:
    """(self_dependent, order). Order is how cells inside the block must be evaluated.

    A backward-pointing relative reference (row offset ≤ 0 and col offset ≤ 0, not both 0)
    gives a well-defined order; anything else that overlaps the block itself is a cycle.
    """
    if ast is None:
        return False, None
    refs = _self_intersecting_refs(block, ast)
    if not refs:
        return False, None
    row_dirs: set[int] = set()
    col_dirs: set[int] = set()
    for ref in refs:
        if isinstance(ref, CellRef):
            if ref.row.abs or ref.col.abs:
                return True, "cycle"
            dr, dc = ref.row.v, ref.col.v
            if dr == 0 and dc == 0:
                return True, "cycle"
            row_dirs.add(_sign(dr))
            col_dirs.add(_sign(dc))
        elif isinstance(ref, RangeRef):
            # Ranges may run from an absolute start to a relative end (running totals);
            # what matters is that the relative ends never reach the current cell or beyond.
            axes = [(ref.r1, ref.r2, "r"), (ref.c1, ref.c2, "c")]
            for a1, a2, kind in axes:
                rel = [a.v for a in (a1, a2) if not a.abs]
                if not rel:
                    continue
                if any(v > 0 for v in rel):
                    return True, "cycle"
                (row_dirs if kind == "r" else col_dirs).update(_sign(v) for v in rel)
            if all(a.abs for a in (ref.r1, ref.r2, ref.c1, ref.c2)):
                return True, "cycle"
            touches_self = all((a.abs or a.v >= 0) for a in (ref.r2, ref.c2)) and all(
                (a.abs or a.v <= 0) for a in (ref.r1, ref.c1)
            )
            if touches_self and any(not a.abs and a.v == 0 for a in (ref.r2, ref.c2)):
                # e.g. SUM(B$2:B2) in column B itself
                rel_r2 = not ref.r2.abs and ref.r2.v == 0
                rel_c2 = not ref.c2.abs and ref.c2.v == 0
                if rel_r2 and rel_c2:
                    return True, "cycle"
        elif isinstance(ref, ColumnRef | RowRef):
            return True, "cycle"
    if 1 in row_dirs or 1 in col_dirs:
        return True, "cycle"
    row_dirs.discard(0)
    col_dirs.discard(0)
    if row_dirs and not col_dirs:
        return True, "top_to_bottom"
    if col_dirs and not row_dirs:
        return True, "left_to_right"
    return True, "row_major"


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def analyse_graph(
    formula_blocks: list[FormulaBlock], edges: list[BlockEdge]
) -> tuple[list[int], list[list[int]]]:
    """Execution order over formula blocks and the list of cross-block cycles (SCCs)."""
    g = nx.DiGraph()
    formula_ids = {b.id for b in formula_blocks}
    g.add_nodes_from(formula_ids)
    for e in edges:
        if e.source in formula_ids and e.source != e.target:
            g.add_edge(e.source, e.target)
    cycles = [sorted(scc) for scc in nx.strongly_connected_components(g) if len(scc) > 1]
    cycles.sort()
    if cycles:
        cond = nx.condensation(g)
        order: list[int] = []
        for cnode in nx.topological_sort(cond):
            order.extend(sorted(cond.nodes[cnode]["members"]))
    else:
        order = list(nx.lexicographical_topological_sort(g))
    return order, cycles


def describe_cycles(
    cycles: list[list[int]], formula_blocks: list[FormulaBlock], edges: list[BlockEdge]
) -> list[str]:
    """Readable explanation of each strongly connected block group, in A1 terms."""
    blocks = {b.id: b for b in formula_blocks}
    out: list[str] = []
    for scc in cycles:
        members = set(scc)
        sheets = sorted({blocks[i].sheet for i in scc})
        ranges = [f"{blocks[i].sheet}!{blocks[i].rect.a1}" for i in scc]
        chain: list[str] = []
        for e in edges:
            if e.source in members and e.target in members:
                src, tgt = blocks[e.source], blocks[e.target]
                via = next(
                    (
                        fp.rect.a1
                        for fp in tgt.footprints
                        if fp.sheet == src.sheet and fp.rect.rect().intersects(src.rect.rect())
                    ),
                    "?",
                )
                chain.append(f"{tgt.rect.a1} reads {via} (hits {src.rect.a1})")
        shown = "; ".join(chain[:6]) + ("; …" if len(chain) > 6 else "")
        out.append(
            f"{len(scc)} blocks on {', '.join(sheets)} form a reference cycle "
            f"[{', '.join(ranges[:8])}{', …' if len(ranges) > 8 else ''}]: {shown}"
        )
    return out


def sheet_edges(
    edges: list[BlockEdge], formula_blocks: list[FormulaBlock], input_blocks: list[InputBlock]
) -> list[SheetEdge]:
    sheet_of = {b.id: b.sheet for b in formula_blocks}
    sheet_of.update({b.id: b.sheet for b in input_blocks})
    counts: Counter[tuple[str, str]] = Counter()
    for e in edges:
        s, t = sheet_of[e.source], sheet_of[e.target]
        if s != t:
            counts[(s, t)] += 1
    return [SheetEdge(source=s, target=t, weight=n) for (s, t), n in sorted(counts.items())]


def ref_texts(ast: Node) -> list[str]:
    seen: dict[str, None] = {}
    for ref in iter_refs(ast):
        seen.setdefault(r1c1_text(ref), None)
    return list(seen)
