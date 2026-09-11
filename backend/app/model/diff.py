"""Logic diff between two WorkbookLogicModels: DATA vs LOGIC vs STRUCTURAL changes with impact.

The comparison happens at the level the model lives at. Per sheet and column, the old and new
template coverage intervals are swept together; a cell whose template key differs is a LOGIC
change, a cell newly covered by a template that already existed is DATA growth, and a cell
whose template is entirely new (or entirely gone) belongs to a template added/removed entry.
Sheet renames are matched by template-set similarity and keys are normalised across them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import networkx as nx
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field

from app.model.formula.ast import (
    ArrayConst,
    Binary,
    Bool,
    Call,
    CellRef,
    ColumnRef,
    Node,
    Number,
    RangeRef,
    RowRef,
    Text,
    Unary,
    a1_text,
    quote_sheet,
)
from app.model.formula.refs import Rect, parse_a1_cell
from app.model.schema import FormulaBlock, Template, WorkbookLogicModel
from app.parser.models import DefinedName, RawSheet
from app.validation.schema import Anomaly

RENAME_SIMILARITY = 0.6
RawLoader = Callable[[str], RawSheet | None]

LogicKind = Literal[
    "template_added",
    "template_removed",
    "template_changed",
    "rule_added",
    "rule_removed",
    "name_added",
    "name_removed",
    "name_changed",
]
DataKind = Literal["rows_added", "rows_removed", "values_changed", "inputs_resized"]
StructuralKind = Literal[
    "sheet_added",
    "sheet_removed",
    "sheet_renamed",
    "role_changed",
    "blocks_merged",
    "blocks_split",
    "anomaly_new",
    "anomaly_resolved",
]


class AffectedOutput(BaseModel):
    block_id: int
    sheet: str
    range: str
    label: str | None = None
    cells: int


class LogicChange(BaseModel):
    id: int
    kind: LogicKind
    sheet: str
    location: str = ""
    cells: int = 0
    title: str
    description: str
    detail: dict[str, Any] = Field(default_factory=dict)
    affected_outputs: list[AffectedOutput] = Field(default_factory=list)
    affected_output_count: int = 0


class DataChange(BaseModel):
    id: int
    kind: DataKind
    sheet: str
    count: int
    description: str
    detail: dict[str, Any] = Field(default_factory=dict)


class StructuralChange(BaseModel):
    id: int
    kind: StructuralKind
    sheet: str
    description: str
    detail: dict[str, Any] = Field(default_factory=dict)


class DiffSummary(BaseModel):
    logic_changes: int
    data_changes: int
    structural_changes: int
    outputs_total: int
    outputs_affected_by_logic: int
    outputs_affected_by_data: int
    logic_cells: int = 0


class DiffReport(BaseModel):
    base_version_id: str
    target_version_id: str
    created_at: datetime
    headline: str
    summary: DiffSummary
    logic: list[LogicChange]
    data: list[DataChange]
    structural: list[StructuralChange]
    sheet_map: dict[str, str] = Field(
        default_factory=dict, description="base sheet -> target sheet"
    )


# ---- sheet matching -----------------------------------------------------------------------------


def _template_keys(model: WorkbookLogicModel, sheet: str) -> set[str]:
    return {t.r1c1 for t in model.templates if t.sheet == sheet}


def match_sheets(
    base: WorkbookLogicModel, target: WorkbookLogicModel
) -> tuple[dict[str, str], list[str], list[str]]:
    """(base -> target name map incl. renames, added target sheets, removed base sheets)."""
    base_names = [s.name for s in base.sheets]
    target_names = [s.name for s in target.sheets]
    mapping = {n: n for n in base_names if n in target_names}
    unmatched_base = [n for n in base_names if n not in mapping]
    unmatched_target = [n for n in target_names if n not in mapping.values()]
    for b in list(unmatched_base):
        bk = _template_keys(base, b)
        best, score = None, 0.0
        for t in unmatched_target:
            tk = _template_keys(target, t)
            if not bk and not tk:
                # No formulas on either: fall back to comparing used ranges and cell counts.
                sb, st = base.sheet(b), target.sheet(t)
                same_shape = sb is not None and st is not None and sb.used_range == st.used_range
                cand = 1.0 if same_shape else 0.0
            else:
                union = bk | tk
                cand = len(bk & tk) / len(union) if union else 0.0
            if cand > score:
                best, score = t, cand
        if best is not None and score >= RENAME_SIMILARITY:
            mapping[b] = best
            unmatched_base.remove(b)
            unmatched_target.remove(best)
    return mapping, unmatched_target, unmatched_base


def _normalise_key(key: str, rename: dict[str, str]) -> str:
    """Rewrite sheet prefixes in a target-version key back to base-version names."""
    for new, old in rename.items():
        if new == old:
            continue
        for form in (quote_sheet(new) + "!", new + "!"):
            key = key.replace(form, quote_sheet(old) + "!")
    return key


# ---- AST change description -------------------------------------------------------------------


def describe_ast_change(old: Node | None, new: Node | None, row: int, col: int) -> list[str]:
    """Human-readable leaf differences between two ASTs, rendered in A1 terms at (row, col)."""
    if old is None or new is None:
        return ["formula changed"]
    changes: list[str] = []

    def walk(a: Node, b: Node, context: str) -> bool:
        if type(a) is not type(b):
            changes.append(f"{context}: {a1_text(a, row, col)} → {a1_text(b, row, col)}")
            return False
        if isinstance(a, Number) and isinstance(b, Number):
            if a.value != b.value:
                changes.append(f"{context}: {_num(a.value)} → {_num(b.value)}")
            return True
        if isinstance(a, Text | Bool) and isinstance(b, Text | Bool):
            if a.value != b.value:
                changes.append(f"{context}: {a1_text(a, row, col)} → {a1_text(b, row, col)}")
            return True
        if isinstance(a, CellRef | RangeRef | ColumnRef | RowRef):
            ta, tb = a1_text(a, row, col), a1_text(b, row, col)
            if ta != tb:
                what = "range" if isinstance(a, RangeRef | ColumnRef | RowRef) else "reference"
                changes.append(f"{context}: {what} {ta} → {tb}")
            return True
        if isinstance(a, Call) and isinstance(b, Call):
            if a.name != b.name:
                changes.append(f"{context}: function {a.name} → {b.name}")
                return False
            if len(a.args) != len(b.args):
                changes.append(f"{context}: {a.name} arguments {len(a.args)} → {len(b.args)}")
                return False
            for i, (x, y) in enumerate(zip(a.args, b.args, strict=True)):
                walk(x, y, _arg_context(a.name, i))
            return True
        if isinstance(a, Binary) and isinstance(b, Binary):
            if a.op != b.op:
                changes.append(f"{context}: {a1_text(a, row, col)} → {a1_text(b, row, col)}")
                return False
            if (
                a.op in ("=", "<>", "<", ">", "<=", ">=")
                and isinstance(b.right, Number)
                and isinstance(a.right, Number)
            ):
                if a.right.value != b.right.value:
                    changes.append(
                        f"threshold {a1_text(a.left, row, col)} {b.op} {_num(a.right.value)} → {_num(b.right.value)}"
                    )
                    walk(a.left, b.left, context)
                    return True
            walk(a.left, b.left, context)
            walk(a.right, b.right, context)
            return True
        if isinstance(a, Unary) and isinstance(b, Unary):
            walk(a.operand, b.operand, context)
            return True
        if isinstance(a, ArrayConst) and isinstance(b, ArrayConst):
            if a1_text(a, row, col) != a1_text(b, row, col):
                changes.append(f"{context}: array constant changed")
            return True
        return True

    walk(old, new, "formula")
    if not changes:
        old_t, new_t = a1_text(old, row, col), a1_text(new, row, col)
        if old_t != new_t:
            changes.append(f"formula: {old_t} → {new_t}")
    return changes


def _arg_context(fn: str, i: int) -> str:
    if fn == "IF":
        return (
            ("IF condition", "IF then-branch", "IF else-branch")[i]
            if i < 3
            else f"IF argument {i + 1}"
        )
    if fn in ("VLOOKUP", "HLOOKUP"):
        return (
            (f"{fn} key", f"{fn} table", f"{fn} column index", f"{fn} match type")[i]
            if i < 4
            else f"{fn} argument {i + 1}"
        )
    if fn in ("COUNTIFS", "SUMIFS"):
        return f"{fn} {'range' if i % 2 == 0 else 'criterion'} {i // 2 + 1}"
    return f"{fn} argument {i + 1}"


def _num(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.15g}"


# ---- coverage sweep ---------------------------------------------------------------------------


def _column_intervals(
    model: WorkbookLogicModel, sheet: str, key_of: dict[int, str]
) -> dict[int, list[tuple[int, int, str, int]]]:
    """column -> [(r1, r2, template key, block id)] for formula blocks on a sheet."""
    out: dict[int, list[tuple[int, int, str, int]]] = defaultdict(list)
    for b in model.formula_blocks:
        if b.sheet != sheet:
            continue
        r = b.rect.rect()
        for c in range(r.c1, r.c2 + 1):
            out[c].append((r.r1, r.r2, key_of[b.template_id], b.id))
    for lst in out.values():
        lst.sort()
    return out


def _sweep(a: list[tuple[int, int, str, int]], b: list[tuple[int, int, str, int]]):
    """Yield (r1, r2, key_a|None, block_a|None, key_b|None, block_b|None) over the union of rows."""
    points = sorted({p for r1, r2, _, _ in a + b for p in (r1, r2 + 1)})
    ia = ib = 0
    for lo, hi in zip(points, points[1:], strict=False):
        while ia < len(a) and a[ia][1] < lo:
            ia += 1
        while ib < len(b) and b[ib][1] < lo:
            ib += 1
        ka = a[ia] if ia < len(a) and a[ia][0] <= lo <= a[ia][1] else None
        kb = b[ib] if ib < len(b) and b[ib][0] <= lo <= b[ib][1] else None
        if ka is None and kb is None:
            continue
        yield (
            lo,
            hi - 1,
            (ka[2] if ka else None),
            (ka[3] if ka else None),
            (kb[2] if kb else None),
            (kb[3] if kb else None),
        )


def _ranges_text(cells: dict[int, list[tuple[int, int]]]) -> str:
    parts = []
    for c in sorted(cells):
        for r1, r2 in sorted(cells[c]):
            letter = get_column_letter(c)
            parts.append(f"{letter}{r1}" if r1 == r2 else f"{letter}{r1}:{letter}{r2}")
    if len(parts) > 6:
        return ", ".join(parts[:6]) + f", … (+{len(parts) - 6})"
    return ", ".join(parts)


# ---- impact -------------------------------------------------------------------------------------


def _output_blocks(model: WorkbookLogicModel) -> dict[int, FormulaBlock]:
    return {b.id: b for b in model.formula_blocks if b.classification == "output"}


def _descendants(model: WorkbookLogicModel, block_ids: set[int]) -> set[int]:
    g = nx.DiGraph()
    g.add_nodes_from(b.id for b in model.formula_blocks)
    g.add_nodes_from(b.id for b in model.input_blocks)
    g.add_edges_from((e.source, e.target) for e in model.edges if e.source != e.target)
    out: set[int] = set()
    for bid in block_ids:
        if bid in g:
            out.add(bid)
            out.update(nx.descendants(g, bid))
    return out


def _affected(model: WorkbookLogicModel, block_ids: set[int]) -> list[AffectedOutput]:
    outputs = _output_blocks(model)
    hit = _descendants(model, block_ids) & set(outputs)
    result = []
    for bid in sorted(hit):
        b = outputs[bid]
        label = next((lbl for lbl in b.column_labels if lbl), None)
        result.append(
            AffectedOutput(
                block_id=bid, sheet=b.sheet, range=b.rect.a1, label=label, cells=b.cell_count
            )
        )
    return result


# ---- main ---------------------------------------------------------------------------------------


def diff_models(
    base: WorkbookLogicModel,
    target: WorkbookLogicModel,
    *,
    base_names: list[DefinedName] | None = None,
    target_names: list[DefinedName] | None = None,
    base_raw: RawLoader | None = None,
    target_raw: RawLoader | None = None,
    base_anomalies: list[Anomaly] | None = None,
    target_anomalies: list[Anomaly] | None = None,
) -> DiffReport:
    counter = iter(range(1, 10**6))
    nid = lambda: next(counter)  # noqa: E731
    logic: list[LogicChange] = []
    data: list[DataChange] = []
    structural: list[StructuralChange] = []

    mapping, added_sheets, removed_sheets = match_sheets(base, target)
    rename = {t: b for b, t in mapping.items() if b != t}
    for b, t in mapping.items():
        if b != t:
            structural.append(
                StructuralChange(
                    id=nid(),
                    kind="sheet_renamed",
                    sheet=t,
                    description=f"Sheet '{b}' renamed to '{t}' (matched by formula patterns)",
                    detail={"from": b, "to": t},
                )
            )
    for s in added_sheets:
        sm = target.sheet(s)
        structural.append(
            StructuralChange(
                id=nid(),
                kind="sheet_added",
                sheet=s,
                description=f"Sheet '{s}' added ({sm.formula_cells:,} formula cells)"
                if sm
                else f"Sheet '{s}' added",
            )
        )
    for s in removed_sheets:
        structural.append(
            StructuralChange(
                id=nid(), kind="sheet_removed", sheet=s, description=f"Sheet '{s}' removed"
            )
        )

    # Template keys normalised to base sheet names.
    base_key = {t.id: t.r1c1 for t in base.templates}
    target_key = {t.id: _normalise_key(t.r1c1, rename) for t in target.templates}
    base_tpl_by_key: dict[tuple[str, str], Template] = {
        (t.sheet, base_key[t.id]): t for t in base.templates
    }
    target_tpl_by_key: dict[tuple[str, str], Template] = {
        (mapping_inv(rename, t.sheet), target_key[t.id]): t for t in target.templates
    }

    logic_block_ids_target: set[int] = set()
    logic_block_ids_base: set[int] = set()
    data_block_ids_target: set[int] = set()
    total_logic_cells = 0

    for b_sheet, t_sheet in mapping.items():
        ia = _column_intervals(base, b_sheet, base_key)
        ib = _column_intervals(target, t_sheet, target_key)
        changed: dict[tuple[str | None, str | None], dict] = {}
        grown: dict[str, dict] = {}
        shrunk: dict[str, dict] = {}
        for col in sorted(set(ia) | set(ib)):
            for r1, r2, ka, ba, kb, bb in _sweep(ia.get(col, []), ib.get(col, [])):
                n = r2 - r1 + 1
                if ka == kb:
                    continue
                if ka is not None and kb is not None:
                    entry = changed.setdefault(
                        (ka, kb),
                        {
                            "cells": 0,
                            "ranges": defaultdict(list),
                            "blocks_t": set(),
                            "blocks_b": set(),
                            "first": (r1, col),
                        },
                    )
                    entry["cells"] += n
                    entry["ranges"][col].append((r1, r2))
                    entry["blocks_t"].add(bb)
                    entry["blocks_b"].add(ba)
                elif kb is not None:  # only in target
                    exists_in_base = (b_sheet, kb) in base_tpl_by_key
                    bucket = grown if exists_in_base else changed
                    key = kb if exists_in_base else (None, kb)
                    entry = bucket.setdefault(
                        key,
                        {
                            "cells": 0,
                            "ranges": defaultdict(list),
                            "blocks_t": set(),
                            "blocks_b": set(),
                            "first": (r1, col),
                        },
                    )
                    entry["cells"] += n
                    entry["ranges"][col].append((r1, r2))
                    entry["blocks_t"].add(bb)
                else:  # only in base
                    exists_in_target = (b_sheet, ka) in target_tpl_by_key
                    bucket = shrunk if exists_in_target else changed
                    key = ka if exists_in_target else (ka, None)
                    entry = bucket.setdefault(
                        key,
                        {
                            "cells": 0,
                            "ranges": defaultdict(list),
                            "blocks_t": set(),
                            "blocks_b": set(),
                            "first": (r1, col),
                        },
                    )
                    entry["cells"] += n
                    entry["ranges"][col].append((r1, r2))
                    entry["blocks_b"].add(ba)

        repairs: dict[tuple[int, int], dict] = {}
        for (ka, kb), entry in changed.items():
            row, col = entry["first"]
            loc = _ranges_text(entry["ranges"])
            total_logic_cells += entry["cells"]
            if ka is not None and kb is not None:
                old_t = base_tpl_by_key[(b_sheet, ka)]
                new_t = target_tpl_by_key[(b_sheet, kb)]
                notes = describe_ast_change(old_t.ast, new_t.ast, row, col)
                kb_exists_in_base = (b_sheet, kb) in base_tpl_by_key
                blocks = set(entry["blocks_t"]) - {None}
                logic_block_ids_target |= blocks
                old_text = "=" + (
                    a1_text(old_t.ast, row, col) if old_t.ast else old_t.example_formula
                )
                new_text = "=" + (
                    a1_text(new_t.ast, row, col) if new_t.ast else new_t.example_formula
                )
                spans = {(r1, r2) for rs in entry["ranges"].values() for r1, r2 in rs}
                if kb_exists_in_base and len(spans) == 1:
                    # A repaired row: merge all columns of the same rows into one entry.
                    rep = repairs.setdefault(
                        next(iter(spans)),
                        {
                            "cells": 0,
                            "cols": set(),
                            "notes": [],
                            "blocks": set(),
                            "old": [],
                            "new": [],
                        },
                    )
                    rep["cells"] += entry["cells"]
                    rep["cols"].update(entry["ranges"].keys())
                    rep["notes"].extend(n for n in notes if n not in rep["notes"])
                    rep["blocks"] |= blocks
                    rep["old"].append(old_text)
                    rep["new"].append(new_text)
                    continue
                change = LogicChange(
                    id=nid(),
                    kind="template_changed",
                    sheet=t_sheet,
                    location=loc,
                    cells=entry["cells"],
                    title=f"{t_sheet} {loc}: formula changed",
                    description="; ".join(notes) if notes else "formula changed",
                    detail={
                        "old_formula": old_text,
                        "new_formula": new_text,
                        "changes": notes,
                        "repair": kb_exists_in_base,
                    },
                )
                change.affected_outputs = _affected(target, blocks)
            elif kb is not None:
                new_t = target_tpl_by_key[(b_sheet, kb)]
                text = "=" + (a1_text(new_t.ast, row, col) if new_t.ast else new_t.example_formula)
                change = LogicChange(
                    id=nid(),
                    kind="template_added",
                    sheet=t_sheet,
                    location=loc,
                    cells=entry["cells"],
                    title=f"{t_sheet} {loc}: new formula pattern ({entry['cells']:,} cell(s))",
                    description=text,
                    detail={"new_formula": text, "functions": new_t.functions},
                )
                blocks = set(entry["blocks_t"]) - {None}
                logic_block_ids_target |= blocks
                change.affected_outputs = _affected(target, blocks)
            else:
                old_t = base_tpl_by_key[(b_sheet, ka)]
                text = "=" + (a1_text(old_t.ast, row, col) if old_t.ast else old_t.example_formula)
                change = LogicChange(
                    id=nid(),
                    kind="template_removed",
                    sheet=t_sheet,
                    location=loc,
                    cells=entry["cells"],
                    title=f"{t_sheet} {loc}: formula pattern removed ({entry['cells']:,} cell(s))",
                    description=text,
                    detail={"old_formula": text},
                )
                blocks = set(entry["blocks_b"]) - {None}
                logic_block_ids_base |= blocks
                change.affected_outputs = _affected(base, blocks)
            change.affected_output_count = len(change.affected_outputs)
            logic.append(change)

        for (r1, r2), rep in sorted(repairs.items()):
            letters = [get_column_letter(c) for c in sorted(rep["cols"])]
            rows = f"row {r1}" if r1 == r2 else f"rows {r1}-{r2}"
            loc = ", ".join(
                f"{letter}{r1}" if r1 == r2 else f"{letter}{r1}:{letter}{r2}" for letter in letters
            )
            span = letters[0] if len(letters) == 1 else f"{letters[0]}-{letters[-1]}"
            change = LogicChange(
                id=nid(),
                kind="template_changed",
                sheet=t_sheet,
                location=loc,
                cells=rep["cells"],
                title=f"{t_sheet} {rows}: {rep['cells']:,} cell(s) in column(s) {span} now follow the column pattern",
                description="; ".join(rep["notes"][:4]) + (" ..." if len(rep["notes"]) > 4 else ""),
                detail={
                    "repair": True,
                    "columns": letters,
                    "old_formula": rep["old"][0],
                    "new_formula": rep["new"][0],
                    "changes": rep["notes"],
                },
            )
            change.affected_outputs = _affected(target, rep["blocks"])
            change.affected_output_count = len(change.affected_outputs)
            logic.append(change)

        if grown:
            cells = sum(e["cells"] for e in grown.values())
            rows = sorted(
                {
                    r
                    for e in grown.values()
                    for rs in e["ranges"].values()
                    for r1, r2 in rs
                    for r in range(r1, r2 + 1)
                }
            )
            data_block_ids_target |= {
                b for e in grown.values() for b in e["blocks_t"] if b is not None
            }
            data.append(
                DataChange(
                    id=nid(),
                    kind="rows_added",
                    sheet=t_sheet,
                    count=len(rows),
                    description=f"{t_sheet}: {len(rows):,} row(s) added ({cells:,} formula cells extend existing patterns)",
                    detail={
                        "cells": cells,
                        "first_row": rows[0],
                        "last_row": rows[-1],
                        "patterns": len(grown),
                    },
                )
            )
        if shrunk:
            cells = sum(e["cells"] for e in shrunk.values())
            rows = sorted(
                {
                    r
                    for e in shrunk.values()
                    for rs in e["ranges"].values()
                    for r1, r2 in rs
                    for r in range(r1, r2 + 1)
                }
            )
            data.append(
                DataChange(
                    id=nid(),
                    kind="rows_removed",
                    sheet=t_sheet,
                    count=len(rows),
                    description=f"{t_sheet}: {len(rows):,} row(s) removed ({cells:,} formula cells)",
                    detail={"cells": cells, "first_row": rows[0], "last_row": rows[-1]},
                )
            )

        # Block topology of shared templates (merges / splits), aggregated per sheet.
        merged: list[str] = []
        split: list[str] = []
        for key, old_t in base_tpl_by_key.items():
            if key[0] != b_sheet:
                continue
            new_t = target_tpl_by_key.get(key)
            if new_t is None:
                continue
            nb, na = len(new_t.block_ids), len(old_t.block_ids)
            if nb < na:
                merged.append(new_t.example_cell)
            elif nb > na:
                split.append(new_t.example_cell)
        if merged:
            structural.append(
                StructuralChange(
                    id=nid(),
                    kind="blocks_merged",
                    sheet=t_sheet,
                    description=(
                        f"{t_sheet}: {len(merged)} formula pattern(s) now run as fewer blocks "
                        f"(e.g. {', '.join(merged[:3])}); usually a repaired or removed row"
                    ),
                    detail={"patterns": merged},
                )
            )
        if split:
            structural.append(
                StructuralChange(
                    id=nid(),
                    kind="blocks_split",
                    sheet=t_sheet,
                    description=(
                        f"{t_sheet}: {len(split)} formula pattern(s) are now split into more blocks "
                        f"(e.g. {', '.join(split[:3])}); usually an inserted or edited row"
                    ),
                    detail={"patterns": split},
                )
            )

        # Roles.
        sb, st = base.sheet(b_sheet), target.sheet(t_sheet)
        if sb and st and sb.in_scope and st.in_scope and sb.role != st.role:
            structural.append(
                StructuralChange(
                    id=nid(),
                    kind="role_changed",
                    sheet=t_sheet,
                    description=f"{t_sheet}: role {sb.role} → {st.role} ({st.role_source})",
                    detail={"from": sb.role, "to": st.role, "source": st.role_source},
                )
            )

        # Input values and input block sizes.
        if base_raw is not None and target_raw is not None:
            ra, rt = base_raw(b_sheet), target_raw(t_sheet)
            if ra is not None and rt is not None:
                changed_vals, added_vals, removed_vals = _compare_inputs(ra, rt)
                if changed_vals or added_vals or removed_vals:
                    parts = []
                    if changed_vals:
                        parts.append(f"{changed_vals:,} value(s) changed")
                    if added_vals:
                        parts.append(f"{added_vals:,} value(s) added")
                    if removed_vals:
                        parts.append(f"{removed_vals:,} value(s) removed")
                    data.append(
                        DataChange(
                            id=nid(),
                            kind="values_changed",
                            sheet=t_sheet,
                            count=changed_vals + added_vals + removed_vals,
                            description=f"{t_sheet}: " + ", ".join(parts),
                            detail={
                                "changed": changed_vals,
                                "added": added_vals,
                                "removed": removed_vals,
                            },
                        )
                    )
                    data_block_ids_target |= {
                        b.id for b in target.input_blocks if b.sheet == t_sheet
                    }
        ib_base = sum(b.cell_count for b in base.input_blocks if b.sheet == b_sheet)
        ib_target = sum(b.cell_count for b in target.input_blocks if b.sheet == t_sheet)
        if ib_base != ib_target and not any(
            d.sheet == t_sheet and d.kind == "values_changed" for d in data
        ):
            data.append(
                DataChange(
                    id=nid(),
                    kind="inputs_resized",
                    sheet=t_sheet,
                    count=abs(ib_target - ib_base),
                    description=f"{t_sheet}: input cells {ib_base:,} → {ib_target:,}",
                    detail={"from": ib_base, "to": ib_target},
                )
            )

    # Named ranges.
    bn = {n.name: n for n in (base_names or []) if not n.builtin}
    tn = {n.name: n for n in (target_names or []) if not n.builtin}
    for name in sorted(set(bn) | set(tn)):
        if name in bn and name not in tn:
            logic.append(
                LogicChange(
                    id=nid(),
                    kind="name_removed",
                    sheet="",
                    title=f"Named range '{name}' removed",
                    description=bn[name].refers_to,
                    detail={"old": bn[name].refers_to},
                )
            )
        elif name in tn and name not in bn:
            logic.append(
                LogicChange(
                    id=nid(),
                    kind="name_added",
                    sheet="",
                    title=f"Named range '{name}' added",
                    description=tn[name].refers_to,
                    detail={"new": tn[name].refers_to},
                )
            )
        elif bn[name].refers_to != tn[name].refers_to:
            logic.append(
                LogicChange(
                    id=nid(),
                    kind="name_changed",
                    sheet="",
                    title=f"Named range '{name}' now refers to {tn[name].refers_to}",
                    description=f"{bn[name].refers_to} → {tn[name].refers_to}",
                    detail={"old": bn[name].refers_to, "new": tn[name].refers_to},
                )
            )

    # Business rules (descriptions are template-derived; only report ones not explained by a template change).
    changed_locs = {(c.sheet, c.location) for c in logic if c.kind.startswith("template")}
    base_rules = {(mapping.get(r.sheet, r.sheet), r.kind, r.description) for r in base.rules}
    target_rules = {(r.sheet, r.kind, r.description) for r in target.rules}
    for sheet, kind, desc in sorted(target_rules - base_rules):
        if not any(sheet == s for s, _ in changed_locs):
            logic.append(
                LogicChange(
                    id=nid(),
                    kind="rule_added",
                    sheet=sheet,
                    title=f"{sheet}: new {kind} rule",
                    description=desc,
                )
            )
    for sheet, kind, desc in sorted(base_rules - target_rules):
        if not any(sheet == s for s, _ in changed_locs):
            logic.append(
                LogicChange(
                    id=nid(),
                    kind="rule_removed",
                    sheet=sheet,
                    title=f"{sheet}: {kind} rule removed",
                    description=desc,
                )
            )

    # Anomaly deltas.
    if base_anomalies is not None and target_anomalies is not None:

        def akey(a: Anomaly) -> tuple:
            return (
                a.kind,
                mapping.get(a.sheet, a.sheet) if a.sheet in mapping else a.sheet,
                a.location,
            )

        bset = {akey(a): a for a in base_anomalies}
        tset = {(a.kind, a.sheet, a.location): a for a in target_anomalies}
        for k, a in tset.items():
            if k not in bset:
                structural.append(
                    StructuralChange(
                        id=nid(),
                        kind="anomaly_new",
                        sheet=a.sheet,
                        description=f"New {a.kind.replace('_', ' ')} anomaly: {a.title}",
                        detail={"kind": a.kind, "location": a.location},
                    )
                )
        for k, a in bset.items():
            if k not in tset:
                structural.append(
                    StructuralChange(
                        id=nid(),
                        kind="anomaly_resolved",
                        sheet=k[1],
                        description=f"Resolved {a.kind.replace('_', ' ')} anomaly: {a.title}",
                        detail={"kind": a.kind, "location": a.location},
                    )
                )

    outputs_total = len(_output_blocks(target))
    logic_outputs = {o.block_id for c in logic for o in c.affected_outputs}
    data_outputs = set(_affected_ids(target, data_block_ids_target))
    summary = DiffSummary(
        logic_changes=len(logic),
        data_changes=len(data),
        structural_changes=len(structural),
        outputs_total=outputs_total,
        outputs_affected_by_logic=len(logic_outputs),
        outputs_affected_by_data=len(data_outputs),
        logic_cells=total_logic_cells,
    )
    headline = _headline(summary)
    return DiffReport(
        base_version_id=base.version_id,
        target_version_id=target.version_id,
        created_at=datetime.now(UTC),
        headline=headline,
        summary=summary,
        logic=logic,
        data=data,
        structural=structural,
        sheet_map=mapping,
    )


def _affected_ids(model: WorkbookLogicModel, block_ids: set[int]) -> set[int]:
    return _descendants(model, block_ids) & set(_output_blocks(model))


def _headline(s: DiffSummary) -> str:
    if s.logic_changes == 0 and s.data_changes == 0 and s.structural_changes == 0:
        return "No changes"
    parts = []
    if s.logic_changes:
        parts.append(
            f"{s.logic_changes} logic change{'s' if s.logic_changes != 1 else ''} affecting {s.outputs_affected_by_logic} of {s.outputs_total} outputs"
        )
    if s.data_changes:
        parts.append(
            f"{s.data_changes} data change{'s' if s.data_changes != 1 else ''} reaching {s.outputs_affected_by_data} of {s.outputs_total} outputs"
        )
    if s.structural_changes:
        parts.append(
            f"{s.structural_changes} structural change{'s' if s.structural_changes != 1 else ''}"
        )
    return "; ".join(parts)


def mapping_inv(rename: dict[str, str], target_sheet: str) -> str:
    return rename.get(target_sheet, target_sheet)


def _compare_inputs(ra: RawSheet, rt: RawSheet) -> tuple[int, int, int]:
    """(changed, added, removed) constant cells between two raw sheets."""
    a = {
        addr: v
        for addr, f, v in zip(ra.cells.address, ra.cells.formula, ra.cells.value, strict=True)
        if f is None
    }
    t = {
        addr: v
        for addr, f, v in zip(rt.cells.address, rt.cells.formula, rt.cells.value, strict=True)
        if f is None
    }
    changed = sum(1 for k, v in a.items() if k in t and t[k] != v)
    added = sum(1 for k in t if k not in a)
    removed = sum(1 for k in a if k not in t)
    return changed, added, removed


__all__ = [
    "DiffReport",
    "LogicChange",
    "DataChange",
    "StructuralChange",
    "diff_models",
    "describe_ast_change",
    "match_sheets",
    "Rect",
    "parse_a1_cell",
]
