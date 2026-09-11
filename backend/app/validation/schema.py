"""ValidationReport: reconciliation of the engine against Excel's cached values, plus anomalies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ValidationStatus = Literal["passed", "passed_with_warnings", "failed"]
MismatchClass = Literal["precision", "semantics", "data"]
AnomalyKind = Literal["fragmentation", "own_row", "duplicate_keys", "stale"]


class ValidationPolicy(BaseModel):
    significant_digits: int = 15
    max_mismatch_ratio: float = Field(
        0.0, description="semantics + data mismatches / checked; above this → failed"
    )
    max_precision_ratio: float = Field(
        0.001, description="precision mismatches / checked; above this → failed"
    )


class Totals(BaseModel):
    checked: int = 0
    matched: int = 0
    mismatched: int = 0
    skipped_unsupported: int = 0
    skipped_stale: int = 0


class SheetCoverage(BaseModel):
    sheet: str
    formula_cells: int
    checked: int
    matched: int
    mismatched: int
    skipped_unsupported: int
    skipped_stale: int


class Mismatch(BaseModel):
    sheet: str
    cell: str
    template_id: int | None
    formula: str | None
    excel: Any
    engine: Any
    delta: float | None
    classification: MismatchClass


class UnsupportedTemplate(BaseModel):
    function: str
    sheet: str
    cell: str
    cells: int


class Anomaly(BaseModel):
    id: int
    kind: AnomalyKind
    sheet: str
    location: str = Field(description="A1 range(s), comma separated")
    title: str
    explanation: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    id: str
    version_id: str
    run_id: str | None
    created_at: datetime
    status: ValidationStatus
    policy: ValidationPolicy
    totals: Totals
    by_sheet: list[SheetCoverage]
    mismatches: list[Mismatch] = Field(
        default_factory=list, description="Capped; totals carry the full count"
    )
    mismatches_truncated: bool = False
    unsupported: list[UnsupportedTemplate] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    anomaly_counts: dict[str, int] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list, description="Why the status is what it is")
    seconds: float = 0.0
