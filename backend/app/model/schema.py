"""WorkbookLogicModel: the block-level, workbook-agnostic model every later phase consumes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.model.formula.ast import Node
from app.model.formula.refs import Rect

SheetRole = Literal["input", "reference", "transformation", "calculation", "output"]
RoleSource = Literal["heuristic", "config", "override"]
BlockClass = Literal["calculation", "output"]
RuleKind = Literal["condition", "threshold", "lookup", "error_fallback"]


class RectModel(BaseModel):
    r1: int
    c1: int
    r2: int
    c2: int

    @classmethod
    def of(cls, rect: Rect) -> RectModel:
        return cls(r1=rect.r1, c1=rect.c1, r2=rect.r2, c2=rect.c2)

    def rect(self) -> Rect:
        return Rect(self.r1, self.c1, self.r2, self.c2)

    @property
    def a1(self) -> str:
        return self.rect().to_a1()


class Template(BaseModel):
    id: int
    sheet: str
    r1c1: str = Field(description="Canonical R1C1 serialisation; the template key")
    ast: Node | None = None
    example_cell: str
    example_formula: str
    cell_count: int
    block_ids: list[int] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    array_ref: str | None = None
    parse_error: str | None = None


class Footprint(BaseModel):
    sheet: str
    rect: RectModel
    ref: str = Field(description="The R1C1 reference that produced this footprint")


class FormulaBlock(BaseModel):
    id: int
    sheet: str
    template_id: int
    rect: RectModel
    cell_count: int
    footprints: list[Footprint] = Field(default_factory=list)
    self_dependent: bool = False
    self_order: str | None = Field(
        default=None, description="top_to_bottom | left_to_right | row_major | cycle"
    )
    classification: BlockClass = "calculation"
    column_labels: list[str | None] = Field(default_factory=list)
    row_label_col: int | None = None


class InputBlock(BaseModel):
    id: int
    sheet: str
    rect: RectModel
    cell_count: int = Field(description="Non-empty constant cells inside the rect")
    kind: Literal["input", "external"] = "input"
    value_types: dict[str, int] = Field(default_factory=dict)
    column_labels: list[str | None] = Field(default_factory=list)
    row_label_col: int | None = None


class SheetModel(BaseModel):
    name: str
    index: int
    state: str = "visible"
    in_scope: bool = True
    role: SheetRole = "input"
    role_source: RoleSource = "heuristic"
    role_reason: str | None = None
    used_range: str | None = None
    cell_count: int = 0
    formula_cells: int = 0
    input_cells: int = 0
    output_cells: int = 0
    static_cells: int = 0
    formula_block_ids: list[int] = Field(default_factory=list)
    input_block_ids: list[int] = Field(default_factory=list)
    feeds: list[str] = Field(
        default_factory=list, description="Sheets this sheet's cells are read by"
    )
    reads: list[str] = Field(
        default_factory=list, description="Sheets whose cells this sheet reads"
    )


class BlockEdge(BaseModel):
    source: int
    target: int


class SheetEdge(BaseModel):
    source: str
    target: str
    weight: int


class BusinessRule(BaseModel):
    id: int
    kind: RuleKind
    template_id: int
    sheet: str
    cells: list[str]
    description: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ModelSummary(BaseModel):
    sheets_in_scope: int
    templates: int
    formula_blocks: int
    input_blocks: int
    external_blocks: int
    formula_cells: int
    input_cells: int
    output_cells: int
    static_cells: int
    rules: int
    parse_errors: int
    cycles: int
    self_dependent_blocks: int
    unresolved_references: int
    seconds: float
    peak_mb: float


class WorkbookLogicModel(BaseModel):
    version_id: str
    created_at: datetime
    scope: list[str]
    sheets: list[SheetModel]
    templates: list[Template]
    formula_blocks: list[FormulaBlock]
    input_blocks: list[InputBlock]
    edges: list[BlockEdge]
    sheet_edges: list[SheetEdge]
    execution_order: list[int] = Field(description="Formula block ids in evaluation order")
    cycles: list[list[int]] = Field(
        default_factory=list, description="Strongly connected block groups"
    )
    cycle_descriptions: list[str] = Field(
        default_factory=list, description="One readable explanation per cycle, in A1 terms"
    )
    unresolved: list[str] = Field(
        default_factory=list, description="Names/refs that could not be resolved"
    )
    rules: list[BusinessRule]
    summary: ModelSummary

    def sheet(self, name: str) -> SheetModel | None:
        return next((s for s in self.sheets if s.name == name), None)

    def template(self, template_id: int) -> Template:
        return self.templates[template_id]

    def formula_block(self, block_id: int) -> FormulaBlock:
        return self.formula_blocks[block_id]

    def block_at(self, sheet: str, row: int, col: int) -> FormulaBlock | InputBlock | None:
        for b in self.formula_blocks:
            if b.sheet == sheet and b.rect.rect().contains(row, col):
                return b
        for b in self.input_blocks:
            if b.sheet == sheet and b.rect.rect().contains(row, col):
                return b
        return None
