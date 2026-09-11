"""Logic-model endpoints: interpret, model, graph, rules, sheet-role overrides."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.model.formula.refs import Rect, parse_a1_cell
from app.model.interpreter import cell_dependencies, cell_dependents
from app.model.schema import (
    BusinessRule,
    FormulaBlock,
    ModelSummary,
    SheetModel,
    SheetRole,
    WorkbookLogicModel,
)
from app.storage import logic as store
from app.storage import workbooks
from app.storage.db import get_session

router = APIRouter(prefix="/workbooks/{version_id}")
SessionDep = Annotated[Session, Depends(get_session)]


class InterpretRequest(BaseModel):
    sheets: list[str] | None = Field(
        default=None,
        description="Sheets to interpret; omit to use dashboard.config.json sheetScope (empty = all)",
    )


class InterpretResponse(BaseModel):
    version_id: str
    scope: list[str]
    summary: ModelSummary
    sheets: list[SheetModel]
    cycles: list[list[int]]
    cycle_descriptions: list[str]
    unresolved: list[str]


class RoleUpdate(BaseModel):
    role: SheetRole
    reason: str | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str
    depth: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    weight: int = 1
    label: str | None = None


class GraphResponse(BaseModel):
    level: str
    nodes: list[GraphNode]
    edges: list[GraphEdgeOut]


def _model_or_404(session: Session, version_id: str) -> WorkbookLogicModel:
    try:
        workbooks.get_version(session, version_id)
    except workbooks.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc
    try:
        return store.get_model(session, version_id)
    except store.ModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No logic model for this version yet. POST /interpret first."
        ) from exc


@router.post("/interpret", response_model=InterpretResponse)
def interpret_workbook(
    version_id: str, session: SessionDep, body: InterpretRequest | None = None
) -> InterpretResponse:
    body = body or InterpretRequest()
    try:
        model = store.interpret_version(
            session, version_id, scope=body.sheets, config=load_dashboard_config()
        )
    except workbooks.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return InterpretResponse(
        version_id=version_id,
        scope=model.scope,
        summary=model.summary,
        sheets=model.sheets,
        cycles=model.cycles,
        cycle_descriptions=model.cycle_descriptions,
        unresolved=model.unresolved,
    )


@router.get("/model", response_model=WorkbookLogicModel, response_model_exclude_none=True)
def get_model(
    version_id: str,
    session: SessionDep,
    sheet: Annotated[
        str | None, Query(description="Restrict blocks, templates and rules to one sheet")
    ] = None,
    include: Annotated[
        str, Query(description="Comma list; add 'ast' to include template ASTs")
    ] = "",
) -> WorkbookLogicModel:
    model = _model_or_404(session, version_id)
    wants = {p.strip() for p in include.split(",") if p.strip()}
    if sheet is not None:
        if model.sheet(sheet) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model.")
        model.formula_blocks = [b for b in model.formula_blocks if b.sheet == sheet]
        model.input_blocks = [b for b in model.input_blocks if b.sheet == sheet]
        model.templates = [t for t in model.templates if t.sheet == sheet]
        model.rules = [r for r in model.rules if r.sheet == sheet]
        ids = {b.id for b in model.formula_blocks} | {b.id for b in model.input_blocks}
        model.edges = [e for e in model.edges if e.source in ids and e.target in ids]
    if "ast" not in wants:
        for t in model.templates:
            t.ast = None
    return model


@router.get("/rules", response_model=list[BusinessRule])
def get_rules(
    version_id: str,
    session: SessionDep,
    sheet: str | None = None,
    kind: str | None = None,
) -> list[BusinessRule]:
    model = _model_or_404(session, version_id)
    rules = model.rules
    if sheet is not None:
        rules = [r for r in rules if r.sheet == sheet]
    if kind is not None:
        rules = [r for r in rules if r.kind == kind]
    return rules


@router.patch("/model/sheets/{sheet}", response_model=SheetModel)
def set_sheet_role(
    version_id: str, sheet: str, body: RoleUpdate, session: SessionDep
) -> SheetModel:
    _model_or_404(session, version_id)
    try:
        model = store.set_sheet_role(session, version_id, sheet, body.role, body.reason)
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model."
        ) from exc
    result = model.sheet(sheet)
    assert result is not None
    return result


def _depths(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path depth from sources, for left-to-right layout."""
    import networkx as nx

    g = nx.DiGraph()
    g.add_nodes_from(nodes)
    g.add_edges_from(edges)
    depth: dict[str, int] = {}
    if not nx.is_directed_acyclic_graph(g):
        g = nx.condensation(g)
        members = {n: g.nodes[n]["members"] for n in g.nodes}
        order = list(nx.topological_sort(g))
        cdepth: dict[int, int] = {}
        for n in order:
            cdepth[n] = max((cdepth[p] + 1 for p in g.predecessors(n)), default=0)
        for n, ms in members.items():
            for m in ms:
                depth[m] = cdepth[n]
        return depth
    for n in nx.topological_sort(g):
        depth[n] = max((depth[p] + 1 for p in g.predecessors(n)), default=0)
    return depth


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    version_id: str,
    session: SessionDep,
    level: Literal["sheet", "block", "cell"] = "sheet",
    cell: Annotated[str | None, Query(description="For level=cell: 'Sheet!A1'")] = None,
    depth: Annotated[int, Query(ge=1, le=5)] = 1,
) -> GraphResponse:
    model = _model_or_404(session, version_id)
    if level == "sheet":
        names = [s.name for s in model.sheets if s.in_scope or s.input_block_ids]
        edges = [(e.source, e.target) for e in model.sheet_edges]
        depths = _depths(names, edges)
        nodes = [
            GraphNode(
                id=s.name,
                label=s.name,
                kind=s.role if s.in_scope else "external",
                depth=depths.get(s.name, 0),
                data={
                    "in_scope": s.in_scope,
                    "role": s.role,
                    "role_source": s.role_source,
                    "formula_cells": s.formula_cells,
                    "input_cells": s.input_cells,
                    "output_cells": s.output_cells,
                    "static_cells": s.static_cells,
                    "state": s.state,
                },
            )
            for s in model.sheets
            if s.name in depths
        ]
        return GraphResponse(
            level="sheet",
            nodes=nodes,
            edges=[
                GraphEdgeOut(source=e.source, target=e.target, weight=e.weight)
                for e in model.sheet_edges
            ],
        )

    if level == "block":
        ids = [str(b.id) for b in model.formula_blocks] + [str(b.id) for b in model.input_blocks]
        edges = [(str(e.source), str(e.target)) for e in model.edges]
        depths = _depths(ids, edges)
        nodes = [
            GraphNode(
                id=str(b.id),
                label=f"{b.sheet}!{b.rect.a1}",
                kind=b.classification,
                depth=depths[str(b.id)],
                data={
                    "sheet": b.sheet,
                    "template_id": b.template_id,
                    "cell_count": b.cell_count,
                    "self_dependent": b.self_dependent,
                    "column_labels": b.column_labels,
                },
            )
            for b in model.formula_blocks
        ] + [
            GraphNode(
                id=str(b.id),
                label=f"{b.sheet}!{b.rect.a1}",
                kind=b.kind,
                depth=depths[str(b.id)],
                data={
                    "sheet": b.sheet,
                    "cell_count": b.cell_count,
                    "column_labels": b.column_labels,
                },
            )
            for b in model.input_blocks
        ]
        return GraphResponse(
            level="block",
            nodes=nodes,
            edges=[GraphEdgeOut(source=str(e.source), target=str(e.target)) for e in model.edges],
        )

    if not cell or "!" not in cell:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "level=cell requires cell=Sheet!A1"
        )
    sheet, addr = cell.rsplit("!", 1)
    sheet = sheet.strip("'")
    if model.sheet(sheet) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not in this model.")
    try:
        row, col = parse_a1_cell(addr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _cell_graph(model, sheet, row, col, depth)


def _cell_graph(
    model: WorkbookLogicModel, sheet: str, row: int, col: int, depth: int
) -> GraphResponse:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdgeOut] = []

    def node_for(s: str, rect: Rect) -> str:
        nid = f"{s}!{rect.to_a1()}"
        if nid not in nodes:
            block = model.block_at(s, rect.r1, rect.c1)
            kind = "static"
            data: dict[str, Any] = {"sheet": s, "range": rect.to_a1(), "cells": rect.cells}
            if isinstance(block, FormulaBlock):
                tpl = model.template(block.template_id)
                kind = block.classification
                data["template_id"] = tpl.id
                data["formula"] = tpl.example_formula if rect.cells == 1 else None
            elif block is not None:
                kind = block.kind
            nodes[nid] = GraphNode(id=nid, label=nid, kind=kind, data=data)
        return nid

    focus = node_for(sheet, Rect.cell(row, col))
    frontier = [(sheet, row, col, 0)]
    seen = {(sheet, row, col)}
    while frontier:
        s, r, c, d = frontier.pop(0)
        src = node_for(s, Rect.cell(r, c))
        for dep_sheet, rect in cell_dependencies(model, s, r, c):
            tgt = node_for(dep_sheet, rect)
            edges.append(GraphEdgeOut(source=tgt, target=src, label="reads"))
            if d + 1 < depth and rect.cells == 1 and (dep_sheet, rect.r1, rect.c1) not in seen:
                seen.add((dep_sheet, rect.r1, rect.c1))
                frontier.append((dep_sheet, rect.r1, rect.c1, d + 1))
    for block, cells in cell_dependents(model, sheet, row, col):
        for addr in cells[:20]:
            r2, c2 = parse_a1_cell(addr)
            tgt = node_for(block.sheet, Rect.cell(r2, c2))
            edges.append(GraphEdgeOut(source=focus, target=tgt, label="read by"))
    for n in nodes.values():
        n.depth = 0
    return GraphResponse(level="cell", nodes=list(nodes.values()), edges=edges)
