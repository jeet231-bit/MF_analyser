"""RawWorkbook: a faithful, workbook-agnostic extraction of an .xlsx/.xlsm file.

Cells are stored per sheet in a columnar layout (parallel lists) because real research
workbooks reach millions of non-empty cells; one Pydantic object per cell does not fit in
memory. ``RawSheet.records()`` yields row-oriented ``RawCell`` views when convenience matters
more than memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

CellValue = int | float | str | bool | None
ValueType = Literal["number", "text", "date", "bool", "error", "empty"]
SheetState = Literal["visible", "hidden", "veryHidden"]

EXCEL_ERRORS = frozenset(
    {
        "#NULL!",
        "#DIV/0!",
        "#VALUE!",
        "#REF!",
        "#NAME?",
        "#NUM!",
        "#N/A",
        "#GETTING_DATA",
        "#SPILL!",
        "#CALC!",
    }
)


class DefinedName(BaseModel):
    name: str
    refers_to: str
    scope: str | None = Field(
        default=None, description="Sheet name for sheet-scoped names; None = workbook"
    )
    builtin: bool = Field(default=False, description="_xlnm.* names such as Print_Area")
    hidden: bool = False


class TableDef(BaseModel):
    name: str
    display_name: str
    sheet: str
    ref: str
    columns: list[str]
    header_row: bool = True
    totals_row: bool = False


class RawCell(BaseModel):
    address: str
    row: int
    col: int
    formula: str | None = Field(default=None, description="Effective formula including leading '='")
    value: CellValue = Field(
        default=None, description="Cached value; dates are Excel serial numbers"
    )
    value_type: ValueType = "empty"
    number_format: str = "General"
    merged_range: str | None = None
    table: str | None = None
    array_ref: str | None = Field(
        default=None, description="Set when the formula is an array formula"
    )


class CellColumns(BaseModel):
    """Parallel lists; index i describes one non-empty cell."""

    address: list[str] = Field(default_factory=list)
    row: list[int] = Field(default_factory=list)
    col: list[int] = Field(default_factory=list)
    formula: list[str | None] = Field(default_factory=list)
    value: list[CellValue] = Field(default_factory=list)
    value_type: list[ValueType] = Field(default_factory=list)
    number_format: list[str] = Field(default_factory=list)
    merged_range: list[str | None] = Field(default_factory=list)
    table: list[str | None] = Field(default_factory=list)
    array_ref: list[str | None] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.address)

    def append(
        self,
        address: str,
        row: int,
        col: int,
        *,
        formula: str | None,
        value: CellValue,
        value_type: ValueType,
        number_format: str,
        merged_range: str | None = None,
        table: str | None = None,
        array_ref: str | None = None,
    ) -> int:
        self.address.append(address)
        self.row.append(row)
        self.col.append(col)
        self.formula.append(formula)
        self.value.append(value)
        self.value_type.append(value_type)
        self.number_format.append(number_format)
        self.merged_range.append(merged_range)
        self.table.append(table)
        self.array_ref.append(array_ref)
        return len(self.address) - 1

    def record(self, i: int) -> RawCell:
        return RawCell(
            address=self.address[i],
            row=self.row[i],
            col=self.col[i],
            formula=self.formula[i],
            value=self.value[i],
            value_type=self.value_type[i],
            number_format=self.number_format[i],
            merged_range=self.merged_range[i],
            table=self.table[i],
            array_ref=self.array_ref[i],
        )


class RawSheet(BaseModel):
    name: str
    index: int
    state: SheetState = "visible"
    used_range: str | None = None
    merged_ranges: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    cell_count: int = 0
    formula_count: int = 0
    cells: CellColumns = Field(default_factory=CellColumns)

    _index: dict[str, int] | None = PrivateAttr(default=None)

    def records(self) -> Iterator[RawCell]:
        for i in range(len(self.cells)):
            yield self.cells.record(i)

    def position(self, address: str) -> int | None:
        if self._index is None:
            self._index = {addr: i for i, addr in enumerate(self.cells.address)}
        return self._index.get(address)

    def cell(self, address: str) -> RawCell | None:
        i = self.position(address)
        return None if i is None else self.cells.record(i)

    def formulas(self) -> Iterator[tuple[str, str]]:
        """(address, formula) for every formula cell."""
        for addr, f in zip(self.cells.address, self.cells.formula, strict=True):
            if f is not None:
                yield addr, f


class WorkbookSummary(BaseModel):
    filename: str
    sheets: int
    cells: int
    formula_cells: int
    named_ranges: int
    tables: int
    distinct_functions: int
    functions: dict[str, int] = Field(description="Excel function -> number of formulas using it")
    has_macros: bool = False
    warnings: list[str] = Field(default_factory=list)
    sheet_names: list[str] = Field(default_factory=list)


class RawWorkbook(BaseModel):
    filename: str
    epoch: Literal[1900, 1904] = 1900
    has_macros: bool = False
    warnings: list[str] = Field(default_factory=list)
    defined_names: list[DefinedName] = Field(default_factory=list)
    tables: list[TableDef] = Field(default_factory=list)
    functions: dict[str, int] = Field(default_factory=dict)
    sheets: list[RawSheet] = Field(default_factory=list)

    def sheet(self, name: str) -> RawSheet | None:
        return next((s for s in self.sheets if s.name == name), None)

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]

    def summary(self) -> WorkbookSummary:
        return WorkbookSummary(
            filename=self.filename,
            sheets=len(self.sheets),
            cells=sum(s.cell_count for s in self.sheets),
            formula_cells=sum(s.formula_count for s in self.sheets),
            named_ranges=sum(1 for n in self.defined_names if not n.builtin),
            tables=len(self.tables),
            distinct_functions=len(self.functions),
            functions=dict(sorted(self.functions.items(), key=lambda kv: (-kv[1], kv[0]))),
            has_macros=self.has_macros,
            warnings=list(self.warnings),
            sheet_names=self.sheet_names,
        )
